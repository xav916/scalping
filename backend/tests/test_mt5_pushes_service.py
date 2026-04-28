"""Tests pour ``mt5_pushes_service`` — Phase B du multi-tenant bridge routing.

Vérifie la dedup atomique en DB (UNIQUE constraint), le cycle complet
(register → update → discard) et la purge.
"""
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.services import mt5_pushes_service, trade_log_service


@pytest.fixture
def db(tmp_path: Path):
    """DB SQLite isolée par test, schema initialisé."""
    db_file = tmp_path / "trades.db"
    with patch.object(trade_log_service, "_DB_PATH", db_file):
        mt5_pushes_service._ensure_schema()
        yield db_file


# ─── try_register_push ────────────────────────────────────────────────


def test_try_register_push_returns_true_for_new_key(db):
    ok = mt5_pushes_service.try_register_push(
        "admin_legacy", "2026-04-28", "EUR/USD", "buy", "1.10000"
    )
    assert ok is True


def test_try_register_push_returns_false_on_duplicate(db):
    """Même clé (date, pair, direction, entry, dest) → False au 2e essai."""
    first = mt5_pushes_service.try_register_push(
        "admin_legacy", "2026-04-28", "EUR/USD", "buy", "1.10000"
    )
    second = mt5_pushes_service.try_register_push(
        "admin_legacy", "2026-04-28", "EUR/USD", "buy", "1.10000"
    )
    assert first is True
    assert second is False


def test_try_register_push_different_destination_returns_true(db):
    """Même pair/direction/entry mais destination différente → autorisé."""
    a = mt5_pushes_service.try_register_push(
        "admin_legacy", "2026-04-28", "EUR/USD", "buy", "1.10000"
    )
    b = mt5_pushes_service.try_register_push(
        "user:42", "2026-04-28", "EUR/USD", "buy", "1.10000"
    )
    assert a is True
    assert b is True


def test_try_register_push_different_entry_returns_true(db):
    """Même destination/pair/direction mais entry différent → autorisé."""
    a = mt5_pushes_service.try_register_push(
        "admin_legacy", "2026-04-28", "EUR/USD", "buy", "1.10000"
    )
    b = mt5_pushes_service.try_register_push(
        "admin_legacy", "2026-04-28", "EUR/USD", "buy", "1.10005"
    )
    assert a is True
    assert b is True


def test_try_register_push_different_date_returns_true(db):
    """Même clé mais date différente → autorisé (purge journalière implicite)."""
    a = mt5_pushes_service.try_register_push(
        "admin_legacy", "2026-04-28", "EUR/USD", "buy", "1.10000"
    )
    b = mt5_pushes_service.try_register_push(
        "admin_legacy", "2026-04-29", "EUR/USD", "buy", "1.10000"
    )
    assert a is True
    assert b is True


# ─── update_push_result ───────────────────────────────────────────────


def test_update_push_result_marks_ok_true(db):
    mt5_pushes_service.try_register_push(
        "admin_legacy", "2026-04-28", "EUR/USD", "buy", "1.10000"
    )
    mt5_pushes_service.update_push_result(
        "admin_legacy", "2026-04-28", "EUR/USD", "buy", "1.10000",
        ok=True, response={"ticket": 12345, "mode": "live"},
    )
    import sqlite3
    with sqlite3.connect(db) as c:
        row = c.execute(
            "SELECT ok, bridge_response FROM mt5_pushes WHERE pair='EUR/USD'"
        ).fetchone()
    assert row[0] == 1
    assert "12345" in row[1]


def test_update_push_result_truncates_long_response(db):
    mt5_pushes_service.try_register_push(
        "admin_legacy", "2026-04-28", "EUR/USD", "buy", "1.10000"
    )
    long_resp = {"data": "x" * 1000}
    mt5_pushes_service.update_push_result(
        "admin_legacy", "2026-04-28", "EUR/USD", "buy", "1.10000",
        ok=False, response=long_resp,
    )
    import sqlite3
    with sqlite3.connect(db) as c:
        row = c.execute(
            "SELECT bridge_response FROM mt5_pushes WHERE pair='EUR/USD'"
        ).fetchone()
    assert len(row[0]) <= 500


# ─── discard_push ─────────────────────────────────────────────────────


def test_discard_push_allows_retry(db):
    """Après discard, le même setup peut être re-registré (retry)."""
    mt5_pushes_service.try_register_push(
        "admin_legacy", "2026-04-28", "EUR/USD", "buy", "1.10000"
    )
    mt5_pushes_service.discard_push(
        "admin_legacy", "2026-04-28", "EUR/USD", "buy", "1.10000"
    )
    retry = mt5_pushes_service.try_register_push(
        "admin_legacy", "2026-04-28", "EUR/USD", "buy", "1.10000"
    )
    assert retry is True


# ─── purge_old_pushes ─────────────────────────────────────────────────


def test_purge_old_pushes_removes_old_entries(db):
    """Pushes de plus de retention_days jours sont supprimés."""
    mt5_pushes_service.try_register_push(
        "admin_legacy", "2026-04-01", "EUR/USD", "buy", "1.10000"
    )
    mt5_pushes_service.try_register_push(
        "admin_legacy", "2026-04-28", "EUR/USD", "buy", "1.10000"
    )
    deleted = mt5_pushes_service.purge_old_pushes(retention_days=10)
    # Le test tourne à une date arbitraire — on vérifie juste qu'au moins
    # la ligne du 2026-04-01 (très ancienne) a été supprimée.
    import sqlite3
    with sqlite3.connect(db) as c:
        remaining = c.execute(
            "SELECT date FROM mt5_pushes ORDER BY date"
        ).fetchall()
    dates = [r[0] for r in remaining]
    assert "2026-04-01" not in dates  # purgée
    assert deleted >= 1


# ─── _ensure_schema idempotent ────────────────────────────────────────


def test_ensure_schema_is_idempotent(db):
    """Appeler _ensure_schema 2 fois ne plante pas."""
    mt5_pushes_service._ensure_schema()
    mt5_pushes_service._ensure_schema()  # ne doit pas raise


# ─── best-effort fallback ─────────────────────────────────────────────


def test_try_register_push_returns_true_on_db_error(monkeypatch):
    """Si la DB est inaccessible, fallback safe = retourne True (autorise push)."""
    monkeypatch.setattr(
        trade_log_service, "_DB_PATH", "/nonexistent/path/trades.db"
    )
    ok = mt5_pushes_service.try_register_push(
        "admin_legacy", "2026-04-28", "EUR/USD", "buy", "1.10000"
    )
    assert ok is True
