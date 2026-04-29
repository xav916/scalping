"""Tests Phase MQL.B — endpoints `/api/ea/{pending,result,heartbeat}`.

L'EA est appelé sans cookie session. Auth via ``api_key`` en query param
(GET) ou dans le body JSON (POST). Le user est résolu via
``users_service.find_user_by_bridge_api_key``.
"""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from backend import app as app_module
from backend.services import (
    mt5_pending_orders_service,
    trade_log_service,
    users_service,
)


@pytest.fixture
def db(tmp_path: Path):
    db_file = tmp_path / "trades.db"
    with patch.object(users_service, "_DB_PATH", db_file), \
         patch.object(trade_log_service, "_DB_PATH", db_file):
        users_service.init_users_schema()
        mt5_pending_orders_service._ensure_schema()
        yield db_file


def _create_premium_user(
    email: str = "alice@test.com",
    api_key: str = "u" * 32,
    has_active_sub: bool = True,
) -> int:
    uid = users_service.create_user(email, "password123")
    cfg = {
        "bridge_url": "http://user-bridge:8787",
        "bridge_api_key": api_key,
        "auto_exec_enabled": True,
    }
    with users_service._conn() as c:
        sub_id = "sub_test_xxx" if has_active_sub else None
        c.execute(
            "UPDATE users SET tier='premium', broker_config=?, "
            "stripe_subscription_id=? WHERE id=?",
            (json.dumps(cfg), sub_id, uid),
        )
    return uid


# ─── GET /api/ea/pending ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pending_returns_orders_for_valid_api_key(db):
    uid = _create_premium_user(api_key="alice_key_" + "x" * 22)
    mt5_pending_orders_service.enqueue(
        uid, "alice_key_" + "x" * 22,
        {"pair": "EUR/USD", "direction": "buy", "entry": 1.10},
    )
    result = await app_module.api_ea_pending(api_key="alice_key_" + "x" * 22)
    assert "orders" in result
    assert len(result["orders"]) == 1
    assert result["orders"][0]["payload"]["pair"] == "EUR/USD"


@pytest.mark.asyncio
async def test_pending_marks_orders_sent_atomically(db):
    """2 polls successifs : 1er retourne, 2e vide."""
    uid = _create_premium_user()
    mt5_pending_orders_service.enqueue(uid, "u" * 32, {"pair": "EUR/USD"})

    first = await app_module.api_ea_pending(api_key="u" * 32)
    assert len(first["orders"]) == 1

    second = await app_module.api_ea_pending(api_key="u" * 32)
    assert second["orders"] == []


@pytest.mark.asyncio
async def test_pending_rejects_invalid_api_key(db):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await app_module.api_ea_pending(api_key="invalid_key_xxxxxxxxxxxxx")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_pending_rejects_short_api_key(db):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await app_module.api_ea_pending(api_key="short")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_pending_rejects_non_premium_user(db):
    """User pro avec api_key valide mais pas Premium → 403."""
    uid = users_service.create_user("alice@test.com", "password123")
    cfg = {"bridge_api_key": "x" * 32}
    with users_service._conn() as c:
        c.execute(
            "UPDATE users SET tier='pro', broker_config=? WHERE id=?",
            (json.dumps(cfg), uid),
        )
    from fastapi import HTTPException

    # find_user_by_bridge_api_key filtre déjà tier='premium' donc 401, pas 403.
    # C'est OK : on ne dit pas à l'attaquant si la clé existe mais sur un
    # mauvais tier — meilleur côté sécurité.
    with pytest.raises(HTTPException) as exc:
        await app_module.api_ea_pending(api_key="x" * 32)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_pending_updates_heartbeat(db):
    uid = _create_premium_user()
    cfg_before = users_service.get_broker_config(uid)
    assert "last_ea_heartbeat" not in cfg_before

    await app_module.api_ea_pending(api_key="u" * 32)

    cfg_after = users_service.get_broker_config(uid)
    assert "last_ea_heartbeat" in cfg_after


# ─── POST /api/ea/result ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_result_acks_executed(db):
    uid = _create_premium_user()
    order_id = mt5_pending_orders_service.enqueue(uid, "u" * 32, {"pair": "EUR/USD"})
    await app_module.api_ea_pending(api_key="u" * 32)  # passe en SENT

    result = await app_module.api_ea_result(
        payload={
            "api_key": "u" * 32,
            "order_id": order_id,
            "ok": True,
            "mt5_ticket": 999888,
        }
    )
    assert result == {"acked": True}
    counts = mt5_pending_orders_service.count_by_status(user_id=uid)
    assert counts == {"EXECUTED": 1}


@pytest.mark.asyncio
async def test_result_acks_failed(db):
    uid = _create_premium_user()
    order_id = mt5_pending_orders_service.enqueue(uid, "u" * 32, {"pair": "EUR/USD"})
    await app_module.api_ea_pending(api_key="u" * 32)

    result = await app_module.api_ea_result(
        payload={
            "api_key": "u" * 32,
            "order_id": order_id,
            "ok": False,
            "error": "rc=10016 INVALID_STOPS",
        }
    )
    assert result == {"acked": True}
    counts = mt5_pending_orders_service.count_by_status(user_id=uid)
    assert counts == {"FAILED": 1}


@pytest.mark.asyncio
async def test_result_rejects_missing_fields(db):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await app_module.api_ea_result(payload={"api_key": "x" * 32})  # pas d'order_id
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_result_rejects_invalid_api_key(db):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await app_module.api_ea_result(
            payload={"api_key": "invalid_xxxxxxxxxxxxxxxxxxx", "order_id": 1, "ok": True}
        )
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_result_cant_ack_other_user_order(db):
    """User Bob ne peut pas ack un order de Alice."""
    uid_alice = _create_premium_user("alice@test.com", api_key="a" * 32)
    _create_premium_user("bob@test.com", api_key="b" * 32)
    order_id = mt5_pending_orders_service.enqueue(uid_alice, "a" * 32, {"pair": "EUR/USD"})
    await app_module.api_ea_pending(api_key="a" * 32)

    # Bob essaie d'ack l'order d'Alice avec sa propre key
    result = await app_module.api_ea_result(
        payload={"api_key": "b" * 32, "order_id": order_id, "ok": True}
    )
    assert result == {"acked": False}  # record_result retourne False (api_key ne match pas)
    counts = mt5_pending_orders_service.count_by_status(user_id=uid_alice)
    assert counts == {"SENT": 1}  # toujours SENT


# ─── POST /api/ea/heartbeat ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_heartbeat_updates_timestamp(db):
    uid = _create_premium_user()
    cfg_before = users_service.get_broker_config(uid)
    assert "last_ea_heartbeat" not in cfg_before

    result = await app_module.api_ea_heartbeat(api_key="u" * 32)
    assert result == {"ok": True}

    cfg_after = users_service.get_broker_config(uid)
    assert "last_ea_heartbeat" in cfg_after


@pytest.mark.asyncio
async def test_heartbeat_rejects_invalid_api_key(db):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await app_module.api_ea_heartbeat(api_key="invalid_xxxxxxxxxxxxxxxxxxx")
    assert exc.value.status_code == 401
