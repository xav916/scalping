"""Coût de portage — le prix de la détention (2026-08-05).

Le scalping ne payait pas ce coût : une position ouverte et fermée dans la
même heure ne traverse aucune échéance de funding. À 4h et 1d, si.
"""
import sqlite3

import pytest

from backend.services.cost_model import (
    CostModel, holding_cost_in_r, median_holding_hours,
)


def test_le_portage_est_proportionnel_a_la_duree():
    # entry/distance = 2000/10 = 200. rate 0,0001 par heure, 24 heures.
    # 200 * 0,0001 * 24 = 0,48 R
    r = holding_cost_in_r(entry=2000.0, stop_loss=1990.0,
                          rate_per_interval=0.0001, interval_hours=1.0,
                          holding_hours=24.0)
    assert r == pytest.approx(0.48)


def test_doubler_la_duree_double_le_cout():
    a = holding_cost_in_r(2000.0, 1990.0, 0.0001, 1.0, 12.0)
    b = holding_cost_in_r(2000.0, 1990.0, 0.0001, 1.0, 24.0)
    assert b == pytest.approx(2 * a)


def test_le_portage_ne_depend_pas_de_la_taille_de_position():
    # Meme propriete que le cout proportionnel du plan 1 : le risque se
    # simplifie. C'est la raison mathematique pour laquelle plus de capital
    # ne sauvera pas une route dont le portage est trop cher.
    serre = holding_cost_in_r(2000.0, 1998.0, 0.0001, 1.0, 24.0)
    large = holding_cost_in_r(2000.0, 1990.0, 0.0001, 1.0, 24.0)
    # Un stop 5x plus serre coute 5x plus cher en R, a duree egale.
    assert serre == pytest.approx(5 * large)


def test_un_funding_negatif_ne_devient_jamais_un_credit():
    # Un funding negatif rapporte au long. Le compter comme un gain
    # financerait une position sur une recette qui peut s'inverser d'une
    # heure a l'autre. Plancher a zero : on ne facture pas, on ne credite pas.
    r = holding_cost_in_r(2000.0, 1990.0, -0.0005, 1.0, 24.0)
    assert r == 0.0


def test_duree_inconnue_rend_none_jamais_zero():
    assert holding_cost_in_r(2000.0, 1990.0, 0.0001, 1.0, None) is None


def test_taux_inconnu_rend_none_jamais_zero():
    assert holding_cost_in_r(2000.0, 1990.0, None, 1.0, 24.0) is None


def test_entree_ou_stop_invalides_rendent_none():
    assert holding_cost_in_r(0.0, 1990.0, 0.0001, 1.0, 24.0) is None
    assert holding_cost_in_r(2000.0, 2000.0, 0.0001, 1.0, 24.0) is None


def test_intervalle_nul_rend_none():
    # Une route sans echeance de funding ne se modelise pas en divisant par zero.
    assert holding_cost_in_r(2000.0, 1990.0, 0.0001, 0.0, 24.0) is None


def test_le_modele_de_cout_declare_son_intervalle_de_funding():
    assert CostModel().funding_interval_hours == 0.0
    assert CostModel(funding_interval_hours=1.0).funding_interval_hours == 1.0


def _base(tmp_path, lignes):
    db = tmp_path / "t.db"
    with sqlite3.connect(db) as c:
        c.execute("""CREATE TABLE shadow_setups (
            id INTEGER PRIMARY KEY, system_id TEXT, bar_timestamp TIMESTAMP,
            detected_at TIMESTAMP, outcome TEXT, exit_at TIMESTAMP)""")
        c.executemany(
            "INSERT INTO shadow_setups (system_id, bar_timestamp, detected_at,"
            " outcome, exit_at) VALUES (?,?,?,?,?)", lignes)
    return db


def test_median_holding_hours_rend_none_sous_l_echantillon_minimum(tmp_path):
    # Deux trades ne mesurent rien. Rendre leur mediane serait inventer.
    lignes = [("S", "2026-08-05T00:00:00+00:00", "2026-08-05T00:00:00+00:00",
               "TP1", "2026-08-05T06:00:00+00:00")] * 2
    db = _base(tmp_path, lignes)
    assert median_holding_hours("S", min_sample=30, db_path=db) is None


def test_median_holding_hours_mesure_quand_l_echantillon_suffit(tmp_path):
    lignes = [("S", "2026-08-05T00:00:00+00:00", "2026-08-05T00:00:00+00:00",
               "TP1", "2026-08-05T06:00:00+00:00")] * 30
    db = _base(tmp_path, lignes)
    assert median_holding_hours("S", min_sample=30, db_path=db) == pytest.approx(6.0)


def test_median_holding_hours_ignore_l_historique_corrompu(tmp_path):
    # Tout le shadow anterieur au 2026-08-05 est a ecarter : la deduplication
    # comptait un meme setup jusqu'a 960 fois. L'inclure biaiserait la mediane
    # vers le comportement d'une poignee de setups sur-representes.
    vieux = [("S", "2026-07-01T00:00:00+00:00", "2026-07-01T00:00:00+00:00",
              "TP1", "2026-07-01T01:00:00+00:00")] * 100
    recent = [("S", "2026-08-05T00:00:00+00:00", "2026-08-05T00:00:00+00:00",
               "TP1", "2026-08-05T06:00:00+00:00")] * 30
    db = _base(tmp_path, vieux + recent)
    assert median_holding_hours("S", min_sample=30, db_path=db) == pytest.approx(6.0)


def test_median_holding_hours_ignore_les_setups_non_resolus(tmp_path):
    lignes = [("S", "2026-08-05T00:00:00+00:00", "2026-08-05T00:00:00+00:00",
               "TP1", "2026-08-05T06:00:00+00:00")] * 30
    lignes += [("S", "2026-08-05T00:00:00+00:00", "2026-08-05T00:00:00+00:00",
                None, None)] * 50
    db = _base(tmp_path, lignes)
    assert median_holding_hours("S", min_sample=30, db_path=db) == pytest.approx(6.0)


def test_kraken_declare_son_intervalle_de_funding():
    from backend.services import bridge_destinations as bd

    k = bd._admin_kraken_destination()
    if k is not None:
        assert k.cost_model.funding_interval_hours == 1.0
