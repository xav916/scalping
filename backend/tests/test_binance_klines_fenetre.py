"""La recuperation de bougies Binance sur une FENETRE DE DATES.

Pose le 2026-10-26 pour le palier 1 du rattrapage : 84 % des 22 592 setups en
file sont de la crypto, et l'API publique Binance accepte `startTime`/`endTime`
nativement, gratuitement et sans quota.

⛔ CE QUE CES TESTS PROTEGENT. `fetch_klines` existant demande les N DERNIERES
bougies : pour une fenetre d'aout il rend donc vide PAR CONSTRUCTION, et non
parce que la donnee manque. C'est la cause racine du silence de 65 jours.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.services import binance_klines_service as bks


def _kline(ts_ms: int) -> list:
    """Une kline Binance brute, au format array documente."""
    return [ts_ms, "100.0", "101.0", "99.0", "100.5", "12.0",
            ts_ms + 299_999, "1200.0", 42, "6.0", "600.0", "0"]


class _FausseReponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


class _FauxClient:
    """Enregistre CHAQUE appel, pour pouvoir affirmer sur les bornes."""

    def __init__(self, pages):
        self.pages = list(pages)
        self.appels: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None):
        self.appels.append(dict(params or {}))
        return _FausseReponse(self.pages.pop(0) if self.pages else [])


@pytest.fixture
def client_espion(monkeypatch):
    """Remplace httpx.AsyncClient et rend l'espion, pages injectables."""
    boite = {}

    def installe(pages):
        faux = _FauxClient(pages)
        boite["faux"] = faux
        monkeypatch.setattr(bks.httpx, "AsyncClient", lambda **kw: faux)
        return faux

    return installe


@pytest.mark.asyncio
async def test_les_bornes_de_temps_sont_bien_envoyees(client_espion):
    """`startTime` et `endTime` doivent partir en MILLISECONDES."""
    debut = datetime(2026, 8, 20, 4, 0, tzinfo=timezone.utc)
    fin = debut + timedelta(hours=1)
    espion = client_espion([[_kline(int(debut.timestamp() * 1000))], []])

    await bks.fetch_klines_fenetre("BTC/USD", "5min", debut, fin)

    assert espion.appels, "aucune requete partie"
    p = espion.appels[0]
    assert p["symbol"] == "BTCUSDT"
    assert p["interval"] == "5m"
    assert p["startTime"] == int(debut.timestamp() * 1000)
    assert p["endTime"] == int(fin.timestamp() * 1000)
    # ⛔ `limit` seul, sans bornes, est exactement le defaut qu'on corrige.
    assert "startTime" in p and "endTime" in p


@pytest.mark.asyncio
async def test_une_fenetre_longue_est_PAGINEE(client_espion):
    """Au-dela du plafond par appel, il faut enchainer les pages.

    Sans pagination, une fenetre de 68 jours rendrait les 1 500 premieres
    bougies et laisserait le reste invisible -- un trou SILENCIEUX, du meme
    genre que celui qu'on repare.
    """
    debut = datetime(2026, 8, 20, tzinfo=timezone.utc)
    fin = debut + timedelta(days=30)
    pas = 300_000  # 5 min en ms
    t0 = int(debut.timestamp() * 1000)
    page1 = [_kline(t0 + i * pas) for i in range(bks._PLAFOND_PAR_APPEL)]
    page2 = [_kline(t0 + (bks._PLAFOND_PAR_APPEL + i) * pas) for i in range(10)]
    espion = client_espion([page1, page2, []])

    bougies = await bks.fetch_klines_fenetre("ETH/USD", "5min", debut, fin)

    assert len(espion.appels) >= 2, "la fenetre longue n'a pas ete paginee"
    assert len(bougies) == bks._PLAFOND_PAR_APPEL + 10
    # la 2e page doit repartir APRES la derniere bougie recue
    assert espion.appels[1]["startTime"] > espion.appels[0]["startTime"]
    # et l'ordre chronologique doit tenir bout a bout
    assert bougies == sorted(bougies, key=lambda c: c.timestamp)


