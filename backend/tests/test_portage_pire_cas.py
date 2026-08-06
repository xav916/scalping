"""Coût de portage : repli sur le pire cas plutôt que refus perpétuel.

Constaté le 2026-08-06 : la porte de coût exigeait une durée de détention
médiane, mesurable seulement à partir de **30 setups résolus depuis le
2026-08-05**. Or les systèmes crypto journaliers en avaient **zéro** et en
produisent au plus un par jour, chacun mettant des jours à se résoudre. La
route Kraken restait donc fermée à l'argent réel pendant un à deux mois — un
« incalculable donc refus » devenu blocage à vie.

La borne supérieure suffit à trancher : la détention ne peut pas dépasser le
délai de sortie, donc l'estimer par ce délai **majore** le portage réel.
Surestimer un coût ne peut que refuser un trade marginal, jamais en laisser
passer un mauvais.

⚠️ C'est fail-SAFE, pas permissif. Le test qui compte est celui qui vérifie
qu'un repli TROP COURT — donc sous-estimant les frais — serait un défaut.
"""
import pytest

from backend.services import mt5_bridge as mb
from backend.services.cost_model import cost_in_r, holding_cost_in_r, exceeds_edge


TAUX_BTC = 1.1447171830793396e-05   # mesuré le 2026-08-06, par heure
TAUX_ETH = 6.390407531947004e-06
EDGE = 0.11                          # expected_edge_r de la destination Kraken
PLAFOND = 0.30


class _Modele:
    proportional_rate_per_leg = 0.0005
    fixed_per_order = 0.0
    min_per_order = 0.0
    funding_interval_hours = 1.0


def _cout_total(sl_pct, taux, heures, entry=64000.0):
    sl = entry * (1 - sl_pct / 100)
    base = cost_in_r(entry=entry, stop_loss=sl, model=_Modele(), risk_money=None)
    portage = holding_cost_in_r(
        entry=entry, stop_loss=sl, rate_per_interval=taux,
        interval_hours=1.0, holding_hours=heures,
    )
    return base + portage


# ── Le repli lui-même ─────────────────────────────────────────────────

def test_le_repli_existe_et_vaut_le_delai_de_sortie():
    assert mb._duree_detention_pire_cas() == pytest.approx(96.0)


def test_le_repli_peut_etre_desactive(monkeypatch):
    """Mettre 0 restaure l'ancien comportement : portage incalculable, donc
    refus de tout argent réel sur les routes à funding."""
    import config.settings
    monkeypatch.setattr(config.settings, "HOLDING_WORST_CASE_HOURS", 0)
    assert mb._duree_detention_pire_cas() is None


# ── Le pire cas suffit à ouvrir la route ──────────────────────────────

@pytest.mark.parametrize("taux,nom", [(TAUX_BTC, "BTC"), (TAUX_ETH, "ETH")])
def test_un_setup_journalier_passe_meme_au_pire_cas(taux, nom):
    """7,69 % est la distance au stop MÉDIANE mesurée en journalier. À cette
    distance, même 96 h de portage laissent le coût sous le plafond."""
    total = _cout_total(7.69, taux, 96.0)
    assert not exceeds_edge(total, EDGE, auto_exec=True), (
        f"{nom} : {total:.4f} R = {100*total/EDGE:.1f} % de l'edge"
    )
    assert total / EDGE < PLAFOND


def test_un_stop_trop_serre_echoue_meme_avec_le_repli():
    """Le repli n'ouvre pas la porte à tout : un stop à 3 % reste refusé, car
    les frais y consomment plus de 30 % de l'edge."""
    total = _cout_total(3.0, TAUX_BTC, 96.0)
    assert exceeds_edge(total, EDGE, auto_exec=True)


# ── La propriété qui rend le repli SÛR ────────────────────────────────

def test_le_pire_cas_majore_toujours_la_mediane():
    """LA garantie du correctif : estimer par le délai de sortie ne peut que
    SURESTIMER le portage. Un trade accepté ici le serait a fortiori avec la
    vraie médiane — l'inverse serait un défaut de sécurité."""
    pire = _cout_total(7.69, TAUX_BTC, 96.0)
    for mediane in (1.0, 6.0, 24.0, 48.0, 95.9):
        assert _cout_total(7.69, TAUX_BTC, mediane) <= pire


def test_un_repli_trop_court_sous_estimerait_les_frais():
    """Garde-fou de configuration : un repli inférieur au délai de sortie
    laisserait passer des trades dont les frais dépassent le plafond une fois
    la position réellement tenue. Ce test documente pourquoi la valeur ne doit
    jamais être abaissée sous 96 h."""
    court = _cout_total(4.0, TAUX_BTC, 12.0)     # repli optimiste
    reel = _cout_total(4.0, TAUX_BTC, 96.0)      # détention réelle
    assert not exceeds_edge(court, EDGE, auto_exec=True), "passerait à tort"
    assert exceeds_edge(reel, EDGE, auto_exec=True), "alors qu'il coûte trop"
