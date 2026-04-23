"""Tests pour backend.auth._authenticate_credentials (Chantier 2 SaaS).

Vérifie l'ordre DB users → fallback AUTH_USERS env, et les cas d'échec.
"""

import sqlite3
from unittest.mock import patch

import pytest

from backend import auth
from backend.services import users_service


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_file = tmp_path / "trades.db"
    # personal_trades vide pour que la migration douce ne plante pas.
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE personal_trades (id INTEGER PRIMARY KEY, user TEXT)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(users_service, "_DB_PATH", db_file)
    users_service.init_users_schema()
    return db_file


def test_db_user_logs_in(db, monkeypatch):
    users_service.create_user("alice@test.com", "goodpw123", tier="pro")
    monkeypatch.setattr(auth, "AUTH_USERS", {})
    assert auth._authenticate_credentials("alice@test.com", "goodpw123") == "alice@test.com"


def test_db_user_email_normalized(db, monkeypatch):
    users_service.create_user("Alice@Test.com", "goodpw123", tier="pro")
    monkeypatch.setattr(auth, "AUTH_USERS", {})
    # Input utilisateur en majuscules → doit matcher le record lowercased.
    assert auth._authenticate_credentials("ALICE@test.com", "goodpw123") == "alice@test.com"


def test_db_user_wrong_password_falls_through_and_fails(db, monkeypatch):
    users_service.create_user("alice@test.com", "goodpw123", tier="pro")
    monkeypatch.setattr(auth, "AUTH_USERS", {})
    assert auth._authenticate_credentials("alice@test.com", "wrong") is None


def test_disabled_user_cannot_log_in(db, monkeypatch):
    uid = users_service.create_user("alice@test.com", "goodpw123")
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE users SET is_active = 0 WHERE id = ?", (uid,))
    monkeypatch.setattr(auth, "AUTH_USERS", {})
    assert auth._authenticate_credentials("alice@test.com", "goodpw123") is None


def test_env_fallback_when_user_not_in_db(db, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_USERS", {"legacy": "legacypw"})
    assert auth._authenticate_credentials("legacy", "legacypw") == "legacy"


def test_env_rejects_wrong_password(db, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_USERS", {"legacy": "legacypw"})
    assert auth._authenticate_credentials("legacy", "nope") is None


def test_unknown_user_fails(db, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_USERS", {})
    assert auth._authenticate_credentials("ghost@test.com", "anything") is None


def test_touch_last_login_called(db, monkeypatch):
    uid = users_service.create_user("alice@test.com", "goodpw123")
    monkeypatch.setattr(auth, "AUTH_USERS", {})
    # Avant login : last_login_at is None.
    assert users_service.get_user_by_id(uid)["last_login_at"] is None
    auth._authenticate_credentials("alice@test.com", "goodpw123")
    # Après : mise à jour.
    assert users_service.get_user_by_id(uid)["last_login_at"] is not None


def test_db_failure_falls_back_to_env(db, monkeypatch):
    """Si users_service lève, on ne doit pas casser le login env."""
    monkeypatch.setattr(auth, "AUTH_USERS", {"legacy": "legacypw"})
    with patch.object(users_service, "get_user_by_email", side_effect=RuntimeError("db down")):
        assert auth._authenticate_credentials("legacy", "legacypw") == "legacy"
