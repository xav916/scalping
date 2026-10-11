"""La détection de l'or doit voir des prix FRAIS, et ceux du courtier.

> Xavier, 2026-10-11 : « mettre de la détection sur le live, sur les ticks du
> live, et pas sur les bougies M1 ou M5 qui n'ont plus aucun sens avec la
> détection de patterns en live. »

## ⛔ LE DÉFAUT QU'IL AVAIT RAISON DE DÉNONCER, mesuré

    le cycle de l'or tourne toutes les         **5 secondes**
    mais le cache des bougies 5 min a un TTL de **200 secondes**
    et l'or n'était PAS servi par le pont (`PAIRES_BOUGIES_PONT=WTI/USD`)

⇒ La détection relisait **les mêmes bougies pendant plus de trois minutes**, et
ces bougies venaient de **Twelve Data** — la source dont l'écart aux clôtures
du courtier vaut **0,53 à 0,76 $** en médiane. Les 5 secondes du cycle rapide
ne servaient qu'à redécider sur une photo périmée, prise ailleurs.

⚠️ Et ma propre description était fausse : j'avais dit « le motif n'est
confirmé qu'à la clôture de la bougie, donc jusqu'à 5 minutes de retard ». Le
retard réel ne venait pas de la clôture mais du **cache**.

## Ce que ces tests garantissent

Que le contournement du cache est **inerte par défaut**, qu'il ne s'applique
**qu'aux paires servies par le pont** (les autres restent sur leur cache, sinon
le quota Twelve Data saute — 954 refus 429 déjà payés), et qu'une paire du pont
ne mémorise rien quand il est armé.
"""
from __future__ import annotations

import pytest

from backend.services import price_service as PS


@pytest.fixture(autouse=True)
def _propre(monkeypatch):
    monkeypatch.delenv("BOUGIES_PONT_SANS_CACHE", raising=False)
    yield


def test_inerte_par_defaut():
    assert PS._pont_sans_cache() is False


@pytest.mark.parametrize("valeur,attendu", [
    ("1", True), ("true", True), ("ON", True), ("yes", True),
    ("0", False), ("", False), ("non", False), ("off", False),
])
def test_le_drapeau_se_lit(monkeypatch, valeur, attendu):
    monkeypatch.setenv("BOUGIES_PONT_SANS_CACHE", valeur)
    assert PS._pont_sans_cache() is attendu


@pytest.mark.asyncio
async def test_une_paire_du_PONT_ne_met_rien_en_cache_quand_c_est_arme(
        monkeypatch):
    monkeypatch.setenv("BOUGIES_PONT_SANS_CACHE", "1")
    from backend.models.schemas import Candle
    import datetime as dt

    faux = [Candle(timestamp=dt.datetime(2026, 10, 9, 12, 0,
                                         tzinfo=dt.timezone.utc),
                   open=4150.0, high=4151.0, low=4149.0, close=4150.5,
                   volume=0)]

    from backend.services import bougies_du_pont as BP

    async def faux_fetch(pair, interval, outputsize):
        return faux

    monkeypatch.setattr(BP, "paire_du_pont", lambda pair: True)
    monkeypatch.setattr(BP, "fetch_candles", faux_fetch)

    ranges = {"n": 0}
    monkeypatch.setattr(PS, "_cache_store_candles",
                        lambda *a, **k: ranges.__setitem__("n", ranges["n"] + 1))

    candles, simule = await PS._fetch_depuis_source("XAU/USD", "5min", 50)
    assert candles == faux
    assert simule is False
    # ⛔ le coeur du test : RIEN n'est memorise, donc le prochain cycle
    # (5 s plus tard) ira rechercher des prix FRAIS
    assert ranges["n"] == 0


@pytest.mark.asyncio
async def test_sans_le_drapeau_le_cache_est_alimente_comme_avant(monkeypatch):
    monkeypatch.delenv("BOUGIES_PONT_SANS_CACHE", raising=False)
    from backend.models.schemas import Candle
    import datetime as dt

    faux = [Candle(timestamp=dt.datetime(2026, 10, 9, 12, 0,
                                         tzinfo=dt.timezone.utc),
                   open=4150.0, high=4151.0, low=4149.0, close=4150.5,
                   volume=0)]

    from backend.services import bougies_du_pont as BP

    async def faux_fetch(pair, interval, outputsize):
        return faux

    monkeypatch.setattr(BP, "paire_du_pont", lambda pair: True)
    monkeypatch.setattr(BP, "fetch_candles", faux_fetch)

    ranges = {"n": 0}
    monkeypatch.setattr(PS, "_cache_store_candles",
                        lambda *a, **k: ranges.__setitem__("n", ranges["n"] + 1))

    await PS._fetch_depuis_source("XAU/USD", "5min", 50)
    # comportement d'avant, a l'identique
    assert ranges["n"] == 1


@pytest.mark.asyncio
async def test_une_paire_qui_n_est_PAS_du_pont_garde_son_cache(monkeypatch):
    """⛔ Le contournement ne doit pas fuir sur Twelve Data : son quota a deja
    saute une fois (954 refus 429), et raccourcir son cache multiplierait ses
    appels par quarante."""
    monkeypatch.setenv("BOUGIES_PONT_SANS_CACHE", "1")
    from backend.services import bougies_du_pont as BP
    monkeypatch.setattr(BP, "paire_du_pont", lambda pair: False)

    appele = {"pont": False}

    async def ne_doit_pas_etre_appele(*a, **k):
        appele["pont"] = True
        return []

    monkeypatch.setattr(BP, "fetch_candles", ne_doit_pas_etre_appele)
    try:
        await PS._fetch_depuis_source("EUR/USD", "5min", 50)
    except Exception:
        # la cascade Twelve Data peut echouer sans reseau : ce n'est pas l'objet
        pass
    assert appele["pont"] is False
