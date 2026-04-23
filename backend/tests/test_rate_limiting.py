"""Tests rate limiting — vérifie que les endpoints sensibles renvoient 429
après N requêtes depuis la même IP.

Le fixture `rate_limit_on` (conftest.py) réactive slowapi pour ces tests
uniquement ; il est désactivé par défaut pour les autres tests qui appellent
les handlers async sans passer par TestClient.
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.services import users_service


@pytest.fixture
def db(tmp_path, monkeypatch):
    """DB SQLite isolée, même approche que les autres tests qui mutent users."""
    db_file = tmp_path / "trades.db"
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE personal_trades (id INTEGER PRIMARY KEY, user TEXT)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(users_service, "_DB_PATH", db_file)
    users_service.init_users_schema()
    return db_file


@pytest.fixture
def client():
    return TestClient(app)


# ─── /api/login ─────────────────────────────────────────────

def test_login_rate_limit_triggers_after_10_per_minute(client, db, rate_limit_on):
    """10 POST /api/login OK, le 11ème → 429."""
    for i in range(10):
        r = client.post("/api/login", json={"username": f"ghost{i}", "password": "x"})
        assert r.status_code == 401, f"attempt {i+1} expected 401, got {r.status_code}"

    r = client.post("/api/login", json={"username": "ghost11", "password": "x"})
    assert r.status_code == 429
    body = r.json()
    assert "retry_after_seconds" in body
    assert "Retry-After" in r.headers


# ─── /api/auth/signup ───────────────────────────────────────

def test_signup_rate_limit_triggers_after_5_per_hour(client, db, rate_limit_on, monkeypatch):
    """5 POST /api/auth/signup OK, le 6ème → 429."""
    import config.settings as settings
    monkeypatch.setattr(settings, "SAAS_SIGNUP_ENABLED", True)
    import backend.app as app_module
    monkeypatch.setattr(app_module, "SAAS_SIGNUP_ENABLED", True)

    for i in range(5):
        r = client.post(
            "/api/auth/signup",
            json={"email": f"user{i}@test.com", "password": "password123"},
        )
        assert r.status_code != 429, f"attempt {i+1} hit rate limit prematurely"

    r = client.post(
        "/api/auth/signup",
        json={"email": "user6@test.com", "password": "password123"},
    )
    assert r.status_code == 429


# ─── /api/auth/forgot-password ──────────────────────────────

def test_forgot_password_rate_limit_triggers_after_3_per_hour(client, db, rate_limit_on):
    """3 POST /api/auth/forgot-password OK, le 4ème → 429."""
    for i in range(3):
        r = client.post(
            "/api/auth/forgot-password",
            json={"email": f"ghost{i}@test.com"},
        )
        assert r.status_code == 200, f"attempt {i+1} expected 200, got {r.status_code}"

    r = client.post(
        "/api/auth/forgot-password",
        json={"email": "ghost4@test.com"},
    )
    assert r.status_code == 429


# ─── /api/auth/reset-password ───────────────────────────────

def test_reset_password_rate_limit_triggers_after_10_per_hour(client, db, rate_limit_on):
    """Brute-force protection sur token reset : 10 OK, 11ème → 429."""
    for i in range(10):
        r = client.post(
            "/api/auth/reset-password",
            json={"token": f"fake{i}", "new_password": "newpass123"},
        )
        assert r.status_code == 400, f"attempt {i+1} expected 400, got {r.status_code}"

    r = client.post(
        "/api/auth/reset-password",
        json={"token": "fake11", "new_password": "newpass123"},
    )
    assert r.status_code == 429


# ─── /api/auth/verify-email ─────────────────────────────────

def test_verify_email_rate_limit_triggers_after_20_per_hour(client, db, rate_limit_on):
    """Brute-force protection sur token verify-email : 20 OK, 21ème → 429."""
    for i in range(20):
        r = client.post(
            "/api/auth/verify-email",
            json={"token": f"fake{i}"},
        )
        assert r.status_code == 400, f"attempt {i+1} expected 400, got {r.status_code}"

    r = client.post(
        "/api/auth/verify-email",
        json={"token": "fake21"},
    )
    assert r.status_code == 429


# ─── key_func comportement X-Forwarded-For ──────────────────

def test_rate_limit_key_respects_x_forwarded_for(client, db, rate_limit_on):
    """Deux IP distinctes (via X-Forwarded-For) ne se partagent pas le
    compteur : chaque IP garde son propre quota."""
    for i in range(10):
        r = client.post(
            "/api/login",
            json={"username": "x", "password": "y"},
            headers={"X-Forwarded-For": "1.2.3.4"},
        )
        assert r.status_code == 401

    r = client.post(
        "/api/login",
        json={"username": "x", "password": "y"},
        headers={"X-Forwarded-For": "1.2.3.4"},
    )
    assert r.status_code == 429

    r = client.post(
        "/api/login",
        json={"username": "x", "password": "y"},
        headers={"X-Forwarded-For": "5.6.7.8"},
    )
    assert r.status_code == 401


# ─── Endpoints non rate-limited (sanity) ────────────────────

def test_health_endpoint_not_rate_limited(client, db, rate_limit_on):
    """/api/health ne doit pas être limité — monitoring l'appelle en boucle."""
    for _ in range(30):
        r = client.get("/api/health")
        assert r.status_code != 429


def test_stripe_webhook_not_rate_limited(client, db, rate_limit_on):
    """/api/stripe/webhook ne doit pas être limité — Stripe peut retry
    en burst. La signature HMAC protège déjà.
    """
    for _ in range(15):
        r = client.post("/api/stripe/webhook", content=b"{}")
        # 503 si STRIPE_ENABLED=false, ou 400 si signature invalide.
        # L'important : jamais 429.
        assert r.status_code != 429
