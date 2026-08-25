"""Aiguillage des dialectes de mesure du risque engagé (2026-08-25).

Chaque type de bridge parle un dialecte différent. Ce qui est verrouillé ici,
c'est qu'une destination ne puisse pas être mesurée par le mauvais dialecte —
ni, pire, être silencieusement sautée.
"""
from __future__ import annotations

import pytest


def test_chaque_type_de_bridge_a_un_dialecte():
    from backend.services.risque_engage import DIALECTES
    from backend.services.destinations_registry import DESTINATIONS

    attendus = {DESTINATIONS[d].bridge_type
                for d in ("admin_legacy", "admin_live", "admin_kraken",
                          "admin_kraken_spot", "admin_ibkr_us")}
    manquants = attendus - set(DIALECTES)
    assert not manquants, f"types sans dialecte : {manquants}"


def test_un_type_inconnu_rend_illisible_et_ne_leve_PAS():
    """⛔ Une destination ajoutée demain ne doit pas faire planter la commande —
    ni se faire compter pour zéro. `illisible` est le seul repli honnête."""
    from backend.services.risque_engage import mesurer_destination

    class _Faux:
        id = "inconnue"
        badge = "?"
        bridge_type = "type_qui_nexiste_pas"

    e = mesurer_destination(_Faux())
    assert e["lisible"] is False
    assert e["risque_total"] is None


def test_une_destination_SANS_PLAFOND_n_est_PAS_indecidable():
    """⛔ Le piège que ce filtre existe pour éviter.

    `verdict()` de la sonde traite `pct is None` comme une indécision — juste
    pour MT5, faux pour Kraken : n'avoir aucun plafond n'est pas ne pas savoir.
    Sans ce filtre, la production dirait `indecidable` sur toutes les
    destinations non-MT5 pendant que les tests, qui fabriquent la mesure à la
    main, resteraient verts.
    """
    from backend.services.risque_engage import verdict_destination

    e = {"lisible": True, "indecidable": False, "pct": None,
         "risque_total": 1.409, "sans_plafond": True}
    assert verdict_destination(e, 72.0) == "sans_plafond"


def test_le_filtre_ne_MASQUE_pas_une_vraie_indecision():
    """Une position nue reste indécidable, plafond ou pas."""
    from backend.services.risque_engage import verdict_destination

    e = {"lisible": True, "indecidable": True, "pct": None,
         "risque_total": 1.409, "sans_plafond": True, "nues": 1}
    assert verdict_destination(e, 72.0) == "indecidable"


def test_le_filtre_laisse_MT5_intact():
    from backend.services.risque_engage import verdict_destination

    assert verdict_destination(
        {"lisible": True, "indecidable": False, "pct": 89.3}, 72.0) == "sature"
    assert verdict_destination(
        {"lisible": True, "indecidable": False, "pct": 40.0}, 72.0) == "ok"
    assert verdict_destination({"lisible": False}, 72.0) == "illisible"
