"""Tests pour backend.services.pair_admission_controller."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Redirige _DB_PATH vers une DB temporaire pour isolation."""
    db_path = tmp_path / "trades.db"
    from backend.services import trade_log_service
    monkeypatch.setattr(trade_log_service, "_DB_PATH", db_path)

    # backtest.db alimente le scoring depuis le 2026-08-04 — l'isoler aussi,
    # sinon les tests liraient (et créeraient) le fichier du dépôt.
    from backend.services import backtest_service
    monkeypatch.setattr(backtest_service, "_DB_PATH", tmp_path / "backtest.db")

    # Reset schema-ensured caches
    from backend.services import (
        pair_admission_controller,
        pair_pnl_regulator,
        ea_closed_trades_service,
    )
    monkeypatch.setattr(pair_admission_controller, "_SCHEMA_ENSURED", False)
    monkeypatch.setattr(pair_pnl_regulator, "_SCHEMA_ENSURED", False)
    monkeypatch.setattr(ea_closed_trades_service, "_SCHEMA_ENSURED", False)

    # Tables sources nécessaires pour scoring
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
        c.execute(
            """
            CREATE TABLE shadow_setups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                system_id TEXT, pair TEXT, direction TEXT,
                outcome TEXT, exit_at TEXT, pnl_eur REAL
            )
            """
        )
    yield db_path


def _insert_trade(db_path, pair: str, pnl: float, closed_at: str | None = None):
    closed_at = closed_at or datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as c:
        c.execute(
            "INSERT INTO personal_trades (pair, status, pnl, is_auto, closed_at, close_reason) "
            "VALUES (?, 'CLOSED', ?, 1, ?, ?)",
            (pair, pnl, closed_at, "SL" if pnl < 0 else "TP1"),
        )


# ─── State management ──────────────────────────────────────────────────


def test_default_state_is_observed(_isolated_db):
    from backend.services import pair_admission_controller as pac
    assert pac.get_current_state("EUR/USD") == pac.STATE_OBSERVED


def test_set_state_transitions(_isolated_db):
    from backend.services import pair_admission_controller as pac
    pac.set_state("XAU/USD", pac.STATE_AUTO_EXEC, "test setup")
    assert pac.get_current_state("XAU/USD") == pac.STATE_AUTO_EXEC
    pac.set_state("XAU/USD", pac.STATE_PAUSED, "test pause")
    assert pac.get_current_state("XAU/USD") == pac.STATE_PAUSED


def test_set_state_idempotent_if_same(_isolated_db):
    from backend.services import pair_admission_controller as pac
    pac.set_state("XAU/USD", pac.STATE_AUTO_EXEC, "first")
    result = pac.set_state("XAU/USD", pac.STATE_AUTO_EXEC, "same")
    assert result == -1  # signal idempotent


def test_invalid_state_raises(_isolated_db):
    from backend.services import pair_admission_controller as pac
    with pytest.raises(ValueError):
        pac.set_state("XAU/USD", "INVALID_STATE", "test")


# ─── Eligibility ───────────────────────────────────────────────────────


def test_is_auto_exec_eligible(_isolated_db):
    from backend.services import pair_admission_controller as pac
    assert not pac.is_auto_exec_eligible("XAU/USD")
    pac.set_state("XAU/USD", pac.STATE_AUTO_EXEC, "test")
    assert pac.is_auto_exec_eligible("XAU/USD")
    pac.set_state("XAU/USD", pac.STATE_PAUSED, "test")
    assert not pac.is_auto_exec_eligible("XAU/USD")


def test_is_telegram_eligible(_isolated_db):
    from backend.services import pair_admission_controller as pac
    # OBSERVED → pas eligible Telegram
    assert not pac.is_telegram_eligible("XAU/USD")
    # TELEGRAM/AUTO_EXEC/PAUSED → eligible
    pac.set_state("XAU/USD", pac.STATE_TELEGRAM, "test")
    assert pac.is_telegram_eligible("XAU/USD")
    pac.set_state("XAU/USD", pac.STATE_AUTO_EXEC, "test")
    assert pac.is_telegram_eligible("XAU/USD")
    pac.set_state("XAU/USD", pac.STATE_PAUSED, "test")
    assert pac.is_telegram_eligible("XAU/USD")
    # DEMOTED → pas eligible
    pac.set_state("XAU/USD", pac.STATE_DEMOTED, "test")
    assert not pac.is_telegram_eligible("XAU/USD")


# ─── Score composite ───────────────────────────────────────────────────


def test_compute_promotion_score_no_data(_isolated_db):
    from backend.services import pair_admission_controller as pac
    score = pac.compute_promotion_score("EUR/USD")
    assert score["sample"] == 0
    assert score["eligible_for"] == pac.STATE_OBSERVED


