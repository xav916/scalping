"""Mesure du risque engagé, un dialecte par type de bridge (2026-08-25).

Chaque courtier rend ses positions dans une forme différente. MT5 porte le
stop DANS la position et permet de dériver le risque du profit rapporté ;
Kraken et IBKR n'ont ni profit ni prix courant dans leur charge de position,
et leur stop vit dans un ordre séparé.

⛔ La mesure MT5 n'est PAS réécrite ici : elle est importée de
`scripts/notify_saturation_risque.py`, couverte par 24 tests et vérifiée au
centime près contre les positions réelles du 23/08. Une seconde
implémentation serait l'endroit exact où les deux chiffres divergeraient.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

DESTINATIONS_MESUREES = (
    "admin_live", "admin_legacy", "admin_kraken",
    "admin_kraken_spot", "admin_ibkr_us",
)


def evaluation_illisible(devise: str = "EUR") -> dict:
    """⛔ Muet n'est pas sain. Un bridge injoignable ne vaut pas « 0 € »."""
    return {
        "lisible": False, "indecidable": True,
        "risque_total": None, "plafond": None, "pct": None, "restant": None,
        "nues": 0, "non_mesurables": 0, "positions": 0,
        "candidats": 0, "liberable": 0.0, "login": None, "devise": devise,
    }


def _dialecte_mt5(dest) -> dict:
    from scripts.notify_saturation_risque import _lire_destination
    e = _lire_destination(dest)
    e["devise"] = "EUR"
    return e


def _dialecte_kraken_futures(dest) -> dict:
    return evaluation_illisible("USD")      # Task 2


def _dialecte_kraken_spot(dest) -> dict:
    return evaluation_illisible("USD")      # Task 5


def _dialecte_ibkr(dest) -> dict:
    return evaluation_illisible("USD")      # Task 6


# Clés = `Destination.bridge_type`, relevées dans le registre le 2026-08-25 :
#   admin_legacy / admin_live -> "mt5"      admin_kraken      -> "kraken"
#   admin_kraken_spot         -> "kraken_spot"  admin_ibkr_us -> "ibkr"
DIALECTES = {
    "mt5": _dialecte_mt5,
    "kraken": _dialecte_kraken_futures,
    "kraken_spot": _dialecte_kraken_spot,
    "ibkr": _dialecte_ibkr,
}


def mesurer_destination(dest) -> dict:
    """Mesure une destination via son dialecte. Toute panne ⇒ `illisible`."""
    dialecte = DIALECTES.get(getattr(dest, "bridge_type", ""))
    if dialecte is None:
        logger.warning("risque_engage: aucun dialecte pour bridge_type=%r "
                       "(destination %s)", getattr(dest, "bridge_type", None),
                       getattr(dest, "id", "?"))
        return evaluation_illisible()
    try:
        return dialecte(dest)
    except Exception:
        logger.exception("risque_engage: dialecte en échec sur %s",
                         getattr(dest, "id", "?"))
        return evaluation_illisible()


def verdict_destination(evaluation: dict, seuil_pct: float) -> str:
    """Verdict d'une destination, plafond ou pas.

    ⛔ `verdict()` de la sonde rend `indecidable` dès que `pct is None`. C'est
    juste pour MT5 — un pourcentage absent y signale une mesure impossible —
    et faux pour Kraken et IBKR : **n'avoir aucun plafond n'est pas ne pas
    savoir.** Sans ce filtre, la production dirait `indecidable` sur toutes
    les destinations non-MT5.

    ⛔ Et `verdict()` ne peut PAS être corrigée à la place : elle est partagée
    avec la sonde horaire de saturation, dont elle commande le seuil d'alerte.
    """
    from scripts.notify_saturation_risque import verdict

    if (evaluation.get("sans_plafond")
            and evaluation.get("lisible")
            and not evaluation.get("indecidable")):
        return "sans_plafond"
    return verdict(evaluation, seuil_pct)


def mesurer(destination_ids: tuple[str, ...] = DESTINATIONS_MESUREES) -> list[dict]:
    """Une mesure par destination, dans l'ordre donné. Bloquant."""
    from backend.services.destinations_registry import DESTINATIONS
    from scripts.notify_saturation_risque import SEUIL_PCT

    mesures = []
    for did in destination_ids:
        dest = DESTINATIONS.get(did)
        if dest is None:
            continue
        evaluation = mesurer_destination(dest)
        mesures.append({
            "id": did, "badge": dest.badge,
            "evaluation": evaluation,
            "verdict": verdict_destination(evaluation, SEUIL_PCT),
        })
    return mesures
