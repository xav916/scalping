"""Tests pour l'accès historique point-in-time du CNN Fear & Greed
(table `fear_greed_snapshots`, insert-only, alimentée quotidiennement en
production — voir audit du 2026-08-05).

`get_current()` (déjà existant) retourne toujours le DERNIER snapshot connu,
quel que soit T : inutilisable pour du scoring/backtest daté, car il fuite
le futur. `get_value_at(ts)` doit au contraire ne jamais retourner un
snapshot postérieur à `ts`.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.services import fear_greed_service, trade_log_service


def _insert(db_path: Path, recorded_at: str, value: float, classification: str) -> None:
    with sqlite3.connect(db_path) as c:
        c.execute(
            "INSERT INTO fear_greed_snapshots (recorded_at, value, classification) "
            "VALUES (?, ?, ?)",
            (recorded_at, value, classification),
        )


@pytest.fixture
def temp_trades_db(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "t.db"
    monkeypatch.setattr(trade_log_service, "_DB_PATH", db_path)
    trade_log_service._init_schema()
    fear_greed_service._init_schema()
    return db_path


# ─── Cas nominal : valeur historique rendue pour une date passée ───────────


def test_get_value_at_returns_snapshot_before_ts(temp_trades_db):
    _insert(temp_trades_db, "2026-05-19T22:30:00+00:00", 60.4, "greed")
    _insert(temp_trades_db, "2026-05-20T22:30:00+00:00", 60.9, "greed")

    ts = datetime(2026, 5, 21, 10, 0, tzinfo=timezone.utc)
    snap = fear_greed_service.get_value_at(ts)

    assert snap is not None
    assert snap["value"] == 60.9
    assert snap["classification"] == "greed"


def test_get_value_at_boundary_is_inclusive(temp_trades_db):
    """recorded_at == ts doit être visible : la ligne existait déjà en base
    à cet instant précis (recorded_at est un vrai timestamp d'insertion,
    pas une date calendaire à marge de sécurité)."""
    _insert(temp_trades_db, "2026-05-20T22:30:00+00:00", 42.0, "fear")

    ts = datetime(2026, 5, 20, 22, 30, 0, tzinfo=timezone.utc)
    snap = fear_greed_service.get_value_at(ts)

    assert snap is not None
    assert snap["value"] == 42.0


# ─── Avant le début de l'historique → None, jamais une constante ──────────


def test_get_value_at_before_history_start_returns_none(temp_trades_db):
    _insert(temp_trades_db, "2026-05-19T22:30:00+00:00", 60.4, "greed")

    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert fear_greed_service.get_value_at(ts) is None


def test_get_value_at_empty_table_returns_none(temp_trades_db):
    ts = datetime(2026, 5, 20, tzinfo=timezone.utc)
    assert fear_greed_service.get_value_at(ts) is None


# ─── Test de fuite : jamais une valeur postérieure à ts ────────────────────


def test_get_value_at_never_leaks_future_value(temp_trades_db):
    """Le test le plus important : une valeur enregistrée APRÈS ts ne doit
    jamais être retournée, même si elle est la plus proche chronologiquement."""
    _insert(temp_trades_db, "2026-05-18T22:30:00+00:00", 30.0, "fear")
    _insert(temp_trades_db, "2026-05-22T22:30:00+00:00", 90.0, "extreme_greed")  # futur

    ts = datetime(2026, 5, 20, 12, 0, tzinfo=timezone.utc)
    snap = fear_greed_service.get_value_at(ts)

    assert snap is not None
    assert snap["value"] == 30.0  # jamais 90.0, même si "plus proche" en valeur absolue de temps


def test_get_value_at_no_row_at_all_before_ts_but_rows_exist_after(temp_trades_db):
    _insert(temp_trades_db, "2026-06-01T00:00:00+00:00", 55.0, "greed")

    ts = datetime(2026, 5, 1, tzinfo=timezone.utc)
    assert fear_greed_service.get_value_at(ts) is None
