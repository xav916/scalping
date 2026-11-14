"""Tests du watchdog bridge Kraken (backend/services/kraken_bridge_watchdog.py)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.services import kraken_bridge_watchdog as kbw


@pytest.fixture
def temp_state(tmp_path, monkeypatch):
    """Rebase STATE_PATH sur un tmp pour isoler les tests."""
    state_file = tmp_path / "kraken_bridge_watchdog.json"
    monkeypatch.setattr(kbw, "STATE_PATH", str(state_file))
    return state_file


def test_enabled_par_defaut(monkeypatch):
    monkeypatch.delenv("KRAKEN_BRIDGE_WATCHDOG_ENABLED", raising=False)
    assert kbw._enabled() is True


def test_disabled_si_env_false(monkeypatch):
    monkeypatch.setenv("KRAKEN_BRIDGE_WATCHDOG_ENABLED", "false")
    assert kbw._enabled() is False


def test_is_connected_accepte_200_sans_champ_connected():
    # Le bridge Kraken peut rendre {"ok": true} sans champ connected.
    assert kbw._is_connected({"ok": True}) is True


def test_is_connected_refuse_ok_false():
    assert kbw._is_connected({"ok": False, "error": "X"}) is False


def test_is_connected_respecte_connected_explicite_false():
    assert kbw._is_connected({"ok": True, "connected": False}) is False


def test_cooldown_elapsed_si_jamais_alerted():
    assert kbw._cooldown_elapsed(None, 60) is True


def test_cooldown_elapsed_si_alert_recente():
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(seconds=30)).isoformat()
    assert kbw._cooldown_elapsed(recent, 60) is False  # 30s < 60s


def test_cooldown_elapsed_si_alert_ancienne():
    now = datetime.now(timezone.utc)
    old = (now - timedelta(seconds=120)).isoformat()
    assert kbw._cooldown_elapsed(old, 60) is True  # 120s > 60s


def test_state_save_load_roundtrip(temp_state):
    kbw._save_state({"was_connected": False, "last_alert_at": "2026-11-14T20:00:00"})
    loaded = kbw._load_state()
    assert loaded["was_connected"] is False
    assert loaded["last_alert_at"] == "2026-11-14T20:00:00"


def test_state_load_defaut_si_absent(temp_state):
    loaded = kbw._load_state()
    assert loaded == {"was_connected": True, "last_alert_at": None}


@pytest.mark.asyncio
async def test_check_disabled_short_circuit(monkeypatch, temp_state):
    monkeypatch.setenv("KRAKEN_BRIDGE_WATCHDOG_ENABLED", "false")
    res = await kbw.check_and_alert()
    assert res["ran"] is False
    assert "disabled" in res["reason"]


@pytest.mark.asyncio
async def test_check_down_alerte_premiere_fois(monkeypatch, temp_state):
    """Si Kraken DOWN et état UP précédent → alerte émise immédiatement."""
    monkeypatch.setenv("KRAKEN_BRIDGE_WATCHDOG_ENABLED", "true")
    monkeypatch.setenv("KRAKEN_BRIDGE_URL", "http://fake:9999")
    monkeypatch.setenv("KRAKEN_BRIDGE_API_KEY", "fake")

    async def _fake(): return {"ok": False, "error": "connection_refused"}
    monkeypatch.setattr(kbw, "_fetch_health", _fake)

    sent_alerts = []
    async def _fake_down(h): sent_alerts.append(("down", h))
    async def _fake_up(h): sent_alerts.append(("up", h))
    monkeypatch.setattr(kbw, "_send_down_alert", _fake_down)
    monkeypatch.setattr(kbw, "_send_recovery_alert", _fake_up)

    kbw._save_state({"was_connected": True, "last_alert_at": None})
    res = await kbw.check_and_alert()

    assert res["ran"] is True
    assert res["connected"] is False
    assert res["alerted"] is True
    assert len(sent_alerts) == 1
    assert sent_alerts[0][0] == "down"
    assert kbw._load_state()["was_connected"] is False


@pytest.mark.asyncio
async def test_check_down_cooldown_respecte(monkeypatch, temp_state):
    """Si DOWN récemment alerté, pas de ré-alerte avant cooldown."""
    monkeypatch.setenv("KRAKEN_BRIDGE_WATCHDOG_ENABLED", "true")
    monkeypatch.setenv("KRAKEN_BRIDGE_WATCHDOG_COOLDOWN_SEC", "60")
    monkeypatch.setenv("KRAKEN_BRIDGE_URL", "http://fake:9999")

    async def _fake(): return {"ok": False, "error": "still_down"}
    monkeypatch.setattr(kbw, "_fetch_health", _fake)

    sent = []
    async def _fake_down(h): sent.append("down")
    monkeypatch.setattr(kbw, "_send_down_alert", _fake_down)

    recent = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    kbw._save_state({"was_connected": False, "last_alert_at": recent})

    res = await kbw.check_and_alert()
    assert res["ran"] is True
    assert res["connected"] is False
    assert res["alerted"] is False
    assert sent == []


@pytest.mark.asyncio
async def test_check_recovery_alerte_remontee(monkeypatch, temp_state):
    """Si Kraken UP et état DOWN précédent → alerte recovery."""
    monkeypatch.setenv("KRAKEN_BRIDGE_WATCHDOG_ENABLED", "true")
    monkeypatch.setenv("KRAKEN_BRIDGE_URL", "http://fake:9999")

    async def _fake(): return {"ok": True, "connected": True, "mode": "live"}
    monkeypatch.setattr(kbw, "_fetch_health", _fake)

    sent = []
    async def _fake_up(h): sent.append(("up", h.get("mode")))
    async def _fake_down(h): sent.append(("down", h))
    monkeypatch.setattr(kbw, "_send_recovery_alert", _fake_up)
    monkeypatch.setattr(kbw, "_send_down_alert", _fake_down)

    kbw._save_state({"was_connected": False, "last_alert_at": "2026-11-14T20:00:00"})

    res = await kbw.check_and_alert()
    assert res["ran"] is True
    assert res["connected"] is True
    assert res["alerted"] is True
    assert sent == [("up", "live")]
    assert kbw._load_state()["was_connected"] is True
    assert kbw._load_state()["last_alert_at"] is None


@pytest.mark.asyncio
async def test_check_sans_url_renvoie_down(monkeypatch, temp_state):
    """Pas de KRAKEN_BRIDGE_URL → health rend ok=False, pas d'exception."""
    monkeypatch.setenv("KRAKEN_BRIDGE_WATCHDOG_ENABLED", "true")
    monkeypatch.delenv("KRAKEN_BRIDGE_URL", raising=False)

    sent = []
    async def _fake_down(h): sent.append(h.get("error"))
    monkeypatch.setattr(kbw, "_send_down_alert", _fake_down)

    kbw._save_state({"was_connected": True, "last_alert_at": None})
    res = await kbw.check_and_alert()

    assert res["ran"] is True
    assert res["connected"] is False
    assert res["alerted"] is True
    assert sent == ["no_KRAKEN_BRIDGE_URL"]
