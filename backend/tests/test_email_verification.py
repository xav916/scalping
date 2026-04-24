"""Tests email verification flow."""

import sqlite3
from unittest.mock import patch

import pytest

from backend.services import users_service


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


# ─── Schema ─────────────────────────────────────────

def test_schema_has_verify_columns(db):
    with sqlite3.connect(db) as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(users)").fetchall()]
    assert "email_verified_at" in cols
    assert "email_verification_token" in cols


# ─── Helpers ─────────────────────────────────────────

def test_new_user_is_not_verified(db):
    uid = users_service.create_user("alice@test.com", "pw12345678")
    user = users_service.get_user_by_id(uid)
    assert users_service.is_email_verified(user) is False


def test_generate_token_persists(db):
    uid = users_service.create_user("alice@test.com", "pw12345678")
    token = users_service.generate_email_verification_token(uid)
    user = users_service.get_user_by_id(uid)
    assert user["email_verification_token"] == token


def test_verify_email_token_marks_verified(db):
    uid = users_service.create_user("alice@test.com", "pw12345678")
    token = users_service.generate_email_verification_token(uid)
    result = users_service.verify_email_token(token)
    assert result == uid
    user = users_service.get_user_by_id(uid)
    assert user["email_verified_at"] is not None
    # Le token est invalidé après usage.
    assert user["email_verification_token"] is None


def test_verify_email_token_rejects_garbage(db):
    assert users_service.verify_email_token("not-a-token") is None
    assert users_service.verify_email_token("") is None


def test_verify_email_token_single_use(db):
    uid = users_service.create_user("alice@test.com", "pw12345678")
    token = users_service.generate_email_verification_token(uid)
    users_service.verify_email_token(token)
    # 2e usage → None car token a été invalidé.
    assert users_service.verify_email_token(token) is None


def test_new_token_overrides_previous(db):
    uid = users_service.create_user("alice@test.com", "pw12345678")
    t1 = users_service.generate_email_verification_token(uid)
    t2 = users_service.generate_email_verification_token(uid)
    assert t1 != t2
    assert users_service.verify_email_token(t1) is None
    assert users_service.verify_email_token(t2) == uid


def test_mark_email_auto_verified(db):
    uid = users_service.create_user("alice@test.com", "pw12345678")
    users_service.mark_email_auto_verified(uid)
    assert users_service.is_email_verified(users_service.get_user_by_id(uid))


# ─── Endpoints ─────────────────────────────────────────

def test_endpoint_verify_email_success(db):
    from backend import app as app_module
    import asyncio

    uid = users_service.create_user("alice@test.com", "pw12345678")
    token = users_service.generate_email_verification_token(uid)
    from backend.tests.conftest import mock_request
    result = asyncio.run(app_module.api_verify_email(mock_request(), {"token": token}))
    assert result == {"ok": True, "user_id": uid}


def test_endpoint_verify_email_invalid(db):
    from fastapi import HTTPException
    from backend import app as app_module
    import asyncio

    with pytest.raises(HTTPException) as exc:
        from backend.tests.conftest import mock_request
        asyncio.run(app_module.api_verify_email(mock_request(), {"token": "bad"}))
    assert exc.value.status_code == 400


def test_endpoint_verify_email_empty(db):
    from fastapi import HTTPException
    from backend import app as app_module
    import asyncio

    with pytest.raises(HTTPException) as exc:
        from backend.tests.conftest import mock_request
        asyncio.run(app_module.api_verify_email(mock_request(), {"token": ""}))
    assert exc.value.status_code == 400


def test_endpoint_resend_verification_already_verified(db):
    from backend import app as app_module
    from backend.auth import AuthContext
    import asyncio

    uid = users_service.create_user("alice@test.com", "pw12345678")
    users_service.mark_email_auto_verified(uid)
    ctx = AuthContext(username="alice@test.com", user_id=uid)
    from backend.tests.conftest import mock_request
    result = asyncio.run(app_module.api_resend_verification(mock_request(), ctx=ctx))
    assert result["already_verified"] is True


def test_endpoint_resend_verification_sends_email(db, monkeypatch):
    from backend import app as app_module
    from backend.auth import AuthContext
    from backend.services import user_email_service
    import asyncio

    uid = users_service.create_user("alice@test.com", "pw12345678")
    monkeypatch.setattr(user_email_service, "EMAIL_SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(user_email_service, "EMAIL_FROM", "test@test.com")

    ctx = AuthContext(username="alice@test.com", user_id=uid)
    from backend.tests.conftest import mock_request
    with patch.object(user_email_service, "send_email_verification", return_value=True) as mk:
        result = asyncio.run(app_module.api_resend_verification(mock_request(), ctx=ctx))
    assert result["ok"] is True
    mk.assert_called_once()


def test_endpoint_resend_verification_smtp_off_returns_503(db):
    from fastapi import HTTPException
    from backend import app as app_module
    from backend.auth import AuthContext
    from backend.services import user_email_service
    import asyncio

    uid = users_service.create_user("alice@test.com", "pw12345678")
    # SMTP off par défaut dans les tests
    assert not user_email_service.is_configured()
    ctx = AuthContext(username="alice@test.com", user_id=uid)
    from backend.tests.conftest import mock_request
    with pytest.raises(HTTPException) as exc:
        asyncio.run(app_module.api_resend_verification(mock_request(), ctx=ctx))
    assert exc.value.status_code == 503


# ─── Signup auto-verify quand SMTP off ─────────────────

def test_signup_auto_verifies_when_smtp_off(db, monkeypatch):
    from backend import app as app_module
    from backend.services import user_email_service
    from config import settings
    import asyncio

    monkeypatch.setattr(user_email_service, "EMAIL_SMTP_HOST", "")
    monkeypatch.setattr(user_email_service, "EMAIL_FROM", "")
    monkeypatch.setattr(settings, "SAAS_SIGNUP_ENABLED", True)
    monkeypatch.setattr(app_module, "SAAS_SIGNUP_ENABLED", True)

    from backend.tests.conftest import mock_request
    result = asyncio.run(
        app_module.api_signup(
            mock_request(),
            {"email": "alice@test.com", "password": "pw12345678", "accepted_terms": True},
        )
    )
    uid = result["user_id"]
    user = users_service.get_user_by_id(uid)
    assert users_service.is_email_verified(user) is True


# ─── Gate Stripe checkout ─────────────────────────────

def test_stripe_checkout_blocked_if_unverified(db, monkeypatch):
    """Un user non vérifié ne peut pas lancer un checkout (403)."""
    from fastapi import HTTPException
    from backend import app as app_module
    from backend.auth import AuthContext
    from config import settings
    import asyncio

    monkeypatch.setattr(settings, "STRIPE_ENABLED", True)
    monkeypatch.setattr(app_module, "STRIPE_ENABLED", True)

    uid = users_service.create_user("alice@test.com", "pw12345678")
    # User pas encore vérifié
    ctx = AuthContext(username="alice@test.com", user_id=uid)
    with pytest.raises(HTTPException) as exc:
        from backend.tests.conftest import mock_request
        asyncio.run(app_module.api_stripe_checkout(mock_request(), {"tier": "pro"}, ctx=ctx))
    assert exc.value.status_code == 403
    assert "mail" in exc.value.detail.lower()
