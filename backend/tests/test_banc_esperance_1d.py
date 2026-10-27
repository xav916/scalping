"""Le moteur et les branches du banc d'esperance 1d.

⛔ CE QUI EST EN JEU. Le banc rejoue 272 400 simulations, ce qui interdit
d'appeler `simulate_trade_forward` a chaque fois : la recherche du premier
franchissement est donc vectorisee. Une divergence, meme sur la regle « SL et
TP dans la MEME bougie », deplacerait silencieusement l'esperance -- et c'est
exactement le genre de detail qui decide sur un stop large.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.models.schemas import Candle, TradeDirection
from backend.services.backtest_engine import simulate_trade_forward
from scripts import banc_esperance_1d as banc

T0 = datetime(2026, 8, 20, tzinfo=timezone.utc)


def _bougies(specs: list[tuple[float, float, float]]) -> list[Candle]:
    """`(high, low, close)` par bougie de 5 min, a partir de T0."""
    return [Candle(timestamp=T0 + timedelta(minutes=5 * (i + 1)),
                   open=(h + b) / 2, high=h, low=b, close=cl, volume=0)
            for i, (h, b, cl) in enumerate(specs)]


class _Stub:
    def __init__(self, achat, entry, sl, tp, pair="EUR/USD"):
        self.pair = pair
        self.direction = TradeDirection.BUY if achat else TradeDirection.SELL
        self.entry_price = entry
        self.stop_loss = sl
        self.take_profit_1 = tp


def _les_deux(bougies, achat, entry, sl, tp, heures=240):
    """Rend (issue_production, issue_vectorisee) pour comparaison."""
    prod = simulate_trade_forward(_Stub(achat, entry, sl, tp), bougies, T0,
                                  timeout_hours=heures)
    s = banc.Serie(bougies)
    vect = s.simule(s.index_apres(T0.timestamp()),
                    T0.timestamp() + heures * 3600, achat, sl, tp)
    return prod[0], (vect[0] if vect else None)


# ─── Le moteur vectorise contre la production ───────────────────────────────


def test_un_TP_touche_donne_TP1_dans_les_deux_moteurs():
    b = _bougies([(100.5, 99.5, 100.0), (102.0, 99.8, 101.5)])
    prod, vect = _les_deux(b, True, 100.0, 95.0, 101.0)
    assert prod == vect == "TP1", (prod, vect)


def test_un_SL_touche_donne_SL_dans_les_deux_moteurs():
    b = _bougies([(100.5, 99.5, 100.0), (100.2, 94.0, 94.5)])
    prod, vect = _les_deux(b, True, 100.0, 95.0, 110.0)
    assert prod == vect == "SL", (prod, vect)


def test_LA_REGLE_QUI_COMPTE_le_SL_gagne_dans_la_MEME_bougie():
    """⛔ Une bougie qui touche les DEUX bornes : la production prend le SL
    (pire cas). Un moteur qui prendrait le TP surestimerait l'esperance."""
    b = _bougies([(111.0, 94.0, 100.0)])
    prod, vect = _les_deux(b, True, 100.0, 95.0, 110.0)
    assert prod == "SL", prod
    assert vect == "SL", "le moteur vectorise doit AUSSI prendre le pire cas"


def test_la_meme_regle_a_la_VENTE():
    b = _bougies([(106.0, 89.0, 100.0)])
    prod, vect = _les_deux(b, False, 100.0, 105.0, 90.0)
    assert prod == vect == "SL", (prod, vect)


def test_aucune_borne_touchee_donne_TIMEOUT_dans_les_deux():
    b = _bougies([(100.5, 99.5, 100.0)] * 5)
    prod, vect = _les_deux(b, True, 100.0, 90.0, 110.0)
    assert prod == vect == "TIMEOUT", (prod, vect)


def test_une_bougie_HORS_FENETRE_est_ignoree_par_les_deux():
    """La borne est franchie APRES l'echeance : ce n'est pas un hit."""
    b = [Candle(timestamp=T0 + timedelta(hours=250), open=100, high=120,
                low=99, close=119, volume=0)]
    prod, vect = _les_deux(b, True, 100.0, 95.0, 110.0, heures=240)
    assert prod == "TIMEOUT"
    assert vect is None or vect == "TIMEOUT", vect


def test_une_bougie_AVANT_l_entree_ne_compte_pas():
    avant = Candle(timestamp=T0 - timedelta(minutes=5), open=100, high=120,
                   low=99, close=119, volume=0)
    b = [avant] + _bougies([(100.5, 99.5, 100.0)])
    prod, vect = _les_deux(b, True, 100.0, 95.0, 110.0)
    assert prod == vect == "TIMEOUT", (prod, vect)


def test_le_TP_avant_le_SL_donne_bien_TP1():
    b = _bougies([(111.0, 99.0, 110.5), (100.0, 94.0, 94.5)])
    prod, vect = _les_deux(b, True, 100.0, 95.0, 110.0)
    assert prod == vect == "TP1", (prod, vect)


# ─── Les statistiques ───────────────────────────────────────────────────────


def test_l_esperance_est_la_moyenne_des_R():
    # pnl 1,8 % sur un risque de 1 % => +1,8 R ; -1 % => -1 R
    assert banc.esperance_R([(1.8, 1.0), (-1.0, 1.0)]) == pytest.approx(0.4)


