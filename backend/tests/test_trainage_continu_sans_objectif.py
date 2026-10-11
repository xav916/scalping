"""Le traînage CONTINU sans objectif — dicté par Xavier le 2026-10-11.

> « Je ne veux pas arrêter l'échelle à 20 euros. Si le cours augmente jusqu'à
> 30 euros, tu mets le stop à 29,5. Si le stop augmente dans la minute à 41, tu
> poses le stop à 40,5. Jamais de take profit. Juste un stop loss qui fait
> sortir le trade. »

## Ce que la mesure dit, et que ces tests ne surjouent pas

Sur 6 668 trades aveugles et 99 999 bougies M1 du courtier (2026-07-01 →
2026-10-09) :

    trainage 0,50 sans objectif          **+0,0467 EUR/trade**, reussite 71,2 %
    le meme avec objectif a palier + 2    -0,0227
    objectif qui fuit (2p + 1)            -0,0334   t -3,12 contre sans objectif
    objectif fixe a 2 EUR                 -0,1015   t -6,85 contre sans objectif

⇒ Retirer l'objectif est **etabli** ; le traînage lui-meme reste **sous la
barre** (t +2,30 contre 2,50 pour l'elargissement avec le temps). Ces tests ne
disent donc pas que le reglage gagne : ils garantissent qu'il fait **exactement**
ce qui a ete dicte, qu'il est **inerte par defaut**, et qu'il ne pose jamais un
stop du mauvais cote du cours.
"""
from __future__ import annotations

import importlib

import pytest

from backend.services import echelle_stop_or as E


@pytest.fixture(autouse=True)
def _env_propre(monkeypatch):
    """Chaque test part d'un environnement SANS les nouveaux drapeaux."""
    monkeypatch.delenv("ECHELLE_STOP_OR_TRAINAGE_EUR", raising=False)
    monkeypatch.delenv("ECHELLE_STOP_OR_SANS_OBJECTIF", raising=False)
    monkeypatch.delenv("ECHELLE_STOP_OR_PALIERS", raising=False)
    monkeypatch.delenv("ECHELLE_STOP_OR_PAS_MINI_EUR", raising=False)
    yield


# ─── Inerte par defaut : le comportement d'avant, a l'identique ───────────

def test_sans_drapeau_le_trainage_est_absent():
    assert E.trainage_eur() is None
    assert E.sans_objectif() is False


def test_sans_drapeau_les_paliers_dictes_le_2026_10_09_sont_intacts():
    assert E.palier_atteint(0.99) is None
    assert E.palier_atteint(1.00) == 0.75
    assert E.palier_atteint(1.80) == 1.50
    # et l'objectif suit, comme avant
    assert E.tp_vise_eur(1.00) == pytest.approx(3.00)


# ─── Le trainage continu, SANS PLAFOND ────────────────────────────────────

def test_le_trainage_suit_le_profit_sans_aucun_plafond(monkeypatch):
    monkeypatch.setenv("ECHELLE_STOP_OR_TRAINAGE_EUR", "0.50")
    # ⛔ C'est le point de sa demande : l'echelle ne s'arrete NULLE PART.
    assert E.palier_atteint(30.0) == pytest.approx(29.50)
    assert E.palier_atteint(41.0) == pytest.approx(40.50)
    assert E.palier_atteint(1000.0) == pytest.approx(999.50)


def test_le_point_mort_tombe_exactement_a_la_largeur(monkeypatch):
    monkeypatch.setenv("ECHELLE_STOP_OR_TRAINAGE_EUR", "0.50")
    # sous la largeur : rien a poser, le stop serait SOUS l'entree
    assert E.palier_atteint(0.49) is None
    # a la largeur pile : le point mort
    assert E.palier_atteint(0.50) == pytest.approx(0.0)
    assert E.palier_atteint(1.00) == pytest.approx(0.50)
    assert E.palier_atteint(2.37) == pytest.approx(1.87)


def test_une_largeur_nulle_ou_negative_est_REFUSEE(monkeypatch):
    # ⛔ Un stop colle au cours FERME la position : on refuse plutot que de
    # poser une sortie immediate.
    for mauvais in ("0", "0.0", "-1", "-0.5"):
        monkeypatch.setenv("ECHELLE_STOP_OR_TRAINAGE_EUR", mauvais)
        assert E.trainage_eur() is None, mauvais


def test_un_reglage_illisible_retombe_sur_les_paliers_pas_sur_rien(monkeypatch):
    monkeypatch.setenv("ECHELLE_STOP_OR_TRAINAGE_EUR", "zero virgule cinq")
    assert E.trainage_eur() is None
    # et les paliers d'avant repondent encore
    assert E.palier_atteint(1.00) == 0.75


# ─── L'objectif : retire, et jamais fuyant ────────────────────────────────

