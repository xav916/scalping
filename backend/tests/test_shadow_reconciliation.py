"""Tests Phase 4 — module shadow_reconciliation.

Couvre :
- reconcile_pending_setups : pas de pending → 0/0/0
- reconcile avec mock fetch → résolution + UPDATE DB
- _MinimalSetup compatible avec simulate_trade_forward (pas de Pydantic validation)
"""
from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.models.schemas import Candle, TradeDirection
from backend.services import shadow_v2_core_long as shadow
from backend.services import shadow_reconciliation as recon


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "shadow_recon_test.db"
    monkeypatch.setattr(shadow, "DB_PATH", db_path)
    monkeypatch.setattr(recon, "DB_PATH", db_path)
    shadow.ensure_schema()
    return db_path


def _insert_pending_setup(db_path, bar_ts: datetime, pair: str = "XAU/USD",
                          entry: float = 2000.0, sl: float = 1980.0,
                          tp1: float = 2050.0):
    """Insert un setup pending pour test reconcile."""
    with sqlite3.connect(db_path) as c:
        c.execute(
            """INSERT INTO shadow_setups (
                cycle_at, bar_timestamp, system_id, pair, timeframe,
                direction, pattern, entry_price, stop_loss, take_profit_1,
                risk_pct, rr, sizing_capital_eur, sizing_risk_pct,
                sizing_position_eur, sizing_max_loss_eur
            ) VALUES (?, ?, ?, ?, '4h', 'buy', 'momentum_up',
                      ?, ?, ?, 0.01, 2.5, 10000, 0.005, 5000, 50)""",
            (
                bar_ts.isoformat(), bar_ts.isoformat(),
                f"V2_CORE_LONG_{pair.replace('/', '')}_4H", pair,
                entry, sl, tp1,
            ),
        )


def _make_5min_candles(start: datetime, prices: list[float]) -> list[Candle]:
    """Crée des bougies 5min avec prix passés en paramètre."""
    return [
        Candle(
            timestamp=start + timedelta(minutes=5 * i),
            open=p, high=p + 1, low=p - 1, close=p, volume=10,
        )
        for i, p in enumerate(prices)
    ]


# ─── Tests ──────────────────────────────────────────────────────────────────


def test_reconcile_no_pending(temp_db):
    """DB vide → résolution 0/0/0."""
    stats = asyncio.run(recon.reconcile_pending_setups(max_per_run=10))
    assert stats == {
        "resolved": 0, "skipped_no_data": 0, "errors": 0,
        "no_data_final": 0, "still_open": 0, "pending_remaining": 0,
    }


def test_reconcile_still_open_stays_pending(temp_db):
    """Fenêtre encore ouverte + aucun hit → reste pending, pas de faux TIMEOUT.

    Régression 2026-08-04 : ``simulate_trade_forward`` renvoie TIMEOUT dès
    qu'il épuise les bougies. Sur une fenêtre non échue ça veut seulement dire
    « pas encore dénoué » — l'enregistrer figerait un verdict faux.
    """
    bar_ts = datetime.now(timezone.utc) - timedelta(hours=50)  # < timeout 96h
    _insert_pending_setup(temp_db, bar_ts, entry=2000.0, sl=1980.0, tp1=2050.0)

    # Prix qui stagne : ni SL ni TP touchés.
    async def mock_fetch(pair, start, end):
        return _make_5min_candles(start + timedelta(minutes=5), [2000, 2001, 2002])

    stats = asyncio.run(recon.reconcile_pending_setups(
        max_per_run=10, fetch_5min_fn=mock_fetch,
    ))
    assert stats["resolved"] == 0
    assert stats["still_open"] == 1
    assert stats["pending_remaining"] == 1

    with sqlite3.connect(temp_db) as c:
        outcome = c.execute("SELECT outcome FROM shadow_setups").fetchone()[0]
    assert outcome is None


def test_reconcile_early_resolution_before_timeout(temp_db):
    """TP touché à 50h → enregistré tout de suite, sans attendre les 96h.

    C'est le cœur du fix latence : mesure sur 16802 setups H1, p50 = 0.1h.
    Attendre l'échéance complète retardait le feedback de 4 jours sur des
    trades déjà dénoués.
    """
    bar_ts = datetime.now(timezone.utc) - timedelta(hours=50)  # < timeout 96h
    _insert_pending_setup(temp_db, bar_ts, entry=2000.0, sl=1980.0, tp1=2050.0)

    async def mock_fetch(pair, start, end):
        return _make_5min_candles(
            start + timedelta(minutes=5), [2005, 2020, 2055],
        )

    stats = asyncio.run(recon.reconcile_pending_setups(
        max_per_run=10, fetch_5min_fn=mock_fetch,
    ))
    assert stats["resolved"] == 1
    assert stats["still_open"] == 0
    assert stats["pending_remaining"] == 0

    with sqlite3.connect(temp_db) as c:
        row = c.execute("SELECT outcome, exit_price FROM shadow_setups").fetchone()
    assert row[0] == "TP1"
    assert row[1] == pytest.approx(2050.0)


