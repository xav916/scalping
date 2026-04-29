"""Tests Phase MQL.C — routing destinations admin (HTTP) vs user (DB queue).

Vérifie que ``send_setup`` :
- pour ``admin_legacy`` : POST HTTP vers le bridge (comportement V1 inchangé)
- pour ``user:{id}`` : INSERT dans ``mt5_pending_orders`` (queue EA)
- gère les 2 simultanément si admin + user en parallèle
"""
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.services import (
    bridge_destinations,
    mt5_bridge,
    mt5_pending_orders_service,
    trade_log_service,
)


@pytest.fixture
def db(tmp_path: Path):
    db_file = tmp_path / "trades.db"
    with patch.object(trade_log_service, "_DB_PATH", db_file):
        mt5_pending_orders_service._ensure_schema()
        yield db_file


@pytest.fixture(autouse=True)
def _reset_dedup():
    mt5_bridge._sent_setups_today.clear()
    yield
    mt5_bridge._sent_setups_today.clear()


@pytest.fixture(autouse=True)
def _disable_star_filter(monkeypatch):
    """Neutralise le filtre stars pour ces tests qui utilisent EUR/USD."""
    monkeypatch.setattr(
        mt5_bridge,
        "_STAR_PAIRS_SET",
        frozenset({"EUR/USD", "XAU/USD", "BTC/USD"}),
    )


def _mk_setup(pair: str = "EUR/USD") -> MagicMock:
    s = MagicMock()
    s.pair = pair
    s.direction = MagicMock(value="buy")
    s.entry_price = 1.10
    s.stop_loss = 1.09
    s.take_profit_1 = 1.11
    s.take_profit_2 = 1.12
    s.confidence_score = 95.0
    s.verdict_action = "TAKE"
    s.verdict_blockers = []
    s.is_simulated = False
    s.timestamp = datetime.now(timezone.utc)
    return s


def _admin_dest() -> bridge_destinations.BridgeConfig:
    return bridge_destinations.BridgeConfig(
        destination_id="admin_legacy",
        user_id=None,
        bridge_url="http://admin-bridge:8787",
        bridge_api_key="a" * 32,
        min_confidence=55.0,
        allowed_asset_classes=frozenset({"forex", "metal"}),
        auto_exec_enabled=True,
    )


def _user_dest(user_id: int = 17, api_key: str = "u" * 32) -> bridge_destinations.BridgeConfig:
    return bridge_destinations.BridgeConfig(
        destination_id=f"user:{user_id}",
        user_id=user_id,
        bridge_url="http://user-bridge:8787",
        bridge_api_key=api_key,
        min_confidence=55.0,
        allowed_asset_classes=frozenset({"forex", "metal"}),
        auto_exec_enabled=True,
    )


class _FakeAsyncClient:
    """Mock httpx.AsyncClient pour capturer les POST."""

    last_url: str | None = None
    last_payload: dict | None = None
    last_headers: dict | None = None

    def __init__(self, *_a, **_kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def post(self, url, json=None, headers=None):
        _FakeAsyncClient.last_url = url
        _FakeAsyncClient.last_payload = json
        _FakeAsyncClient.last_headers = headers
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"ok": True, "mode": "paper"}
        return resp


@pytest.fixture
def reset_fake_client():
    _FakeAsyncClient.last_url = None
    _FakeAsyncClient.last_payload = None
    _FakeAsyncClient.last_headers = None
    yield
    _FakeAsyncClient.last_url = None
    _FakeAsyncClient.last_payload = None
    _FakeAsyncClient.last_headers = None


# ─── admin_legacy → HTTP push ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_destination_uses_http_post(db, reset_fake_client, monkeypatch):
    """Pour admin_legacy : POST HTTP vers bridge_url + 0 entry dans queue."""
    monkeypatch.setattr(
        bridge_destinations,
        "resolve_destinations",
        lambda setup: [_admin_dest()],
    )
    monkeypatch.setattr(
        "backend.services.mt5_bridge.httpx.AsyncClient", _FakeAsyncClient
    )

    await mt5_bridge.send_setup(_mk_setup("EUR/USD"))

    # HTTP POST a été fait
    assert _FakeAsyncClient.last_url == "http://admin-bridge:8787/order"
    assert _FakeAsyncClient.last_payload["pair"] == "EUR/USD"
    # Aucun order en queue (admin n'enqueue pas)
    counts = mt5_pending_orders_service.count_by_status()
    assert counts == {}


