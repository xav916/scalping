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


# --------------------------------------------------------------------------
# Kraken Futures — |entrée − stop| × taille
# --------------------------------------------------------------------------

def test_le_cas_REEL_du_25_08_DOT():
    """PF_DOTUSD : entrée 0,9507, stop 0,7136, taille 2,2 ⇒ 0,5216 USD.
    Mesuré en production le 25/08."""
    from backend.services.risque_engage import risque_position_stop
    assert risque_position_stop(0.9507, 0.7136, 2.2) == pytest.approx(0.5216, abs=1e-4)


def test_le_cas_REEL_du_25_08_PAXG():
    from backend.services.risque_engage import risque_position_stop
    assert risque_position_stop(4608.0, 4312.2, 0.003) == pytest.approx(0.8874, abs=1e-4)


def test_un_stop_A_L_ENTREE_est_un_VRAI_zero():
    """Le stop ramené au prix d'entrée : la position ne peut plus perdre.
    C'est une mesure, pas une faute de mesure."""
    from backend.services.risque_engage import risque_position_stop
    assert risque_position_stop(1.2345, 1.2345, 10.0) == 0.0


@pytest.mark.parametrize("entree,stop,taille", [
    (None, 0.7, 2.2), (0.95, None, 2.2), (0.95, 0.7, None),
    (0.95, 0.7, 0.0), (0.0, 0.7, 2.2),
])
def test_une_donnee_manquante_rend_None_JAMAIS_zero(entree, stop, taille):
    """⛔ Zéro dirait « aucun risque ». None dit « on ne sait pas »."""
    from backend.services.risque_engage import risque_position_stop
    assert risque_position_stop(entree, stop, taille) is None


def test_seuls_les_stops_reduceOnly_comptent():
    """Un ordre d'ENTRÉE en attente sur le même symbole n'est pas une
    protection — le compter en ferait une, et la position passerait pour
    bornée alors qu'elle ne l'est pas."""
    from backend.services.risque_engage import _stops_reduce_only
    charge = {"orders": [
        {"symbol": "PF_DOTUSD", "orderType": "stp", "reduceOnly": True,
         "stopPrice": 0.7136},
        {"symbol": "PF_SOLUSD", "orderType": "stp", "reduceOnly": False,
         "stopPrice": 100.0},
        {"symbol": "PF_ETHUSD", "orderType": "lmt", "reduceOnly": True,
         "stopPrice": None},
    ]}
    assert _stops_reduce_only(charge) == {"PF_DOTUSD": 0.7136}


def test_une_position_sans_stop_rend_le_compte_INDECIDABLE():
    from backend.services.risque_engage import evaluer_positions_stop
    e = evaluer_positions_stop(
        positions=[{"symbol": "PF_DOTUSD", "price": 0.9507, "size": 2.2}],
        stops={}, devise="USD")
    assert e["nues"] == 1
    assert e["indecidable"] is True
    assert e["pct"] is None


def test_sans_plafond_il_n_y_a_ni_pct_ni_restant():
    """⛔ Kraken n'a pas de garde-fou de risque engagé. Inventer un
    pourcentage donnerait un chiffre comparable à celui de MT5 sans mesurer
    la même chose."""
    from backend.services.risque_engage import evaluer_positions_stop
    e = evaluer_positions_stop(
        positions=[{"symbol": "PF_DOTUSD", "price": 0.9507, "size": 2.2}],
        stops={"PF_DOTUSD": 0.7136}, devise="USD")
    assert e["risque_total"] == pytest.approx(0.5216, abs=1e-4)
    assert e["plafond"] is None
    assert e["pct"] is None
    assert e["restant"] is None
    assert e["indecidable"] is False


# --------------------------------------------------------------------------
# Conversion — elle a le droit d'échouer, pas de mentir
# --------------------------------------------------------------------------

def test_l_euro_ne_se_convertit_pas():
    from backend.services.risque_engage import en_euros
    assert en_euros(12.34, "EUR", None) == 12.34


def test_l_usd_se_divise_par_le_taux():
    """1,08 USD pour 1 EUR ⇒ 10,80 USD valent 10,00 EUR."""
    from backend.services.risque_engage import en_euros
    assert en_euros(10.80, "USD", 1.08) == pytest.approx(10.0)


@pytest.mark.parametrize("taux", [None, 0.0, -1.2])
def test_un_taux_ABSENT_ou_ABSURDE_rend_None(taux):
    """⛔ Pas de repli sur un taux « à peu près ». Un total crédible et faux
    est pire qu'une absence de total."""
    from backend.services.risque_engage import en_euros
    assert en_euros(10.80, "USD", taux) is None


def test_un_montant_absent_reste_absent():
    from backend.services.risque_engage import en_euros
    assert en_euros(None, "USD", 1.08) is None
