"""Palier 2 : le filtre forex, et ce qu'il doit REFUSER de toucher."""
from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from backend.services import shadow_v2_core_long as shadow
from scripts import rattrapage_commun as commun
from scripts import rattrapage_forex as rf


@pytest.fixture
def db(tmp_path, monkeypatch):
    chemin = tmp_path / "rattrapage_forex_test.db"
    monkeypatch.setattr(shadow, "DB_PATH", chemin)
    monkeypatch.setattr(commun, "DB_PATH", chemin)
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
                      1.1, 1.0, 1.3, 0.01, 2.5, 10000, 0.005, 5000, 50)""",
            (bar_ts.isoformat(), bar_ts.isoformat(),
             f"V2_{pair.replace('/', '')}_{bar_ts.isoformat()}", pair),
        )


def test_la_CRYPTO_est_exclue_du_palier_2(monkeypatch):
    """Elle releve du palier 1 : la rattraper ici la resoudrait DEUX FOIS,
    avec une AUTRE source -- donc en ecrasant une issue deja etablie."""
    monkeypatch.setattr(rf.bougies_du_pont, "paire_du_pont", lambda p: False)

    for p in ("BTC/USD", "ETH/USD", "DOGE/USD"):
        assert rf.est_forex_rattrapable(p) is False, p


def test_les_paires_du_PONT_sont_exclues(monkeypatch):
    """XAU et WTI sont cotes par le COURTIER, pas par Twelve Data.

    ⛔ Le defaut que ca evite est mesure et deja inscrit dans la cascade de
    `price_service` : sur le WTI, Twelve Data divergeait de 3,394 % du contrat
    reellement trade. Juger un setup XAU avec ces prix declarerait des stops
    touches a tort.
    """
    monkeypatch.setattr(rf.bougies_du_pont, "paire_du_pont",
                        lambda p: p in ("XAU/USD", "WTI/USD"))

    assert rf.est_forex_rattrapable("XAU/USD") is False
    assert rf.est_forex_rattrapable("WTI/USD") is False
    assert rf.est_forex_rattrapable("EUR/USD") is True


def test_le_filtre_du_pont_suit_la_PRODUCTION_et_non_une_copie(monkeypatch):
    """Si une paire est ajoutee au pont demain, le rattrapage doit l'exclure.

    🔑 On interroge `bougies_du_pont.paire_du_pont`, la MEME fonction que la
    cascade de production. Recopier la liste ici aurait garanti qu'elle derive.
    """
    monkeypatch.setattr(rf.bougies_du_pont, "paire_du_pont",
                        lambda p: p == "GBP/USD")

    assert rf.est_forex_rattrapable("GBP/USD") is False, (
        "une paire nouvellement cablee sur le pont doit etre exclue"
        " SANS modifier ce script")


def test_la_file_ne_retient_que_le_forex(db, monkeypatch):
    monkeypatch.setattr(rf.bougies_du_pont, "paire_du_pont",
                        lambda p: p in ("XAU/USD", "WTI/USD"))
    t = datetime(2026, 8, 20, 4, tzinfo=timezone.utc)
    for p in ("EUR/USD", "GBP/USD", "BTC/USD", "XAU/USD", "WTI/USD"):
        _pose(db, t, p)

    retenues = commun.paires_en_file(rf.est_forex_rattrapable, db)

    assert set(retenues) == {"EUR/USD", "GBP/USD"}, set(retenues)


def test_une_paire_muette_reste_en_file_sans_etre_marquee(db, monkeypatch):
    """Twelve Data ne rend rien pour une paire : ne RIEN ecrire.

    ⛔ Lecon du `NO_DATA` du 2026-10-26 : une source muette ne prouve pas
    qu'une donnee est irrecuperable.
    """
    async def _rien(paire, interval, debut, fin, **kw):
        return []

    monkeypatch.setattr(rf.price_service, "fetch_candles_fenetre", _rien)
    t = datetime(2026, 8, 20, 4, tzinfo=timezone.utc)
    _pose(db, t, "EUR/USD")

    blocs = asyncio.run(commun.charge_les_blocs({"EUR/USD": (t, t)}, rf.chargeur))
    faits = asyncio.run(commun.resout(blocs))

    assert blocs == {"EUR/USD": []}
    assert faits == 0
    with sqlite3.connect(db) as c:
        issue, marque = c.execute(
            "SELECT outcome, resolved_backfill FROM shadow_setups").fetchone()
    assert issue is None, "le setup doit RESTER en file"
    assert marque == 0, "rien ne doit etre marque"


def test_le_rattrapage_forex_passe_par_le_chemin_de_PRODUCTION(db, monkeypatch):
    """L'issue doit etre calculee par `reconcile_pending_setups`, pas ici."""
    appels = []
    vrai = commun.recon.reconcile_pending_setups

    async def _espion(**kw):
        appels.append(kw)
        return await vrai(**kw)

    monkeypatch.setattr(commun.recon, "reconcile_pending_setups", _espion)
    monkeypatch.setattr(commun.recon, "DB_PATH", db)

    t = datetime.now(timezone.utc) - timedelta(hours=120)
    _pose(db, t, "EUR/USD")
    from backend.models.schemas import Candle
    blocs = {"EUR/USD": [
        Candle(timestamp=t + timedelta(minutes=5 * i),
               open=1.1, high=1.1 + 0.05 * i, low=1.09, close=1.1, volume=0)
        for i in range(10)]}

    asyncio.run(commun.resout(blocs, limite=5))

    assert appels, "la resolution n'est pas passee par la production"
    assert appels[0]["marque_rattrapage"] is True, "etiquette absente"
    assert appels[0]["paires"] == ["EUR/USD"], appels[0]["paires"]
