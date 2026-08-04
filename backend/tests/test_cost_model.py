"""Le modele de cout doit reproduire les mesures faites en production."""
from __future__ import annotations

import pytest


def test_le_cout_proportionnel_reproduit_la_mesure_kraken():
    """SL median 0,347 % du prix, 0,05 % de frais par jambe -> 0,288 R.

    Chiffre mesure le 2026-08-04 sur 876 trades reels.
    """
    from backend.services.cost_model import CostModel, cost_in_r

    kraken = CostModel(proportional_rate_per_leg=0.0005)
    entry = 1000.0
    stop_loss = 1000.0 * (1 - 0.00347)

    cout = cost_in_r(entry=entry, stop_loss=stop_loss, model=kraken)

    assert cout == pytest.approx(0.288, abs=0.002)


def test_le_cout_proportionnel_ne_depend_pas_de_la_taille():
    """Le risque se simplifie : c'est ce qui rend Kraken insauvable par le capital."""
    from backend.services.cost_model import CostModel, cost_in_r

    kraken = CostModel(proportional_rate_per_leg=0.0005)
    entry, stop_loss = 1000.0, 996.53

    petit = cost_in_r(entry=entry, stop_loss=stop_loss, model=kraken, risk_money=10.0)
    gros = cost_in_r(entry=entry, stop_loss=stop_loss, model=kraken, risk_money=10_000.0)

    assert petit == pytest.approx(gros)


def test_un_stop_nul_ne_produit_pas_une_division_par_zero():
    from backend.services.cost_model import CostModel, cost_in_r

    assert cost_in_r(entry=100.0, stop_loss=100.0,
                     model=CostModel(proportional_rate_per_leg=0.0005)) is None


def test_le_cout_fixe_decroit_quand_le_risque_grandit():
    """C'est ce qui rend IBKR debloquable par le capital, contrairement a Kraken."""
    from backend.services.cost_model import CostModel, cost_in_r

    ibkr = CostModel(fixed_per_order=1.0, min_per_order=1.0)

    petit = cost_in_r(entry=100.0, stop_loss=99.0, model=ibkr, risk_money=5.0)
    gros = cost_in_r(entry=100.0, stop_loss=99.0, model=ibkr, risk_money=50.0)

    assert petit == pytest.approx(0.4)   # 2 USD sur 5 de risque
    assert gros == pytest.approx(0.04)   # 2 USD sur 50 de risque
    assert gros < petit


def test_le_plancher_broker_l_emporte_sur_le_montant_par_ordre():
    from backend.services.cost_model import CostModel, cost_in_r

    modele = CostModel(fixed_per_order=0.20, min_per_order=1.0)
    cout = cost_in_r(entry=100.0, stop_loss=99.0, model=modele, risk_money=10.0)

    assert cout == pytest.approx(0.2)  # 2 × 1,0 sur 10 de risque


def test_un_cout_fixe_sans_risque_connu_vaut_inconnu():
    """Ne jamais retourner 0.0 : une route non mesurable n'est pas gratuite."""
    from backend.services.cost_model import CostModel, cost_in_r

    modele = CostModel(fixed_per_order=1.0)
    assert cost_in_r(entry=100.0, stop_loss=99.0, model=modele, risk_money=None) is None


def test_les_deux_composantes_s_additionnent():
    from backend.services.cost_model import CostModel, cost_in_r

    modele = CostModel(proportional_rate_per_leg=0.0005, fixed_per_order=1.0)
    cout = cost_in_r(entry=100.0, stop_loss=99.0, model=modele, risk_money=10.0)

    # proportionnel : (100/1) × 0,0005 × 2 = 0,1 R ; fixe : 2/10 = 0,2 R
    assert cout == pytest.approx(0.3)


def test_les_trois_verdicts_rendus_en_production_sont_reproduits():
    """MT5 accepté, Kraken refusé, xStocks refusée — mesures du 2026-08-04."""
    from backend.services.cost_model import exceeds_edge

    assert exceeds_edge(0.022, 0.129, auto_exec=True) is False   # MT5, 17 %
    assert exceeds_edge(0.288, 0.110, auto_exec=True) is True    # Kraken, 262 %
    assert exceeds_edge(0.199, 0.129, auto_exec=True) is True    # xStocks, 154 %


def test_le_seuil_est_bien_a_trente_pour_cent():
    from backend.services.cost_model import EDGE_COST_MAX_SHARE, exceeds_edge

    assert EDGE_COST_MAX_SHARE == 0.30
    assert exceeds_edge(0.0299, 0.10, auto_exec=True) is False
    assert exceeds_edge(0.0301, 0.10, auto_exec=True) is True


def test_un_edge_inconnu_bloque_l_argent_reel():
    """Une destination sans edge mesuré ne peut pas passer en AUTO_EXEC."""
    from backend.services.cost_model import exceeds_edge

    assert exceeds_edge(0.02, None, auto_exec=True) is True


def test_un_edge_inconnu_laisse_passer_l_observation():
    """En TELEGRAM aucun argent n'est engagé : la porte n'a rien à arbitrer."""
    from backend.services.cost_model import exceeds_edge

    assert exceeds_edge(0.02, None, auto_exec=False) is False


def test_un_cout_inconnu_bloque_l_argent_reel():
    from backend.services.cost_model import exceeds_edge

    assert exceeds_edge(None, 0.129, auto_exec=True) is True
    assert exceeds_edge(None, 0.129, auto_exec=False) is False


def test_un_edge_nul_ou_negatif_bloque():
    """Un edge mesuré à zéro n'est pas un edge inconnu : c'est une route morte."""
    from backend.services.cost_model import exceeds_edge

    assert exceeds_edge(0.001, 0.0, auto_exec=True) is True
    assert exceeds_edge(0.001, -0.05, auto_exec=True) is True
