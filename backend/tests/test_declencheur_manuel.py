"""`/trade` : déclencher une analyse de l'or à la demande, depuis Telegram.

Demandé par Xavier le 2026-10-10, option **A** : *« A, la version qui équipe
tes trades à la main »*.

## ⛔ CE QUE CE MODULE NE FAIT PAS, ET POURQUOI

Il **ne construit aucun setup**. Il appelle `run_analysis_cycle(univers_force)`
— le chemin de production à l'identique, mêmes portes, mêmes verdicts, même
routage. C'est le choix déjà fait par `lanceur_sur_fermeture`, dont l'en-tête
explique la raison :

> ⛔ Écrire ici une analyse allégée aurait produit une doublure qui dérive en
> silence : le dépôt a déjà payé ce piège deux fois.

⇒ **Xavier ne choisit donc pas le sens.** C'est assumé, et c'est mesuré :
le 2026-10-10, sur 5 jours et 59 trades, la direction du radar s'est révélée
**indiscernable du hasard** (aucune p-valeur sous 0,27), et celle de Xavier
n'est mesurable que sur un jour, où elle ne bat pas un biais acheteur constant.
Aucune des deux ne justifiait d'ouvrir un chemin dédié.

⛔ **Et l'autre voie était barrée par conception.** L'entrée officielle des
signaux externes (`/api/signals/external`) ne peut pas atteindre l'argent
réel :

```python
# bridge_destinations.py
if externe:
    # ⛔ Un setup venu d'un bot externe n'atteint JAMAIS l'argent réel.
```

## Ce que `/trade` fait vraiment

« Regarde l'or maintenant. » S'il y a un setup qualifié à cet instant, il part
par le chemin normal ; sinon il ne se passe rien, et c'est voulu — le
déclencheur supprime une attente, il ne fabrique pas de signal.

## Les trois gardes

1. **Inerte par défaut** (`DECLENCHEUR_MANUEL=0`).
2. **Paires déclarées** (`DECLENCHEUR_PAIRES`, défaut `XAU/USD`).
3. **Délai de garde** (`DECLENCHEUR_COOLDOWN_SEC`, défaut 30 s) — deux `/trade`
   envoyés coup sur coup ne doivent déclencher qu'un cycle. Le verrou de
   `run_analysis_cycle` empêche déjà la superposition, mais un refus explicite
   se LIT, alors qu'une attente silencieuse ressemble à une panne.
"""
from __future__ import annotations

import asyncio
import importlib

import pytest


@pytest.fixture()
def D(monkeypatch):
    monkeypatch.setenv("DECLENCHEUR_MANUEL", "1")
    monkeypatch.delenv("DECLENCHEUR_PAIRES", raising=False)
    monkeypatch.delenv("DECLENCHEUR_COOLDOWN_SEC", raising=False)
    from backend.services import declencheur_manuel as mod
    importlib.reload(mod)
    return mod


def _brancher(monkeypatch, mod, erreur=None):
    """Remplace le cycle de production par une doublure qui CAPTURE l'univers."""
    vus = []

    async def _faux(univers_force=None, **kw):
        vus.append(univers_force)
        if erreur:
            raise erreur

    import backend.services.scheduler as sch
    monkeypatch.setattr(sch, "run_analysis_cycle", _faux)
    return vus


# ─────────────────────────────────────────────────────────────────────────
# 1. Il appelle LE CHEMIN DE PRODUCTION, restreint à la paire
# ─────────────────────────────────────────────────────────────────────────

def test_il_appelle_le_cycle_de_production_sur_la_PAIRE(D, monkeypatch):
    """🔑 `univers_force=["XAU/USD"]` — le chemin normal, restreint."""
    vus = _brancher(monkeypatch, D)

    r = asyncio.run(D.declencher("XAU/USD"))

    assert vus == [["XAU/USD"]], vus
    assert r["lance"] is True
    assert r["paire"] == "XAU/USD"


