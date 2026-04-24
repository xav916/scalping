"""Tests pour le hard delete admin (/api/admin/users/{id}).

Hard delete réservé aux users de test (sans trades). Un user avec des
trades liés est refusé 409 pour forcer le soft delete RGPD via
delete_account.
"""

import sqlite3

import pytest

from backend.services import users_service


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_file = tmp_path / "trades.db"
    conn = sqlite3.connect(db_file)
    conn.execute("""
        CREATE TABLE personal_trades (
            id INTEGER PRIMARY KEY,
            user TEXT,
            user_id INTEGER,
            pair TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()
    monkeypatch.setattr(users_service, "_DB_PATH", db_file)
    users_service.init_users_schema()
    return db_file


class TestHasTrades:
    def test_no_trades(self, db):
        uid = users_service.create_user("clean@test.com", "password123")
        assert users_service.has_trades(uid) is False

    def test_with_trades(self, db):
        uid = users_service.create_user("trader@test.com", "password123")
        with sqlite3.connect(db) as c:
            c.execute(
                "INSERT INTO personal_trades (user, user_id, pair, created_at) "
                "VALUES (?, ?, ?, ?)",
                ("trader@test.com", uid, "EUR/USD", "2026-04-24T00:00:00Z"),
            )
        assert users_service.has_trades(uid) is True

    def test_other_users_trades_dont_count(self, db):
        uid_a = users_service.create_user("a@test.com", "password123")
        uid_b = users_service.create_user("b@test.com", "password123")
        with sqlite3.connect(db) as c:
            c.execute(
                "INSERT INTO personal_trades (user, user_id, pair, created_at) "
                "VALUES (?, ?, ?, ?)",
                ("a@test.com", uid_a, "EUR/USD", "2026-04-24T00:00:00Z"),
            )
        assert users_service.has_trades(uid_a) is True
        assert users_service.has_trades(uid_b) is False


class TestHardDelete:
    def test_deletes_user_row(self, db):
        uid = users_service.create_user("drop@test.com", "password123")
        assert users_service.get_user_by_id(uid) is not None
        ok = users_service.admin_hard_delete_user(uid)
        assert ok is True
        assert users_service.get_user_by_id(uid) is None

    def test_returns_false_if_user_missing(self, db):
        assert users_service.admin_hard_delete_user(99999) is False

    def test_idempotent_on_missing(self, db):
        uid = users_service.create_user("x@test.com", "password123")
        users_service.admin_hard_delete_user(uid)
        # Second call returns False, no exception.
        assert users_service.admin_hard_delete_user(uid) is False
