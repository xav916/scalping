"""Tests pour users_service (Chantier 1 SaaS).

Couvre :
- hash/verify round-trip et rejet des inputs invalides
- create_user + get_user_by_email/id + normalisation email
- unicité email
- validation tier
- migration user_id sur personal_trades
"""

import sqlite3

import pytest

from backend.services import users_service


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Isole chaque test dans sa propre trades.db."""
    db_file = tmp_path / "trades.db"
    # Crée une personal_trades pré-migration pour tester l'ALTER idempotent.
    conn = sqlite3.connect(db_file)
    conn.execute("""
        CREATE TABLE personal_trades (
            id INTEGER PRIMARY KEY,
            user TEXT,
            pair TEXT
        )
    """)
    conn.commit()
    conn.close()

    monkeypatch.setattr(users_service, "_DB_PATH", db_file)
    users_service.init_users_schema()
    return db_file


# ─── Hash / verify ─────────────────────────────────────────────

def test_hash_verify_roundtrip():
    h = users_service.hash_password("correct horse battery")
    assert users_service.verify_password("correct horse battery", h)
    assert not users_service.verify_password("mauvais", h)


def test_hash_empty_rejects():
    with pytest.raises(ValueError):
        users_service.hash_password("")


def test_verify_handles_garbage():
    assert not users_service.verify_password("x", "not-a-bcrypt-hash")
    assert not users_service.verify_password("", "anything")


# ─── CRUD ─────────────────────────────────────────────

def test_create_user_returns_id_and_fetchable(db):
    uid = users_service.create_user("user@test.com", "password123", tier="free")
    assert uid > 0
    user = users_service.get_user_by_id(uid)
    assert user is not None
    assert user["email"] == "user@test.com"
    assert user["tier"] == "free"
    assert user["is_active"] == 1
    # Password hash stocké, pas le password clair.
    assert user["password_hash"] != "password123"
    assert users_service.verify_password("password123", user["password_hash"])


def test_email_normalized(db):
    uid = users_service.create_user("  Mixed@Case.COM ", "pw", tier="pro")
    user = users_service.get_user_by_email("mixed@case.com")
    assert user is not None and user["id"] == uid


def test_email_unique(db):
    users_service.create_user("dup@test.com", "a")
    with pytest.raises(ValueError, match="déjà utilisé"):
        users_service.create_user("DUP@test.com", "b")


def test_invalid_email(db):
    with pytest.raises(ValueError, match="email invalide"):
        users_service.create_user("no-at-sign", "pw")


def test_invalid_tier(db):
    with pytest.raises(ValueError, match="tier invalide"):
        users_service.create_user("x@y.com", "pw", tier="enterprise")


def test_get_user_by_email_missing(db):
    assert users_service.get_user_by_email("nope@test.com") is None
    assert users_service.get_user_by_email("") is None


def test_get_user_by_id_missing(db):
    assert users_service.get_user_by_id(9999) is None


def test_touch_last_login(db):
    uid = users_service.create_user("x@y.com", "pw")
    assert users_service.get_user_by_id(uid)["last_login_at"] is None
    users_service.touch_last_login(uid)
    assert users_service.get_user_by_id(uid)["last_login_at"] is not None


# ─── Migration personal_trades.user_id ─────────────────────────

def test_personal_trades_has_user_id_after_init(db):
    conn = sqlite3.connect(db)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(personal_trades)").fetchall()]
    conn.close()
    assert "user_id" in cols


def test_init_schema_idempotent(db):
    # Deuxième appel ne doit pas planter.
    users_service.init_users_schema()
    users_service.init_users_schema()