def test_compute_promotion_score_meets_threshold(_isolated_db, monkeypatch):
    monkeypatch.setenv("TRADING_CAPITAL", "10000")
    import importlib
    from config import settings
    importlib.reload(settings)
    from backend.services import pair_admission_controller as pac
    importlib.reload(pac)

    # 30 trades, 18 wins de +20€, 12 losses de -10€ → sum=240€=2.4%pct, WR=60%, PF=3.0
    for i in range(30):
        pnl = 20.0 if i % 5 < 3 else -10.0
        _insert_trade(
            _isolated_db, "XAU/USD", pnl,
            closed_at=(datetime.now(timezone.utc) + timedelta(minutes=i)).isoformat(),
        )
    score = pac.compute_promotion_score("XAU/USD")
    assert score["sample"] == 30
    assert score["wr"] >= 45.0
    assert score["pnl_pct"] >= 2.0
    assert score["pf"] >= 1.3
    assert score["eligible_for"] == pac.AUTO_PROMOTE_TARGET


# ─── shadow_setups n'alimente plus le scoring (2026-08-04) ─────────────
#
# Ces deux tests vérifiaient auparavant que le fallback shadow filtrait bien
# `system_id LIKE 'V1_SHADOW_%'`, pour éviter que les shadows V2_CORE_LONG
# (TF H4, SL/TP différents) ne contaminent le scoring V1. La préoccupation
# reste valide mais est désormais structurelle : la source est
# `backtest.db.trades`, qui ne contient que des signaux du radar V1.
#
# Le fallback shadow a été retiré parce que la table était corrompue — sa
# déduplication ne mordait pas, cf. test_admission_backtest_source.py.


def _insert_shadow(db_path, pair: str, direction: str, pnl: float, system_id: str, idx: int = 0):
    exit_at = (datetime.now(timezone.utc) + timedelta(minutes=idx)).isoformat()
    with sqlite3.connect(db_path) as c:
        c.execute(
            "INSERT INTO shadow_setups (system_id, pair, direction, exit_at, outcome, pnl_eur) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (system_id, pair, direction, exit_at, "TP1" if pnl > 0 else "SL", pnl),
        )


def test_shadow_setups_nalimente_plus_le_scoring(_isolated_db):
    """Même gorgé de shadows résolus, le scoring doit rester vide."""
    from backend.services import pair_admission_controller as pac

    for i in range(20):
        _insert_shadow(_isolated_db, "XAU/USD", "buy", 50.0, "V1_SHADOW_XAUUSD_buy", idx=i)
    for i in range(20):
        _insert_shadow(_isolated_db, "XAU/USD", "buy", -50.0, "V2_CORE_LONG_XAUUSD_4H", idx=100 + i)

    assert pac._fetch_trades_for_pair("XAU/USD", window=30, direction="buy") == []
    assert pac._fetch_trades_for_pair("XAU/USD", window=30, direction=None) == []


# ─── Auto transitions ──────────────────────────────────────────────────


def test_evaluate_observed_promotes_to_target_if_criteria_met(_isolated_db):
    from backend.services import pair_admission_controller as pac

    # 30 winning trades clean
    for i in range(30):
        _insert_trade(
            _isolated_db, "XAU/USD", 50.0,
            closed_at=(datetime.now(timezone.utc) + timedelta(minutes=i)).isoformat(),
        )
    d = pac.evaluate_pair("XAU/USD")
    assert d["action"] == "transition"
    # Target dépend de AUTO_PROMOTE_TARGET env (default TELEGRAM ; AUTO_EXEC si full-auto).
    assert d["to_state"] == pac.AUTO_PROMOTE_TARGET
    assert pac.get_current_state("XAU/USD") == pac.AUTO_PROMOTE_TARGET


def test_evaluate_auto_exec_demotes_to_paused_on_drawdown(_isolated_db):
    from backend.services import pair_admission_controller as pac

    # Initial state AUTO_EXEC
    pac.set_state("XAG/USD", pac.STATE_AUTO_EXEC, "test init")
    # 30 trades pertes : -50€ chacun → -1500€ sur 10k = -15% > seuil -3%
    for i in range(30):
        _insert_trade(
            _isolated_db, "XAG/USD", -50.0,
            closed_at=(datetime.now(timezone.utc) + timedelta(minutes=i)).isoformat(),
        )
    d = pac.evaluate_pair("XAG/USD")
    assert d["action"] == "transition"
    assert d["to_state"] == pac.STATE_PAUSED


def test_demoted_requires_manual_transition(_isolated_db):
    from backend.services import pair_admission_controller as pac

    pac.set_state("XYZ/ABC", pac.STATE_DEMOTED, "test demote")
    d = pac.evaluate_pair("XYZ/ABC")
    assert d["action"] == "keep"
    assert pac.get_current_state("XYZ/ABC") == pac.STATE_DEMOTED


# ─── Backfill ──────────────────────────────────────────────────────────


def test_backfill_initial_states_idempotent(_isolated_db):
    from backend.services import pair_admission_controller as pac

    result1 = pac.backfill_initial_states()
    n1 = result1["applied"]
    assert n1 > 0
    # Second run : déjà des rows, donc 0 nouvelle transition
    result2 = pac.backfill_initial_states()
    assert result2["applied"] == 0