def test_reconcile_matured_rows_have_priority(temp_db):
    """Les lignes échues passent avant les tentatives anticipées.

    Sans cette priorité, un setup destiné au TIMEOUT occuperait un slot à
    chaque run pendant ~94h sans jamais aboutir, et pourrait affamer la file.
    Ici : 1 slot disponible, 1 ligne échue et 1 ligne récente → c'est l'échue
    qui doit être traitée.
    """
    matured_ts = datetime.now(timezone.utc) - timedelta(hours=120)  # > 96h
    early_ts = datetime.now(timezone.utc) - timedelta(hours=10)     # < 96h
    _insert_pending_setup(temp_db, matured_ts, pair="XAU/USD")
    _insert_pending_setup(temp_db, early_ts, pair="XAG/USD")

    fetched: list[str] = []

    async def mock_fetch(pair, start, end):
        fetched.append(pair)
        return _make_5min_candles(start + timedelta(minutes=5), [2000, 2001])

    asyncio.run(recon.reconcile_pending_setups(
        max_per_run=1, fetch_5min_fn=mock_fetch,
    ))
    # Le seul slot doit être allé à la ligne échue, malgré son bar_timestamp
    # plus ancien ET plus récent selon l'ordre global.
    assert fetched == ["XAU/USD"]


def test_reconcile_never_fetches_beyond_now(temp_db):
    """La fenêtre demandée est bornée à maintenant, pas à bar_ts + timeout."""
    bar_ts = datetime.now(timezone.utc) - timedelta(hours=10)
    _insert_pending_setup(temp_db, bar_ts)
    seen: list[tuple] = []

    async def mock_fetch(pair, start, end):
        seen.append((start, end))
        return _make_5min_candles(start + timedelta(minutes=5), [2000, 2001])

    asyncio.run(recon.reconcile_pending_setups(
        max_per_run=10, fetch_5min_fn=mock_fetch,
    ))
    assert len(seen) == 1
    _, end = seen[0]
    # bar_ts + 96h serait ~86h dans le futur : on doit s'arrêter à maintenant.
    assert end <= datetime.now(timezone.utc) + timedelta(seconds=5)


def test_reconcile_with_mock_fetch_tp1(temp_db):
    """Setup pending résolu via fetch mocké : prix qui touche TP1."""
    bar_ts = datetime.now(timezone.utc) - timedelta(hours=120)  # > 96h, résolvable
    _insert_pending_setup(temp_db, bar_ts, entry=2000.0, sl=1980.0, tp1=2050.0)

    # Mock fetch_5min : prix monte de 2000 à 2060 sur 4h (touche TP 2050)
    async def mock_fetch(pair, start, end):
        return _make_5min_candles(
            start + timedelta(minutes=5),
            [2005, 2015, 2030, 2045, 2055, 2060],
        )

    stats = asyncio.run(recon.reconcile_pending_setups(
        max_per_run=10, fetch_5min_fn=mock_fetch,
    ))
    assert stats["resolved"] == 1
    assert stats["errors"] == 0
    assert stats["pending_remaining"] == 0

    # Vérifier l'outcome en DB
    with sqlite3.connect(temp_db) as c:
        row = c.execute(
            "SELECT outcome, exit_price, pnl_eur FROM shadow_setups"
        ).fetchone()
    assert row[0] == "TP1"
    assert row[1] == pytest.approx(2050.0)
    # pnl_eur > 0 (TP1 hit, profit)
    assert row[2] > 0


def test_reconcile_with_mock_fetch_sl(temp_db):
    """Setup pending résolu via fetch mocké : prix qui touche SL."""
    bar_ts = datetime.now(timezone.utc) - timedelta(hours=120)
    _insert_pending_setup(temp_db, bar_ts, entry=2000.0, sl=1980.0, tp1=2050.0)

    async def mock_fetch(pair, start, end):
        # Prix descend, touche SL à 1980
        return _make_5min_candles(
            start + timedelta(minutes=5),
            [1995, 1985, 1978, 1975],
        )

    stats = asyncio.run(recon.reconcile_pending_setups(
        max_per_run=10, fetch_5min_fn=mock_fetch,
    ))
    assert stats["resolved"] == 1

    with sqlite3.connect(temp_db) as c:
        row = c.execute("SELECT outcome, pnl_eur FROM shadow_setups").fetchone()
    assert row[0] == "SL"
    assert row[1] < 0  # pertes


