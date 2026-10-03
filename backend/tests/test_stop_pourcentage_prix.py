"""Le stop a un POURCENTAGE DU PRIX, avec un plancher au spread.

Demande de Xavier le 2026-10-03 : « mettre une regle de SL a 10 points de
l'entree », puis, apres mesure, « un % du prix, uniforme ».

## ⛔ POURQUOI PAS << 10 POINTS >>

Mesure sur le compte reel ce jour-la. Le `point` de MT5 n'est pas une unite
commune : 0,01 sur l'or et le BTC, 0,00001 sur l'EUR/USD. << 10 points >> tombe
donc SOUS le spread sur 9 paires sur 10 :

    BTC/USD   10 points = 0,10 $   spread 12,50 $   ⛔ 125x trop petit
    ETH/USD   10 points = 0,10 $   spread  4,31 $   ⛔  43x trop petit
    XAU/USD   10 points = 0,10 $   spread  0,50 $   ⛔   5x trop petit
    WTI/USD   10 points = 0,10 $   spread  0,02 $   seule plausible

🔑 Un stop sous le spread n'est pas un stop serre : c'est une PERTE CERTAINE,
touchee a la seconde ou l'ordre passe.

## ⛔ ET POURQUOI UN POURCENTAGE SEUL NE SUFFIT PAS

Un pourcentage uniforme ne donne PAS un cout uniforme, parce que le spread va
de 0,0121 % du prix (or) a 0,1176 % (ETH). Cout du spread en fraction du
RISQUE, pour un stop a 0,30 % :

    XAU   4,0 %      BTC   4,7 %      EUR/USD  4,4 %
    WTI   7,1 %      AUD  14,4 %      XAG     23,7 %
    ETH  39,2 %   ⛔

D'ou la regle retenue : **`stop = max(X % du prix, N x spread)`**. Une seule
regle, appliquee partout ; le plancher ne mord que la ou le spread est large,
et il borne le cout a `1/N` du risque.
"""
from __future__ import annotations

import pytest

from backend.services import pattern_detector as pd


# ─── La distance elle-meme ───────────────────────────────────────────────

def test_le_stop_vaut_le_pourcentage_demande_quand_le_spread_est_fin():
    """L'or : spread 0,50 $ sur 4 139, soit 0,0121 %. A 0,30 % le plancher
    (8 x 0,50 = 4 $) est tres en dessous : c'est le pourcentage qui decide."""
    d = pd.distance_sl_pourcentage(4139.72, spread=0.50, pct=0.30, planchers=8)
    assert d == pytest.approx(4139.72 * 0.003)


def test_le_PLANCHER_prend_la_main_quand_le_spread_est_large():
    """L'ETH : spread 4,31 $ sur 2 687. A 0,30 % le stop vaudrait 8,06 $, donc
    39 % du risque paye en spread. Le plancher 8 x 4,31 = 34,48 $ l'emporte."""
    d = pd.distance_sl_pourcentage(2687.70, spread=4.31, pct=0.30, planchers=8)
    assert d == pytest.approx(8 * 4.31)
    assert d > 2687.70 * 0.003


def test_le_cout_en_R_est_BORNE_par_le_plancher():
    """🔑 C'est tout l'objet du plancher : quel que soit le spread, le cout ne
    depasse pas 1/N du risque."""
    for prix, spread in ((4139.72, 0.50), (2687.70, 4.31), (84963.0, 12.50),
                         (1.1250, 0.00015), (36.0, 0.0256), (93.48, 0.02)):
        d = pd.distance_sl_pourcentage(prix, spread=spread, pct=0.30,
                                       planchers=8)
        cout = spread / d
        assert cout <= 1 / 8 + 1e-9, (prix, spread, cout)


def test_un_stop_n_est_JAMAIS_sous_le_spread():
    """⛔ La propriete qui justifie toute cette mecanique."""
    for prix, spread in ((84963.0, 12.50), (2687.70, 4.31), (4139.72, 0.50),
                         (1.1250, 0.00015), (0.24, 0.0044)):
        d = pd.distance_sl_pourcentage(prix, spread=spread, pct=0.30,
                                       planchers=8)
        assert d > spread, (prix, spread, d)


# ─── Les refus, et ils doivent etre EXPLICITES ───────────────────────────

def test_un_pourcentage_nul_ou_negatif_rend_None():
    """⚠️ `None` = << je ne sais pas >>, et l'appelant retombe sur l'ATR. Un
    stop de taille inconnue serait pire que l'ancien comportement."""
    assert pd.distance_sl_pourcentage(4139.0, spread=0.5, pct=0) is None
    assert pd.distance_sl_pourcentage(4139.0, spread=0.5, pct=-1) is None


def test_un_prix_absurde_rend_None():
    for prix in (0, -1, None):
        assert pd.distance_sl_pourcentage(prix, spread=0.5, pct=0.30) is None


def test_un_spread_INCONNU_n_empeche_pas_le_pourcentage():
    """⚠️ Si le spread est illisible on applique le pourcentage SEUL, au lieu
    de refuser : un stop a 0,30 % reste bien meilleur que pas de regle. Mais
    on ne peut alors plus garantir le plancher — et c'est a dire."""
    d = pd.distance_sl_pourcentage(4139.72, spread=None, pct=0.30)
    assert d == pytest.approx(4139.72 * 0.003)
    d2 = pd.distance_sl_pourcentage(4139.72, spread=0, pct=0.30)
    assert d2 == pytest.approx(4139.72 * 0.003)


