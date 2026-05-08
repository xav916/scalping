"""Tests pour `scripts.research.track_a_veto_counterfactual`.

Couvre l'extraction depuis SQLite, l'agrégation par groupe, et le
rendu Markdown. DB synthétique en tmp_path.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.research import track_a_veto_counterfactual as ctf


# ─── Fixtures ────────────────────────────────────────────────────────


def _create_schema(db_path: Path) -> None:
    """Crée une table shadow_setups minimale compatible avec le script."""
    with sqlite3.connect(db_path) as c:
        c.execute("""
            CREATE TABLE shadow_setups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                detected_at TIMESTAMP,
                cycle_at TIMESTAMP,
                bar_timestamp TIMESTAMP NOT NULL,
                system_id TEXT NOT NULL,
                pair TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                direction TEXT NOT NULL,
                pattern TEXT,
                entry_price REAL,
                stop_loss REAL,
                take_profit_1 REAL,
                take_profit_2 REAL,
                risk_pct REAL,
                rr REAL,
                sizing_capital_eur REAL,
                sizing_risk_pct REAL,
                sizing_position_eur REAL,
                sizing_max_loss_eur REAL,
                macro_features_json TEXT,
                outcome TEXT,
                exit_at TIMESTAMP,
                exit_price REAL,
                pnl_pct_net REAL,
                pnl_eur REAL,
                geopolitical_features_json TEXT
            )
        """)


def _insert(db_path: Path, *, pair: str, outcome: str | None,
            pnl_pct: float | None, would_veto: bool, rules_matched: list[str],
            bar_ts: str = "2026-05-08T12:00:00+00:00") -> None:
    geo = {
        "captured_at": "2026-05-08T12:00:00Z",
        "veto_evaluated": {
            "would_veto": would_veto,
            "rules_matched": rules_matched,
            "rules_evaluated": ["iran_hormuz", "fed_dovish", "recession", "gdelt_stress"],
        },
    }
    with sqlite3.connect(db_path) as c:
        c.execute(
            """
            INSERT INTO shadow_setups
                (bar_timestamp, system_id, pair, timeframe, direction,
                 outcome, pnl_pct_net, geopolitical_features_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (bar_ts, f"V2_CORE_LONG_{pair.replace('/', '')}_4H", pair, "4h", "buy",
             outcome, pnl_pct, json.dumps(geo)),
        )


# ─── load_reconciled_setups ──────────────────────────────────────────


def test_load_returns_empty_on_missing_db(tmp_path):
    setups = ctf.load_reconciled_setups(tmp_path / "nope.db")
    assert setups == []


def test_load_filters_unresolved_setups(tmp_path):
    db = tmp_path / "trades.db"
    _create_schema(db)
    _insert(db, pair="XAU/USD", outcome=None, pnl_pct=None,
            would_veto=False, rules_matched=[])
    _insert(db, pair="XAU/USD", outcome="TP1", pnl_pct=2.5,
            would_veto=False, rules_matched=[])

    setups = ctf.load_reconciled_setups(db)
    assert len(setups) == 1
    assert setups[0]["outcome"] == "TP1"


def test_load_filters_setups_without_geopolitical_payload(tmp_path):
    """Les setups antérieurs au commit 3ac0d70 ont geopolitical_features_json
    = NULL et doivent être exclus de l'analyse contrefactuelle."""
    db = tmp_path / "trades.db"
    _create_schema(db)
    # Setup avec payload géopolitique
    _insert(db, pair="XAU/USD", outcome="SL", pnl_pct=-1.2,
            would_veto=True, rules_matched=["iran_hormuz"])
    # Setup sans payload (legacy)
    with sqlite3.connect(db) as c:
        c.execute(
            """INSERT INTO shadow_setups
               (bar_timestamp, system_id, pair, timeframe, direction,
                outcome, pnl_pct_net, geopolitical_features_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, NULL)""",
            ("2026-04-27T12:00:00+00:00", "V2_CORE_LONG_XAUUSD_4H",
             "XAU/USD", "4h", "buy", "SL", -1.5),
        )

    setups = ctf.load_reconciled_setups(db)
    assert len(setups) == 1
    assert setups[0]["would_veto"] is True


# ─── compute_group_stats ──────────────────────────────────────────────


def test_stats_empty_group():
    st = ctf.compute_group_stats([])
    assert st["n"] == 0
    assert st["pf"] is None
    assert st["win_rate"] is None
    assert st["total_pnl_pct"] == 0.0


