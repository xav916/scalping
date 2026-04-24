"""Tests consentement CGU/CGV/Privacy à l'inscription.

Obligation UE : le signup public doit exiger l'acceptation explicite des
documents légaux, et stocker timestamp + version acceptée en DB (preuve
de consentement en cas de litige).
"""

import sqlite3

import pytest
from fastapi import HTTPException

from backend.services import users_service
from backend.services.users_service import TERMS_CURRENT_VERSION


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_file = tmp_path / "trades.db"
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE personal_trades (id INTEGER PRIMARY KEY, user TEXT)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(users_service, "_DB_PATH", db_file)
    users_service.init_users_schema()
    return db_file


# ─── Schema ──────────────────────────────────────────────────

def test_schema_has_terms_columns(db):
    with sqlite3.connect(db) as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(users)").fetchall()]
    assert "terms_accepted_at" in cols
    assert "terms_version" in cols


# ─── create_user : tracking consentement ─────────────────────

def test_create_user_with_terms_version_stores_acceptance(db):
    uid = users_service.create_user(
        "alice@test.com", "pw12345678",
        terms_version=TERMS_CURRENT_VERSION,
    )
    user = users_service.get_user_by_id(uid)
    assert user["terms_version"] == TERMS_CURRENT_VERSION
    assert user["terms_accepted_at"] is not None
    # Format ISO attendu
    assert "T" in user["terms_accepted_at"]


def test_create_user_without_terms_version_leaves_null(db):
    """Backward compat : seed/admin scripts qui créent des users via code
    direct (pas via endpoint public) n'ont pas besoin de consentement tracé.
    """
    uid = users_service.create_user("admin@test.com", "pw12345678")
    user = users_service.get_user_by_id(uid)
    assert user["terms_version"] is None
    assert user["terms_accepted_at"] is None


# ─── Endpoint /api/auth/signup ───────────────────────────────

def test_endpoint_signup_rejects_without_accepted_terms(db, monkeypatch):
    """Signup public sans checkbox cochée → 400."""
    from backend import app as app_module
    from config import settings
    import asyncio

    monkeypatch.setattr(settings, "SAAS_SIGNUP_ENABLED", True)
    monkeypatch.setattr(app_module, "SAAS_SIGNUP_ENABLED", True)

    from backend.tests.conftest import mock_request
    with pytest.raises(HTTPException) as exc:
        asyncio.run(app_module.api_signup(
            mock_request(),
            {"email": "alice@test.com", "password": "pw12345678"},  # pas d'accepted_terms
        ))
    assert exc.value.status_code == 400
    assert "CGU" in exc.value.detail or "accepter" in exc.value.detail.lower()


def test_endpoint_signup_rejects_when_accepted_terms_false(db, monkeypatch):
    """accepted_terms=False explicite → 400."""
    from backend import app as app_module
    from config import settings
    import asyncio

    monkeypatch.setattr(settings, "SAAS_SIGNUP_ENABLED", True)
    monkeypatch.setattr(app_module, "SAAS_SIGNUP_ENABLED", True)

    from backend.tests.conftest import mock_request
    with pytest.raises(HTTPException) as exc:
        asyncio.run(app_module.api_signup(
            mock_request(),
            {"email": "alice@test.com", "password": "pw12345678", "accepted_terms": False},
        ))
    assert exc.value.status_code == 400


def test_endpoint_signup_accepts_with_accepted_terms_true(db, monkeypatch):
    """accepted_terms=True + store terms_version + terms_accepted_at."""
    from backend import app as app_module
    from backend.services import user_email_service
    from config import settings
    import asyncio

    monkeypatch.setattr(settings, "SAAS_SIGNUP_ENABLED", True)
    monkeypatch.setattr(app_module, "SAAS_SIGNUP_ENABLED", True)
    monkeypatch.setattr(user_email_service, "EMAIL_SMTP_HOST", "")
    monkeypatch.setattr(user_email_service, "EMAIL_FROM", "")

    from backend.tests.conftest import mock_request
    result = asyncio.run(app_module.api_signup(
        mock_request(),
        {
            "email": "alice@test.com",
            "password": "pw12345678",
            "accepted_terms": True,
        },
    ))
    uid = result["user_id"]
    user = users_service.get_user_by_id(uid)
    assert user["terms_version"] == TERMS_CURRENT_VERSION
    assert user["terms_accepted_at"] is not None
