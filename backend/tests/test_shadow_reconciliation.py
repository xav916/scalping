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
        "still_open": 0, "pending_remaining": 0,
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


def test_reconcile_skipped_no_data(temp_db):
    """Si fetch retourne vide, le setup reste pending (skipped_no_data++)."""
    bar_ts = datetime.now(timezone.utc) - timedelta(hours=120)
    _insert_pending_setup(temp_db, bar_ts)

    async def mock_empty_fetch(pair, start, end):
        return []

    stats = asyncio.run(recon.reconcile_pending_setups(
        max_per_run=10, fetch_5min_fn=mock_empty_fetch,
    ))
    assert stats["resolved"] == 0
    assert stats["skipped_no_data"] == 1
    assert stats["pending_remaining"] == 1


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
