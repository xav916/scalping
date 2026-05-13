"""Tests pour backend.services.pair_pnl_regulator."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Redirige _DB_PATH du trade_log_service vers une DB temporaire."""
    db_path = tmp_path / "trades.db"
    from backend.services import trade_log_service

    monkeypatch.setattr(trade_log_service, "_DB_PATH", db_path)

    # Reset le cache schema-ensured pour que les modules recréent les tables dans tmp
    from backend.services import pair_pnl_regulator, ea_closed_trades_service

    monkeypatch.setattr(pair_pnl_regulator, "_SCHEMA_ENSURED", False)
    monkeypatch.setattr(ea_closed_trades_service, "_SCHEMA_ENSURED", False)

    # Crée la table personal_trades minimale
    with sqlite3.connect(db_path) as c:
        c.execute(
            """
            CREATE TABLE personal_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pair TEXT, direction TEXT, entry_price REAL,
                stop_loss REAL, take_profit REAL, size_lot REAL,
                signal_pattern TEXT, signal_confidence REAL,
                checklist_passed INTEGER, notes TEXT,
                status TEXT, exit_price REAL, pnl REAL,
                created_at TEXT, closed_at TEXT, user TEXT,
                post_entry_sl REAL, post_entry_tp REAL, post_entry_size REAL,
                post_entry_alarm TEXT, mt5_ticket TEXT, is_auto INTEGER,
                context_macro TEXT, signal_id TEXT, fill_price REAL,
                slippage_pips REAL, close_reason TEXT, user_id INTEGER
            )
            """
        )
    yield db_path


def _insert_trade(db_path: Path, pair: str, pnl: float, closed_at: str | None = None):
    closed_at = closed_at or datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as c:
        c.execute(
            """
            INSERT INTO personal_trades (pair, status, pnl, is_auto, closed_at, close_reason)
            VALUES (?, 'CLOSED', ?, 1, ?, ?)
            """,
            (pair, pnl, closed_at, "SL" if pnl < 0 else "TP1"),
        )


# ─── compute_window_metrics ─────────────────────────────────────────────


def test_compute_window_metrics_empty(_isolated_db):
    from backend.services import pair_pnl_regulator

    m = pair_pnl_regulator.compute_window_metrics("XAG/USD", 30)
    assert m["n"] == 0
    assert m["sum_pnl"] == 0.0


def test_compute_window_metrics_aggregates_last_n(_isolated_db):
    from backend.services import pair_pnl_regulator

    for i in range(40):
        # Plus récent = i grand, on alterne signe
        _insert_trade(
            _isolated_db,
            "XAG/USD",
            pnl=10.0 if i % 2 == 0 else -20.0,
            closed_at=(datetime.now(timezone.utc) + timedelta(minutes=i)).isoformat(),
        )
    m = pair_pnl_regulator.compute_window_metrics("XAG/USD", 30)
    # Les 30 derniers (i=10..39) : 15 wins de 10€, 15 losses de -20€
    assert m["n"] == 30
    assert m["sum_pnl"] == 15 * 10 - 15 * 20  # = -150


# ─── evaluate_pair decision tree ────────────────────────────────────────


def test_evaluate_pair_keep_active_if_sample_too_small(_isolated_db, monkeypatch):
    monkeypatch.setenv("PAIR_PNL_REGULATOR_MIN_SAMPLE", "10")
    # Reload settings
    import importlib
    from config import settings as _s
    importlib.reload(_s)
    from backend.services import pair_pnl_regulator
    importlib.reload(pair_pnl_regulator)

    # Seulement 5 trades, en grosse perte
    for _ in range(5):
        _insert_trade(_isolated_db, "XAG/USD", pnl=-100.0)

    d = pair_pnl_regulator.evaluate_pair("XAG/USD")
    assert d["action"] == "keep_active"


def test_evaluate_pair_pause_if_pnl_below_threshold(_isolated_db, monkeypatch):
    monkeypatch.setenv("PAIR_PNL_REGULATOR_MIN_SAMPLE", "10")
    monkeypatch.setenv("PAIR_PNL_REGULATOR_PAUSE_THRESHOLD_PCT", "-3.0")
    monkeypatch.setenv("TRADING_CAPITAL", "10000")
    import importlib
    from config import settings as _s
    importlib.reload(_s)
    from backend.services import pair_pnl_regulator
    importlib.reload(pair_pnl_regulator)

    # 15 trades, sum_pnl = -500€ → -5% sur 10000€ capital → < -3% → pause
    for _ in range(15):
        _insert_trade(_isolated_db, "XAG/USD", pnl=-33.33)

    d = pair_pnl_regulator.evaluate_pair("XAG/USD")
    assert d["action"] == "pause"
    assert pair_pnl_regulator.is_paused("XAG/USD") is True


def test_evaluate_pair_keep_paused_if_not_expired(_isolated_db):
    from backend.services import pair_pnl_regulator

    pair_pnl_regulator.apply_pause("XAG/USD", "ev_negative", -5.0, 30)
    d = pair_pnl_regulator.evaluate_pair("XAG/USD")
    assert d["action"] == "keep_paused"


def test_apply_pause_idempotent(_isolated_db):
    from backend.services import pair_pnl_regulator

    id1 = pair_pnl_regulator.apply_pause("XAG/USD", "ev_negative", -5.0, 30)
    id2 = pair_pnl_regulator.apply_pause("XAG/USD", "ev_negative", -6.0, 30)
    # Même id retourné (pas créé de doublon)
    assert id1 == id2


def test_resume_clears_active_pause(_isolated_db):
    from backend.services import pair_pnl_regulator

    pair_pnl_regulator.apply_pause("XAG/USD", "ev_negative", -5.0, 30)
    assert pair_pnl_regulator.is_paused("XAG/USD") is True
    pair_pnl_regulator.apply_resume("XAG/USD", "manual_test")
    assert pair_pnl_regulator.is_paused("XAG/USD") is False
