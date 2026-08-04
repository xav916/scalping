"""`signal_rejections.destination_id` — observabilité par destination (2026-08-04).

La table n'enregistrait que `user_id`, qui vaut `None` pour **toutes** les
destinations admin. Un rejet `admin_kraken` était donc indiscernable d'un rejet
`admin_legacy`, et deux destinations ont passé des semaines à ne rien exécuter
sans que rien ne l'indique :

- les Voies A/B, bloquées sur `_not_a_star` (reason code privé, non loggé)
- Kraken, dont **34 des 40 derniers signaux crypto** tombaient en
  `_not_admitted` — diagnostiquer a exigé de reconstruire le `BridgeConfig` à
  la main et de rejouer `_check_rejection` hors ligne.
"""
from __future__ import annotations

import sqlite3
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest

from backend.services import rejection_service as rs


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    from backend.services import trade_log_service
    monkeypatch.setattr(trade_log_service, "_DB_PATH", tmp_path / "trades.db")
    return tmp_path / "trades.db"


def _cols(db):
    with sqlite3.connect(db) as c:
        return [r[1] for r in c.execute("PRAGMA table_info(signal_rejections)")]


def _rows(db):
    with sqlite3.connect(db) as c:
        return c.execute(
            "SELECT reason_code, destination_id FROM signal_rejections"
        ).fetchall()


# --- le schéma -------------------------------------------------------------

def test_la_colonne_existe(_db):
    rs._ensure_schema()
    assert "destination_id" in _cols(_db)


def test_migration_sur_une_table_ancienne(_db):
    """Une base créée avant le 2026-08-04 doit se migrer sans perdre ses lignes."""
    with sqlite3.connect(_db) as c:
        c.execute("""
            CREATE TABLE signal_rejections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL, pair TEXT, direction TEXT,
                confidence REAL, reason_code TEXT NOT NULL, details TEXT
            )""")
        c.execute(
            "INSERT INTO signal_rejections (created_at, pair, reason_code) "
            "VALUES ('2026-07-01T10:00:00+00:00', 'EUR/USD', 'below_confidence')")

    rs._ensure_schema()
    assert "destination_id" in _cols(_db)
    assert _rows(_db) == [("below_confidence", None)]


# --- l'écriture ------------------------------------------------------------

def test_la_destination_est_persistee(_db):
    rs.record_rejection("BTC/USD", "buy", 70.0, "_not_admitted",
                        destination_id="admin_kraken")
    assert _rows(_db) == [("_not_admitted", "admin_kraken")]


def test_appel_legacy_sans_destination(_db):
    """`_should_push` mono-tenant n'a pas de destination : None accepté."""
    rs.record_rejection("EUR/USD", "sell", 50.0, "below_confidence")
    assert _rows(_db) == [("below_confidence", None)]


# --- l'agrégation, c'est elle qui rend le champ utile ----------------------

def _seed(db):
    for dest, reason, n in (
        ("admin_kraken", "_not_admitted", 34),
        ("admin_kraken", "below_confidence", 2),
        ("admin_live", "market_closed", 5),
        (None, "sl_too_close", 3),
    ):
        for _ in range(n):
            rs.record_rejection("BTC/USD", "buy", 70.0, reason, destination_id=dest)


def test_ventilation_par_destination(_db):
    _seed(_db)
    agg = rs.get_rejections("2000-01-01", "2999-01-01")
    by = {d["destination_id"]: d for d in agg["by_destination"]}

    assert by["admin_kraken"]["count"] == 36
    assert by["admin_kraken"]["top_reason"] == "_not_admitted"
    assert by["admin_live"]["count"] == 5
    assert agg["total"] == 44


def test_les_lignes_anciennes_sont_visibles_pas_perdues(_db):
    """NULL doit apparaître sous « (inconnu) », pas disparaître du total."""
    _seed(_db)
    agg = rs.get_rejections("2000-01-01", "2999-01-01")
    by = {d["destination_id"]: d for d in agg["by_destination"]}
    assert by["(inconnu)"]["count"] == 3
    assert sum(d["count"] for d in agg["by_destination"]) == agg["total"]


def test_tri_par_volume_decroissant(_db):
    _seed(_db)
    counts = [d["count"] for d in rs.get_rejections("2000-01-01", "2999-01-01")["by_destination"]]
    assert counts == sorted(counts, reverse=True)


def test_le_libelle_fr_accompagne_le_motif_dominant(_db):
    _seed(_db)
    agg = rs.get_rejections("2000-01-01", "2999-01-01")
    live = next(d for d in agg["by_destination"] if d["destination_id"] == "admin_live")
    assert live["top_reason_label_fr"] == "Marché fermé"


# --- le câblage depuis le dispatch ----------------------------------------

def test_le_dispatch_propage_bien_la_destination(_db):
    """Le scénario Kraken : sans ce câblage, le rejet reste anonyme.

    ⚠️ Vérifie la chaîne réelle `_push_to_destination` -> `record_rejection`,
    pas seulement la signature — c'est le câblage qui manquait.
    """
    import asyncio
    from backend.services import mt5_bridge

    dest = NS(destination_id="admin_kraken", user_id=None,
              min_confidence=60.0, allowed_asset_classes=frozenset({"crypto"}),
              excluded_pairs=frozenset(), bridge_url="", auto_exec_enabled=True,
              extra_pairs_allowed=frozenset())
    setup = NS(pair="BTC/USD", direction=NS(value="buy"), confidence_score=90,
               entry_price=50000.0, stop_loss=49000.0, take_profit_1=51800.0,
               take_profit_2=None, verdict_action="TAKE", verdict_blockers=[],
               is_simulated=False, pattern=None)

    with patch.object(mt5_bridge, "_check_rejection", return_value="market_closed"):
        asyncio.run(mt5_bridge._push_to_destination(setup, dest))

    assert _rows(_db) == [("market_closed", "admin_kraken")]
