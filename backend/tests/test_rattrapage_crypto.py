"""Le coeur testable du rattrapage crypto : selection et service des fenetres."""
from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from backend.models.schemas import Candle
from backend.services import shadow_v2_core_long as shadow
from scripts import rattrapage_crypto as rc


@pytest.fixture
def db(tmp_path, monkeypatch):
    chemin = tmp_path / "rattrapage_test.db"
    monkeypatch.setattr(shadow, "DB_PATH", chemin)
    monkeypatch.setattr(rc, "DB_PATH", chemin)
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


def _bougies(debut: datetime, n: int) -> list[Candle]:
    return [Candle(timestamp=debut + timedelta(minutes=5 * i),
                   open=100, high=101, low=99, close=100, volume=1)
            for i in range(n)]


def test_seules_les_paires_que_BINANCE_cote_sont_retenues(db):
    """XAU/USD en file ne doit pas entrer dans un rattrapage Binance.

    ⛔ Le defaut que ca evite : resoudre un setup sur l'or avec des bougies de
    BTCUSDT, c'est-a-dire fabriquer une issue a partir du mauvais instrument.
    """
    t = datetime(2026, 8, 20, 4, tzinfo=timezone.utc)
    _pose(db, t, "BTC/USD")
    _pose(db, t, "XAU/USD")
    _pose(db, t, "EUR/USD")

    retenues = rc.paires_crypto_en_file(db)

    assert set(retenues) == {"BTC/USD"}, set(retenues)


def test_l_intervalle_rendu_encadre_les_barres_en_file(db):
    t0 = datetime(2026, 8, 20, 4, tzinfo=timezone.utc)
    t1 = datetime(2026, 10, 1, 9, tzinfo=timezone.utc)
    _pose(db, t0, "ETH/USD")
    _pose(db, t1, "ETH/USD")

    mn, mx = rc.paires_crypto_en_file(db)["ETH/USD"]

    assert mn == t0 and mx == t1


def test_une_paire_RESOLUE_ne_revient_pas_en_file(db):
    """Seuls les `outcome IS NULL` comptent."""
    t = datetime(2026, 8, 20, 4, tzinfo=timezone.utc)
    _pose(db, t, "SOL/USD")
    with sqlite3.connect(db) as c:
        c.execute("UPDATE shadow_setups SET outcome = 'TP1'")

    assert rc.paires_crypto_en_file(db) == {}


def test_la_source_sert_la_TRANCHE_demandee_sans_requete():
    debut = datetime(2026, 8, 20, tzinfo=timezone.utc)
    blocs = {"BTC/USD": _bougies(debut, 100)}
    source = rc.fabrique_source(blocs)

    a = debut + timedelta(minutes=25)
    b = debut + timedelta(minutes=50)
    tranche = asyncio.run(source("BTC/USD", a, b))

    assert [c.timestamp for c in tranche] == [
        debut + timedelta(minutes=5 * i) for i in range(5, 11)]
    assert all(a <= c.timestamp <= b for c in tranche)


def test_la_source_rend_vide_pour_une_paire_NON_chargee():
    """Et surtout : ne leve pas, et ne sert pas les bougies d'une AUTRE paire.

    🔑 Un `dict.get` qui retomberait sur une valeur par defaut partagee
    melangerait les instruments en silence.
    """
    debut = datetime(2026, 8, 20, tzinfo=timezone.utc)
    source = rc.fabrique_source({"BTC/USD": _bougies(debut, 10)})

    assert asyncio.run(source("XAU/USD", debut, debut + timedelta(hours=1))) == []


def test_la_source_rend_vide_hors_de_toute_couverture():
    debut = datetime(2026, 8, 20, tzinfo=timezone.utc)
    source = rc.fabrique_source({"BTC/USD": _bougies(debut, 10)})

    loin = debut + timedelta(days=400)
    assert asyncio.run(source("BTC/USD", loin, loin + timedelta(hours=1))) == []


def test_une_paire_SANS_bougie_obtenue_n_est_pas_servable(db, monkeypatch):
    """Si Binance ne rend rien, la paire doit rester en file -- pas etre marquee.

    ⛔ C'est la lecon du `NO_DATA` du matin : une source muette ne prouve pas
    qu'une donnee est irrecuperable. Ne rien ecrire est le comportement juste.
    """
    async def _rien(pair, interval, debut, fin, **kw):
        return []

    monkeypatch.setattr(rc.bks, "fetch_klines_fenetre", _rien)
    t = datetime(2026, 8, 20, 4, tzinfo=timezone.utc)
    blocs = asyncio.run(rc.charge_les_blocs({"BTC/USD": (t, t)}))

    assert blocs == {"BTC/USD": []}
    servables = [p for p, cs in blocs.items() if cs]
    assert servables == [], "une paire sans bougie ne doit pas etre servable"
