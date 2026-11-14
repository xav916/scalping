"""Tests du watchdog Gateway IBKR (backend/services/ibkr_gateway_watchdog.py)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from backend.services import ibkr_gateway_watchdog as igw


@pytest.fixture
def temp_state(tmp_path, monkeypatch):
    """Rebase STATE_PATH sur un tmp pour isoler les tests."""
    state_file = tmp_path / "ibkr_watchdog.json"
    monkeypatch.setattr(igw, "STATE_PATH", str(state_file))
    return state_file


def test_enabled_par_defaut(monkeypatch):
    monkeypatch.delenv("IBKR_GATEWAY_WATCHDOG_ENABLED", raising=False)
    assert igw._enabled() is True


def test_disabled_si_env_false(monkeypatch):
    monkeypatch.setenv("IBKR_GATEWAY_WATCHDOG_ENABLED", "false")
    assert igw._enabled() is False


def test_cooldown_elapsed_si_jamais_alerted():
    assert igw._cooldown_elapsed(None, 60) is True


def test_cooldown_elapsed_si_alert_recente():
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(seconds=30)).isoformat()
    assert igw._cooldown_elapsed(recent, 60) is False  # 30s < 60s


def test_cooldown_elapsed_si_alert_ancienne():
    now = datetime.now(timezone.utc)
    old = (now - timedelta(seconds=120)).isoformat()
    assert igw._cooldown_elapsed(old, 60) is True  # 120s > 60s


def test_state_save_load_roundtrip(temp_state):
    igw._save_state({"was_connected": False, "last_alert_at": "2026-11-14T20:00:00"})
    loaded = igw._load_state()
    assert loaded["was_connected"] is False
    assert loaded["last_alert_at"] == "2026-11-14T20:00:00"


def test_state_load_defaut_si_absent(temp_state):
    loaded = igw._load_state()
    assert loaded == {"was_connected": True, "last_alert_at": None}


@pytest.mark.asyncio
async def test_check_disabled_short_circuit(monkeypatch, temp_state):
    monkeypatch.setenv("IBKR_GATEWAY_WATCHDOG_ENABLED", "false")
    res = await igw.check_and_alert()
    assert res["ran"] is False
    assert "disabled" in res["reason"]


@pytest.mark.asyncio
async def test_check_down_alerte_premiere_fois(monkeypatch, temp_state):
    """Si Gateway DOWN et état UP précédent → alerte émise immédiatement."""
    monkeypatch.setenv("IBKR_GATEWAY_WATCHDOG_ENABLED", "true")
    monkeypatch.setenv("IBKR_BRIDGE_URL", "http://fake:9999")
    monkeypatch.setenv("IBKR_BRIDGE_API_KEY", "fake")

    # Fake fetch qui dit DOWN
    async def _fake(): return {"ok": False, "error": "connection_refused"}
    monkeypatch.setattr(igw, "_fetch_health", _fake)

    sent_alerts = []
    async def _fake_down(h): sent_alerts.append(("down", h))
    async def _fake_up(h): sent_alerts.append(("up", h))
    monkeypatch.setattr(igw, "_send_down_alert", _fake_down)
    monkeypatch.setattr(igw, "_send_recovery_alert", _fake_up)

    # état initial = UP
    igw._save_state({"was_connected": True, "last_alert_at": None})
    res = await igw.check_and_alert()

    assert res["ran"] is True
    assert res["connected"] is False
    assert res["alerted"] is True
    assert len(sent_alerts) == 1
    assert sent_alerts[0][0] == "down"
    # État doit maintenant être DOWN
    assert igw._load_state()["was_connected"] is False


@pytest.mark.asyncio
async def test_check_down_cooldown_respecte(monkeypatch, temp_state):
    """Si DOWN récemment alerté, pas de ré-alerte avant cooldown."""
    monkeypatch.setenv("IBKR_GATEWAY_WATCHDOG_ENABLED", "true")
    monkeypatch.setenv("IBKR_GATEWAY_WATCHDOG_COOLDOWN_SEC", "60")
    monkeypatch.setenv("IBKR_BRIDGE_URL", "http://fake:9999")

    async def _fake(): return {"ok": False, "error": "still_down"}
    monkeypatch.setattr(igw, "_fetch_health", _fake)

    sent = []
    async def _fake_down(h): sent.append("down")
    monkeypatch.setattr(igw, "_send_down_alert", _fake_down)

    # état : alert envoyé il y a 10s, encore dans cooldown 60s
    recent = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    igw._save_state({"was_connected": False, "last_alert_at": recent})

    res = await igw.check_and_alert()
    assert res["ran"] is True
    assert res["connected"] is False
    assert res["alerted"] is False  # cooldown non écoulé
    assert sent == []


@pytest.mark.asyncio
async def test_check_recovery_alerte_remontee(monkeypatch, temp_state):
    """Si Gateway UP et état DOWN précédent → alerte recovery."""
    monkeypatch.setenv("IBKR_GATEWAY_WATCHDOG_ENABLED", "true")
    monkeypatch.setenv("IBKR_BRIDGE_URL", "http://fake:9999")

    async def _fake(): return {
        "ok": True, "connected": True, "accounts": ["DUR358393"],
        "orders_allowed": True, "read_only": False,
    }
    monkeypatch.setattr(igw, "_fetch_health", _fake)

    sent = []
    async def _fake_up(h): sent.append(("up", h.get("accounts")))
    async def _fake_down(h): sent.append(("down", h))
    monkeypatch.setattr(igw, "_send_recovery_alert", _fake_up)
    monkeypatch.setattr(igw, "_send_down_alert", _fake_down)

    # état précédent = DOWN
    igw._save_state({"was_connected": False, "last_alert_at": "2026-11-14T20:00:00"})

    res = await igw.check_and_alert()
    assert res["ran"] is True
    assert res["connected"] is True
    assert res["alerted"] is True
    assert sent == [("up", ["DUR358393"])]
    # État UP, cooldown reset
    assert igw._load_state()["was_connected"] is True
    assert igw._load_state()["last_alert_at"] is None
