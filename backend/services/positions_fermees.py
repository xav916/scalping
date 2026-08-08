"""Détection des clôtures par comparaison de deux relevés de positions.

Les positions auto ne sont enregistrées **nulle part** en base : `personal_trades`
ne porte que le journal manuel (1 583 clôtures, toutes `MANUAL`), et un ordre
poussé au bridge n'est plus suivi ensuite. Le seul témoin d'une clôture est le
courtier lui-même. On compare donc le relevé courant au précédent : une position
présente avant et absente maintenant a été fermée.

⚠️ **Le piège de cette méthode** : un bridge injoignable rend « aucune position ».
Sans garde-fou, trente secondes de coupure réseau annonceraient la clôture de
TOUTES les positions ouvertes — et le relevé vide écraserait l'instantané, donc
les vraies clôtures suivantes passeraient inaperçues. `clotures()` refuse donc de
conclure quand la lecture a échoué : le refus vit **dans la fonction**, pas dans
la discipline de l'appelant.

Les deux courtiers n'identifient pas une position de la même façon :

- MT5 donne un `ticket` entier, stable et unique ;
- Kraken Futures n'a pas de ticket : une position est le couple
  (`symbol`, `side`). Deux positions de sens opposé sur le même symbole sont
  donc bien distinctes, et un retournement long → short compte pour une
  clôture suivie d'une ouverture — ce qui est exactement ce qui s'est passé.
"""
from __future__ import annotations

from typing import Any, Iterable


def cle_position(bridge_type: str, pos: dict[str, Any]) -> str | None:
    """Identifiant stable d'une position, selon le courtier.

    Rend ``None`` quand la position n'est pas identifiable — une position sans
    clé ne doit jamais être comparée : elle serait vue comme fermée à chaque
    passage, puis rouverte, indéfiniment.
    """
    if not isinstance(pos, dict):
        return None

    if (bridge_type or "").startswith("kraken"):
        symbole = str(pos.get("symbol") or "").strip().upper()
        sens = str(pos.get("side") or "").strip().lower()
        return f"{symbole}|{sens}" if symbole and sens else None

    ticket = pos.get("ticket")
    try:
        ticket = int(ticket)
    except (TypeError, ValueError):
        return None
    return str(ticket) if ticket > 0 else None


def indexer(bridge_type: str, positions: Iterable[dict[str, Any]]) -> dict[str, dict]:
    """Relevé sous forme de dictionnaire clé → position, clés nulles écartées."""
    index: dict[str, dict] = {}
    for pos in positions or []:
        cle = cle_position(bridge_type, pos)
        if cle is not None:
            index[cle] = pos
    return index


def clotures(
    bridge_type: str,
    avant: dict[str, dict] | None,
    maintenant: dict[str, dict] | None,
    lecture_reussie: bool,
) -> list[dict]:
    """Positions présentes dans `avant` et absentes de `maintenant`.

    `lecture_reussie` vaut faux dès que le bridge n'a pas répondu proprement.
    Dans ce cas la fonction rend une liste vide **quoi qu'il arrive** : on ne
    déduit rien d'un relevé qu'on n'a pas pu lire.

    Un `avant` vide ou absent rend également une liste vide — c'est le premier
    passage, il n'y a pas de référence, et il n'y a rien à annoncer.
    """
    if not lecture_reussie or not avant:
        return []

    presentes = set(maintenant or {})
    return [pos for cle, pos in avant.items() if cle not in presentes]


def doit_memoriser(lecture_reussie: bool) -> bool:
    """L'instantané ne s'écrase que sur une lecture réussie.

    Corollaire indispensable du garde-fou ci-dessus : si une lecture ratée
    écrasait l'instantané avec du vide, la comparaison suivante repartirait de
    zéro et la clôture réelle ne serait jamais annoncée. Le silence d'un
    passage ne doit pas coûter la mémoire du précédent.
    """
    return bool(lecture_reussie)
