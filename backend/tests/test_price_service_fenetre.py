"""`fetch_candles_fenetre` : bougies Twelve Data sur une PLAGE DE DATES.

Palier 2 du rattrapage (2026-10-26). 2 875 setups forex sont en file sur 38
paires, et `time_series` accepte `start_date`/`end_date`.

⛔ LE PIEGE MESURE AVANT D'ECRIRE CE CODE. Sur une plage large, Twelve Data ne
rend pas les 5 000 premieres bougies de la plage mais les 5 000 **DERNIERES** :
demander [01/08 -> 26/10] rend du 08/10 au 26/10 et jette aout en SILENCE. Une
pagination naive aurait donc « couvert » la periode en n'en rapportant que le
quart, sans la moindre erreur. D'ou le decoupage en TRANCHES DE DATES.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.services import price_service as ps


def _valeur(ts: datetime) -> dict:
    return {"datetime": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "open": "1.1", "high": "1.2", "low": "1.0",
            "close": "1.15", "volume": "0"}


class _FausseReponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


class _FauxClient:
    def __init__(self, fabrique):
        self.fabrique = fabrique
        self.appels: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None, headers=None):
        self.appels.append(dict(params or {}))
        return _FausseReponse(self.fabrique(dict(params or {})))


@pytest.fixture
def api(monkeypatch):
    """Installe une fausse API et neutralise le limiteur de debit."""
    monkeypatch.setattr(ps, "TWELVEDATA_API_KEY", "cle-de-test")

    class _SeauOuvert:
        async def acquerir(self):
            return True

    monkeypatch.setattr(ps, "_get_seau", lambda: _SeauOuvert())

    def installe(fabrique):
        faux = _FauxClient(fabrique)
        monkeypatch.setattr(ps.httpx, "AsyncClient", lambda **kw: faux)
        return faux

    return installe


def _api_honnete(params):
    """Imite Twelve Data : ordre DECROISSANT, plafonne aux plus RECENTES."""
    debut = datetime.fromisoformat(params["start_date"]).replace(tzinfo=timezone.utc)
    fin = datetime.fromisoformat(params["end_date"]).replace(tzinfo=timezone.utc)
    plafond = int(params["outputsize"])
    toutes = []
    t = debut
    while t <= fin:
        toutes.append(t)
        t += timedelta(minutes=5)
    recentes = toutes[-plafond:]
    return {"values": [_valeur(t) for t in reversed(recentes)]}


@pytest.mark.asyncio
async def test_les_bornes_de_dates_sont_bien_envoyees(api):
    debut = datetime(2026, 8, 20, 0, 0, tzinfo=timezone.utc)
    fin = debut + timedelta(hours=2)
    espion = api(_api_honnete)

    await ps.fetch_candles_fenetre("EUR/USD", "5min", debut, fin)

    assert espion.appels, "aucune requete partie"
    p = espion.appels[0]
    assert p["start_date"] == "2026-08-20 00:00:00"
    assert p["interval"] == "5min"
    assert p["timezone"] == "UTC", "sans timezone=UTC les horodatages derivent"
    assert int(p["outputsize"]) <= 5000


@pytest.mark.asyncio
async def test_une_plage_LARGE_est_couverte_EN_ENTIER(api):
    """Le test central : aout ne doit pas disparaitre.

    Avec une seule requete sur 68 jours, l'API rendrait les 5 000 dernieres
    bougies -- soit ~17 jours d'octobre -- et aout serait perdu SANS ERREUR.
    """
    debut = datetime(2026, 8, 20, tzinfo=timezone.utc)
    fin = datetime(2026, 10, 26, tzinfo=timezone.utc)
    api(_api_honnete)

    bougies = await ps.fetch_candles_fenetre("EUR/USD", "5min", debut, fin)

    assert bougies, "rien rendu"
    assert bougies[0].timestamp <= debut + timedelta(minutes=5), (
        "le DEBUT de la plage manque : c'est le piege des 5 000 plus recentes",
        bougies[0].timestamp.isoformat())
    assert bougies[-1].timestamp >= fin - timedelta(minutes=10), (
        "la FIN de la plage manque", bougies[-1].timestamp.isoformat())
    # couverture : 68 jours a 288 bougies/jour
    attendu = int((fin - debut).total_seconds() / 300) + 1
    assert len(bougies) >= 0.99 * attendu, (len(bougies), attendu)


@pytest.mark.asyncio
async def test_pas_de_doublon_entre_deux_tranches(api):
    debut = datetime(2026, 8, 20, tzinfo=timezone.utc)
    fin = debut + timedelta(days=40)
    api(_api_honnete)

    bougies = await ps.fetch_candles_fenetre("EUR/USD", "5min", debut, fin)

    horodatages = [c.timestamp for c in bougies]
    assert len(horodatages) == len(set(horodatages)), "des bougies en double"
    assert horodatages == sorted(horodatages), "ordre non chronologique"


@pytest.mark.asyncio
async def test_le_CACHE_n_est_NI_lu_NI_ecrit(api, monkeypatch):
    """Une serie historique ne doit jamais atteindre le chemin qui TRADE.

    ⛔ Defaut du 2026-09-08 : un cache indexe sur (paire, intervalle) SANS la
    taille avait servi la serie courte du cycle en cours a un appelant qui
    demandait une serie longue. Y ranger 19 584 bougies d'aout servirait de
    l'aout a la detection pendant tout le TTL.
    """
    lectures, ecritures = [], []
    monkeypatch.setattr(ps, "_cache_get_candles",
                        lambda *a, **k: lectures.append(a) or None)
    monkeypatch.setattr(ps, "_cache_store_candles",
                        lambda *a, **k: ecritures.append(a))
    debut = datetime(2026, 8, 20, tzinfo=timezone.utc)
    api(_api_honnete)

    await ps.fetch_candles_fenetre("EUR/USD", "5min", debut,
                                   debut + timedelta(hours=1))

    assert lectures == [], "le cache a ete LU"
    assert ecritures == [], "le cache a ete ECRIT"


@pytest.mark.asyncio
async def test_le_limiteur_de_debit_de_la_PRODUCTION_est_respecte(api, monkeypatch):
    """Un rattrapage ne doit pas pouvoir affamer le cycle qui trade.

    Si le seau refuse, on s'arrete en le DISANT -- on ne contourne pas.
    """
    import logging

    class _SeauFerme:
        async def acquerir(self):
            return False

    monkeypatch.setattr(ps, "_get_seau", lambda: _SeauFerme())
    espion = api(_api_honnete)
    debut = datetime(2026, 8, 20, tzinfo=timezone.utc)

    with caplog_at(logging.WARNING) as journal:
        bougies = await ps.fetch_candles_fenetre(
            "EUR/USD", "5min", debut, debut + timedelta(days=30))

    assert espion.appels == [], "une requete est passee malgre le seau ferme"
    assert bougies == []
    assert any("satur" in m.lower() for m in journal), journal


@pytest.mark.asyncio
async def test_une_tranche_VIDE_arrete_sans_boucler(api):
    """Marche ferme, paire inconnue : rendre ce qu'on a, et ne pas tourner."""
    appels = {"n": 0}

    def _vide(params):
        appels["n"] += 1
        return {"values": []}

    espion = api(_vide)
    debut = datetime(2026, 8, 20, tzinfo=timezone.utc)

    bougies = await ps.fetch_candles_fenetre(
        "EUR/USD", "5min", debut, debut + timedelta(days=60))

    assert bougies == []
    assert len(espion.appels) <= 6, f"{len(espion.appels)} requetes pour rien"