# ─── Destination-aware (2026-07-29 Sprint 1) ──────────────────────────
# Une même (pair, direction) peut avoir des états distincts par destination.
# Ex : XAU/USD sell = AUTO_EXEC sur admin_legacy (Demo tradable) et
# TELEGRAM sur admin_live (Live observation). Permet le workflow test-then-promote.


def test_destination_specific_state_overrides_legacy_row(_isolated_db):
    """Row (pair, dir, dest) doit primer sur row (pair, dir, dest IS NULL)."""
    from backend.services import pair_admission_controller as pac

    # Legacy : XAU/USD sell = AUTO_EXEC sur toutes destinations
    pac.set_state("XAU/USD", pac.STATE_AUTO_EXEC, "legacy", direction="sell")
    # Override : sur admin_live seulement, on veut TELEGRAM (observation)
    pac.set_state("XAU/USD", pac.STATE_TELEGRAM, "live obs", direction="sell", destination="admin_live")

    # Résolution destination-specific
    assert pac.get_current_state("XAU/USD", direction="sell", destination="admin_live") == pac.STATE_TELEGRAM
    # Legacy row s'applique quand pas d'override (admin_legacy sans row propre)
    assert pac.get_current_state("XAU/USD", direction="sell", destination="admin_legacy") == pac.STATE_AUTO_EXEC


def test_two_destinations_independent_states(_isolated_db):
    """WTI/USD buy = AUTO_EXEC sur admin_legacy + TELEGRAM sur admin_live."""
    from backend.services import pair_admission_controller as pac

    pac.set_state("WTI/USD", pac.STATE_AUTO_EXEC, "demo trad",
                  direction="buy", destination="admin_legacy")
    pac.set_state("WTI/USD", pac.STATE_TELEGRAM, "live obs",
                  direction="buy", destination="admin_live")

    assert pac.get_current_state("WTI/USD", direction="buy", destination="admin_legacy") == pac.STATE_AUTO_EXEC
    assert pac.get_current_state("WTI/USD", direction="buy", destination="admin_live") == pac.STATE_TELEGRAM


def test_destination_none_uses_legacy_cascade(_isolated_db):
    """destination=None ne matche PAS les rows destination-specific."""
    from backend.services import pair_admission_controller as pac

    # Row destination-specific uniquement
    pac.set_state("EUR/USD", pac.STATE_AUTO_EXEC, "live only",
                  direction="buy", destination="admin_live")

    # Query sans destination → tombe sur DEFAULT_STATE (rien en cascade legacy)
    assert pac.get_current_state("EUR/USD", direction="buy") == pac.DEFAULT_STATE


def test_is_auto_exec_eligible_respects_destination(_isolated_db):
    """XAU/USD = AUTO_EXEC sur admin_legacy uniquement → seul admin_legacy éligible."""
    from backend.services import pair_admission_controller as pac

    pac.set_state("XAU/USD", pac.STATE_AUTO_EXEC, "demo",
                  direction="sell", destination="admin_legacy")
    pac.set_state("XAU/USD", pac.STATE_TELEGRAM, "live obs",
                  direction="sell", destination="admin_live")

    assert pac.is_auto_exec_eligible("XAU/USD", direction="sell", destination="admin_legacy") is True
    assert pac.is_auto_exec_eligible("XAU/USD", direction="sell", destination="admin_live") is False


def test_has_explicit_state_matches_via_cascade(_isolated_db):
    """Row destination-agnostic (dest IS NULL) satisfait check destination-specific."""
    from backend.services import pair_admission_controller as pac

    pac.set_state("BTC/USD", pac.STATE_AUTO_EXEC, "legacy", direction="buy")

    # Row (dir, dest=NULL) → check (dir, dest="admin_legacy") True via cascade
    assert pac.has_explicit_state("BTC/USD", direction="buy", destination="admin_legacy") is True
    assert pac.has_explicit_state("BTC/USD", direction="buy", destination="admin_live") is True


def test_destination_normalization_invalid_returns_none(_isolated_db):
    """Destination invalide → fallback rétro-compat (comportement legacy)."""
    from backend.services import pair_admission_controller as pac

    pac.set_state("ETH/USD", pac.STATE_AUTO_EXEC, "legacy", direction="sell")

    # Destination invalide traitée comme None → matche row legacy
    assert pac.get_current_state("ETH/USD", direction="sell", destination="ADMIN_BINANCE_FUTURES") == pac.STATE_AUTO_EXEC


def test_get_full_state_includes_destination(_isolated_db):
    """get_full_state doit exposer le champ destination dans le dict retourné."""
    from backend.services import pair_admission_controller as pac

    pac.set_state("XAU/USD", pac.STATE_AUTO_EXEC, "demo trad",
                  direction="sell", destination="admin_legacy")

    full = pac.get_full_state("XAU/USD", direction="sell", destination="admin_legacy")
    assert full["state"] == pac.STATE_AUTO_EXEC
    assert full["destination"] == "admin_legacy"
    assert full["direction"] == "sell"
