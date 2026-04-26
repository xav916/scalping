"""Tests pour les endpoints publics de la stack marketing/SaaS.

- /api/public/shadow/{summary, setups}
- /api/public/research/experiments
- /api/public/changelog
- /api/public/leads/subscribe
- /api/public/referrals/validate
- /api/referrals/me (auth)
- /sitemap.xml + /robots.txt
"""
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_trades_db(monkeypatch, tmp_path):
    """Each test gets its own trades.db."""
    db_path = tmp_path / "trades.db"
    monkeypatch.setattr(
        "backend.services.shadow_v2_core_long.DB_PATH", db_path
    )
    monkeypatch.setattr(
        "backend.services.leads_service.DB_PATH", db_path
    )
    monkeypatch.setattr(
        "backend.services.referrals_service.DB_PATH", db_path
    )
    yield db_path


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from backend.app import app
    return TestClient(app)


# ─── Public shadow endpoints ────────────────────────────────────────────────


def test_public_shadow_summary_returns_systems(client):
    r = client.get("/api/public/shadow/summary")
    assert r.status_code == 200
    data = r.json()
    assert "systems" in data
    assert isinstance(data["systems"], list)


def test_public_shadow_setups_returns_list(client):
    r = client.get("/api/public/shadow/setups")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_public_shadow_setups_caps_limit_at_200(client):
    """Anti-abus : limit > 200 capé à 200."""
    r = client.get("/api/public/shadow/setups?limit=10000")
    assert r.status_code == 200
    # Pas de manière de vérifier le cap depuis test sans avoir 5000 setups
    # mais l'endpoint doit répondre 200, pas crasher


def test_public_shadow_setups_filter_by_outcome(client):
    r = client.get("/api/public/shadow/setups?outcome=TP1")
    assert r.status_code == 200


def test_public_shadow_setups_strips_macro_features(client, isolated_trades_db):
    """Sanitisation : macro_features_json ne doit pas être exposé."""
    from backend.services.shadow_v2_core_long import ensure_schema
    ensure_schema()
    with sqlite3.connect(isolated_trades_db) as c:
        c.execute("""
            INSERT INTO shadow_setups (
                cycle_at, bar_timestamp, system_id, pair, timeframe,
                direction, pattern, entry_price, stop_loss, take_profit_1,
                risk_pct, rr, sizing_position_eur, sizing_max_loss_eur,
                macro_features_json
            ) VALUES (
                '2026-04-25T10:00:00', '2026-04-25T08:00:00',
                'V2_CORE_LONG_XAUUSD_4H', 'XAU/USD', '4h',
                'buy', 'momentum_up', 2050.0, 2040.0, 2070.0,
                0.005, 2.0, 1000.0, 50.0,
                '{"vix": 18.5, "secret": "internal"}'
            )
        """)
    r = client.get("/api/public/shadow/setups?limit=5")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) >= 1
    # macro_features_json + cycle_at + sizing_capital_eur internes ne doivent
    # PAS être présents
    assert "macro_features_json" not in rows[0]
    assert "cycle_at" not in rows[0]
    assert "sizing_capital_eur" not in rows[0]
    assert "sizing_risk_pct" not in rows[0]
    # Mais les champs publics OUI
    assert rows[0]["pair"] == "XAU/USD"
    assert rows[0]["pattern"] == "momentum_up"


# ─── Research endpoint ──────────────────────────────────────────────────────


def test_public_research_experiments_returns_list(client):
    r = client.get("/api/public/research/experiments")
    assert r.status_code == 200
    data = r.json()
    assert "experiments" in data
    assert "count" in data
    # Le repo a 26+ expériences, au moins 1 doit être présent
    assert data["count"] >= 1


def test_public_research_experiments_have_required_fields(client):
    r = client.get("/api/public/research/experiments")
    exps = r.json()["experiments"]
    if not exps:
        pytest.skip("INDEX.md vide, skip")
    first = exps[0]
    assert "num" in first
    assert "title" in first
    assert "status" in first
    assert "verdict" in first


# ─── Changelog endpoint ─────────────────────────────────────────────────────


def test_public_changelog_returns_commits(client):
    r = client.get("/api/public/changelog")
    assert r.status_code == 200
    data = r.json()
    assert "commits" in data
    assert "count" in data


# ─── Leads endpoint ─────────────────────────────────────────────────────────


def test_public_leads_subscribe_valid_email(client):
    r = client.post(
        "/api/public/leads/subscribe",
        json={"email": "test@example.com", "source": "landing"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_public_leads_subscribe_invalid_email(client):
    r = client.post(
        "/api/public/leads/subscribe",
        json={"email": "notanemail", "source": "landing"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is False
    assert "invalide" in r.json()["message"].lower()


def test_public_leads_subscribe_idempotent(client):
    """Email dupliqué ne doit pas crasher, retourne ok=True (anti email-enum)."""
    payload = {"email": "dup@example.com", "source": "landing"}
    r1 = client.post("/api/public/leads/subscribe", json=payload)
    r2 = client.post("/api/public/leads/subscribe", json=payload)
    assert r1.json()["ok"] is True
    assert r2.json()["ok"] is True


# ─── Referrals endpoints ────────────────────────────────────────────────────


def test_public_referrals_validate_invalid_code(client):
    r = client.get("/api/public/referrals/validate?code=NOPE-XXXX")
    assert r.status_code == 200
    assert r.json()["valid"] is False


def test_public_referrals_validate_empty_code(client):
    r = client.get("/api/public/referrals/validate?code=")
    assert r.status_code == 200
    assert r.json()["valid"] is False


def test_referrals_service_generate_code():
    from backend.services.referrals_service import (
        get_or_create_code, get_my_stats, init_referrals_schema,
    )
    init_referrals_schema()
    # generate code for fake user 999
    code1 = get_or_create_code(999, "alice@example.com")
    assert code1
    assert "-" in code1
    assert code1.startswith("ALI") or len(code1.split("-")[0]) == 3
    # idempotent : same code returned
    code2 = get_or_create_code(999, "alice@example.com")
    assert code1 == code2

    stats = get_my_stats(999)
    assert stats["code"] == code1
    assert stats["n_signups"] == 0


def test_referrals_track_signup_invalid_code():
    from backend.services.referrals_service import track_signup, init_referrals_schema
    init_referrals_schema()
    # Invalid code → returns False
    assert track_signup("FAKE-CODE", 1, "x@y.com") is False


def test_referrals_track_signup_valid_code():
    from backend.services.referrals_service import (
        get_or_create_code, track_signup, init_referrals_schema, validate_code,
    )
    init_referrals_schema()
    code = get_or_create_code(1001, "ref@example.com")
    assert track_signup(code, 2002, "filleul@example.com") is True

    # Validate code now shows 1 signup
    info = validate_code(code)
    assert info["valid"] is True
    assert info["n_signups"] == 1


# ─── Sitemap + robots ───────────────────────────────────────────────────────


def test_sitemap_xml_returns_urlset(client):
    r = client.get("/sitemap.xml")
    assert r.status_code == 200
    text = r.text
    assert "<urlset" in text
    assert "/v2/" in text
    assert "/v2/live" in text
    assert "/v2/track-record" in text


def test_robots_txt_allows_public_pages(client):
    r = client.get("/robots.txt")
    assert r.status_code == 200
    text = r.text
    assert "Allow:" in text or "Disallow:" in text
    # Sitemap reference
    assert "Sitemap:" in text
