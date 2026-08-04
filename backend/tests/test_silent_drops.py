"""Drops silencieux — journalisation des reason codes privés (2026-08-04).

Les codes préfixés `_` ne produisaient **aucune trace** : pas de push, pas de
rejet, rien dans les logs. Deux conséquences constatées, à des semaines
d'intervalle :

- `_not_a_star` a empêché les Voies A/B de trader une seule action
- `_not_admitted` bloquait **34 des 40 derniers signaux crypto** de Kraken

Dans les deux cas la destination était silencieusement morte, et il a fallu
rejouer le filtre hors ligne pour s'en apercevoir.

⚠️ Agrégation par jour et non ligne par ligne : ces codes se déclenchent sur
la majorité des ~30 000 tentatives de dispatch quotidiennes. Le compteur
mesure donc des **tentatives**, pas des idées de trade distinctes — le radar
réémet le même setup à chaque cycle.
"""
from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest

from backend.services import rejection_service as rs


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    from backend.services import trade_log_service
    monkeypatch.setattr(trade_log_service, "_DB_PATH", tmp_path / "trades.db")
    return tmp_path / "trades.db"


def _counters(db):
    # La table est créée paresseusement, au premier drop. Sans ce garde, un
    # test qui vérifie l'ABSENCE de compteur planterait au lieu de constater
    # une liste vide.
    rs._ensure_silent_schema()
    with sqlite3.connect(db) as c:
        return c.execute(
            "SELECT destination_id, pair, direction, reason_code, count "
            "  FROM silent_drop_counters ORDER BY reason_code, destination_id"
        ).fetchall()


TODAY = datetime.now(timezone.utc).date().isoformat()


# --- le compteur -----------------------------------------------------------

def test_un_drop_cree_une_ligne(_db):
    rs.record_silent_drop("BTC/USD", "buy", "_not_admitted", "admin_kraken")
    assert _counters(_db) == [("admin_kraken", "BTC/USD", "buy", "_not_admitted", 1)]


def test_les_repetitions_sagregent(_db):
    """Le radar réémet le même setup à chaque cycle : on compte, on n'empile pas."""
    for _ in range(250):
        rs.record_silent_drop("BTC/USD", "buy", "_not_admitted", "admin_kraken")
    rows = _counters(_db)
    assert len(rows) == 1, "250 tentatives doivent tenir sur UNE ligne"
    assert rows[0][4] == 250


def test_les_dimensions_restent_separees(_db):
    rs.record_silent_drop("BTC/USD", "buy", "_not_admitted", "admin_kraken")
    rs.record_silent_drop("BTC/USD", "sell", "_not_admitted", "admin_kraken")
    rs.record_silent_drop("ETH/USD", "buy", "_not_admitted", "admin_kraken")
    rs.record_silent_drop("BTC/USD", "buy", "_not_a_star", "admin_kraken")
    rs.record_silent_drop("BTC/USD", "buy", "_not_admitted", "admin_live")
    assert len(_counters(_db)) == 5


def test_les_horodatages_encadrent(_db):
    rs.record_silent_drop("BTC/USD", "buy", "_not_admitted", "admin_kraken")
    rs.record_silent_drop("BTC/USD", "buy", "_not_admitted", "admin_kraken")
    with sqlite3.connect(_db) as c:
        first, last, n = c.execute(
            "SELECT first_at, last_at, count FROM silent_drop_counters").fetchone()
    assert n == 2 and first <= last


# --- l'agrégation ----------------------------------------------------------

def _seed():
    for _ in range(34):
        rs.record_silent_drop("BTC/USD", "buy", "_not_admitted", "admin_kraken")
    for _ in range(6):
        rs.record_silent_drop("ETH/USD", "sell", "_not_admitted", "admin_kraken")
    for _ in range(5):
        rs.record_silent_drop("AAPL", "buy", "_not_a_star", "admin_live")