@pytest.mark.asyncio
async def test_un_message_d_erreur_de_l_API_est_JOURNALISE(api):
    import logging

    api(lambda p: {"code": 400, "message": "symbol not found"})
    debut = datetime(2026, 8, 20, tzinfo=timezone.utc)

    with caplog_at(logging.WARNING) as journal:
        bougies = await ps.fetch_candles_fenetre(
            "EUR/USD", "5min", debut, debut + timedelta(hours=1))

    assert bougies == []
    assert any("symbol not found" in m for m in journal), journal


# ─── 429 : le plan Grow est a 55 credits PAR MINUTE, partages ───────────────


class _Reponse429:
    """Imite un refus de quota : `raise_for_status` leve, comme httpx."""

    status_code = 429
    headers: dict = {}

    def raise_for_status(self):
        import httpx as _h
        raise _h.HTTPStatusError("429 Too Many Requests", request=None,
                                 response=self)

    def json(self):
        return {}


@pytest.mark.asyncio
async def test_un_429_est_REESSAYE_puis_aboutit(api, monkeypatch):
    """Mesure en production le 2026-10-26 : 38 tranches en rafale => 429 sur
    TOUTES les paires, zero bougie, rien rattrape.

    Le plan Grow donne **55 credits par MINUTE**, partages avec le cycle qui
    trade. Un refus temporaire ne doit pas condamner la paire : on attend et on
    reessaie.
    """
    pauses = []

    async def _pause(d):
        pauses.append(d)

    monkeypatch.setattr(ps.asyncio, "sleep", _pause)

    etat = {"n": 0}

    def _refuse_puis_accepte(params):
        etat["n"] += 1
        if etat["n"] == 1:
            raise _Reponse429().raise_for_status()
        return _api_honnete(params)

    debut = datetime(2026, 8, 20, tzinfo=timezone.utc)
    api(_refuse_puis_accepte)

    bougies = await ps.fetch_candles_fenetre(
        "EUR/USD", "5min", debut, debut + timedelta(hours=2))

    assert bougies, "le reessai n'a pas eu lieu : la paire est perdue sur un 429"
    assert pauses, "aucune attente avant le reessai"
    assert pauses[0] >= 1.0, f"attente trop courte : {pauses[0]}s"


