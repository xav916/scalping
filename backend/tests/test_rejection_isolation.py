"""Tests isolation multi-tenant pour rejection_service (Chantier 3D SaaS)."""

import sqlite3

import pytest

from backend.services import rejection_service


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_file = tmp_path / "trades.db"
    # La table est créée par _ensure_schema — on ne la pré-crée pas.
    monkeypatch.setattr(
        rejection_service, "_db_path", lambda: str(db_file)
    )
    rejection_service._ensure_schema()
    return str(db_file)


def test_schema_has_user_id_column(db):
    """Migration ajoute user_id."""
    with sqlite3.connect(db) as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(signal_rejections)").fetchall()]
    assert "user_id" in cols


def test_ensure_schema_idempotent(db):
    """Deuxième appel ne plante pas."""
    rejection_service._ensure_schema()
    rejection_service._ensure_schema()


def test_record_rejection_with_user_id(db):
    rejection_service.record_rejection(
        pair="EUR/USD",
        direction="buy",
        confidence=75.0,
        reason_code="sl_too_close",
        user_id=1,
    )
    with sqlite3.connect(db) as c:
        row = c.execute(
            "SELECT user_id, reason_code FROM signal_rejections"
        ).fetchone()
    assert row == (1, "sl_too_close")


def test_record_rejection_without_user_id_stores_null(db):
    """Back-compat : caller sans user_id → NULL stocké."""
    rejection_service.record_rejection(
        pair="EUR/USD", direction="buy", confidence=75.0, reason_code="kill_switch"
    )
    with sqlite3.connect(db) as c:
        row = c.execute("SELECT user_id FROM signal_rejections").fetchone()
    assert row[0] is None


def test_get_rejections_scoped_by_user_id(db):
    # Alice (uid=1) : 2 rejections, Bob (uid=2) : 1, legacy (NULL) : 1.
    for _ in range(2):
        rejection_service.record_rejection(
            "EUR/USD", "buy", 75, "sl_too_close", user_id=1
        )
    rejection_service.record_rejection(
        "XAU/USD", "sell", 65, "kill_switch", user_id=2
    )
    rejection_service.record_rejection(
        "GBP/USD", "buy", 70, "bridge_timeout"
    )  # user_id=NULL

    since, until = "2020-01-01T00:00:00+00:00", "2099-12-31T23:59:59+00:00"

    alice = rejection_service.get_rejections(since, until, user_id=1)
    bob = rejection_service.get_rejections(since, until, user_id=2)
    all_ = rejection_service.get_rejections(since, until)  # admin, no scope

    assert alice["total"] == 2
    assert bob["total"] == 1
    assert all_["total"] == 4  # 2 + 1 + 1 legacy


def test_get_rejections_scope_excludes_null_rows(db):
    """Un user ne voit PAS les rejections legacy NULL (pas attribuées)."""
    rejection_service.record_rejection(
        "EUR/USD", "buy", 75, "kill_switch"
    )  # NULL
    rejection_service.record_rejection(
        "EUR/USD", "buy", 75, "kill_switch", user_id=42
    )

    since, until = "2020-01-01T00:00:00+00:00", "2099-12-31T23:59:59+00:00"
    scoped = rejection_service.get_rejections(since, until, user_id=42)
    assert scoped["total"] == 1  # seulement sa propre row, pas le NULL


def test_get_rejections_by_reason_includes_labels(db):
    rejection_service.record_rejection(
        "EUR/USD", "buy", 75, "sl_too_close", user_id=1
    )
    rejection_service.record_rejection(
        "EUR/USD", "buy", 75, "sl_too_close", user_id=1
    )
    since, until = "2020-01-01T00:00:00+00:00", "2099-12-31T23:59:59+00:00"
    out = rejection_service.get_rejections(since, until, user_id=1)
    by_reason = out["by_reason"]
    assert len(by_reason) == 1
    assert by_reason[0]["reason_code"] == "sl_too_close"
    assert by_reason[0]["count"] == 2
    assert by_reason[0]["label_fr"] == "SL trop serré"