def test_un_spread_NEGATIF_est_ignore():
    """Un ask sous le bid n'arrive pas, mais s'il arrivait il ne doit pas
    produire un plancher negatif qui annulerait la regle."""
    d = pd.distance_sl_pourcentage(4139.72, spread=-5.0, pct=0.30)
    assert d == pytest.approx(4139.72 * 0.003)


# ─── Le reglage ──────────────────────────────────────────────────────────

def test_les_valeurs_par_defaut_sont_celles_qui_ont_ete_MESUREES():
    """0,30 % du prix et un plancher a 8 x le spread : les deux chiffres
    viennent du tableau de cout mesure le 2026-10-03, pas d'une intuition."""
    assert pd.SL_PCT_PRIX == pytest.approx(0.30)
    assert pd.SL_PLANCHER_SPREADS == 8


def test_le_pourcentage_est_reglable(monkeypatch):
    monkeypatch.setattr(pd, "SL_PCT_PRIX", 1.0)
    d = pd.distance_sl_pourcentage(100.0, spread=0.01)
    assert d == pytest.approx(1.0)


def test_a_zero_la_regle_est_DESARMEE(monkeypatch):
    """⚠️ Mettre le pourcentage a zero doit rendre le comportement d'avant,
    pas un stop nul."""
    monkeypatch.setattr(pd, "SL_PCT_PRIX", 0.0)
    assert pd.distance_sl_pourcentage(100.0, spread=0.01) is None


# ─── LE CABLAGE, pas seulement la fonction ───────────────────────────────
#
# ⛔ Trois fois le 2026-10-03 le module etait juste et le branchement faux. Un
# test qui n'eprouve que `distance_sl_pourcentage` ne dirait rien de la regle
# REELLEMENT appliquee aux setups.

def _bougies(prix=100.0, n=60):
    from datetime import datetime, timedelta, timezone
    from backend.models.schemas import Candle
    t0 = datetime(2026, 10, 3, 8, 0, tzinfo=timezone.utc)
    return [Candle(timestamp=t0 + timedelta(minutes=5 * i),
                   open=prix, high=prix * 1.002, low=prix * 0.998,
                   close=prix, volume=100.0) for i in range(n)]


def test_la_regle_n_est_PAS_cablee_dans_le_detecteur():
    """⛔ ET C'EST DELIBERE. Verifie le 2026-10-03 : cabler cette regle dans
    `calculate_trade_setup` casse les QUATRE controles du laboratoire —

        test_le_hasard_produit_QUAND_MEME_des_cellules
        test_un_edge_INJECTE_deplace_les_R_vers_le_haut
        test_le_controle_ALEATOIRE_n_ABSORBE_PAS_l_edge
        test_le_controle_suit_le_SENS_de_la_cellule

    Ce sont les controles POSITIF et NEGATIF du laboratoire lui-meme : ceux qui
    prouvent qu'il sait dire oui quand il faut et non quand il faut. Sans eux,
    << 0 retenu sur 4 580 cellules >> devient indiscernable d'un laboratoire
    qui ne mesure RIEN.

    🔑 La cause est structurelle : un stop UNIFORME donne a toutes les cellules
    le MEME risque. Le controle aleatoire, apparie au risque median, devient
    alors identique aux cellules qu'il doit departager — il absorbe l'edge, et
    plus aucun ecart ne peut ressortir. Mesure a l'appui : le controle atteint
    +1,599 contre +1,572 pour la meilleure cellule, et une autre serie ne
    produit PLUS AUCUNE cellule peuplee.

    ⚠️ Et la largeur du stop a DEJA ete eprouvee : banc du 2026-09-30, k de 0,5
    a 3 predit d'avance, cout divise par 2,9, R negatif PARTOUT. Changer la
    largeur a ete mesure comme n'aidant pas.

    La fonction reste donc posee, testee et documentee, mais INERTE. L'armer
    demande de reconstruire d'abord les controles du laboratoire pour un monde
    a risque uniforme : c'est un chantier, pas un reglage.
    """
    import inspect
    src = inspect.getsource(pd.calculate_trade_setup)
    assert "distance_sl_pourcentage" not in src, (
        "la regle vient d'etre cablee : relancer "
        "test_laboratoire_controles.py AVANT de considerer que c'est bon")


def test_l_OR_garde_sa_regle_en_euros(monkeypatch):
    """⛔ Decision explicite de Xavier du 2026-10-02 : je ne la revoque pas en
    silence. Et les deux regles sont a 10 % l'une de l'autre."""
    monkeypatch.setattr(pd, "XAU_SL_FIXE_EUR", 10.0)
    monkeypatch.setattr(pd, "_eur_usd_courant", lambda: 1.1257)
    euros = pd._distance_sl_or()
    pct = pd.distance_sl_pourcentage(4139.72)
    assert euros == pytest.approx(11.257, rel=1e-3)
    assert pct == pytest.approx(12.419, rel=1e-3)
    ecart = abs(euros - pct) / pct
    assert ecart < 0.12, f"les deux regles doivent etre proches, ecart {ecart:.1%}"


def test_si_le_taux_or_est_illisible_le_POURCENTAGE_prend_le_relais(monkeypatch):
    """⚠️ Avant, un taux illisible faisait retomber l'or sur l'ATR. Desormais
    il y a un echelon intermediaire, et c'est mieux : une regle connue."""
    monkeypatch.setattr(pd, "_eur_usd_courant", lambda: None)
    assert pd._distance_sl_or() is None
    assert pd.distance_sl_pourcentage(4139.72) == pytest.approx(12.419,
                                                               rel=1e-3)
