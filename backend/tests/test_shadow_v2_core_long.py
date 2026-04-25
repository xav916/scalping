"""Tests Phase 4 — module shadow_v2_core_long.

Couvre :
- aggregate_to_h4 (skip bars partiels)
- ensure_schema (idempotent)
- _persist_setup (UNIQUE constraint + risk_pct invalide)
- run_shadow_log (filtrage pattern + direction, no doublons)
- list_setups / summary
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.models.schemas import Candle, TradeDirection
from backend.services import shadow_v2_core_long as shadow


# ─── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """DB SQLite temporaire isolée pour chaque test."""
    db_path = tmp_path / "shadow_test.db"
    monkeypatch.setattr(shadow, "DB_PATH", db_path)
    return db_path


def _h1_candle(ts: datetime, close: float, span: float = 1.0) -> Candle:
    return Candle(
        timestamp=ts,
        open=close - span / 2,
        high=close + span,
        low=close - span,
        close=close,
        volume=100,
    )


def _make_h1_sequence(start: datetime, n: int, base: float = 2000.0,
                      step: float = 0.5) -> list[Candle]:
    """Séquence montante simple pour permettre des patterns LONG."""
    return [
        _h1_candle(start + timedelta(hours=i), base + i * step)
        for i in range(n)
    ]


# ─── aggregate_to_h4 ────────────────────────────────────────────────────────


def test_aggregate_to_h4_skips_partial_bars():
    """Les bars H4 incomplets (<4 H1) sont exclus."""
    start = datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)  # 00 UTC = bucket 0
    # 4 H1 complets pour le bucket 00-04, puis 2 H1 du bucket 04-08 (partiel)
    candles = _make_h1_sequence(start, 6)
    h4 = shadow.aggregate_to_h4(candles)
    assert len(h4) == 1, "Seul le bucket complet 00-04 doit être retenu"
    assert h4[0].timestamp == start
    assert h4[0].open == candles[0].open
    assert h4[0].close == candles[3].close
    assert h4[0].high == max(c.high for c in candles[:4])
    assert h4[0].low == min(c.low for c in candles[:4])


def test_aggregate_to_h4_alignment_buckets():
    """Bars alignés sur 00/04/08/12/16/20 UTC."""
    # Démarrage à 02 UTC (mid-bucket)
    start = datetime(2026, 4, 1, 2, 0, tzinfo=timezone.utc)
    candles = _make_h1_sequence(start, 12)
    h4 = shadow.aggregate_to_h4(candles)
    # Buckets attendus : 00 (incomplet 02-03 = 2 candles, skip),
    # 04 (4 candles complet), 08 (4 candles complet), 12 (2 candles, skip)
    assert len(h4) == 2
    assert h4[0].timestamp.hour == 4
    assert h4[1].timestamp.hour == 8


def test_aggregate_to_h4_empty_input():
    assert shadow.aggregate_to_h4([]) == []


# ─── ensure_schema ──────────────────────────────────────────────────────────


def test_ensure_schema_idempotent(temp_db):
    """Appel multiple ne casse pas la DB."""
    shadow.ensure_schema()
    shadow.ensure_schema()
    shadow.ensure_schema()
    with sqlite3.connect(temp_db) as c:
        # Vérifie que la table existe
        rows = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='shadow_setups'"
        ).fetchall()
        assert len(rows) == 1


# ─── run_shadow_log ─────────────────────────────────────────────────────────


def test_run_shadow_log_empty_input(temp_db):
    """Pas de candles → 0 nouveaux setups, pas d'exception."""
    result = asyncio.run(shadow.run_shadow_log({}))
    assert result == {"XAU/USD": 0, "XAG/USD": 0}


def test_run_shadow_log_too_few_candles(temp_db):
    """Moins de 30 H1 → skipped, 0 setup."""
    start = datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)
    short_h1 = _make_h1_sequence(start, 20)
    result = asyncio.run(shadow.run_shadow_log({"XAU/USD": short_h1, "XAG/USD": []}))
    assert result["XAU/USD"] == 0
    assert result["XAG/USD"] == 0


