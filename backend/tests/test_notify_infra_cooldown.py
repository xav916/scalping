"""Tests pour le cooldown de /api/admin/notify-infra-telegram.

Vérifie qu'un payload avec dedup_key + cooldown_seconds suppress les
envois rapprochés mais laisse passer le premier et ceux hors fenêtre.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient


VALID_TOKEN = "shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg"


@pytest.fixture
def client(monkeypatch):
    """Stub Telegram HTTP + force env settings configurés."""
    from backend.app import app
    import config.settings as _settings

    monkeypatch.setattr(_settings, "INFRA_TELEGRAM_BOT_TOKEN", "fake_token", raising=False)
    monkeypatch.setattr(_settings, "INFRA_TELEGRAM_CHAT_ID", "12345", raising=False)

    class _FakeResponse:
        status_code = 200
        text = "ok"

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def post(self, *a, **kw):
            return _FakeResponse()

    import httpx as _httpx
    monkeypatch.setattr(_httpx, "AsyncClient", _FakeClient)

    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_cooldown_state():
    """Reset l'état in-memory entre tests pour isolation."""
    from backend.app import _INFRA_ALERT_LAST_SENT
    _INFRA_ALERT_LAST_SENT.clear()
    yield
    _INFRA_ALERT_LAST_SENT.clear()


def test_no_dedup_key_always_sends(client):
    """Sans dedup_key → comportement legacy, chaque appel envoie."""
    r1 = client.post(
        f"/api/admin/notify-infra-telegram?token={VALID_TOKEN}",
        json={"title": "Test", "body": "first"},
    )
    r2 = client.post(
        f"/api/admin/notify-infra-telegram?token={VALID_TOKEN}",
        json={"title": "Test", "body": "second"},
    )
    assert r1.status_code == 200 and r1.json()["sent"] is True
    assert r2.status_code == 200 and r2.json()["sent"] is True


def test_dedup_key_without_cooldown_always_sends(client):
    """dedup_key sans cooldown_seconds > 0 → pas de suppression."""
    payload = {"title": "T", "body": "b", "dedup_key": "k1"}
    r1 = client.post(f"/api/admin/notify-infra-telegram?token={VALID_TOKEN}", json=payload)
    r2 = client.post(f"/api/admin/notify-infra-telegram?token={VALID_TOKEN}", json=payload)
    assert r1.json()["sent"] is True
    assert r2.json()["sent"] is True


def test_cooldown_suppresses_second_call(client):
    """Premier envoi OK, second sous cooldown → skipped."""
    payload = {
        "title": "EA health",
        "body": "executed_rate low",
        "dedup_key": "ea_health_low",
        "cooldown_seconds": 3600,
    }
    r1 = client.post(f"/api/admin/notify-infra-telegram?token={VALID_TOKEN}", json=payload)
    r2 = client.post(f"/api/admin/notify-infra-telegram?token={VALID_TOKEN}", json=payload)

    assert r1.status_code == 200 and r1.json()["sent"] is True
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["sent"] is False
    assert body2["skipped"] == "cooldown"
    assert body2["dedup_key"] == "ea_health_low"
    assert body2["cooldown_seconds"] == 3600
    assert 0 <= body2["elapsed_seconds"] <= 5
    assert body2["remaining_seconds"] > 3500


def test_cooldown_expired_lets_through(client):
    """Si last_sent_at > cooldown → on relaisse passer."""
    from backend.app import _INFRA_ALERT_LAST_SENT
    payload = {
        "title": "X",
        "body": "y",
        "dedup_key": "k_expired",
        "cooldown_seconds": 60,
    }
    # Simule un envoi qui date de 2h → bien hors fenêtre 60s
    _INFRA_ALERT_LAST_SENT["k_expired"] = datetime.now(timezone.utc) - timedelta(hours=2)
    r = client.post(f"/api/admin/notify-infra-telegram?token={VALID_TOKEN}", json=payload)
    assert r.status_code == 200
    assert r.json()["sent"] is True


def test_different_dedup_keys_are_independent(client):
    """Cooldown sur key A ne bloque pas key B."""
    base = {"title": "T", "body": "b", "cooldown_seconds": 3600}
    r1 = client.post(
        f"/api/admin/notify-infra-telegram?token={VALID_TOKEN}",
        json={**base, "dedup_key": "key_a"},
    )
    r2 = client.post(
        f"/api/admin/notify-infra-telegram?token={VALID_TOKEN}",
        json={**base, "dedup_key": "key_b"},
    )
    r3 = client.post(
        f"/api/admin/notify-infra-telegram?token={VALID_TOKEN}",
        json={**base, "dedup_key": "key_a"},
    )
    assert r1.json()["sent"] is True
    assert r2.json()["sent"] is True
    assert r3.json()["sent"] is False
    assert r3.json()["skipped"] == "cooldown"


def test_invalid_cooldown_seconds_falls_back_to_zero(client):
    """cooldown_seconds non-numérique → pas de cooldown, envoi normal."""
    payload = {
        "title": "T",
        "body": "b",
        "dedup_key": "k_bad",
        "cooldown_seconds": "abc",
    }
    r1 = client.post(f"/api/admin/notify-infra-telegram?token={VALID_TOKEN}", json=payload)
    r2 = client.post(f"/api/admin/notify-infra-telegram?token={VALID_TOKEN}", json=payload)
    assert r1.json()["sent"] is True
    assert r2.json()["sent"] is True
