"""Tests des 4 modules de preparation live : analytics, kill_switch,
sizing, drift_detection."""
from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.services import (
    analytics_service,
    backtest_service,
    drift_detection,
    kill_switch,
    sizing,
    trade_log_service,
)


# ─── Sizing ─────────────────────────────────────────────────────────


def test_confidence_multiplier_clamps_and_scales():
    assert sizing.confidence_multiplier(40) == 0.5
    assert sizing.confidence_multiplier(60) == 0.5
    assert sizing.confidence_multiplier(95) == 1.5
    assert sizing.confidence_multiplier(100) == 1.5
    # 77.5 = milieu de 60-95 → ~1.0
    assert 0.9 < sizing.confidence_multiplier(77.5) < 1.1


def test_confidence_multiplier_none_is_neutral():
    assert sizing.confidence_multiplier(None) == 1.0


def test_compute_risk_money_applies_confidence_and_pnl(tmp_path: Path):
    """risk_money = base * conf_mult * pnl_mult, avec TRADING_CAPITAL
    et RISK_PER_TRADE_PCT des settings."""
    trades_db = tmp_path / "trades.db"
    with patch.object(trade_log_service, "_DB_PATH", trades_db):
        trade_log_service._init_schema()  # DB vide = pnl_mult 1.0

        setup = SimpleNamespace(confidence_score=95)
        result = sizing.compute_risk_money(setup)

    assert result["conf_mult"] == 1.5
    assert result["pnl_mult"] == 1.0
    # base = TRADING_CAPITAL * RISK_PER_TRADE_PCT / 100
    # final = base * 1.5 * 1.0
    assert result["risk_money"] == round(result["base"] * 1.5, 2)


def test_recent_pnl_multiplier_halves_when_negative(tmp_path: Path):
    trades_db = tmp_path / "trades.db"
    with patch.object(trade_log_service, "_DB_PATH", trades_db):
        trade_log_service._init_schema()
        # Insere un trade ferme perdant dans les 7 derniers jours.
        closed_at = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(trades_db) as c:
            c.execute(
                """INSERT INTO personal_trades
                   (user, pair, direction, entry_price, stop_loss, take_profit,
                    size_lot, status, pnl, created_at, closed_at)
                   VALUES ('u', 'EUR/USD', 'buy', 1.1, 1.09, 1.11, 0.1,
                           'CLOSED', -500, ?, ?)""",
                (closed_at, closed_at),
            )
        mult = sizing.recent_pnl_multiplier()
    assert mult == 0.5


# ─── Kill switch ────────────────────────────────────────────────────


@pytest.fixture
def _isolated_kill_switch_state(tmp_path: Path, monkeypatch):
    """Isole l'etat du kill switch dans un fichier temporaire."""
    state_file = tmp_path / "ks.json"
    monkeypatch.setattr(kill_switch, "_STATE_PATH", state_file)
    return state_file


def test_kill_switch_manual_enable_disable(_isolated_kill_switch_state):
    kill_switch.set_manual(enabled=True, reason="test pause")
    assert kill_switch.is_manually_enabled() is True
    st = kill_switch.status()
    assert st["active"] is True
    assert "test pause" in (st["reason"] or "")

    kill_switch.set_manual(enabled=False)
    assert kill_switch.is_manually_enabled() is False
    assert kill_switch.status()["active"] is False


def test_kill_switch_auto_trigger_via_daily_loss(
    _isolated_kill_switch_state, tmp_path: Path
):
    """Si silent_mode_active_any_user retourne True → kill switch auto."""
    with patch(
        "backend.services.trade_log_service.silent_mode_active_any_user",
        return_value=True,
    ):
        st = kill_switch.status()
    assert st["active"] is True
    assert st["auto_triggered_by_daily_loss"] is True


# ─── Drift detection ────────────────────────────────────────────────


def _insert_trade(conn, pair, outcome, emitted_at):
    conn.execute(
        """INSERT INTO trades (pair, direction, entry_price, stop_loss,
           take_profit_1, take_profit_2, pattern, emitted_at, outcome)
           VALUES (?, 'buy', 1.1, 1.09, 1.11, 1.12, 'breakout_up', ?, ?)""",
        (pair, emitted_at, outcome),
    )