def test_stats_only_wins():
    setups = [
        {"outcome": "TP1", "pnl_pct_net": 3.0},
        {"outcome": "TP1", "pnl_pct_net": 2.5},
    ]
    st = ctf.compute_group_stats(setups)
    assert st["n"] == 2
    assert st["n_tp"] == 2
    assert st["n_sl"] == 0
    assert st["win_rate"] == 100.0
    assert st["pf"] is None  # pas de loss → division impossible
    assert st["total_pnl_pct"] == 5.5


def test_stats_mixed_outcomes_with_pf():
    setups = [
        {"outcome": "TP1", "pnl_pct_net": 4.0},
        {"outcome": "TP1", "pnl_pct_net": 2.0},
        {"outcome": "SL", "pnl_pct_net": -1.0},
        {"outcome": "SL", "pnl_pct_net": -2.0},
        {"outcome": "TIMEOUT", "pnl_pct_net": -0.3},
    ]
    st = ctf.compute_group_stats(setups)
    assert st["n"] == 5
    assert st["n_tp"] == 2
    assert st["n_sl"] == 2
    assert st["n_timeout"] == 1
    assert st["win_rate"] == 50.0  # 2 TP / (2 TP + 2 SL)
    # gains = 4+2 = 6; losses = abs(-1-2-0.3) = 3.3
    assert abs(st["pf"] - (6.0 / 3.3)) < 0.001
    assert st["total_pnl_pct"] == pytest.approx(2.7)


# ─── build_report integration ─────────────────────────────────────────


def test_build_report_empty_sample():
    report = ctf.build_report([], datetime(2026, 5, 8, 22, 0, tzinfo=timezone.utc))
    assert "0 setups" in report
    assert "DÉRISOIRE" in report
    assert "Re-lancer ce script dans 2-3 semaines" in report


def test_build_report_partitions_by_would_veto(tmp_path):
    """Vérifie que la table compare bien les 2 groupes."""
    db = tmp_path / "trades.db"
    _create_schema(db)
    # 3 setups vetoed (all SL)
    for _ in range(3):
        _insert(db, pair="XAU/USD", outcome="SL", pnl_pct=-1.0,
                would_veto=True, rules_matched=["iran_hormuz"])
    # 2 setups passed (TP1)
    for _ in range(2):
        _insert(db, pair="XAU/USD", outcome="TP1", pnl_pct=2.0,
                would_veto=False, rules_matched=[])

    setups = ctf.load_reconciled_setups(db)
    assert len(setups) == 5

    report = ctf.build_report(setups, datetime(2026, 5, 8, 22, 0, tzinfo=timezone.utc))
    assert "5 setups" in report
    # Vérifie qu'il distingue les 2 groupes
    assert "Would VETO" in report
    assert "Would PASS" in report
    # Verdict directionnel : ici veto aurait aidé (vetoed all SL, passed all TP)
    assert "LE VETO AURAIT AIDÉ" in report
    # Détail par règle : iran_hormuz mentionné
    assert "`iran_hormuz`" in report


def test_build_report_handles_only_passed_setups():
    setups = [
        {"id": i, "system_id": "V2", "pair": "XAU/USD", "timeframe": "4h",
         "direction": "buy", "bar_timestamp": "2026-05-08T12:00:00+00:00",
         "outcome": "TP1", "pnl_pct_net": 2.0, "pnl_eur": 200.0,
         "would_veto": False, "rules_matched": [], "polymarket": {}, "gdelt": {}}
        for i in range(5)
    ]
    report = ctf.build_report(setups, datetime(2026, 5, 8, 22, 0, tzinfo=timezone.utc))
    assert "Aucun setup réconcilié n'aurait été veto" in report


def test_build_report_handles_all_vetoed_setups():
    setups = [
        {"id": i, "system_id": "V2", "pair": "XAU/USD", "timeframe": "4h",
         "direction": "buy", "bar_timestamp": "2026-05-08T12:00:00+00:00",
         "outcome": "SL", "pnl_pct_net": -1.0, "pnl_eur": -100.0,
         "would_veto": True, "rules_matched": ["iran_hormuz"],
         "polymarket": {}, "gdelt": {}}
        for i in range(3)
    ]
    report = ctf.build_report(setups, datetime(2026, 5, 8, 22, 0, tzinfo=timezone.utc))
    assert "**Tous** les setups réconciliés auraient été veto" in report