@pytest.mark.asyncio
async def test_un_429_PERSISTANT_s_arrete_en_le_DISANT(api, monkeypatch):
    """Borne les reessais : ne pas marteler une API qui refuse."""
    import logging

    appels = {"n": 0}

    async def _pause(d):
        return None

    monkeypatch.setattr(ps.asyncio, "sleep", _pause)

    def _refuse_toujours(params):
        appels["n"] += 1
        raise _Reponse429().raise_for_status()

    debut = datetime(2026, 8, 20, tzinfo=timezone.utc)
    api(_refuse_toujours)

    with caplog_at(logging.WARNING) as journal:
        bougies = await ps.fetch_candles_fenetre(
            "EUR/USD", "5min", debut, debut + timedelta(days=30))

    assert bougies == []
    assert appels["n"] <= 5, f"{appels['n']} appels : martelage"
    assert any("429" in m or "quota" in m.lower() for m in journal), journal


@pytest.mark.asyncio
async def test_la_CADENCE_entre_tranches_est_respectee(api, monkeypatch):
    """Un rattrapage doit laisser de la bande a la production.

    🔑 Le limiteur a jetons borne le DEBIT MOYEN, mais le rattrapage et le
    cycle qui trade tirent sur le MEME seau de 55/min : sans cadence propre, le
    rattrapage le vide et la detection devient aveugle.
    """
    pauses = []

    async def _pause(d):
        pauses.append(d)

    monkeypatch.setattr(ps.asyncio, "sleep", _pause)
    debut = datetime(2026, 8, 20, tzinfo=timezone.utc)
    api(_api_honnete)

    await ps.fetch_candles_fenetre(
        "EUR/USD", "5min", debut, debut + timedelta(days=40),
        pause_entre_tranches=3.0)

    assert pauses, "aucune pause entre les tranches"
    assert all(p == 3.0 for p in pauses), pauses
    # 40 jours a 5 min = 11 520 bougies => au moins 3 tranches, donc >= 2 pauses
    assert len(pauses) >= 2, len(pauses)


@pytest.mark.asyncio
async def test_sans_cadence_demandee_AUCUNE_pause(api, monkeypatch):
    """Le defaut reste le comportement rapide : la cadence est un CHOIX."""
    pauses = []

    async def _pause(d):
        pauses.append(d)

    monkeypatch.setattr(ps.asyncio, "sleep", _pause)
    debut = datetime(2026, 8, 20, tzinfo=timezone.utc)
    api(_api_honnete)

    await ps.fetch_candles_fenetre(
        "EUR/USD", "5min", debut, debut + timedelta(days=40))

    assert pauses == [], pauses

# ─── petit utilitaire de capture, pour ne pas dependre de l'ordre des fixtures ─

import contextlib  # noqa: E402
import logging  # noqa: E402


@contextlib.contextmanager
def caplog_at(niveau):
    messages: list[str] = []

    class _Collecteur(logging.Handler):
        def emit(self, record):
            messages.append(record.getMessage())

    logger = logging.getLogger("backend.services.price_service")
    h = _Collecteur(level=niveau)
    logger.addHandler(h)
    ancien = logger.level
    logger.setLevel(niveau)
    try:
        yield messages
    finally:
        logger.removeHandler(h)
        logger.setLevel(ancien)
