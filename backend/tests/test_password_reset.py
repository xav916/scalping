"""Tests password reset flow (magic link email)."""

import sqlite3
from datetime import datetime, timedelta, timezone
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


# ─── Schema ──────────────────────────────────────────────────

def test_schema_has_reset_columns(db):
    with sqlite3.connect(db) as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(users)").fetchall()]
    assert "password_reset_token" in cols
    assert "password_reset_expires_at" in cols


# ─── request_password_reset ──────────────────────────────────

def test_request_password_reset_generates_token(db):
    users_service.create_user("alice@test.com", "oldpass12")
    token = users_service.request_password_reset("alice@test.com")
    assert token is not None
    assert len(token) > 20  # token_urlsafe 32 bytes → ~43 chars


def test_request_password_reset_returns_none_for_unknown_email(db):
    users_service.create_user("alice@test.com", "oldpass12")
    assert users_service.request_password_reset("ghost@test.com") is None


def test_request_password_reset_rejects_inactive_user(db):
    uid = users_service.create_user("alice@test.com", "oldpass12")
    with sqlite3.connect(db) as c:
        c.execute("UPDATE users SET is_active = 0 WHERE id = ?", (uid,))
    assert users_service.request_password_reset("alice@test.com") is None


def test_request_password_reset_persists_token(db):
    uid = users_service.create_user("alice@test.com", "oldpass12")
    token = users_service.request_password_reset("alice@test.com")
    user = users_service.get_user_by_id(uid)
    assert user["password_reset_token"] == token
    assert user["password_reset_expires_at"] is not None


def test_new_reset_overrides_previous(db):
    """Demander un 2e reset invalide le 1er (single active token)."""
    users_service.create_user("alice@test.com", "oldpass12")
    t1 = users_service.request_password_reset("alice@test.com")
    t2 = users_service.request_password_reset("alice@test.com")
    assert t1 != t2
    assert users_service.validate_reset_token(t1) is None
    assert users_service.validate_reset_token(t2) is not None


# ─── validate_reset_token ────────────────────────────────────

def test_validate_reset_token_ok(db):
    users_service.create_user("alice@test.com", "oldpass12")
    token = users_service.request_password_reset("alice@test.com")
    assert users_service.validate_reset_token(token) is not None


def test_validate_reset_token_empty(db):
    assert users_service.validate_reset_token("") is None
    assert users_service.validate_reset_token(None) is None  # type: ignore[arg-type]


def test_validate_reset_token_garbage(db):
    users_service.create_user("alice@test.com", "oldpass12")
    users_service.request_password_reset("alice@test.com")
    assert users_service.validate_reset_token("not-a-real-token") is None


def test_validate_reset_token_expired(db):
    uid = users_service.create_user("alice@test.com", "oldpass12")
    token = users_service.request_password_reset("alice@test.com")
    # Force l'expiration à il y a 1h.
    past = (datetime.now(timezone.utc) - timedelta(hours=1, minutes=1)).isoformat()
    with sqlite3.connect(db) as c:
        c.execute(
            "UPDATE users SET password_reset_expires_at = ? WHERE id = ?", (past, uid)
        )
    assert users_service.validate_reset_token(token) is None


# ─── consume_reset_token ─────────────────────────────────────

def test_consume_reset_token_updates_password(db):
    uid = users_service.create_user("alice@test.com", "oldpass12")
    token = users_service.request_password_reset("alice@test.com")
    assert users_service.consume_reset_token(token, "newpass345") is True
    user = users_service.get_user_by_id(uid)
    # Ancien password rejeté, nouveau accepté.
    assert not users_service.verify_password("oldpass12", user["password_hash"])
    assert users_service.verify_password("newpass345", user["password_hash"])


def test_consume_reset_token_invalidates_after_use(db):
    users_service.create_user("alice@test.com", "oldpass12")
    token = users_service.request_password_reset("alice@test.com")
    users_service.consume_reset_token(token, "newpass345")
    # 2e tentative avec le même token → refusée.
    assert users_service.consume_reset_token(token, "yetanother1") is False


def test_consume_reset_token_rejects_short_password(db):
    users_service.create_user("alice@test.com", "oldpass12")
    token = users_service.request_password_reset("alice@test.com")
    with pytest.raises(ValueError, match="trop court"):
        users_service.consume_reset_token(token, "short")


def test_consume_reset_token_bad_token_returns_false(db):
    users_service.create_user("alice@test.com", "oldpass12")
    assert users_service.consume_reset_token("not-a-token", "newpass345") is False


# ─── Endpoints ────────────────────────────────────────────────

def test_endpoint_forgot_password_200_for_unknown_email(db):
    """Anti-énumération : même réponse que l'email existe ou pas."""
    from backend import app as app_module
    import asyncio

    result = asyncio.run(app_module.api_forgot_password({"email": "ghost@test.com"}))
    assert result == {"ok": True}


def test_endpoint_forgot_password_sends_email_if_user_exists(db):
    from backend import app as app_module
    from backend.services import user_email_service
    import asyncio

    users_service.create_user("alice@test.com", "oldpass12")
    with patch.object(user_email_service, "send_password_reset", return_value=True) as mk:
        asyncio.run(app_module.api_forgot_password({"email": "alice@test.com"}))
    mk.assert_called_once()
    # Le 2e arg est le token.
    assert mk.call_args.args[0] == "alice@test.com"
    assert len(mk.call_args.args[1]) > 20


def test_endpoint_forgot_password_rejects_invalid_email(db):
    from fastapi import HTTPException
    from backend import app as app_module
    import asyncio

    with pytest.raises(HTTPException) as exc:
        asyncio.run(app_module.api_forgot_password({"email": "not-an-email"}))
    assert exc.value.status_code == 400


def test_endpoint_reset_password_success(db):
    from backend import app as app_module
    import asyncio

    users_service.create_user("alice@test.com", "oldpass12")
    token = users_service.request_password_reset("alice@test.com")
    result = asyncio.run(app_module.api_reset_password({"token": token, "new_password": "newpass345"}))
    assert result == {"ok": True}


def test_endpoint_reset_password_invalid_token(db):
    from fastapi import HTTPException
    from backend import app as app_module
    import asyncio

    with pytest.raises(HTTPException) as exc:
        asyncio.run(app_module.api_reset_password({"token": "bad", "new_password": "newpass345"}))
    assert exc.value.status_code == 400