# ─── user → DB enqueue ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_user_destination_enqueues_in_db(db, reset_fake_client, monkeypatch):
    """Pour user:17 : INSERT dans mt5_pending_orders + 0 POST HTTP."""
    monkeypatch.setattr(
        bridge_destinations,
        "resolve_destinations",
        lambda setup: [_user_dest(user_id=17)],
    )
    monkeypatch.setattr(
        "backend.services.mt5_bridge.httpx.AsyncClient", _FakeAsyncClient
    )

    await mt5_bridge.send_setup(_mk_setup("EUR/USD"))

    # Aucun POST HTTP
    assert _FakeAsyncClient.last_url is None
    # 1 order PENDING dans la queue pour user_id=17
    counts = mt5_pending_orders_service.count_by_status(user_id=17)
    assert counts == {"PENDING": 1}


@pytest.mark.asyncio
async def test_user_enqueue_payload_has_required_fields(db, reset_fake_client, monkeypatch):
    """Le payload enqueué doit contenir tous les champs nécessaires à l'EA."""
    monkeypatch.setattr(
        bridge_destinations,
        "resolve_destinations",
        lambda setup: [_user_dest(user_id=17)],
    )
    monkeypatch.setattr(
        "backend.services.mt5_bridge.httpx.AsyncClient", _FakeAsyncClient
    )

    await mt5_bridge.send_setup(_mk_setup("EUR/USD"))

    fetched = mt5_pending_orders_service.fetch_for_api_key("u" * 32)
    assert len(fetched) == 1
    payload = fetched[0]["payload"]
    assert payload["pair"] == "EUR/USD"
    assert payload["direction"] == "buy"
    assert payload["entry"] == 1.10
    assert payload["sl"] == 1.09
    assert payload["tp"] == 1.11
    assert "risk_money" in payload
    assert "comment" in payload


# ─── admin + user simultanés ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_both_admin_and_user_dispatched(db, reset_fake_client, monkeypatch):
    """Setup avec 2 destinations → admin POST HTTP + user enqueue DB."""
    monkeypatch.setattr(
        bridge_destinations,
        "resolve_destinations",
        lambda setup: [_admin_dest(), _user_dest(user_id=17)],
    )
    monkeypatch.setattr(
        "backend.services.mt5_bridge.httpx.AsyncClient", _FakeAsyncClient
    )

    await mt5_bridge.send_setup(_mk_setup("EUR/USD"))

    # admin a fait son POST
    assert _FakeAsyncClient.last_url == "http://admin-bridge:8787/order"
    # user a son order en queue
    assert mt5_pending_orders_service.count_by_status(user_id=17) == {"PENDING": 1}


# ─── user dedup ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_user_enqueue_dedupe_per_destination(db, reset_fake_client, monkeypatch):
    """2 send_setup successifs pour le même setup user → 1 seul enqueue
    (dedup via mt5_pushes table)."""
    monkeypatch.setattr(
        bridge_destinations,
        "resolve_destinations",
        lambda setup: [_user_dest(user_id=17)],
    )
    monkeypatch.setattr(
        "backend.services.mt5_bridge.httpx.AsyncClient", _FakeAsyncClient
    )

    setup = _mk_setup("EUR/USD")
    await mt5_bridge.send_setup(setup)
    await mt5_bridge.send_setup(setup)

    counts = mt5_pending_orders_service.count_by_status(user_id=17)
    assert counts == {"PENDING": 1}


# ─── isolation entre 2 users ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_two_users_get_separate_enqueues(db, reset_fake_client, monkeypatch):
    monkeypatch.setattr(
        bridge_destinations,
        "resolve_destinations",
        lambda setup: [
            _user_dest(user_id=17, api_key="alice_" + "x" * 26),
            _user_dest(user_id=42, api_key="bob_" + "y" * 28),
        ],
    )
    monkeypatch.setattr(
        "backend.services.mt5_bridge.httpx.AsyncClient", _FakeAsyncClient
    )

    await mt5_bridge.send_setup(_mk_setup("EUR/USD"))

    assert mt5_pending_orders_service.count_by_status(user_id=17) == {"PENDING": 1}
    assert mt5_pending_orders_service.count_by_status(user_id=42) == {"PENDING": 1}

    # Chacun fetch ses propres orders
    alice_orders = mt5_pending_orders_service.fetch_for_api_key("alice_" + "x" * 26)
    bob_orders = mt5_pending_orders_service.fetch_for_api_key("bob_" + "y" * 28)
    assert len(alice_orders) == 1
    assert len(bob_orders) == 1
    assert alice_orders[0]["user_id"] == 17
    assert bob_orders[0]["user_id"] == 42
