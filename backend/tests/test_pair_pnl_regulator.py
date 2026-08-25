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


# ─── PAC_EXCLUDED_TICKETS : le second juge ──────────────────────────────
#
# Le régulateur et `pair_admission_controller` notent la même paire sur les
# mêmes clôtures, mais seul le second consultait la liste d'exclusion. Une
# paire pouvait donc être promue par l'un et gardée en pause par l'autre —
# c'est exactement ce qui est arrivé à l'or le 2026-08-25.


def _poser_ticket(db_path: Path, pair: str, pnl: float, ticket, jours: int = 0):
    """Insère un trade daté et TICKETÉ. `mt5_ticket` est en TEXTE ici, comme
    en production — le piège d'affinité SQLite se reproduit tel quel."""
    quand = (datetime.now(timezone.utc) - timedelta(days=jours)).isoformat()
    with sqlite3.connect(db_path) as c:
        c.execute(
            """
            INSERT INTO personal_trades (pair, status, pnl, is_auto, closed_at,
                                         close_reason, mt5_ticket)
            VALUES (?, 'CLOSED', ?, 1, ?, ?, ?)
            """,
            (pair, pnl, quand, "MANUAL" if pnl < 0 else "TP1", str(ticket)),
        )


@pytest.fixture
def exclure(monkeypatch):
    """Règle la liste telle que la lit la fonction livrée."""
    def _set(tickets):
        import config.settings as st
        monkeypatch.setattr(st, "PAC_EXCLUDED_TICKETS", frozenset(tickets))
    return _set


def test_sans_reglage_aucun_trade_n_est_ecarte(_isolated_db, exclure):
    """Vide par défaut : la fenêtre est celle d'avant le correctif."""
    from backend.services import pair_pnl_regulator

    exclure([])
    for i in range(5):
        _poser_ticket(_isolated_db, "XAU/USD", -10.0, 900 + i, jours=i)

    m = pair_pnl_regulator.compute_window_metrics("XAU/USD", 30)
    assert m["n"] == 5
    assert m["sum_pnl"] == -50.0


def test_un_ticket_exclu_sort_de_la_fenetre(_isolated_db, exclure):
    """Le cas de l'or : une position tenue sans stop sur consigne, fermée à la
    main, pèse à elle seule le verdict. Elle ne doit pas noter le système."""
    from backend.services import pair_pnl_regulator

    _poser_ticket(_isolated_db, "XAU/USD", -265.11, 1353960866, jours=5)
    for i in range(4):
        _poser_ticket(_isolated_db, "XAU/USD", +10.0, 900 + i, jours=i)

    exclure([1353960866])
    m = pair_pnl_regulator.compute_window_metrics("XAU/USD", 30)

    assert m["n"] == 4
    assert m["sum_pnl"] == 40.0


def test_la_fenetre_reste_pleine_un_trade_plus_ancien_remonte(_isolated_db, exclure):
    """⛔ L'exclusion se fait avant le LIMIT. L'écarter après rendrait une
    fenêtre de 9 trades en annonçant 10 : on noterait la paire sur moins de
    clôtures que le relevé ne le prétend."""
    from backend.services import pair_pnl_regulator

    # 12 trades : le plus récent (jours=0) est le ticket honni.
    _poser_ticket(_isolated_db, "XAU/USD", -500.0, 777, jours=0)
    for i in range(11):
        _poser_ticket(_isolated_db, "XAU/USD", +1.0, 800 + i, jours=i + 1)

    exclure([777])
    m = pair_pnl_regulator.compute_window_metrics("XAU/USD", 10)

    assert m["n"] == 10, "la fenêtre doit rester pleine"
    assert m["sum_pnl"] == 10.0


def test_les_trades_des_users_premium_sont_filtres_aussi(_isolated_db, exclure):
    """`ea_closed_trades` stocke `mt5_ticket` en ENTIER quand `personal_trades`
    le stocke en TEXTE. Le filtre doit valoir des deux côtés de l'UNION."""
    from backend.services import ea_closed_trades_service, pair_pnl_regulator

    ea_closed_trades_service._ensure_schema()
    with sqlite3.connect(_isolated_db) as c:
        for ticket, pnl in ((555, -300.0), (556, +20.0)):
            c.execute(
                """
                INSERT INTO ea_closed_trades (user_id, pair, direction,
                    entry_price, exit_price, pnl, mt5_ticket, closed_at, reported_at)
                VALUES (2, 'XAU/USD', 'sell', 1.0, 1.0, ?, ?, ?, ?)
                """,
                (pnl, ticket, datetime.now(timezone.utc).isoformat(),
                 datetime.now(timezone.utc).isoformat()),
            )

    exclure([555])
    m = pair_pnl_regulator.compute_window_metrics("XAU/USD", 30)

    assert m["n"] == 1
    assert m["sum_pnl"] == 20.0


def test_la_fenetre_dit_ce_qu_elle_a_ecarte(_isolated_db, exclure):
    """⚠️ Un relevé qui écarte en silence est indiscernable d'un relevé qui
    n'a rien écarté. Le ticket retiré doit être nommé dans le résultat."""
    from backend.services import pair_pnl_regulator

    _poser_ticket(_isolated_db, "XAU/USD", -265.11, 1353960866, jours=5)
    _poser_ticket(_isolated_db, "XAU/USD", +10.0, 901, jours=1)

    exclure([1353960866, 424242])  # 424242 n'existe pas pour cette paire
    m = pair_pnl_regulator.compute_window_metrics("XAU/USD", 30)

    assert m["excluded_tickets"] == [1353960866]


def test_un_seul_ticket_fait_basculer_la_pause(_isolated_db, exclure, monkeypatch):
    """Bout en bout : c'est `evaluate_pair` qui pose la pause opposable à
    TOUTES les destinations. Sans le ticket exclu, elle ne doit pas être posée.

    ⚠️ `TRADING_CAPITAL` est épinglé à sa valeur de PRODUCTION : le seuil se
    mesure en % du capital, donc un test qui laisse traîner le défaut local
    (10 000 €) jugerait sur une échelle que la prod (650 €) n'a jamais eue.
    """
    import config.settings as st
    from backend.services import pair_pnl_regulator

    monkeypatch.setattr(st, "TRADING_CAPITAL", 650.0)

    _poser_ticket(_isolated_db, "XAU/USD", -265.11, 1353960866, jours=5)
    for i in range(11):
        _poser_ticket(_isolated_db, "XAU/USD", +1.0, 900 + i, jours=i)

    exclure([])
    assert pair_pnl_regulator.evaluate_pair("XAU/USD")["action"] == "pause"

    with sqlite3.connect(_isolated_db) as c:
        c.execute("DELETE FROM auto_paused_pairs")

    exclure([1353960866])
    assert pair_pnl_regulator.evaluate_pair("XAU/USD")["action"] == "keep_active"