@pytest.mark.asyncio
async def test_rien_hors_de_la_fenetre_demandee(client_espion):
    """Binance peut rendre la bougie qui CHEVAUCHE la borne : on la coupe."""
    debut = datetime(2026, 8, 20, 4, 0, tzinfo=timezone.utc)
    fin = debut + timedelta(minutes=10)
    t0 = int(debut.timestamp() * 1000)
    trop = [_kline(t0 - 300_000), _kline(t0), _kline(t0 + 300_000),
            _kline(t0 + 600_000), _kline(t0 + 900_000)]
    client_espion([trop, []])

    bougies = await bks.fetch_klines_fenetre("BTC/USD", "5min", debut, fin)

    assert all(debut <= c.timestamp <= fin for c in bougies), \
        [c.timestamp.isoformat() for c in bougies]
    assert len(bougies) == 3


@pytest.mark.asyncio
async def test_paire_non_crypto_rend_vide_sans_appel(client_espion):
    """XAU/USD n'est pas sur Binance : ne pas interroger pour rien."""
    espion = client_espion([[]])
    debut = datetime(2026, 8, 20, tzinfo=timezone.utc)

    bougies = await bks.fetch_klines_fenetre(
        "XAU/USD", "5min", debut, debut + timedelta(hours=1))

    assert bougies == []
    assert espion.appels == [], "une requete est partie pour une paire absente"


@pytest.mark.asyncio
async def test_une_erreur_reseau_ne_leve_pas_mais_JOURNALISE(monkeypatch, caplog):
    """Best-effort comme le reste du module -- mais jamais en silence.

    🔑 La lecon du jour : un chemin qui echoue sans rien dire est ce qui a
    cache 65 jours de panne. Rendre vide est acceptable, se taire ne l'est pas.

    ⛔ ET LA LECON DE CE TEST-CI. Sa premiere version faisait
    `bks.httpx.AsyncClient = ...` puis un `importlib.reload`. Or `bks.httpx`
    EST le module httpx : l'affectation le cassait pour TOUTE la suite, et le
    reload ne l'annulait pas -- 10 tests d'un AUTRE fichier tombaient, mais
    seulement quand celui-ci passait avant. Vu par la mesure, pas par
    relecture. `monkeypatch` defait ses patchs au demontage ; une affectation
    brute, non.
    """
    import logging

    class _ClientQuiCasse(_FauxClient):
        async def get(self, url, params=None):
            self.appels.append(dict(params or {}))
            raise RuntimeError("reseau coupe")

    casse = _ClientQuiCasse([])
    monkeypatch.setattr(bks.httpx, "AsyncClient", lambda **kw: casse)

    with caplog.at_level(logging.WARNING,
                         logger="backend.services.binance_klines_service"):
        debut = datetime(2026, 8, 20, tzinfo=timezone.utc)
        bougies = await bks.fetch_klines_fenetre(
            "BTC/USD", "5min", debut, debut + timedelta(hours=1))

    assert bougies == []
    assert any("reseau coupe" in r.getMessage() for r in caplog.records), \
        [r.getMessage() for r in caplog.records]


@pytest.mark.asyncio
async def test_le_cache_WEBSOCKET_n_est_JAMAIS_consulte(client_espion, monkeypatch):
    """Une fenetre historique ne doit pas lire le cache du temps reel.

    ⛔ Le defaut du 2026-09-08 : un cache indexe sur (paire, intervalle) sans
    la taille avait servi la serie COURTE du cycle en cours a un appelant qui
    demandait une serie longue -- « 0 bougie », sans erreur ni trace.
    """
    appele = []

    def _piege(*a, **k):
        appele.append(a)
        return True

    import backend.services.binance_klines_ws as ws
    monkeypatch.setattr(ws, "is_ws_supported", _piege)
    debut = datetime(2026, 8, 20, tzinfo=timezone.utc)
    client_espion([[_kline(int(debut.timestamp() * 1000))], []])

    await bks.fetch_klines_fenetre("BTC/USD", "5min", debut,
                                   debut + timedelta(hours=1))

    assert appele == [], "le chemin fenetre a interroge le cache WS"