def test_run_shadow_log_unique_constraint(temp_db):
    """Appels successifs sur les mêmes candles → 1 setup max par bar (idempotent)."""
    start = datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)
    h1 = _make_h1_sequence(start, 200)  # 200 H1 = 50 H4 buckets
    h1_dict = {"XAU/USD": h1, "XAG/USD": h1}

    # 1er appel
    r1 = asyncio.run(shadow.run_shadow_log(h1_dict))
    n1_xau = r1["XAU/USD"]

    # 2e appel identique → 0 nouveau (UNIQUE bloque)
    r2 = asyncio.run(shadow.run_shadow_log(h1_dict))
    assert r2["XAU/USD"] == 0, "Même bar_timestamp ne doit pas créer de doublon"

    # Total en DB = n1
    with sqlite3.connect(temp_db) as c:
        n_total = c.execute(
            "SELECT COUNT(*) FROM shadow_setups WHERE pair = 'XAU/USD'"
        ).fetchone()[0]
        assert n_total == n1_xau


# ─── list_setups / summary ──────────────────────────────────────────────────


def test_list_setups_empty_db(temp_db):
    setups = shadow.list_setups()
    assert setups == []


def test_summary_empty_db(temp_db):
    s = shadow.summary()
    assert s == {"systems": []}


def test_summary_with_resolved_setups(temp_db):
    """Insère manuellement quelques setups résolus, vérifie KPIs."""
    shadow.ensure_schema()
    now = datetime.now(timezone.utc)
    rows_to_insert = [
        # (system_id, bar_ts, outcome, pnl_eur)
        ("V2_CORE_LONG_XAUUSD_4H", now - timedelta(days=10), "TP1", 100.0),
        ("V2_CORE_LONG_XAUUSD_4H", now - timedelta(days=8), "SL", -50.0),
        ("V2_CORE_LONG_XAUUSD_4H", now - timedelta(days=5), "TP1", 150.0),
        ("V2_CORE_LONG_XAUUSD_4H", now - timedelta(days=2), "SL", -50.0),
    ]
    with sqlite3.connect(temp_db) as c:
        for sys_id, bar_ts, outcome, pnl in rows_to_insert:
            c.execute(
                """INSERT INTO shadow_setups (
                    cycle_at, bar_timestamp, system_id, pair, timeframe,
                    direction, pattern, entry_price, stop_loss, take_profit_1,
                    risk_pct, rr, sizing_capital_eur, sizing_risk_pct,
                    sizing_position_eur, sizing_max_loss_eur,
                    outcome, exit_at, exit_price, pnl_pct_net, pnl_eur
                ) VALUES (?, ?, ?, 'XAU/USD', '4h', 'buy', 'momentum_up',
                          2000.0, 1980.0, 2050.0, 0.01, 2.5, 10000, 0.005, 5000, 50,
                          ?, ?, 2050.0, 1.0, ?)""",
                (bar_ts.isoformat(), bar_ts.isoformat(), sys_id, outcome,
                 bar_ts.isoformat(), pnl),
            )

    s = shadow.summary()
    assert len(s["systems"]) == 1
    sys_data = s["systems"][0]
    assert sys_data["n_total"] == 4
    assert sys_data["n_tp1"] == 2
    assert sys_data["n_sl"] == 2
    assert sys_data["n_pending"] == 0
    # PF = 250 / 100 = 2.5
    assert sys_data["pf"] == pytest.approx(2.5, rel=0.01)
    # WR = 2/4 = 50%
    assert sys_data["wr_pct"] == pytest.approx(50.0, rel=0.01)
    # KPIs avancés présents
    assert "advanced" in sys_data
    assert sys_data["advanced"]["max_dd_pct"] is not None
    assert len(sys_data["advanced"]["equity_curve"]) == 4
