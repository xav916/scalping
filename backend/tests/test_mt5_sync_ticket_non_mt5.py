"""Un identifiant Kraken n'est pas un ticket MT5 — et le faisait tomber.

⛔ Incident constaté en prod le 2026-08-09, en cours depuis **10 heures**.
``sync_from_bridge`` levait une exception à **chaque** passage — mesuré à
59 échecs par heure de 00:00 à 10:20, soit ~600 au total, et **0 succès**.

Origine exacte : le premier trade Kraken de l'univers élargi (ETHFI, 08-08 à
23:58) a été matérialisé dans ``personal_trades`` par ``kraken_sync`` à
23:59:25, avec pour ``mt5_ticket`` un **UUID** — ``a274fd62-bd1b-…``. Le
premier échec suit à 00:00:25. ``_select_open_auto_tickets`` faisait
``int(r[0])`` sur toutes les lignes auto ouvertes.

Conséquence : ``_reconcile_open_trades`` est le **dernier** appel de
``sync_from_bridge``, donc la réconciliation des clôtures naturelles MT5
(SL/TP touchés par le marché) ne tournait plus du tout — alors qu'une position
or auto était ouverte.

> **L'élargissement d'une route a cassé une hypothèse de forme d'une autre
> route.** ``mt5_ticket`` est déclaré ``INTEGER``, mais SQLite est typé
> dynamiquement : la colonne a accepté le texte sans broncher.

Le correctif n'est pas défensif, il est sémantique : ``_reconcile_open_trades``
compare ces tickets au ``/positions`` du **bridge MT5**. Un identifiant Kraken
n'a rien à y faire — Kraken a sa propre réconciliation (« Réconciliation
clôtures Kraken », toutes les 2 min).
"""
import logging
import sqlite3

import pytest

from backend.services import mt5_sync

UUID_KRAKEN = "a274fd62-bd1b-4163-8ebe-5df6d1c539a6"


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "trades.db"
    conn = sqlite3.connect(db_file)
    conn.execute("""
        CREATE TABLE personal_trades (
            id INTEGER PRIMARY KEY,
            user TEXT, pair TEXT, direction TEXT,
            entry_price REAL, stop_loss REAL, take_profit REAL,
            size_lot REAL, status TEXT, created_at TEXT,
            mt5_ticket INTEGER, is_auto INTEGER
        )
    """)
    conn.commit()
    conn.close()
    monkeypatch.setattr(mt5_sync, "_db_path", lambda: str(db_file))
    return str(db_file)


def _insert(db_path, ticket, pair="EUR/USD", status="OPEN", is_auto=1):
    with sqlite3.connect(db_path) as c:
        c.execute(
            "INSERT INTO personal_trades (user, pair, direction, entry_price,"
            " stop_loss, take_profit, size_lot, status, created_at, mt5_ticket,"
            " is_auto) VALUES ('auto', ?, 'buy', 1.1, 1.09, 1.12, 0.1, ?,"
            " '2026-08-09T00:00:00+00:00', ?, ?)",
            (pair, status, ticket, is_auto),
        )


def test_un_ticket_kraken_ne_fait_plus_tomber_la_reconciliation(temp_db):
    """LE test de l'incident : la position or doit rester réconciliable."""
    _insert(temp_db, UUID_KRAKEN, pair="ETHFI/USD")
    _insert(temp_db, 82840896, pair="XAU/USD")

    tickets = mt5_sync._select_open_auto_tickets()

    assert tickets == {82840896}


def test_les_trois_positions_kraken_reelles_sont_toutes_ecartees(temp_db):
    """Reproduit l'état exact de la base au moment de l'incident."""
    for uuid, pair in (
        ("a274fd62-bd1b-4163-8ebe-5df6d1c539a6", "ETHFI/USD"),
        ("a2752852-a0c5-4412-ada5-9b7dfe4eb78c", "SEI/USD"),
        ("a275544f-25d4-4a3a-be90-95437e7652d4", "CRV/USD"),
    ):
        _insert(temp_db, uuid, pair=pair)
    _insert(temp_db, 82840896, pair="XAU/USD")

    assert mt5_sync._select_open_auto_tickets() == {82840896}


def test_aucun_ticket_mt5_rend_un_ensemble_vide_sans_lever(temp_db):
    """Et non une exception : c'est un état normal, pas une panne."""
    _insert(temp_db, UUID_KRAKEN, pair="ETHFI/USD")

    assert mt5_sync._select_open_auto_tickets() == set()


def test_les_tickets_mt5_valides_sont_tous_conserves(temp_db):
    _insert(temp_db, 100)
    _insert(temp_db, 101, status="OPEN", is_auto=0)     # pas auto
    _insert(temp_db, 102, status="CLOSED", is_auto=1)   # deja ferme
    _insert(temp_db, 103)

    assert mt5_sync._select_open_auto_tickets() == {100, 103}


def test_un_ticket_stocke_en_texte_numerique_reste_lu(temp_db):
    """SQLite est typé dynamiquement : un ticket MT5 peut arriver en TEXT.

    L'écarter perdrait une vraie position — le filtre porte sur la FORME,
    pas sur le type de stockage.
    """
    _insert(temp_db, "82840896")

    assert mt5_sync._select_open_auto_tickets() == {82840896}


def test_les_tickets_ecartes_sont_journalises(temp_db, caplog):
    """Écarter en silence rejouerait le défaut : on saurait seulement que la
    réconciliation ne trouve rien, jamais pourquoi."""
    _insert(temp_db, UUID_KRAKEN, pair="ETHFI/USD")
    _insert(temp_db, 82840896, pair="XAU/USD")

    with caplog.at_level(logging.DEBUG, logger="backend.services.mt5_sync"):
        mt5_sync._select_open_auto_tickets()

    assert any("1" in r.message and "MT5" in r.message for r in caplog.records)