def test_le_drapeau_sans_objectif_retire_l_objectif(monkeypatch):
    monkeypatch.setenv("ECHELLE_STOP_OR_SANS_OBJECTIF", "1")
    assert E.sans_objectif() is True
    assert E.tp_vise_eur(1.00) is None
    assert E.tp_vise_eur(30.00) is None
    # ⚠️ mais le STOP continue d'etre pose : c'est lui qui fait sortir
    assert E.palier_atteint(1.00) == 0.75


def test_en_mode_trainage_aucun_objectif_n_est_pose(monkeypatch):
    # 🔑 Sans cette garde, l'objectif suivrait le profit et FUIRAIT : mesure
    # le 2026-10-11, un objectif qui recule coute -0,0311 EUR/jour (t -2,72).
    monkeypatch.setenv("ECHELLE_STOP_OR_TRAINAGE_EUR", "0.50")
    assert E.tp_vise_eur(1.00) is None
    assert E.tp_vise_eur(41.00) is None


# ─── La decision complete, telle que la boucle la consomme ────────────────

def _position(entree: float = 4000.0, courant: float = 4040.0,
              sens: str = "buy") -> dict:
    return {"ticket": 1, "symbol": "XAUUSD", "type": sens,
            "price_open": entree, "price_current": courant,
            "comment": E.MARQUE_RADAR + "-2026-10-11", "sl": None}


def test_la_decision_rend_un_stop_et_AUCUN_objectif(monkeypatch):
    monkeypatch.setenv("ECHELLE_STOP_OR", "1")
    monkeypatch.setenv("ECHELLE_STOP_OR_TRAINAGE_EUR", "0.50")
    monkeypatch.setenv("ECHELLE_STOP_OR_SANS_OBJECTIF", "1")
    # +40 $ sur un achat, soit ~35,72 EUR de profit au taux 1,1198
    d = E.decision(_position(), 1.1198)
    assert d is not None
    profit = 40.0 / 1.1198
    attendu = 4000.0 + (profit - 0.50) * 1.1198
    assert d["sl"] == pytest.approx(round(attendu, 2), abs=0.02)
    # ⛔ c'est le coeur de sa demande : pas d'objectif du tout
    assert d["tp"] is None
    assert d["tp_eur"] is None


def test_le_stop_reste_du_BON_cote_du_cours_sur_une_vente(monkeypatch):
    monkeypatch.setenv("ECHELLE_STOP_OR", "1")
    monkeypatch.setenv("ECHELLE_STOP_OR_TRAINAGE_EUR", "0.50")
    monkeypatch.setenv("ECHELLE_STOP_OR_SANS_OBJECTIF", "1")
    d = E.decision(_position(entree=4000.0, courant=3960.0, sens="sell"),
                   1.1198)
    assert d is not None
    # une vente gagne quand le prix BAISSE : le stop doit etre AU-DESSUS du
    # cours, et sous l'entree.
    assert 3960.0 < d["sl"] < 4000.0


def test_le_cliquet_tient_toujours_en_mode_trainage(monkeypatch):
    monkeypatch.setenv("ECHELLE_STOP_OR", "1")
    monkeypatch.setenv("ECHELLE_STOP_OR_TRAINAGE_EUR", "0.50")
    p = _position()
    # un stop DEJA plus haut que celui que l'echelle viserait
    p["sl"] = 4100.0
    assert E.decision(p, 1.1198) is None


# ─── Le plancher ABSOLU de la protection des pertes ───────────────────────

def test_le_plancher_absolu_arrete_les_resserrages(monkeypatch):
    import scripts.protection_perte_or as P
    importlib.reload(P)
    monkeypatch.setenv("PROTECTION_PERTE_PLANCHER_EUR", "2.0")
    # stop a 9 EUR, perte de 1 EUR : le point milieu donnerait 5,00
    assert P.nouveau_stop_eur(9.0, 1.0) == pytest.approx(5.0)
    # stop a 2,5, perte de 1 : le milieu donnerait 1,75, le plancher mord a 2
    assert P.nouveau_stop_eur(2.5, 1.0) == pytest.approx(2.0)
    # deja au plancher : plus rien a faire, et surtout pas desserrer
    assert P.nouveau_stop_eur(2.0, 1.0) is None