def test_drift_flags_pair_with_big_recent_drop(tmp_path: Path):
    bt_db = tmp_path / "bt.db"
    with patch.object(backtest_service, "_DB_PATH", bt_db):
        backtest_service._init_schema()

        now = datetime.now(timezone.utc)
        old = (now - timedelta(days=30)).isoformat()
        recent = (now - timedelta(days=2)).isoformat()

        with sqlite3.connect(bt_db) as c:
            # Baseline : 8 wins / 2 losses sur EUR/USD → 80% win rate
            for _ in range(8):
                _insert_trade(c, "EUR/USD", "WIN_TP1", old)
            for _ in range(2):
                _insert_trade(c, "EUR/USD", "LOSS", old)
            # Recent : 2 wins / 10 losses → ~17% win rate, drop de 63pts
            for _ in range(2):
                _insert_trade(c, "EUR/USD", "WIN_TP1", recent)
            for _ in range(10):
                _insert_trade(c, "EUR/USD", "LOSS", recent)

        result = drift_detection.find_drifts()

    assert "by_pair" in result
    drifts = result["by_pair"]
    assert any(d["key"] == "EUR/USD" for d in drifts)
    eur = next(d for d in drifts if d["key"] == "EUR/USD")
    assert eur["delta_pct"] <= -15  # En-dessous du seuil de drift


def test_drift_ignores_small_samples(tmp_path: Path):
    """Moins de MIN_RECENT_TRADES sur la fenetre recente → pas flag."""
    bt_db = tmp_path / "bt.db"
    with patch.object(backtest_service, "_DB_PATH", bt_db):
        backtest_service._init_schema()
        now = datetime.now(timezone.utc)
        old = (now - timedelta(days=30)).isoformat()
        recent = (now - timedelta(days=2)).isoformat()

        with sqlite3.connect(bt_db) as c:
            for _ in range(20):
                _insert_trade(c, "EUR/USD", "WIN_TP1", old)
            # 3 trades recents seulement → sous le seuil MIN_RECENT_TRADES
            for _ in range(3):
                _insert_trade(c, "EUR/USD", "LOSS", recent)

        result = drift_detection.find_drifts()

    assert all(d["key"] != "EUR/USD" for d in result["by_pair"])


# ─── Analytics ─────────────────────────────────────────────────────


def test_analytics_builds_without_crash_on_empty_dbs(tmp_path: Path):
    """Un deploiement neuf (0 trade) doit retourner un payload complet
    et vide, pas planter."""
    bt_db = tmp_path / "bt.db"
    trades_db = tmp_path / "trades.db"
    with patch.object(backtest_service, "_DB_PATH", bt_db), patch.object(
        trade_log_service, "_DB_PATH", trades_db
    ):
        backtest_service._init_schema()
        trade_log_service._init_schema()
        result = analytics_service.build_analytics()

    for key in (
        "by_pair", "by_hour_utc", "by_pattern", "by_confidence_bucket",
        "by_asset_class", "by_risk_regime", "execution_quality",
        "signal_volume",
    ):
        assert key in result


def test_analytics_confidence_bucket_groups_scores(tmp_path: Path):
    bt_db = tmp_path / "bt.db"
    trades_db = tmp_path / "trades.db"
    with patch.object(backtest_service, "_DB_PATH", bt_db), patch.object(
        trade_log_service, "_DB_PATH", trades_db
    ):
        backtest_service._init_schema()
        trade_log_service._init_schema()

        emitted = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(bt_db) as c:
            # Bucket 80-90 : 2 wins, 1 loss
            c.execute(
                "INSERT INTO trades (pair, direction, entry_price, stop_loss, "
                "take_profit_1, take_profit_2, confidence_score, pattern, "
                "emitted_at, outcome) VALUES "
                "('EUR/USD','buy',1.1,1.09,1.11,1.12,85,'breakout_up',?,'WIN_TP1'),"
                "('GBP/USD','buy',1.3,1.29,1.31,1.32,82,'breakout_up',?,'WIN_TP1'),"
                "('USD/JPY','buy',150,149,151,152,87,'breakout_up',?,'LOSS'),"
                # Bucket 60-70 : 1 win, 2 losses
                "('XAU/USD','sell',4800,4810,4790,4780,65,'breakout_down',?,'WIN_TP1'),"
                "('XAG/USD','sell',30,31,29,28,62,'breakout_down',?,'LOSS'),"
                "('AUD/USD','sell',0.65,0.66,0.64,0.63,68,'breakout_down',?,'LOSS')",
                (emitted,) * 6,
            )
        result = analytics_service.build_analytics()

    buckets = {b["key"]: b for b in result["by_confidence_bucket"]}
    assert buckets["80-90"]["wins"] == 2
    assert buckets["80-90"]["losses"] == 1
    assert buckets["60-70"]["wins"] == 1
    assert buckets["60-70"]["losses"] == 2
