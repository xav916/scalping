"""Tests change password + delete account (RGPD)."""

import sqlite3

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


# ─── change_password ─────────────────────────────────────────

def test_change_password_ok(db):
    uid = users_service.create_user("alice@test.com", "oldpass123")
    assert users_service.change_password(uid, "oldpass123", "newpass789") is True
    user = users_service.get_user_by_id(uid)
    assert users_service.verify_password("newpass789", user["password_hash"])
    assert not users_service.verify_password("oldpass123", user["password_hash"])


def test_change_password_wrong_current(db):
    uid = users_service.create_user("alice@test.com", "oldpass123")
    assert users_service.change_password(uid, "wrong", "newpass789") is False
    # Password inchangé.
    user = users_service.get_user_by_id(uid)
    assert users_service.verify_password("oldpass123", user["password_hash"])


def test_change_password_rejects_short_new(db):
    uid = users_service.create_user("alice@test.com", "oldpass123")
    with pytest.raises(ValueError, match="trop court"):
        users_service.change_password(uid, "oldpass123", "short")


def test_change_password_unknown_user(db):
    assert users_service.change_password(9999, "whatever", "newpass789") is False


# ─── delete_account (anonymisation RGPD) ──────────────────────

def test_delete_account_anonymises(db):
    uid = users_service.create_user("alice@test.com", "mypass12", tier="pro")
    users_service.update_broker_config(
        uid, bridge_url="http://x:8787", bridge_api_key="secretapikey12345"
    )
    users_service.update_watched_pairs(uid, ["EUR/USD"])
    users_service.update_stripe_customer_id(uid, "cus_xxx")

    assert users_service.delete_account(uid, "mypass12") is True

    user = users_service.get_user_by_id(uid)
    assert user is not None  # row existe encore (anonymisée)
    assert user["email"] == f"deleted_{uid}@anon.local"
    assert user["is_active"] == 0
    assert user["broker_config"] is None
    assert user["watched_pairs"] is None
    assert user["stripe_customer_id"] is None


def test_delete_account_wrong_password(db):
    uid = users_service.create_user("alice@test.com", "mypass12")
    assert users_service.delete_account(uid, "wrong") is False
    # Toujours actif.
    user = users_service.get_user_by_id(uid)
    assert user["email"] == "alice@test.com"
    assert user["is_active"] == 1


def test_delete_account_prevents_re_login(db):
    """Après anonymisation, le password original ne permet plus de se connecter."""
    uid = users_service.create_user("alice@test.com", "mypass12")
    old_hash = users_service.get_user_by_id(uid)["password_hash"]
    users_service.delete_account(uid, "mypass12")
    new_hash = users_service.get_user_by_id(uid)["password_hash"]
    # Le hash a été remplacé par un random.
    assert new_hash != old_hash
    assert not users_service.verify_password("mypass12", new_hash)


def test_delete_account_email_freed_for_reuse(db):
    """L'email anonymisé ne bloque pas une nouvelle inscription avec le même email."""
    uid = users_service.create_user("alice@test.com", "mypass12")
    users_service.delete_account(uid, "mypass12")
    # L'email alice@test.com est libéré → on peut recréer un user.
    new_uid = users_service.create_user("alice@test.com", "newpass12")
    assert new_uid != uid


def test_delete_account_unknown_user(db):
    assert users_service.delete_account(9999, "whatever") is False


# ─── Endpoints ─────────────────────────────────────────

def test_endpoint_change_password_success(db):
    from backend import app as app_module
    from backend.auth import AuthContext
    import asyncio

    uid = users_service.create_user("alice@test.com", "mypass12")
    ctx = AuthContext(username="alice@test.com", user_id=uid)
    from backend.tests.conftest import mock_request
    result = asyncio.run(app_module.api_change_password(
        mock_request(), {"current_password": "mypass12", "new_password": "newpass99"}, ctx=ctx
    ))
    assert result == {"ok": True}


def test_endpoint_change_password_wrong_current(db):
    from fastapi import HTTPException
    from backend import app as app_module
    from backend.auth import AuthContext
    import asyncio

    uid = users_service.create_user("alice@test.com", "mypass12")
    ctx = AuthContext(username="alice@test.com", user_id=uid)
    with pytest.raises(HTTPException) as exc:
        from backend.tests.conftest import mock_request
        asyncio.run(app_module.api_change_password(
            mock_request(), {"current_password": "wrong", "new_password": "newpass99"}, ctx=ctx
        ))
    assert exc.value.status_code == 400


def test_endpoint_change_password_legacy_env_blocked(db):
    from fastapi import HTTPException
    from backend import app as app_module
    from backend.auth import AuthContext
    import asyncio

    ctx = AuthContext(username="legacy", user_id=None)
    with pytest.raises(HTTPException) as exc:
        from backend.tests.conftest import mock_request
        asyncio.run(app_module.api_change_password(
            mock_request(), {"current_password": "x", "new_password": "newpass99"}, ctx=ctx
        ))
    assert exc.value.status_code == 400
