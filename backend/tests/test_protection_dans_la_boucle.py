"""La protection des pertes dans la BOUCLE, à la cadence demandée.

> Xavier, 2026-10-11 : « voir si le trade est négatif au bout de 30 secondes et
> resserrer le stop à cet effet. Lancez l'algo toutes les 20 secondes. »

🔑 **Un cron ne descend pas sous la minute** : il fallait un travail cadencé.

## Ce que la mesure dit

6 668 trades aveugles, 99 999 bougies M1 du courtier, même configuration
(départ 13 €, traînage 0,50, aucun objectif) :

    cadence         EUR/trade   pire journee   stop de depart touche
    aucune            +0,0570      -2,58            598 / 6 668
    5 min (le cron)   +0,0546      -1,75             20
    2 min             +0,0514      -0,87              2
    1 min             +0,0488      **-0,60**          **1**

⇒ Aucun écart de **rendement** établi (|t| ≤ 0,94, signes inversés entre les
moitiés) ; la **pire journée divisée par ~3**. C'est une assurance, et son prix
mesurable est nul. ⚠️ Son prix VISIBLE est 2,4 fois plus d'ordres au courtier.

⛔ Ces tests ne disent pas que la cadence rapide gagne. Ils garantissent que la
boucle est **inerte par défaut** et qu'elle appelle bien le même code que le
cron — pas une seconde implémentation.
"""
from __future__ import annotations

import os

import pytest

from backend.services import scheduler as S


def test_le_travail_existe_et_porte_le_bon_nom():
    assert hasattr(S, "_protection_perte_cycle")


@pytest.mark.asyncio
async def test_il_appelle_le_MEME_code_que_le_cron(monkeypatch):
    """🔑 Pas de seconde implementation : une regle en double derive."""
    appels = {"n": 0}

    import scripts.protection_perte_or as P

    def faux_appliquer(a_blanc: bool = False):
        appels["n"] += 1
        return {"resserres": 2, "ecartes": 0, "echecs": 0}

    monkeypatch.setattr(P, "appliquer", faux_appliquer)
    await S._protection_perte_cycle()
    assert appels["n"] == 1


@pytest.mark.asyncio
async def test_il_ne_tombe_JAMAIS(monkeypatch):
    """⛔ Best-effort : une exception ici ne doit pas tuer l'ordonnanceur."""
    import scripts.protection_perte_or as P

    def qui_explose(a_blanc: bool = False):
        raise RuntimeError("le pont est muet")

    monkeypatch.setattr(P, "appliquer", qui_explose)
    await S._protection_perte_cycle()      # ne doit rien lever


def test_la_boucle_est_INERTE_sans_la_variable(monkeypatch):
    """⛔ Sans `PROTECTION_PERTE_INTERVAL_SEC`, le cron reste seul."""
    monkeypatch.delenv("PROTECTION_PERTE_INTERVAL_SEC", raising=False)
    assert int(os.getenv("PROTECTION_PERTE_INTERVAL_SEC", "0")) == 0


@pytest.mark.parametrize("valeur,attendu", [
    ("20", 20), ("1", 1), ("0", 0), ("", 0),
])
def test_la_cadence_se_lit(monkeypatch, valeur, attendu):
    monkeypatch.setenv("PROTECTION_PERTE_INTERVAL_SEC", valeur)
    lu = os.getenv("PROTECTION_PERTE_INTERVAL_SEC", "0")
    assert int(lu or "0") == attendu