def test_un_risque_NUL_est_ecarte_et_ne_divise_pas():
    assert banc.esperance_R([(1.8, 0.0)]) is None
    assert banc.esperance_R([(1.8, 1.0), (5.0, 0.0)]) == pytest.approx(1.8)


def test_une_population_vide_rend_None():
    assert banc.esperance_R([]) is None


def test_le_t_contre_placebo_a_la_bonne_echelle():
    tirages = [0.0, 0.0, 0.1, -0.1]  # moyenne 0, ecart-type connu
    import statistics
    attendu = (0.5 - 0.0) / statistics.stdev(tirages)
    assert banc.t_contre_placebo(0.5, tirages) == pytest.approx(attendu)


def test_moins_de_DEUX_tirages_rend_None_et_pas_zero():
    """⛔ Rendre 0,0 ferait passer une absence de reference pour une egalite."""
    assert banc.t_contre_placebo(0.5, []) is None
    assert banc.t_contre_placebo(0.5, [0.1]) is None


def test_une_dispersion_NULLE_rend_None():
    assert banc.t_contre_placebo(0.5, [0.2, 0.2, 0.2]) is None


def test_la_part_de_tirages_battus():
    assert banc.part_battus_pct(0.5, [0.1, 0.2, 0.9, 1.0]) == pytest.approx(50.0)
    assert banc.part_battus_pct(0.5, []) is None


# ─── Les branches : c'est elles qui publient ────────────────────────────────


def test_la_VALIDITE_passe_avant_tout():
    assert banc.branche(1.0, 0.0, 9.0, 100.0, 0.002, valide=False) \
        == "NON_CONCLUANT_VALIDITE"


def test_reel_et_placebo_INDISCERNABLES_rendent_INDECIDABLE():
    assert banc.branche(-0.001, -0.005, 0.3, 50.0, 0.002, valide=True) \
        == "INDECIDABLE_REEL_ET_PLACEBO_INDISCERNABLES"


def test_l_ADMISSION_exige_les_TROIS_conditions():
    assert banc.branche(0.30, 0.00, 3.0, 99.0, 0.002, valide=True) \
        == "ADMISSION_information_a_l_entree"
    # t insuffisant
    assert banc.branche(0.30, 0.00, 1.0, 99.0, 0.002, valide=True) \
        != "ADMISSION_information_a_l_entree"
    # tirages battus insuffisants
    assert banc.branche(0.30, 0.00, 3.0, 80.0, 0.002, valide=True) \
        != "ADMISSION_information_a_l_entree"
    # sous le cout
    assert banc.branche(0.001, 0.00, 3.0, 99.0, 0.002, valide=True) \
        != "ADMISSION_information_a_l_entree"


def test_le_REJET_exige_une_esperance_NEGATIVE_et_un_t_faible():
    assert banc.branche(-0.20, 0.00, -1.0, 10.0, 0.002, valide=True) \
        == "REJET_horizon_1d_ECARTE"


def test_une_esperance_positive_SANS_le_t_n_est_ni_l_un_ni_l_autre():
    """⛔ Le piege : publier une admission sur le seul signe de l'esperance."""
    assert banc.branche(0.30, 0.00, 1.0, 60.0, 0.002, valide=True) \
        == "NON_CONCLUANT_BRANCHES_EN_DESACCORD"


# ─── Les seuils viennent du fichier PRE-INSCRIT ─────────────────────────────


def test_les_seuils_du_banc_sont_ceux_de_la_PRE_INSCRIPTION():
    """⛔ Un banc qui recopie ses seuils peut deriver du critere engage sans
    que rien ne le signale."""
    import pathlib
    import re
    import sys
    sys.path.insert(0, ".claude/skills")
    from or_commun import sections

    md = pathlib.Path(
        "docs/preinscriptions/2026-10-27-esperance-1d.md"
    ).read_text(encoding="utf-8")
    bloc = sections.bloc_machine(md)
    assert bloc, "bloc machine introuvable"

    assert int(bloc["tirages_placebo"]) == banc.TIRAGES_PLACEBO
    assert bloc["convention"] == "A"
    assert int(bloc["cellules"]) == 1
    assert float(bloc["P2_esperance_R_placebo_abs_max"]) == banc.P2_PLACEBO_ABS_MAX
    assert float(bloc["P4_esperance_R_timeout_abs_max"]) == banc.P4_TIMEOUT_ABS_MAX
    assert float(bloc["P5_ecart_esperance_B_moins_A_max"]) == banc.P5_ECART_B_MOINS_A_MAX
    assert float(bloc["P3_tirages_battus_pct_attendu_max"]) == banc.ADMISSION_BATTUS_PCT

    for attendu in (str(banc.VALIDITE_N_MIN), "99", str(banc.VALIDITE_TIRAGES_MIN)):
        assert attendu in bloc["validite"], (attendu, bloc["validite"])
    assert "2.00" in bloc["admission"] and "95.0" in bloc["admission"]
    assert "0.01" in bloc["indecidable"]
    assert str(banc.INDECIDABLE_ECART_R) in bloc["indecidable"]
