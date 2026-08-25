"""Le moteur de promotion consulte-t-il la liste d'exclusion ?

Troisième juge de la même paire. `pair_admission_controller` la consultait
depuis le 25/08, `pair_pnl_regulator` depuis `762edfa` ; celui-ci décide des
rétrogradations sur une fenêtre de 7 jours et l'ignorait encore.

⚠️ Différence de nature avec les deux autres : la fenêtre est **temporelle**
(`closed_at >= since`), pas un « N derniers trades ». Écarter un ticket réduit
donc l'échantillon de 1 — aucun trade plus ancien ne remonte, et c'est correct :
il n'y a pas de compte à tenir plein.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "trades.db"
    from backend.services import trade_log_service
    monkeypatch.setattr(trade_log_service, "_DB_PATH", db_path)

    from backend.services import (
        ea_closed_trades_service,
        pair_admission_controller,
        pair_pnl_regulator,
    )
    monkeypatch.setattr(pair_admission_controller, "_SCHEMA_ENSURED", False)
    monkeypatch.setattr(pair_pnl_regulator, "_SCHEMA_ENSURED", False)
    monkeypatch.setattr(ea_closed_trades_service, "_SCHEMA_ENSURED", False)

    with sqlite3.connect(db_path) as c:
        c.execute("""
            CREATE TABLE personal_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pair TEXT, direction TEXT, status TEXT, pnl REAL,
                closed_at TEXT, is_auto INTEGER, close_reason TEXT,
                mt5_ticket TEXT
            )
        """)
    yield db_path


def _poser(db_path: Path, pnl: float, ticket, heures: int = 1, direction: str = "sell"):
    """`mt5_ticket` en TEXTE, comme en production."""
    quand = (datetime.now(timezone.utc) - timedelta(hours=heures)).isoformat()
    with sqlite3.connect(db_path) as c:
        c.execute(
            "INSERT INTO personal_trades (pair, direction, status, pnl, closed_at,"
            " is_auto, close_reason, mt5_ticket) VALUES ('XAU/USD', ?, 'CLOSED', ?, ?, 1, ?, ?)",
            (direction, pnl, quand, "MANUAL" if pnl < 0 else "TP1", str(ticket)),
        )


@pytest.fixture
def exclure(monkeypatch):
    def _set(tickets):
        import config.settings as st
        monkeypatch.setattr(st, "PAC_EXCLUDED_TICKETS", frozenset(tickets))
    return _set


def test_sans_reglage_rien_n_est_ecarte(_isolated_db, exclure):
    from backend.services import promotion_engine as pe

    exclure([])
    for i in range(4):
        _poser(_isolated_db, -10.0, 900 + i, heures=i + 1)

    trades = pe._query_trades_pnl("XAU/USD", "sell", pe._iso_since(7))
    assert len(trades) == 4


def test_un_ticket_exclu_sort_de_la_fenetre(_isolated_db, exclure):
    from backend.services import promotion_engine as pe

    _poser(_isolated_db, -265.11, 1353960866, heures=2)
    _poser(_isolated_db, +10.0, 901, heures=1)

    exclure([1353960866])
    trades = pe._query_trades_pnl("XAU/USD", "sell", pe._iso_since(7))

    assert len(trades) == 1
    assert trades[0]["pnl"] == 10.0


def test_les_trades_des_users_premium_sont_filtres_aussi(_isolated_db, exclure):
    """`ea_closed_trades` stocke le ticket en ENTIER, `personal_trades` en TEXTE.
    Sans `CAST`, SQLite ne trouve jamais l'égalité et n'écarte rien, en silence."""
    from backend.services import ea_closed_trades_service, promotion_engine as pe

    ea_closed_trades_service._ensure_schema()
    quand = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(_isolated_db) as c:
        for ticket, pnl in ((555, -300.0), (556, +20.0)):
            c.execute(
                "INSERT INTO ea_closed_trades (user_id, pair, direction, entry_price,"
                " exit_price, pnl, mt5_ticket, closed_at, reported_at)"
                " VALUES (2, 'XAU/USD', 'sell', 1.0, 1.0, ?, ?, ?, ?)",
                (pnl, ticket, quand, quand),
            )

    exclure([555])
    trades = pe._query_trades_pnl("XAU/USD", "sell", pe._iso_since(7))

    assert [t["pnl"] for t in trades] == [20.0]


def test_un_seul_ticket_fait_basculer_la_retrogradation(_isolated_db, exclure, monkeypatch):
    """Bout en bout : c'est ce juge-ci qui rétrograde une paire en AUTO_EXEC
    sur le drawdown 7 jours. Le ticket exclu ne doit pas déclencher le geste."""
    import config.settings as st
    from backend.services import pair_admission_controller as pac
    from backend.services import promotion_engine as pe

    monkeypatch.setattr(st, "TRADING_CAPITAL", 650.0)
    pac.set_state("XAU/USD", pac.STATE_AUTO_EXEC, "test", direction="sell",
                  destination="admin_live")

    _poser(_isolated_db, +5.0, 900, heures=3)
    _poser(_isolated_db, -265.11, 1353960866, heures=2)
    _poser(_isolated_db, +5.0, 901, heures=1)

    exclure([])
    verdict = pe.check_demotion("XAU/USD", "sell", "admin_live")
    assert verdict is not None and verdict["trigger"].startswith("dd_above")

    exclure([1353960866])
    assert pe.check_demotion("XAU/USD", "sell", "admin_live") is None


def test_les_trois_juges_lisent_la_meme_liste(exclure):
    """⛔ La leçon qui a coûté six jours de trading sur l'or : une parade posée
    sur un chemin n'est pas posée sur les autres. Trois modules décident du
    sort d'une paire — ils doivent lire la MÊME liste, par construction."""
    from backend.services import pair_admission_controller as pac
    from backend.services import pair_pnl_regulator as reg
    from backend.services import promotion_engine as pe

    exclure([424242])
    assert pac._tickets_exclus() == frozenset({424242})
    assert reg._tickets_exclus() == frozenset({424242})
    assert pe._tickets_exclus() == frozenset({424242})
