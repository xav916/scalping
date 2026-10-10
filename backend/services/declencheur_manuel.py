"""Déclencher une analyse de l'or à la demande — la commande `/trade`.

Demandé par Xavier le 2026-10-10, option **A**.

## ⛔ CE MODULE NE CONSTRUIT AUCUN SETUP

Il appelle `run_analysis_cycle(univers_force=[paire])` — le chemin de
production **à l'identique**, mêmes portes, mêmes verdicts, même routage.
C'est le choix déjà fait par `lanceur_sur_fermeture`, dont l'en-tête dit
pourquoi :

> ⛔ Écrire ici une analyse allégée aurait produit une doublure qui dérive en
> silence : le dépôt a déjà payé ce piège deux fois.

## 🔑 POURQUOI XAVIER NE CHOISIT PAS LE SENS

Il l'avait demandé. La mesure du **2026-10-10** l'a écarté :

```
direction du RADAR, 5 jours, n=59, horizons 1 a 60 min
  aucune p-valeur sous 0,27   reussite 42-54 %   => indiscernable du hasard
direction de XAVIER, 1 seul jour mesurable (adoption du 09/10)
  h=5 : +0,905 USD, p=0,015 — mais << toujours acheter >> fait +1,203
  => un biais haussier qui a eu raison, pas du discernement
```

⇒ Aucune des deux directions ne justifiait d'ouvrir un chemin dédié vers
l'argent réel. → `project_direction_sans_information_2026_10_10`

⛔ **Et l'autre voie était barrée par conception** : l'entrée officielle des
signaux externes ne peut pas atteindre l'argent réel.

```python
# bridge_destinations.py
if externe:
    # ⛔ Un setup venu d'un bot externe n'atteint JAMAIS l'argent réel.
```

## Ce que `/trade` fait, en une phrase

« Regarde l'or maintenant. » S'il y a un setup qualifié à cet instant, il part
par le chemin normal ; sinon rien ne se passe, **et c'est voulu** — ce
déclencheur supprime une attente, il ne fabrique pas de signal.

## Les trois gardes

1. **Inerte par défaut** (`DECLENCHEUR_MANUEL=0`).
2. **Paires déclarées** (`DECLENCHEUR_PAIRES`, défaut `XAU/USD`) — l'or est la
   seule paire dont la cadence a été mesurée.
3. **Délai de garde** (`DECLENCHEUR_COOLDOWN_SEC`, défaut 30 s). Le verrou de
   `run_analysis_cycle` empêche déjà la superposition, mais un refus explicite
   **se lit**, alors qu'une attente silencieuse ressemble à une panne.
"""
from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger(__name__)

_DERNIER: dict[str, float] = {}


def arme() -> bool:
    return os.getenv("DECLENCHEUR_MANUEL", "0").strip().lower() in (
        "1", "true", "on", "yes", "oui")


def paires() -> set[str]:
    brut = os.getenv("DECLENCHEUR_PAIRES", "XAU/USD")
    return {p.strip().upper() for p in brut.split(",") if p.strip()}


def _cooldown_sec() -> float:
    brut = (os.getenv("DECLENCHEUR_COOLDOWN_SEC") or "").strip()
    if not brut:
        return 30.0
    try:
        v = float(brut.replace(",", "."))
    except (TypeError, ValueError):
        logger.warning("declencheur: COOLDOWN illisible (%r) — repli sur 30 s",
                       brut)
        return 30.0
    return max(v, 0.0)


def motif_de_refus(pair: str | None) -> str | None:
    """Le motif, en clair, ou ``None`` si on peut déclencher."""
    if not arme():
        return "declencheur desarme (DECLENCHEUR_MANUEL=0)"
    p = (pair or "").strip().upper()
    if not p:
        # ⛔ LE PIEGE DU 2026-10-09 : `univers_force=[]` ne restreint RIEN, il
        # relance les 54 paires. Mesure de ce jour-la : 23-25 s de cycle
        # complet contre 0,5-1,9 s restreint, sur une instance ou le radar
        # prend deja 1,83 Gio sur 3,75 — c'est ce qui a fait tomber la
        # production 56 min.
        return "aucune paire indiquee (un univers vide relancerait TOUT)"
    if p not in paires():
        return f"{p} n'est pas une paire declaree ({', '.join(sorted(paires()))})"
    reste = _cooldown_sec() - (time.monotonic() - _DERNIER.get(p, -1e9))
    if reste > 0:
        return f"delai de garde : encore {reste:.0f} secondes"
    return None


async def declencher(pair: str | None) -> dict:
    """Lance un cycle de production restreint à `pair`. Ne lève jamais.

    Rend ``{"lance", "paire", "motif"}`` — appelé depuis un fil Telegram, où
    une exception serait avalée et le message resterait sans réponse.
    """
    motif = motif_de_refus(pair)
    if motif:
        logger.info("declencheur: refuse — %s", motif)
        return {"lance": False, "paire": (pair or "").strip().upper(),
                "motif": motif}

    p = (pair or "").strip().upper()
    # 🔑 Le temps est pose AVANT le cycle, pas apres : un cycle de 20 s
    # laisserait sinon passer un second declenchement pendant qu'il tourne.
    # Meme raison que dans `lanceur_sur_fermeture`.
    _DERNIER[p] = time.monotonic()
    try:
        from backend.services.scheduler import run_analysis_cycle
        logger.warning("declencheur: /trade demande par Xavier -> analyse de %s",
                       p)
        await run_analysis_cycle(univers_force=[p])
        return {"lance": True, "paire": p,
                "motif": "cycle de production lance sur " + p}
    except Exception as e:  # noqa: BLE001
        logger.warning("declencheur: cycle de %s echoue (%s: %s)",
                       p, type(e).__name__, e)
        return {"lance": False, "paire": p,
                "motif": f"echec du cycle : {type(e).__name__}: {e}"}
