"""La porte avant le pont : juge un lot de setups or, par destination.

Deux moities, comme `or-etat` : un juge PUR teste, et un collecteur impur
non teste. Les verdicts de production viennent d'une charge executee dans le
conteneur ; ce module n'en recopie aucun.

Les quatre contraintes ci-dessous sont un AJOUT de la skill, pas une
description de la production : `_check_rejection(setup, dest)` n'a aucun
parametre « fais comme si ceux-la etaient remplis ». Chaque verdict qu'elles
produisent porte donc `origine: lot`.
"""
from __future__ import annotations

ORIGINE_PRODUCTION = "production"
ORIGINE_LOT = "lot"

_LIMITES_REQUISES = ("max_correlated_positions", "order_cooldown_sec",
                     "max_risque_engage_pct", "places_par_paire")


def cumul_vide() -> dict:
    """L'etat de remplissage simule, vide. Separe par destination."""
    return {"paires": {}, "classes": {}, "risque": {}, "cadence": {}}


def contraintes_lot(setup: dict, destination: str, classe: str,
                    limites: dict, cumul: dict) -> tuple[str | None, dict]:
    """`(reason_code ou None, nouveau_cumul)`. Fail-closed sur toute limite
    illisible : on ne laisse pas passer ce qu'on n'a pas pu verifier."""
    for champ in _LIMITES_REQUISES:
        if limites.get(champ) is None:
            return "limite_illisible", cumul

    paire = setup["pair"]
    cle_p = (destination, paire)
    cle_c = (destination, classe)

    if cumul["paires"].get(cle_p, 0) >= int(limites["places_par_paire"]):
        return "lot_places_par_paire", cumul
    if cumul["classes"].get(cle_c, 0) >= int(limites["max_correlated_positions"]):
        return "lot_exposition_correlee", cumul

    risque = float(setup.get("risk_pct") or 0.0)
    engage = cumul["risque"].get(destination, 0.0)
    if engage + risque > float(limites["max_risque_engage_pct"]):
        return "lot_risque_engage", cumul

    # Le lot n'a pas d'horloge : ses setups sont traites comme SIMULTANES,
    # donc le deuxieme sur la meme paire bloque des que la fenetre existe.
    if int(limites["order_cooldown_sec"]) > 0 and cumul["cadence"].get(cle_p):
        return "lot_cadence", cumul

    neuf = {
        "paires": {**cumul["paires"], cle_p: cumul["paires"].get(cle_p, 0) + 1},
        "classes": {**cumul["classes"], cle_c: cumul["classes"].get(cle_c, 0) + 1},
        "risque": {**cumul["risque"], destination: engage + risque},
        "cadence": {**cumul["cadence"], cle_p: True},
    }
    return None, neuf
