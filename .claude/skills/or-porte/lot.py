"""Le lot de setups candidats : ce qu'on accepte, et son empreinte.

Les ONZE champs sont ceux que `_check_rejection` et ses aides lisent
reellement, obtenus par analyse AST transitive le 2026-10-29. Ni plus, ni
moins : hacher davantage perimerait des verdicts pour une modification sans
effet, hacher moins garderait vivant un verdict qu'une modification
materielle a invalide.
"""
from __future__ import annotations

import hashlib
import json

CHAMPS_PORTES = frozenset({
    "chaine", "confidence_score", "direction", "entry_price", "horizon",
    "is_simulated", "pair", "pattern", "shadow_system_id", "stop_loss",
    "verdict_blockers",
})

# `risk_pct` n'est lu par AUCUNE porte : il ne sert qu'a la contrainte de lot
# « risque engage », et il est donc exclu de l'empreinte.
CHAMPS_ADMIS = CHAMPS_PORTES | {"risk_pct"}


class ErreurLot(Exception):
    """Le lot n'est pas jugeable. Toujours en nommant le fautif."""


def empreinte_setup(setup: dict) -> str:
    """`sha256` tronque a 12, sur les ONZE champs seulement."""
    retenu = {k: setup.get(k) for k in sorted(CHAMPS_PORTES)}
    canon = json.dumps(retenu, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:12]


def valider_lot(obj: dict) -> dict:
    """Rend le lot validé, ou leve `ErreurLot` en nommant le fautif."""
    if not isinstance(obj, dict):
        raise ErreurLot("le lot doit etre un objet JSON")
    dests = obj.get("destinations")
    if not isinstance(dests, list) or not dests:
        raise ErreurLot("`destinations` est absent ou vide")
    setups = obj.get("setups")
    if not isinstance(setups, list) or not setups:
        raise ErreurLot("`setups` est absent ou vide")

    for n, s in enumerate(setups):
        if not isinstance(s, dict):
            raise ErreurLot("setup #%d n'est pas un objet" % n)
        inconnues = sorted(set(s) - CHAMPS_ADMIS)
        if inconnues:
            raise ErreurLot(
                "setup #%d : cle(s) inconnue(s) %s -- seules %s sont admises, "
                "pour qu'on ne croie jamais qu'un champ decoratif a influence "
                "le verdict" % (n, ", ".join(inconnues),
                                ", ".join(sorted(CHAMPS_ADMIS))))
        manquants = sorted(CHAMPS_PORTES - set(s))
        if manquants:
            raise ErreurLot(
                "setup #%d : champ(s) requis manquant(s) %s -- les portes les "
                "lisent" % (n, ", ".join(manquants)))
    # ⛔ Deduplique en PRESERVANT l'ordre d'apparition. Une destination
    # repetee double-comptait les contraintes de lot : deux passages
    # consommaient deux places la ou l'operateur n'en voulait qu'une. Le sens
    # etait prudent, mais un verdict faux dans le sens prudent reste faux.
    # 🔑 L'ordre doit survivre : les contraintes de lot simulent des
    # remplissages SUCCESSIFS, donc le reordonner changerait quel setup bloque.
    vues, uniques = set(), []
    for d in dests:
        if d not in vues:
            vues.add(d)
            uniques.append(d)
    return {"destinations": uniques, "setups": [dict(s) for s in setups]}