async def _fetch_vide(pair, start, end):
    return []


def test_reconcile_NON_mature_sans_bougies_reste_pending(temp_db):
    """Fenetre encore OUVERTE et pas de bougies : on reessaiera. C'est juste.

    La donnee 5 min peut arriver en retard ; un setup recent merite une
    seconde chance.

    50 h : au-dela du seuil de SELECTION (2 h) donc candidat, mais en deca du
    TIMEOUT (96 h) donc pas mur. Mon premier jet utilisait 1 h -- le setup
    n'etait alors meme pas selectionne, et le test ne mesurait rien.
    """
    bar_ts = datetime.now(timezone.utc) - timedelta(hours=50)
    _insert_pending_setup(temp_db, bar_ts)

    stats = asyncio.run(recon.reconcile_pending_setups(
        max_per_run=10, fetch_5min_fn=_fetch_vide,
    ))
    assert stats["skipped_no_data"] == 1
    assert stats["pending_remaining"] == 1


def test_reconcile_mature_sans_bougies_est_marque_NO_DATA(temp_db):
    """Fenetre entierement PASSEE et pas de bougies : irrecuperable, on l'inscrit.

    CE TEST REMPLACE `test_reconcile_skipped_no_data`, QUI AFFIRMAIT
    L'INVERSE -- « le setup reste pending » -- sur un setup de 120 h, donc MUR.
    Ce comportement, specifie et vert pendant des mois, a coute 20 513 setups
    perdus : mesure du 2026-10-26.

    La source de bougies 5 min a une retention d'environ deux semaines. Un
    setup mur dont la fenetre est hors retention ne sera JAMAIS resolvable --
    la donnee n'existe plus nulle part. Le laisser `outcome IS NULL` le fait
    reservir indefiniment par la requete `ORDER BY bar_timestamp ASC`, ce qui
    BLOQUE LA FILE par sa propre tete.
    """
    bar_ts = datetime.now(timezone.utc) - timedelta(hours=120)
    _insert_pending_setup(temp_db, bar_ts)

    stats = asyncio.run(recon.reconcile_pending_setups(
        max_per_run=10, fetch_5min_fn=_fetch_vide,
    ))
    assert stats["skipped_no_data"] == 1
    assert stats["no_data_final"] == 1, stats
    assert stats["pending_remaining"] == 0, "le setup doit QUITTER la file"

    with sqlite3.connect(temp_db) as c:
        issue = c.execute("SELECT outcome FROM shadow_setups").fetchone()[0]
    assert issue == "NO_DATA", issue


def test_une_tete_de_file_irrecuperable_ne_bloque_plus_la_file(temp_db):
    """LE test de la panne du 21/08 : un setup irrecuperable en tete de file.

    La requete sert les plus ANCIENS d'abord. Avec `max_per_run=1`, un seul
    setup est servi par passage. Si la tete n'est jamais marquee, elle est
    reservie a chaque fois et le setup recuperable derriere elle n'obtient
    JAMAIS de creneau -- exactement ce qui s'est produit pendant 65 jours.

    Ce test echoue sur l'ancien comportement : le second passage reservirait
    la meme tete et `resolved` resterait a 0.
    """
    vieux = datetime.now(timezone.utc) - timedelta(hours=200)
    recent = datetime.now(timezone.utc) - timedelta(hours=100)
    _insert_pending_setup(temp_db, vieux, pair="XAU/USD")
    _insert_pending_setup(temp_db, recent, pair="XAG/USD")

    async def fetch_selectif(pair, start, end):
        if pair == "XAU/USD":
            return []
        return _make_5min_candles(start, [2000.0, 2010.0, 2060.0])

    p1 = asyncio.run(recon.reconcile_pending_setups(
        max_per_run=1, fetch_5min_fn=fetch_selectif,
    ))
    assert p1["no_data_final"] == 1, p1

    p2 = asyncio.run(recon.reconcile_pending_setups(
        max_per_run=1, fetch_5min_fn=fetch_selectif,
    ))
    assert p2["resolved"] == 1, p2
    assert p2["pending_remaining"] == 0, p2


def test_minimal_setup_dataclass():
    """_MinimalSetup expose les bons attributs pour simulate_trade_forward."""
    setup = recon._MinimalSetup(
        pair="XAU/USD",
        direction=TradeDirection.BUY,
        entry_price=2000.0,
        stop_loss=1980.0,
        take_profit_1=2050.0,
    )
    assert setup.pair == "XAU/USD"
    assert setup.direction == TradeDirection.BUY
    assert setup.entry_price == 2000.0
    # Pas d'erreur Pydantic — c'est un dataclass simple
