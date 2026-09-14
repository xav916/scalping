"""Le registre des chaines armees — sa propre porte, fail-closed.

⛔ **Pourquoi une porte a part.** La liste blanche du pont est fail-closed sur
`PatternType`, et une chaine n'en est pas un — c'est voulu : « le laboratoire
mesure ; il n'ouvre aucune porte ». Promouvoir une chaine en `PatternType` la
ferait passer par la porte des motifs simples, sans decision propre, et
n'importe quelle chaine future serait armee du meme coup.

Elle a donc **sa** porte, avec exactement la meme discipline que l'autre.

## Format, dans l'`.env`

    CHAINES_AUTORISEES={"admin_legacy": {"5min": ["chaine:prise_en_accumulation_haussier"],
                                          "4h":   [...]},
                        "admin_live":   {...}}

destination -> horizon -> noms de chaines. **Rien d'implicite** : une
destination absente n'autorise rien, un horizon absent n'autorise rien.

## Les quatre refus

1. **Registre vide = rien n'est autorise.** Etat par defaut, et etat actuel.
2. **Une chaine armee sur la demo ne l'est pas sur le reel.** Meme lecon que
   la portee des fermetures du laboratoire : une decision vaut la ou elle a
   ete prise.
3. **Un JSON casse ferme**, il n'ouvre pas. Un `.env` mal edite ne doit jamais
   elargir une porte.
4. **Un nom qui n'est pas une chaine DECLAREE est refuse** — sinon ce registre
   deviendrait un second chemin vers la liste blanche des motifs simples, sans
   son controle, et on pourrait armer un nom que rien ne mesure.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

PREFIXE = "chaine:"

_cache: dict[str, dict[str, list[str]]] | None = None


def _declarees() -> set[str]:
    """Les noms de chaines que le laboratoire declare vraiment."""
    from backend.services.laboratoire_or import CHAINES
    return {c["nom"] if c["nom"].startswith(PREFIXE) else PREFIXE + c["nom"]
            for c in CHAINES}


def tout() -> dict[str, dict[str, list[str]]]:
    """Le registre, lu une fois puis garde. `{}` si vide ou illisible."""
    global _cache
    if _cache is not None:
        return _cache
    brut = os.getenv("CHAINES_AUTORISEES", "").strip()
    if not brut:
        _cache = {}
        return _cache
    try:
        lu = json.loads(brut)
        if not isinstance(lu, dict):
            raise ValueError("le registre doit etre un objet")
    except Exception as e:  # noqa: BLE001
        # ⛔ Fail-closed, et BRUYANT : une porte qui ne s'ouvre pas doit se
        # voir, sinon on croira que rien ne s'est declenche.
        logger.warning("CHAINES_AUTORISEES illisible (%s) — AUCUNE chaine "
                       "armee", e)
        _cache = {}
        return _cache

    connues = _declarees()
    propre: dict[str, dict[str, list[str]]] = {}
    for dest, par_horizon in lu.items():
        if not isinstance(par_horizon, dict):
            continue
        for horizon, noms in par_horizon.items():
            if not isinstance(noms, (list, tuple)):
                continue
            gardes = []
            for n in noms:
                n = str(n)
                if not n.startswith(PREFIXE):
                    logger.warning("CHAINES_AUTORISEES : %r n'est pas une "
                                   "chaine — ignore", n)
                    continue
                if n not in connues:
                    logger.warning("CHAINES_AUTORISEES : %r n'est declaree "
                                   "nulle part — ignore", n)
                    continue
                gardes.append(n)
            if gardes:
                propre.setdefault(str(dest), {})[str(horizon)] = gardes
    _cache = propre
    if propre:
        logger.warning("chaines ARMEES : %s", propre)
    return _cache


def autorisee(nom: str, destination_id: str | None, horizon: str | None) -> bool:
    """Cette chaine peut-elle partir sur cette destination, a cet horizon ?

    ⚠️ Une destination inconnue rend **False**. Contrairement aux fermetures du
    laboratoire — ou l'inconnu garde la protection — ici l'inconnu **ferme** :
    on ne parle plus de retirer une porte mais d'en ouvrir une.
    """
    if not nom or not nom.startswith(PREFIXE):
        return False
    if not destination_id or not horizon:
        return False
    return nom in tout().get(str(destination_id), {}).get(str(horizon), [])


def armees() -> list[str]:
    """Tout ce qui est arme, a plat — pour le dire dans un message."""
    out: list[str] = []
    for dest, par_h in tout().items():
        for h, noms in par_h.items():
            out += [f"{dest}/{h}/{n}" for n in noms]
    return sorted(out)
