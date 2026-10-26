"""La file ne doit JAMAIS etre bloquee par des setups insolubles.

MESURE EN PRODUCTION le 2026-10-26, apres la soudure. Les 674 setups les plus
anciens de la file sont des paires du PONT (XAU 503, WTI 171) que la soudure
refuse volontairement -- le courtier ne sert pas d'historique et Twelve Data
cote un autre contrat. Or la file est servie `ORDER BY bar_timestamp ASC
LIMIT 50` : ces 674 occupaient donc la tete A CHAQUE PASSAGE, pour toujours.

Consequence mesuree : 120 lignes « SANS BOUGIES » en 10 minutes, toutes XAU ou
WTI, **zero** resolution, et la file qui MONTE (999 -> 1010 en 7 min). La
soudure etait correcte et INERTE : elle ne pouvait jamais etre atteinte.

🔑 C'est exactement le blocage de tete de file que ce module documente deja
avoir corrige pour une autre population (« on sert d'abord les lignes echues --
qui aboutissent toujours, donc vident la file de facon monotone »). Le meme
raisonnement s'applique : **servir ce qui peut avancer**.

⛔ ET CE QU'ON NE FAIT PAS : marquer ces 674 comme perdus. Ce serait refaire le
`NO_DATA` du matin -- transformer « je ne sais pas aller les chercher » en
« perte actee ». On les met en FIN de file, on ne les condamne pas.
"""
from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from backend.models.schemas import Candle
from backend.services import shadow_reconciliation as recon
from backend.services import shadow_v2_core_long as shadow


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    chemin = tmp_path / "tete_de_file.db"
    monkeypatch.setattr(shadow, "DB_PATH", chemin)
    monkeypatch.setattr(recon, "DB_PATH", chemin)
    shadow.ensure_schema()
    return chemin


def _pose(db, bar_ts: datetime, pair: str):
    with sqlite3.connect(db) as c:
        c.execute(
            """INSERT INTO shadow_setups (
                cycle_at, bar_timestamp, system_id, pair, timeframe,
                direction, pattern, entry_price, stop_loss, take_profit_1,
                risk_pct, rr, sizing_capital_eur, sizing_risk_pct,
                sizing_position_eur, sizing_max_loss_eur
            ) VALUES (?, ?, ?, ?, '4h', 'buy', 'momentum_up',
                      100, 95, 110, 0.01, 2.5, 10000, 0.005, 5000, 50)""",
            (bar_ts.isoformat(), bar_ts.isoformat(),
             f"V2_{pair.replace('/', '')}_{bar_ts.isoformat()}", pair),
        )


async def _fetch_selon_paire(pair, start, end):
    """Insoluble pour l'or, resoluble pour le reste."""
    if pair == "XAU/USD":
        return []
    return [Candle(timestamp=start + timedelta(minutes=5 * i),
                   open=100, high=100 + 3 * i, low=99, close=100, volume=0)
            for i in range(8)]


def test_la_colonne_de_derniere_tentative_existe(temp_db):
    with sqlite3.connect(temp_db) as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(shadow_setups)")}
    assert "derniere_tentative_at" in cols, sorted(cols)


def test_un_setup_INSOLUBLE_ne_bloque_pas_ceux_DERRIERE(temp_db):
    """LE TEST CENTRAL.

    Trois setups d'or plus ANCIENS qu'un setup resoluble. Avec un cap d'un seul
    setup par passage, l'ancien comportement servait l'or trois fois et ne
    touchait JAMAIS au quatrieme.
    """
    vieux = datetime.now(timezone.utc) - timedelta(hours=200)
    for i in range(3):
        _pose(temp_db, vieux + timedelta(minutes=i), "XAU/USD")
    _pose(temp_db, vieux + timedelta(hours=1), "EUR/USD")

    # quatre passages d'UN setup : sans la correction, les 3 or passent et
    # repassent, et EUR/USD n'est jamais servi.
    for _ in range(4):
        asyncio.run(recon.reconcile_pending_setups(
            max_per_run=1, fetch_5min_fn=_fetch_selon_paire))

    with sqlite3.connect(temp_db) as c:
        resolu = c.execute(
            "SELECT outcome FROM shadow_setups WHERE pair = 'EUR/USD'"
        ).fetchone()[0]
    assert resolu is not None, (
        "EUR/USD n'a jamais ete servi : la tete de file bloque encore")


def test_une_tentative_INFRUCTUEUSE_est_HORODATEE(temp_db):
    vieux = datetime.now(timezone.utc) - timedelta(hours=200)
    _pose(temp_db, vieux, "XAU/USD")

    asyncio.run(recon.reconcile_pending_setups(
        max_per_run=5, fetch_5min_fn=_fetch_selon_paire))

    with sqlite3.connect(temp_db) as c:
        issue, essai = c.execute(
            "SELECT outcome, derniere_tentative_at FROM shadow_setups").fetchone()
    assert issue is None, "le setup ne doit PAS etre condamne, seulement reporte"
    assert essai is not None, "la tentative n'a pas ete horodatee"


def test_un_setup_deja_TENTE_recemment_n_est_PAS_resservi(temp_db):
    """Sans ca, le report ne sert a rien : il reviendrait au passage suivant."""
    vieux = datetime.now(timezone.utc) - timedelta(hours=200)
    _pose(temp_db, vieux, "XAU/USD")

    a = asyncio.run(recon.reconcile_pending_setups(
        max_per_run=5, fetch_5min_fn=_fetch_selon_paire))
    b = asyncio.run(recon.reconcile_pending_setups(
        max_per_run=5, fetch_5min_fn=_fetch_selon_paire))

    assert a["skipped_no_data"] == 1, a
    assert b["skipped_no_data"] == 0, (
        "le setup insoluble a ete resservi immediatement", b)


def test_apres_le_DELAI_il_est_RETENTE(temp_db, monkeypatch):
    """Ce n'est pas un abandon : la source peut revenir (pont repare, magasin
    rempli). Un report definitif serait une condamnation deguisee.
    """
    vieux = datetime.now(timezone.utc) - timedelta(hours=200)
    _pose(temp_db, vieux, "XAU/USD")

    asyncio.run(recon.reconcile_pending_setups(
        max_per_run=5, fetch_5min_fn=_fetch_selon_paire))
    # on recule l'horodatage de la tentative au-dela du delai
    with sqlite3.connect(temp_db) as c:
        c.execute("UPDATE shadow_setups SET derniere_tentative_at = ?",
                  ((datetime.now(timezone.utc)
                    - timedelta(hours=recon.REESSAI_HEURES + 1)).isoformat(),))

    encore = asyncio.run(recon.reconcile_pending_setups(
        max_per_run=5, fetch_5min_fn=_fetch_selon_paire))

    assert encore["skipped_no_data"] == 1, (
        "le setup n'est jamais retente : c'est un abandon, pas un report",
        encore)


def test_une_resolution_REUSSIE_n_est_pas_affectee(temp_db):
    """Le chemin heureux ne change pas."""
    vieux = datetime.now(timezone.utc) - timedelta(hours=200)
    _pose(temp_db, vieux, "EUR/USD")

    stats = asyncio.run(recon.reconcile_pending_setups(
        max_per_run=5, fetch_5min_fn=_fetch_selon_paire))

    assert stats["resolved"] == 1, stats
    with sqlite3.connect(temp_db) as c:
        issue = c.execute("SELECT outcome FROM shadow_setups").fetchone()[0]
    assert issue not in (None, "NO_DATA"), issue