def test_un_univers_VIDE_serait_le_cycle_COMPLET_et_est_refuse(D, monkeypatch):
    """⛔ Le piège exact du 2026-10-09 : `univers_force=[]` ne restreint RIEN,
    il relance les 54 paires. Mesuré ce jour-là : 23-25 s de cycle complet
    contre 0,5-1,9 s restreint, sur une instance où le radar prend déjà
    1,83 Gio sur 3,75."""
    vus = _brancher(monkeypatch, D)

    r = asyncio.run(D.declencher(""))

    assert vus == [], "il a lance un cycle COMPLET"
    assert r["lance"] is False
    assert "paire" in r["motif"] or "vide" in r["motif"]


# ─────────────────────────────────────────────────────────────────────────
# 2. Les gardes
# ─────────────────────────────────────────────────────────────────────────

def test_INERTE_par_defaut(monkeypatch):
    monkeypatch.delenv("DECLENCHEUR_MANUEL", raising=False)
    from backend.services import declencheur_manuel as mod
    importlib.reload(mod)
    vus = _brancher(monkeypatch, mod)

    r = asyncio.run(mod.declencher("XAU/USD"))

    assert vus == [] and r["lance"] is False


def test_une_paire_NON_DECLAREE_est_refusee(D, monkeypatch):
    """⚠️ L'or est la seule paire dont la cadence a été mesurée."""
    vus = _brancher(monkeypatch, D)

    r = asyncio.run(D.declencher("EUR/USD"))

    assert vus == [] and r["lance"] is False


def test_le_DELAI_DE_GARDE_refuse_le_second_appel_et_le_DIT(D, monkeypatch):
    """⛔ Deux `/trade` coup sur coup ne doivent déclencher qu'un cycle — et le
    refus doit se LIRE : une attente silencieuse ressemble à une panne."""
    vus = _brancher(monkeypatch, D)

    r1 = asyncio.run(D.declencher("XAU/USD"))
    r2 = asyncio.run(D.declencher("XAU/USD"))

    assert r1["lance"] is True
    assert r2["lance"] is False
    assert "garde" in r2["motif"] or "secondes" in r2["motif"], r2
    assert len(vus) == 1, vus


def test_le_delai_de_garde_est_REGLABLE(monkeypatch):
    monkeypatch.setenv("DECLENCHEUR_MANUEL", "1")
    monkeypatch.setenv("DECLENCHEUR_COOLDOWN_SEC", "0")
    from backend.services import declencheur_manuel as mod
    importlib.reload(mod)
    vus = _brancher(monkeypatch, mod)

    asyncio.run(mod.declencher("XAU/USD"))
    r2 = asyncio.run(mod.declencher("XAU/USD"))

    assert r2["lance"] is True and len(vus) == 2


# ─────────────────────────────────────────────────────────────────────────
# 3. Il ne lève jamais
# ─────────────────────────────────────────────────────────────────────────

def test_un_cycle_qui_LEVE_rend_un_motif_au_lieu_de_tomber(D, monkeypatch):
    """⚠️ Appelé depuis un fil Telegram : une exception y serait avalée et le
    message resterait sans réponse."""
    _brancher(monkeypatch, D, erreur=RuntimeError("boum"))

    r = asyncio.run(D.declencher("XAU/USD"))

    assert r["lance"] is False
    assert "RuntimeError" in r["motif"] or "echec" in r["motif"], r


def test_le_delai_de_garde_est_POSE_AVANT_le_cycle(D, monkeypatch):
    """🔑 Un cycle de 20 s laisserait sinon passer un second declenchement
    pendant qu'il tourne. Meme raison que dans `lanceur_sur_fermeture`."""
    _brancher(monkeypatch, D, erreur=RuntimeError("boum"))

    asyncio.run(D.declencher("XAU/USD"))        # echoue
    r2 = asyncio.run(D.declencher("XAU/USD"))   # doit etre refuse quand meme

    assert r2["lance"] is False, "un echec a remis le compteur a zero"
