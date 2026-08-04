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
