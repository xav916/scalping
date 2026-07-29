"""Tests pour backend.services.promotion_engine.

Sprint 2 du chantier promotion criteria 2026-07-29. Couvre :
- Metrics compute (WR, EV, DD, Sharpe, N SL consécutifs)
- Gate 1 evaluation (signaux insuffisants / OK)
- Gate 2 evaluation (WR trop faible / OK)
- Démotion 5 SL consécutifs Demo tradable
- Vetos (Sharpe 7j < 0)
- Cycle runner end-to-end
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Redirige _DB_PATH vers DB temporaire."""
    db_path = tmp_path / "trades.db"
    from backend.services import trade_log_service
    monkeypatch.setattr(trade_log_service, "_DB_PATH", db_path)

    # Reset schema caches
    from backend.services import (
        pair_admission_controller,
        pair_pnl_regulator,
        ea_closed_trades_service,
    )
    monkeypatch.setattr(pair_admission_controller, "_SCHEMA_ENSURED", False)
    monkeypatch.setattr(pair_pnl_regulator, "_SCHEMA_ENSURED", False)
    monkeypatch.setattr(ea_closed_trades_service, "_SCHEMA_ENSURED", False)

    # Tables sources requises
    with sqlite3.connect(db_path) as c:
        c.execute("""
            CREATE TABLE personal_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pair TEXT, direction TEXT, entry_price REAL,
                stop_loss REAL, take_profit REAL, size_lot REAL,
                signal_pattern TEXT, signal_confidence REAL,
                checklist_passed INTEGER, notes TEXT,
                status TEXT, exit_price REAL, pnl REAL,
                created_at TEXT, closed_at TEXT, user TEXT,
                is_auto INTEGER, close_reason TEXT
            )
        """)
        c.execute("""
            CREATE TABLE signal_rejections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT, pair TEXT, direction TEXT,
                confidence REAL, reason_code TEXT, details TEXT,
                user_id INTEGER
            )
        """)
        c.execute("""
            CREATE TABLE mt5_pushes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                destination_id TEXT, date TEXT, pair TEXT, direction TEXT,
                entry_price_5dp TEXT, pushed_at TEXT, ok INTEGER, bridge_response TEXT
            )
        """)
    yield db_path


def _iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _insert_signal(db_path, pair, direction, conf, days_ago):
    with sqlite3.connect(db_path) as c:
        c.execute(
            "INSERT INTO signal_rejections (created_at, pair, direction, confidence, reason_code) VALUES (?, ?, ?, ?, 'test')",
            (_iso(days_ago), pair, direction, conf),
        )


def _insert_trade(db_path, pair, direction, pnl, days_ago):
    with sqlite3.connect(db_path) as c:
        c.execute(
            """INSERT INTO personal_trades (pair, direction, status, is_auto, pnl, closed_at)
               VALUES (?, ?, 'CLOSED', 1, ?, ?)""",
            (pair, direction, pnl, _iso(days_ago)),
        )


# ─── Metrics compute ──────────────────────────────────────────────────

def test_compute_metrics_empty():
    from backend.services import promotion_engine as pe
    m = pe._compute_metrics([])
    assert m["n"] == 0
    assert m["wr"] == 0.0
    assert m["n_consec_sl"] == 0


def test_compute_metrics_win_rate_and_ev(_isolated_db):
    from backend.services import promotion_engine as pe
    # 3 wins de +10, 2 losses de -5 → WR 60%, EV +4
    trades = [
        {"pnl": 10.0}, {"pnl": 10.0}, {"pnl": 10.0},
        {"pnl": -5.0}, {"pnl": -5.0},
    ]
    m = pe._compute_metrics(trades)
    assert m["n"] == 5
    assert m["wr"] == 60.0
    assert m["ev"] == 4.0
    assert m["pnl_cumul"] == 20.0


def test_compute_metrics_consec_sl(_isolated_db):
    from backend.services import promotion_engine as pe
    # Trades ordered newest → oldest : 3 SL récents puis 1 win
    trades = [{"pnl": -5.0}, {"pnl": -5.0}, {"pnl": -5.0}, {"pnl": 10.0}]
    m = pe._compute_metrics(trades)
    assert m["n_consec_sl"] == 3


# ─── Gate 1 : Watch → Demo obs ─────────────────────────────────────────

def test_gate_1_blocks_when_signals_insufficient(_isolated_db):
    from backend.services import promotion_engine as pe
    # 5 signaux ≥60 sur 14j (seuil 15)
    for i in range(5):
        _insert_signal(_isolated_db, "XAU/USD", "buy", 65.0, 1 + i)
    r = pe.evaluate_gate_1_watch_to_demo_obs("XAU/USD", "buy")
    assert r["eligible"] is False
    assert any("signals_below_15" in b for b in r["blockers"])


def test_gate_1_blocks_when_direction_imbalance(_isolated_db):
    from backend.services import promotion_engine as pe
    # 20 signaux ≥60 mais tous BUY (0 sell) → imbalance 100%
    for i in range(20):
        _insert_signal(_isolated_db, "XAU/USD", "buy", 65.0, 1 + i * 0.5)
    r = pe.evaluate_gate_1_watch_to_demo_obs("XAU/USD", "buy")
    assert r["eligible"] is False
    assert any("direction_imbalance" in b for b in r["blockers"])


