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

# La cle de portee << toutes les paires >>, produite par la forme en LISTE.
# ⛔ Un nom de paire ne peut pas la heurter : aucune paire ne s appelle "*".
TOUTES_PAIRES = "*"

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

    def _garder(noms) -> list[str]:
        """Les noms qui sont des chaines DECLAREES, et le dire pour les autres."""
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
        return gardes

    propre: dict[str, dict[str, dict[str, list[str]]]] = {}
    for dest, par_horizon in lu.items():
        if not isinstance(par_horizon, dict):
            continue
        for horizon, contenu in par_horizon.items():
            if isinstance(contenu, dict):
                # Forme PAR PAIRE (2026-10-01) : la portee est nommee.
                for paire, noms in contenu.items():
                    if not isinstance(noms, (list, tuple)):
                        continue
                    gardes = _garder(noms)
                    if gardes:
                        (propre.setdefault(str(dest), {})
                               .setdefault(str(horizon), {})[str(paire)]) = gardes
            elif isinstance(contenu, (list, tuple)):
                gardes = _garder(contenu)
                if gardes:
                    (propre.setdefault(str(dest), {})
                           .setdefault(str(horizon), {})[TOUTES_PAIRES]) = gardes
                    # ⚠️ Une portee large ne doit pas etre SILENCIEUSE. La
                    # forme en liste vaut TOUTES les paires de la portee du
                    # compte — 25 sur `admin_live` le 01/10, dont 11 cryptos.
                    logger.warning(
                        "CHAINES_AUTORISEES : %s/%s arme pour TOUTES LES "
                        "PAIRES (%s). La forme par paire est preferable : "
                        '{"%s": {"%s": {"XAU/USD": [...]}}}',
                        dest, horizon, ", ".join(gardes), dest, horizon)
    _cache = propre
    if propre:
        logger.warning("chaines ARMEES : %s", propre)
    return _cache


def autorisee(nom: str, destination_id: str | None, horizon: str | None,
              pair: str | None = None) -> bool:
    """Cette chaine peut-elle partir sur cette destination, a cet horizon,
    pour cette paire ?

    ⚠️ Une destination inconnue rend **False**. Contrairement aux fermetures du
    laboratoire — ou l'inconnu garde la protection — ici l'inconnu **ferme** :
    on ne parle plus de retirer une porte mais d'en ouvrir une.

    ⛔ **`pair` (2026-10-01).** Sans cette dimension, armer une chaine a 5 min
    sur `admin_live` l'armait sur les **25 paires** de la portee du compte — 11
    cryptos, l'argent, le WTI — alors que la demande portait sur l'or. Et ce
    registre contourne la liste blanche des motifs : il ouvrait donc un chemin
    vers l'argent reel a 25 instruments dont la plupart n'ont jamais ete
    mesures pour cette chaine.

    ⛔ Si le registre est scope par paire et qu'aucune paire n'est transmise,
    on REFUSE : on ne peut pas verifier une portee qu'on ne connait pas.
    """
    if not nom or not nom.startswith(PREFIXE):
        return False
    if not destination_id or not horizon:
        return False
    par_paire = tout().get(str(destination_id), {}).get(str(horizon), {})
    if nom in par_paire.get(TOUTES_PAIRES, []):
        return True
    if not pair:
        return False
    return nom in par_paire.get(str(pair), [])


def armees() -> list[str]:
    """Tout ce qui est arme, a plat — pour le dire dans un message.

    La portee apparait : `dest/horizon/nom` quand toutes les paires sont
    visees, `dest/horizon/paire/nom` quand une seule l'est. Lire l'un ou
    l'autre dans une alerte doit suffire a savoir ce qui est ouvert.
    """
    out: list[str] = []
    for dest, par_h in tout().items():
        for h, par_paire in par_h.items():
            for paire, noms in par_paire.items():
                if paire == TOUTES_PAIRES:
                    out += [f"{dest}/{h}/{n}" for n in noms]
                else:
                    out += [f"{dest}/{h}/{paire}/{n}" for n in noms]
    return sorted(out)
