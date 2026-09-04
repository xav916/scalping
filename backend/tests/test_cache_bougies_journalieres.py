"""Le fetch des bougies JOURNALIÈRES est cadencé (2026-09-04).

`shadow_v2_core_long` redemandait à Twelve Data les 60 bougies `1day` de
**chaque** paire, **à chaque cycle** — soit toutes les 3 minutes, pour 30
paires.

🔑 Une bougie journalière change une fois par jour. La redemander toutes les
trois minutes, c'est ~480 appels par paire et par jour là où un seul suffirait.

Mesuré en prod avant correctif :

    refus 429             95 par 10 minutes   (~570 / heure)
    paires ignorées      502 en 6 heures
    appels interval=1day  30 par 10 minutes

⚠️ « Paire ignorée ce cycle » signifie que **le radar n'a pas vu ce marché**.
502 fois en six heures, en silence. Ce n'est pas un problème de confort : c'est
de la donnée perdue à l'entrée du système.

Le cache sert donc DEUX buts, et le second compte autant que le premier :

  1. moins d'appels — le quota revient au flux 5 min, celui qui trade ;
  2. **amortir** les refus — un 429 ne fait plus disparaître la paire tant
     qu'une copie récente existe.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.models.schemas import Candle


def _bougies(n=60):
    return [Candle(timestamp=datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(days=i),
                   open=100, high=101, low=99, close=100, volume=0.0)
            for i in range(n)]


@pytest.fixture()
def shadow(monkeypatch):
    from backend.services import shadow_v2_core_long as sh
    monkeypatch.setattr(sh, "_CACHE_1D", {}, raising=False)
    return sh


# ── Moins d'appels ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_un_second_appel_rapproche_ne_refait_PAS_de_requete(shadow, monkeypatch):
    appels = []

    async def _faux(pair, interval, outputsize):
        appels.append(pair)
        return _bougies(), None

    monkeypatch.setattr("backend.services.price_service.fetch_candles", _faux)

    a = await shadow._bougies_journalieres("XAU/USD")
    b = await shadow._bougies_journalieres("XAU/USD")

    assert len(appels) == 1, "la deuxième demande doit être servie par le cache"
    assert len(a) == len(b) == 60


@pytest.mark.asyncio
async def test_le_cache_est_PAR_PAIRE(shadow, monkeypatch):
    appels = []

    async def _faux(pair, interval, outputsize):
        appels.append(pair)
        return _bougies(), None

    monkeypatch.setattr("backend.services.price_service.fetch_candles", _faux)

    await shadow._bougies_journalieres("XAU/USD")
    await shadow._bougies_journalieres("BTC/USD")
    assert appels == ["XAU/USD", "BTC/USD"]


@pytest.mark.asyncio
async def test_apres_expiration_on_redemande(shadow, monkeypatch):
    """Le cache doit vieillir : la bougie du jour se forme encore."""
    import time

    appels = []

    async def _faux(pair, interval, outputsize):
        appels.append(pair)
        return _bougies(), None

    monkeypatch.setattr("backend.services.price_service.fetch_candles", _faux)

    await shadow._bougies_journalieres("XAU/USD")
    # Rembobine l'échéance plutôt que d'attendre une heure.
    b, _ = shadow._CACHE_1D["XAU/USD"]
    shadow._CACHE_1D["XAU/USD"] = (b, time.monotonic() - 1)
    await shadow._bougies_journalieres("XAU/USD")

    assert len(appels) == 2


# ── Amortir les refus ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_un_429_ne_fait_PLUS_disparaitre_la_paire(shadow, monkeypatch):
    """⛔ Le second but du cache, et le plus important.

    502 paires ont été ignorées en 6 h faute de réponse. Avec une copie
    récente sous la main, un refus de l'API ne doit plus rendre le marché
    invisible au radar.
    """
    import time

    etat = {"echouer": False}

    async def _faux(pair, interval, outputsize):
        if etat["echouer"]:
            raise RuntimeError("429 Too Many Requests")
        return _bougies(), None

    monkeypatch.setattr("backend.services.price_service.fetch_candles", _faux)

    await shadow._bougies_journalieres("XAU/USD")
    b, _ = shadow._CACHE_1D["XAU/USD"]
    shadow._CACHE_1D["XAU/USD"] = (b, time.monotonic() - 1)   # périmé
    etat["echouer"] = True

    servi = await shadow._bougies_journalieres("XAU/USD")
    assert len(servi) == 60, "la copie périmée vaut mieux qu'un marché invisible"


@pytest.mark.asyncio
async def test_un_echec_SANS_copie_rend_une_liste_vide(shadow, monkeypatch):
    """Sans rien en réserve, le comportement d'avant : la paire est passée."""
    async def _faux(pair, interval, outputsize):
        raise RuntimeError("429 Too Many Requests")

    monkeypatch.setattr("backend.services.price_service.fetch_candles", _faux)
    assert await shadow._bougies_journalieres("XAU/USD") == []


@pytest.mark.asyncio
async def test_une_reponse_VIDE_n_ecrase_pas_une_copie_valide(shadow, monkeypatch):
    """⚠️ L'API peut répondre 200 avec une liste vide.

    L'accepter effacerait une copie utilisable — un succès apparent qui
    détruit de l'information.
    """
    import time

    etat = {"vide": False}

    async def _faux(pair, interval, outputsize):
        return ([] if etat["vide"] else _bougies()), None

    monkeypatch.setattr("backend.services.price_service.fetch_candles", _faux)

    await shadow._bougies_journalieres("XAU/USD")
    b, _ = shadow._CACHE_1D["XAU/USD"]
    shadow._CACHE_1D["XAU/USD"] = (b, time.monotonic() - 1)
    etat["vide"] = True

    assert len(await shadow._bougies_journalieres("XAU/USD")) == 60
