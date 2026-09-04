"""Limiteur de DÉBIT sur Twelve Data (2026-09-04).

`price_service` avait un sémaphore de 8 requêtes simultanées. ⛔ **La
concurrence n'est pas le débit** : 8 requêtes en vol avec ~100 ms de latence,
c'est jusqu'à 80 appels par seconde.

Mesuré en prod :

    usage en régime          7 / 55     ← aucun dépassement en moyenne
    appels dans une minute 171          ← limite 55
    appels en UNE seconde   54
    paires ignorées        502 en 6 h

Le débit MOYEN était de ~12/min, très en deçà des 55. Tout le problème tenait
à la concentration : ~35 requêtes tirées en une à deux secondes au début de
chaque cycle, puis 178 secondes de silence.

⚠️ « Paire ignorée » = **le radar n'a pas vu ce marché**. C'est de la donnée
perdue à l'entrée, avant tout scoring.

Le commentaire du module disait « 8 requêtes parallèles + un cycle de 200 s →
OK ». C'était vrai avec moins de paires. L'univers a grandi, le raisonnement
n'a pas suivi.
"""
from __future__ import annotations

import asyncio
import time

import pytest


@pytest.fixture()
def limiteur():
    from backend.services.price_service import _SeauAJetons
    return _SeauAJetons


# ── Le débit est tenu ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_la_rafale_initiale_passe_sans_attendre(limiteur):
    """Le seau part plein : une rafale sous la capacité ne coûte rien.

    Sans ce comportement, on paierait une latence même quand le quota est
    largement disponible — c'est le cas 90 % du temps.
    """
    seau = limiteur(par_minute=600, plafond_attente=5)
    debut = time.monotonic()
    for _ in range(600):
        assert await seau.acquerir() is True
    assert time.monotonic() - debut < 0.5


@pytest.mark.asyncio
async def test_au_dela_de_la_capacite_on_ATTEND(limiteur):
    """Le jeton suivant doit patienter le temps qu'il se regagne.

    600/min = 10 jetons/s, donc ~0,1 s d'attente. Cadence rapide choisie pour
    que le test mesure la MECANIQUE sans coûter des secondes à la suite.
    """
    seau = limiteur(par_minute=600, plafond_attente=5)
    for _ in range(600):
        await seau.acquerir()

    debut = time.monotonic()
    assert await seau.acquerir() is True
    attendu = time.monotonic() - debut
    assert 0.05 < attendu < 0.5, f"attente {attendu:.3f}s"


@pytest.mark.asyncio
async def test_le_seau_se_remplit_avec_le_temps(limiteur):
    """6000/min = 100 jetons/s : 0,2 s en regagne ~20.

    ⚠️ Ma première version disait « 0,3 s → ~18 jetons » à 60/min. Faux :
    60/min fait UN jeton par seconde, donc 0,3. Le test échouait sur mon
    arithmétique, pas sur le limiteur.
    """
    seau = limiteur(par_minute=6000, plafond_attente=5)
    for _ in range(6000):
        await seau.acquerir()
    await asyncio.sleep(0.2)          # ~20 jetons regagnes

    debut = time.monotonic()
    for _ in range(10):
        assert await seau.acquerir() is True
    assert time.monotonic() - debut < 0.2, "les jetons regagnes doivent servir"


# ── Le plafond d'attente ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_une_attente_trop_longue_est_REFUSEE(limiteur):
    """⛔ Le garde-fou qui empêche un cycle de déborder sur le suivant.

    Sans plafond, une rafale de réessais ferait la queue indéfiniment et un
    cycle pourrait dépasser son intervalle — on empilerait des cycles au lieu
    d'en rater un proprement.
    """
    seau = limiteur(par_minute=600, plafond_attente=0.02)
    for _ in range(600):
        await seau.acquerir()

    debut = time.monotonic()
    assert await seau.acquerir() is False, "au-delà du plafond, on renonce"
    assert time.monotonic() - debut < 0.1, "et on renonce VITE, sans attendre"


@pytest.mark.asyncio
async def test_un_refus_ne_consomme_PAS_de_jeton(limiteur):
    """Renoncer ne doit pas pénaliser celui qui viendra ensuite."""
    seau = limiteur(par_minute=6000, plafond_attente=0.0)
    for _ in range(6000):
        await seau.acquerir()
    await seau.acquerir()                      # refuse
    await asyncio.sleep(0.2)

    seau.plafond_attente = 5
    assert await seau.acquerir() is True


# ── Concurrence ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_le_debit_tient_sous_des_appels_SIMULTANES(limiteur):
    """⚠️ Le cas réel : 35 requêtes lancées ensemble par `asyncio.gather`.

    Sans verrou, deux coroutines pourraient consommer le même jeton et le
    limiteur laisserait passer plus que sa capacité — exactement le défaut
    qu'il corrige.
    """
    seau = limiteur(par_minute=6000, plafond_attente=10)
    debut = time.monotonic()
    resultats = await asyncio.gather(*[seau.acquerir() for _ in range(6200)])
    ecoule = time.monotonic() - debut

    assert all(resultats), "toutes doivent finir par passer"

    # ⚠️ L'invariant se mesure sur le TEMPS ÉCOULÉ, pas sur les jetons
    # restants. Ma première version affirmait `seau.jetons < 1.0` : vraie
    # isolément, fausse en suite, parce qu'une machine chargée allonge le
    # `gather` et laisse le seau se remplir pendant ce temps. L'assertion
    # dépendait de l'horloge, pas du limiteur.
    #
    # 200 acquisitions au-delà de la capacité, à 100 jetons/s, ne peuvent pas
    # prendre moins de ~2 s — et la charge ne peut que RALLONGER ce temps,
    # jamais le raccourcir. Sans verrou, deux coroutines prendraient le même
    # jeton et l'ensemble passerait instantanément.
    minimum = (6200 - 6000) / (6000 / 60) * 0.8
    assert ecoule >= minimum, (
        f"passe en {ecoule:.2f}s, minimum theorique {minimum:.2f}s — "
        "le limiteur n'a pas bride")


@pytest.mark.asyncio
async def test_un_limiteur_desactive_laisse_tout_passer(limiteur):
    """`par_minute=0` = comportement d'avant, pour pouvoir revenir en arrière."""
    seau = limiteur(par_minute=0, plafond_attente=5)
    debut = time.monotonic()
    for _ in range(200):
        assert await seau.acquerir() is True
    assert time.monotonic() - debut < 0.5