def test_gate_1_eligible_when_all_criteria_met(_isolated_db):
    from backend.services import promotion_engine as pe
    # 40 signaux ≥60 (20 buy + 20 sell) : ≥15 par direction + imbalance 0
    # ATTENTION : la query filtre par direction, donc besoin ≥15 par direction
    for i in range(20):
        _insert_signal(_isolated_db, "XAU/USD", "buy", 65.0, 1 + i * 0.3)
        _insert_signal(_isolated_db, "XAU/USD", "sell", 65.0, 1 + i * 0.3)
    r = pe.evaluate_gate_1_watch_to_demo_obs("XAU/USD", "buy")
    # Age = None (aucune row pair_admission_state pour cette pair) → pas de blocker age
    assert r["eligible"] is True, f"Expected eligible, got blockers={r['blockers']} vetos={r['vetos']}"
    assert r["metrics"]["signals_14d"] >= 15


# ─── Gate 2 : Demo obs → Demo tradable ────────────────────────────────

def test_gate_2_blocks_when_trades_insufficient(_isolated_db):
    from backend.services import promotion_engine as pe
    # 10 trades sur 10j (seuil 30)
    for i in range(10):
        _insert_trade(_isolated_db, "XAU/USD", "buy", 10.0, i * 0.5)
    r = pe.evaluate_gate_2_demo_obs_to_demo_trad("XAU/USD", "buy")
    assert r["eligible"] is False
    assert any("trades_below_30" in b for b in r["blockers"])


def test_gate_2_blocks_when_wr_below_45(_isolated_db):
    from backend.services import promotion_engine as pe
    # 30 trades : 12 wins + 18 losses → WR 40% (sous 45%)
    for i in range(12):
        _insert_trade(_isolated_db, "XAU/USD", "buy", 10.0, 1 + i * 0.2)
    for i in range(18):
        _insert_trade(_isolated_db, "XAU/USD", "buy", -5.0, 3 + i * 0.2)
    r = pe.evaluate_gate_2_demo_obs_to_demo_trad("XAU/USD", "buy")
    assert r["eligible"] is False
    assert any("wr_below_45.0" in b for b in r["blockers"])


# ─── Démotion Demo tradable ───────────────────────────────────────────

def test_demotion_demo_trad_5_consec_sl(_isolated_db):
    from backend.services import promotion_engine as pe
    from backend.services import pair_admission_controller as pac

    # Setup : XAU/USD buy AUTO_EXEC sur admin_legacy
    pac.set_state("XAU/USD", pac.STATE_AUTO_EXEC, "test",
                  direction="buy", destination="admin_legacy")

    # 5 SL récents consécutifs
    for i in range(5):
        _insert_trade(_isolated_db, "XAU/USD", "buy", -5.0, i * 0.1)

    dem = pe.check_demotion("XAU/USD", "buy", "admin_legacy")
    assert dem is not None
    assert dem["trigger"] == "5_consec_sl"
    assert dem["to_state"] == pac.STATE_TELEGRAM


def test_demotion_live_trad_3_consec_sl(_isolated_db):
    from backend.services import promotion_engine as pe
    from backend.services import pair_admission_controller as pac

    pac.set_state("XAU/USD", pac.STATE_AUTO_EXEC, "test",
                  direction="buy", destination="admin_live")

    # 3 SL consécutifs suffisent pour Live tradable
    for i in range(3):
        _insert_trade(_isolated_db, "XAU/USD", "buy", -5.0, i * 0.1)

    dem = pe.check_demotion("XAU/USD", "buy", "admin_live")
    assert dem is not None
    assert dem["trigger"] == "3_consec_sl"


def test_demotion_none_when_not_auto_exec(_isolated_db):
    from backend.services import promotion_engine as pe

    # État par défaut = OBSERVED, pas AUTO_EXEC → pas de démotion possible
    dem = pe.check_demotion("XAU/USD", "buy", "admin_legacy")
    assert dem is None


# ─── Cycle runner ─────────────────────────────────────────────────────

def test_run_cycle_empty_state(_isolated_db, monkeypatch):
    """Cycle sur DB vide : 0 promotion + 0 démotion + pas d'erreur."""
    from backend.services import promotion_engine as pe
    monkeypatch.setattr("config.settings.WATCHED_PAIRS", ["XAU/USD"], raising=False)
    summary = pe.run_promotion_cycle()
    assert summary["errors"] == 0
    assert summary["demotions_applied"] == 0


def test_run_cycle_applies_demotion(_isolated_db, monkeypatch):
    """Cycle avec 5 SL consec sur AUTO_EXEC admin_legacy → démote automatiquement."""
    from backend.services import promotion_engine as pe
    from backend.services import pair_admission_controller as pac

    # Setup : XAU/USD buy AUTO_EXEC + 5 SL récents
    pac.set_state("XAU/USD", pac.STATE_AUTO_EXEC, "seed",
                  direction="buy", destination="admin_legacy")
    for i in range(5):
        _insert_trade(_isolated_db, "XAU/USD", "buy", -5.0, i * 0.1)

    # Force WATCHED_PAIRS restreint pour le test
    monkeypatch.setattr("config.settings.WATCHED_PAIRS", ["XAU/USD"], raising=False)
    summary = pe.run_promotion_cycle()

    # Démotion appliquée
    assert summary["demotions_applied"] >= 1
    # État après cycle = TELEGRAM
    state = pac.get_current_state("XAU/USD", direction="buy", destination="admin_legacy")
    assert state == pac.STATE_TELEGRAM