def test_le_stop_reste_TOUJOURS_du_bon_cote_du_cours(monkeypatch):
    """L'invariant, sur une grille — pas sur un cas choisi.

    ⛔ Mon premier test de cette propriete etait VACUEUX : je l'ai reinjecte en
    retirant la garde, et il passait quand meme. C'est que la garde etait
    MORTE — le point milieu de `(stop, perte)` avec `stop > perte` est
    toujours superieur a `perte`. Ce test verifie donc l'INVARIANT lui-meme,
    sur toute la grille, au lieu de proteger une ligne de code inutile.
    """
    import scripts.protection_perte_or as P
    importlib.reload(P)
    for absolu in ("0.5", "2.0", "5.0"):
        monkeypatch.setenv("PROTECTION_PERTE_PLANCHER_EUR", absolu)
        for stop in (2.5, 4.0, 9.0, 20.0):
            for perte in (0.1, 0.5, 1.0, 2.0, 3.0, 8.0):
                if perte >= stop:
                    continue        # etat impossible : le stop aurait ete touche
                vise = P.nouveau_stop_eur(stop, perte)
                if vise is None:
                    continue
                assert vise > perte, (absolu, stop, perte, vise)
                assert vise < stop, (absolu, stop, perte, vise)


def test_sans_le_drapeau_la_protection_est_inchangee(monkeypatch):
    import scripts.protection_perte_or as P
    importlib.reload(P)
    monkeypatch.delenv("PROTECTION_PERTE_PLANCHER_EUR", raising=False)
    # comportement d'avant : plancher = perte + marge_min (2,00 par defaut)
    assert P.nouveau_stop_eur(9.0, 1.0) == pytest.approx(5.0)
    assert P.nouveau_stop_eur(4.0, 1.0) == pytest.approx(3.0)
    # a 3,0 de stop et 1,0 de perte, le milieu (2,0) touche le plancher (3,0)
    assert P.nouveau_stop_eur(3.0, 1.0) is None


# ─── Le PAS MINIMAL, pour sonder a la seconde sans inonder le courtier ────

def test_sans_pas_mini_un_petit_gain_declenche_quand_meme(monkeypatch):
    """⚠️ Mon premier test visait un gain d'un MILLI-euro : il echouait, et la
    source avait raison. Le stop est arrondi au centime (`round(sl, 2)`), donc
    un mouvement d'un milli-dollar rend le MEME prix et le cliquet le refuse
    deja. Le pas minimal ne sert donc pas contre les milli-euros — il sert
    contre les gains de quelques CENTIMES, qui changent bien le prix arrondi.
    """
    monkeypatch.setenv("ECHELLE_STOP_OR", "1")
    monkeypatch.setenv("ECHELLE_STOP_OR_TRAINAGE_EUR", "0.50")
    assert E.pas_mini_eur() == 0.0
    p = _position(entree=4000.0, courant=4040.0)
    d1 = E.decision(p, 1.1198)
    assert d1 is not None
    p["sl"] = d1["sl"]
    # +0,05 EUR : assez pour changer le prix arrondi, donc l'ordre part
    p["price_current"] = 4040.0 + 0.05 * 1.1198
    assert E.decision(p, 1.1198) is not None


def test_le_pas_mini_retient_les_deplacements_minuscules(monkeypatch):
    monkeypatch.setenv("ECHELLE_STOP_OR", "1")
    monkeypatch.setenv("ECHELLE_STOP_OR_TRAINAGE_EUR", "0.50")
    monkeypatch.setenv("ECHELLE_STOP_OR_PAS_MINI_EUR", "0.10")
    assert E.pas_mini_eur() == pytest.approx(0.10)
    p = _position(entree=4000.0, courant=4040.0)
    d1 = E.decision(p, 1.1198)
    assert d1 is not None
    p["sl"] = d1["sl"]
    # +0,05 EUR : le prix arrondi change, mais c'est SOUS le pas de 0,10
    p["price_current"] = 4040.0 + 0.05 * 1.1198
    assert E.decision(p, 1.1198) is None
    # +0,20 EUR de plus : au-dela du pas, l'ordre part
    p["price_current"] = 4040.0 + 0.20 * 1.1198
    assert E.decision(p, 1.1198) is not None


def test_le_pas_mini_vaut_aussi_pour_une_VENTE(monkeypatch):
    monkeypatch.setenv("ECHELLE_STOP_OR", "1")
    monkeypatch.setenv("ECHELLE_STOP_OR_TRAINAGE_EUR", "0.50")
    monkeypatch.setenv("ECHELLE_STOP_OR_PAS_MINI_EUR", "0.10")
    p = _position(entree=4000.0, courant=3960.0, sens="sell")
    d1 = E.decision(p, 1.1198)
    assert d1 is not None
    p["sl"] = d1["sl"]
    p["price_current"] = 3960.0 - 0.05 * 1.1198   # +0,05 EUR, sous le pas
    assert E.decision(p, 1.1198) is None
    p["price_current"] = 3960.0 - 0.20 * 1.1198
    assert E.decision(p, 1.1198) is not None


def test_un_pas_illisible_ou_negatif_retombe_sur_zero(monkeypatch):
    for mauvais in ("dix centimes", "-0.10"):
        monkeypatch.setenv("ECHELLE_STOP_OR_PAS_MINI_EUR", mauvais)
        assert E.pas_mini_eur() == 0.0, mauvais