def test_ventilation_par_destination(_db):
    _seed()
    agg = rs.get_silent_drops(TODAY, TODAY)
    by = {d["destination_id"]: d for d in agg["by_destination"]}
    assert agg["total"] == 45
    assert by["admin_kraken"]["count"] == 40
    assert by["admin_kraken"]["top_reason"] == "_not_admitted"
    assert by["admin_kraken"]["top_reason_label_fr"] == "Paire non admise à l'auto-exec"
    assert by["admin_live"]["count"] == 5


def test_ventilation_par_motif(_db):
    _seed()
    by = {r["reason_code"]: r for r in rs.get_silent_drops(TODAY, TODAY)["by_reason"]}
    assert by["_not_admitted"]["count"] == 40
    assert by["_not_a_star"]["label_fr"] == "Hors portefeuille stars (fallback legacy)"


def test_les_paires_sont_conservees(_db):
    """Sans le détail par paire, on sait qu'une destination est morte
    mais pas laquelle de ses paires est en cause."""
    _seed()
    kraken = next(d for d in rs.get_silent_drops(TODAY, TODAY)["by_destination"]
                  if d["destination_id"] == "admin_kraken")
    assert kraken["pairs"] == {"BTC/USD": 34, "ETH/USD": 6}


def test_hors_plage_de_dates(_db):
    _seed()
    assert rs.get_silent_drops("2020-01-01", "2020-01-02")["total"] == 0


def test_plage_vide_ne_casse_pas(_db):
    agg = rs.get_silent_drops(TODAY, TODAY)
    assert agg["total"] == 0 and agg["by_destination"] == []


# --- le câblage depuis le dispatch ----------------------------------------

def _dest():
    return NS(destination_id="admin_kraken", user_id=None, min_confidence=60.0,
              allowed_asset_classes=frozenset({"crypto"}), excluded_pairs=frozenset(),
              bridge_url="", auto_exec_enabled=True, extra_pairs_allowed=frozenset())


def _setup():
    return NS(pair="BTC/USD", direction=NS(value="buy"), confidence_score=90,
              entry_price=50000.0, stop_loss=49000.0, take_profit_1=51800.0,
              take_profit_2=None, verdict_action="TAKE", verdict_blockers=[],
              is_simulated=False, pattern=None)


def test_le_dispatch_compte_le_drop_silencieux(_db):
    """Le scénario Kraken exact : `_not_admitted` doit laisser une trace."""
    from backend.services import mt5_bridge
    with patch.object(mt5_bridge, "_check_rejection", return_value="_not_admitted"):
        asyncio.run(mt5_bridge._push_to_destination(_setup(), _dest()))
    assert _counters(_db) == [("admin_kraken", "BTC/USD", "buy", "_not_admitted", 1)]


def test_le_code_public_ne_va_pas_dans_le_compteur(_db):
    """Les deux journaux restent disjoints : pas de double comptage."""
    from backend.services import mt5_bridge
    with patch.object(mt5_bridge, "_check_rejection", return_value="market_closed"):
        asyncio.run(mt5_bridge._push_to_destination(_setup(), _dest()))
    assert _counters(_db) == []
    with sqlite3.connect(_db) as c:
        assert c.execute("SELECT COUNT(*) FROM signal_rejections").fetchone()[0] == 1


def test_le_drapeau_coupe_lecriture(_db):
    """Kill-switch sans redéploiement, l'écriture a lieu sur chaque tentative."""
    from backend.services import mt5_bridge
    with patch.object(mt5_bridge, "SILENT_DROPS_LOG_ENABLED", False), \
         patch.object(mt5_bridge, "_check_rejection", return_value="_not_admitted"):
        asyncio.run(mt5_bridge._push_to_destination(_setup(), _dest()))
    assert _counters(_db) == []


def test_le_defaut_du_drapeau_est_actif():
    import config.settings as st
    assert st.SILENT_DROPS_LOG_ENABLED is True
