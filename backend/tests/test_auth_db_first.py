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
    uid = users_service.create_user("alice@test.com", "goodpw123", tier="pro")
    monkeypatch.setattr(auth, "AUTH_USERS", {})
    assert auth._authenticate_credentials("alice@test.com", "goodpw123") == (
        "alice@test.com",
        uid,
    )


def test_db_user_email_normalized(db, monkeypatch):
    uid = users_service.create_user("Alice@Test.com", "goodpw123", tier="pro")
    monkeypatch.setattr(auth, "AUTH_USERS", {})
    # Input en majuscules → doit matcher le record lowercased + même user_id.
    assert auth._authenticate_credentials("ALICE@test.com", "goodpw123") == (
        "alice@test.com",
        uid,
    )


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
    # user_id vaut None pour un user env-only (pas de row en DB).
    assert auth._authenticate_credentials("legacy", "legacypw") == ("legacy", None)


def test_env_rejects_wrong_password(db, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_USERS", {"legacy": "legacypw"})
    assert auth._authenticate_credentials("legacy", "nope") is None


def test_unknown_user_fails(db, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_USERS", {})
    assert auth._authenticate_credentials("ghost@test.com", "anything") is None


def test_touch_last_login_called(db, monkeypatch):
    uid = users_service.create_user("alice@test.com", "goodpw123")
    monkeypatch.setattr(auth, "AUTH_USERS", {})
    assert users_service.get_user_by_id(uid)["last_login_at"] is None
    auth._authenticate_credentials("alice@test.com", "goodpw123")
    assert users_service.get_user_by_id(uid)["last_login_at"] is not None


def test_db_failure_falls_back_to_env(db, monkeypatch):
    """Si users_service lève, on ne doit pas casser le login env."""
    monkeypatch.setattr(auth, "AUTH_USERS", {"legacy": "legacypw"})
    with patch.object(users_service, "get_user_by_email", side_effect=RuntimeError("db down")):
        assert auth._authenticate_credentials("legacy", "legacypw") == ("legacy", None)


# ─── Session user_id + AuthContext (Chantier 3) ─────────────────

def test_session_stores_user_id(db, monkeypatch):
    """create_session persiste user_id et _load_session le rend."""
    # Nettoie le store in-memory pour isoler ce test.
    auth._sessions.clear()
    sid = auth.create_session("alice@test.com", user_id=42)
    session = auth._load_session(sid)
    assert session is not None
    assert session["user"] == "alice@test.com"
    assert session["user_id"] == 42


def test_session_user_id_none_for_env_user(db, monkeypatch):
    auth._sessions.clear()
    sid = auth.create_session("legacy-admin")  # user_id par défaut = None
    session = auth._load_session(sid)
    assert session["user_id"] is None


def test_validate_session_back_compat(db, monkeypatch):
    """validate_session continue de retourner juste le username (back-compat)."""
    auth._sessions.clear()
    sid = auth.create_session("alice@test.com", user_id=7)
    assert auth.validate_session(sid) == "alice@test.com"


def test_auth_context_dep_from_session(db, monkeypatch):
    """auth_context() extrait user_id du session dict quand Cookie présent."""
    from unittest.mock import MagicMock

    monkeypatch.setattr(auth, "AUTH_USERS", {"dummy": "x"})  # AUTH_USERS non-vide
    auth._sessions.clear()
    sid = auth.create_session("alice@test.com", user_id=99)

    req = MagicMock()
    req.cookies = {auth.SESSION_COOKIE: sid}
    req.headers = {}

    ctx = auth.auth_context(req)
    assert ctx.username == "alice@test.com"
    assert ctx.user_id == 99


def test_auth_context_no_auth_when_auth_users_empty(db, monkeypatch):
    """Si AUTH_USERS vide (pas d'auth), ctx = ('anonymous', None)."""
    from unittest.mock import MagicMock

    monkeypatch.setattr(auth, "AUTH_USERS", {})
    req = MagicMock()
    req.cookies, req.headers = {}, {}
    ctx = auth.auth_context(req)
    assert ctx.username == "anonymous"
    assert ctx.user_id is None


def test_authenticate_still_returns_username_only(db, monkeypatch):
    """authenticate() (dep legacy) continue de retourner juste le username."""
    from unittest.mock import MagicMock

    monkeypatch.setattr(auth, "AUTH_USERS", {"dummy": "x"})
    auth._sessions.clear()
    sid = auth.create_session("alice@test.com", user_id=11)

    req = MagicMock()
    req.cookies = {auth.SESSION_COOKIE: sid}
    req.headers = {}
    assert auth.authenticate(req) == "alice@test.com"
