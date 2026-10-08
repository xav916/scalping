"""Reprendre la main sur une paire dès qu'une de ses positions se ferme.

Demandé par Xavier le 2026-10-08 : *« Je trouve que le fait d'attendre
3 minutes est un peu long. Peut-on redévelopper le lanceur ? […] qu'il soit à
l'écoute des threads fermés. »*

## Ce que ça gagne, mesuré et non supposé

```
synchro MT5 (détection de la fermeture)   60 s
cycle d'analyse (tour d'horloge)         180 s
⇒ latence observée après une fermeture : 2 min 03
```

Avec ce lanceur, la fermeture **déclenche** l'analyse au lieu de l'attendre :
il ne reste que la détection. ⇒ **~30 s en moyenne** au lieu de ~2 min.

⚠️ Et ce qu'il ne gagne PAS : l'écart entre deux trades d'or est gouverné par
l'**arrivée des setups qualifiés** — 33/jour mesurés, soit un toutes les
~25 min. Ce lanceur supprime une latence de 2 min ; il ne fabrique pas de
signal. Sans setup qualifié au moment où il tire, il ne se passe rien, et c'est
voulu.

## ⛔ Pourquoi il NE contient aucune analyse

Il appelle `run_analysis_cycle(univers_force=[paire])` — le chemin de
production **à l'identique**, mêmes portes, mêmes verdicts, même routage.
Écrire ici une analyse allégée aurait produit une doublure qui dérive en
silence : le dépôt a déjà payé ce piège deux fois
(`feedback_router_une_source_en_laisser_deux`, où le WTI avait **trois**
chemins de prix, et `feedback_doublure_de_test_absente_en_prod`).

## Les quatre gardes, et la raison de chacune

1. **Inerte par défaut** (`LANCEUR_SUR_FERMETURE=0`) — rien ne change tant que
   Xavier n'arme pas, comme `XAU_TP_FIXE_EUR`.
2. **Paires déclarées** (`LANCEUR_PAIRES`, défaut `XAU/USD`) — l'or est la
   seule paire dont la cadence a été mesurée.
3. **Délai de garde** (`LANCEUR_COOLDOWN_SEC`, défaut 60 s) — deux fermetures
   dans la même passe de synchro ne doivent déclencher qu'**un** lancement.
4. **Verrou partagé** avec le cycle — porté par `run_analysis_cycle`, qui
   refuse de se superposer à lui-même. Deux cycles concurrents, c'est deux fois
   les bougies en mémoire sur une instance où le radar seul prend déjà
   1,83 Gio sur 3,75 : exactement ce qui a fait tomber la production 56 min.

⚠️ Le délai de garde **n'est pas** un plafond de trades : le plafond de
positions (`metal: 1`) et le `order_cooldown` par destination restent seuls
juges de ce qui part. Celui-ci ne borne que la **relance**.
"""
from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger(__name__)

_DERNIER_LANCEMENT: dict[str, float] = {}


def arme() -> bool:
    """⛔ Inerte par défaut : un lanceur qui s'allume tout seul au déploiement
    changerait la cadence de l'argent réel sans que personne l'ait demandé."""
    return os.getenv("LANCEUR_SUR_FERMETURE", "0").strip().lower() in (
        "1", "true", "yes", "on")


def paires_ecoutees() -> set[str]:
    brut = os.getenv("LANCEUR_PAIRES", "XAU/USD")
    return {p.strip().upper() for p in brut.split(",") if p.strip()}


def _cooldown_sec() -> float:
    try:
        return float(os.getenv("LANCEUR_COOLDOWN_SEC", "60"))
    except ValueError:
        # ⛔ Un réglage illisible ne doit pas rendre le délai de garde NUL :
        # ce serait la porte ouverte à une rafale de relances.
        logger.warning("LANCEUR_COOLDOWN_SEC illisible, repli sur 60 s")
        return 60.0


def motif_de_refus(pair: str | None) -> str | None:
    """Rend la raison de NE PAS relancer, ou ``None`` s'il faut relancer.

    🔑 Rend un motif plutôt qu'un booléen : un lanceur muet qui ne part pas
    est indiscernable d'un lanceur cassé — c'est le défaut relevé le 2026-10-07
    (11 refus, 0 question) et celui des huit doublons de la sonde métaux.
    """
    if not arme():
        return "lanceur_desarme"
    p = (pair or "").strip().upper()
    if not p:
        return "paire_inconnue"
    if p not in paires_ecoutees():
        return "paire_non_ecoutee"
    reste = _cooldown_sec() - (time.monotonic() - _DERNIER_LANCEMENT.get(p, 0.0))
    if _DERNIER_LANCEMENT.get(p) and reste > 0:
        return "cooldown_%.0fs" % reste
    return None


async def relancer_apres_fermeture(pair: str | None,
                                   ticket: int | None = None) -> str:
    """Relance l'analyse de `pair` si les quatre gardes le permettent.

    Rend une chaîne décrivant ce qui s'est passé — jamais une exception :
    appelé depuis la réconciliation, qui ne doit pas tomber pour ça.
    """
    motif = motif_de_refus(pair)
    if motif:
        logger.debug("lanceur: %s (paire=%s ticket=%s)", motif, pair, ticket)
        return motif

    p = (pair or "").strip().upper()
    # 🔑 Le temps est posé AVANT le lancement, pas après : un cycle de 20 s
    # laisserait sinon passer une seconde relance pendant qu'il tourne.
    _DERNIER_LANCEMENT[p] = time.monotonic()
    try:
        from backend.services.scheduler import run_analysis_cycle
        logger.info(
            "lanceur: %s vient de fermer (ticket %s) -> relance de l'analyse",
            p, ticket)
        await run_analysis_cycle(univers_force=[p])
        return "relance"
    except Exception as e:  # noqa: BLE001
        # ⚠️ Best-effort, comme la notification de fermeture juste à côté :
        # une relance qui échoue ne doit pas empêcher la clôture d'être
        # enregistrée. Le prochain tour d'horloge reprendra la main.
        logger.warning("lanceur: relance de %s echouee (%s)", p, e)
        return "echec_%s" % type(e).__name__
