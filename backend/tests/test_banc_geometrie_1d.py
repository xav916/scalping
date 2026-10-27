"""Les fonctions pures du banc 1d : c'est la qu'une erreur retourne le verdict.

Un banc se trompe en silence : il rend un chiffre, et le chiffre a l'air d'un
resultat. Les quatre fonctions testees ici decident l'issue publiee -- la
branche, le z, les deux conventions, la conformite du R:R.
"""
from __future__ import annotations

import math

import pytest

from scripts import banc_geometrie_1d as banc


# ─── rapport_rr et rr_conforme ──────────────────────────────────────────────


def test_le_rapport_rr_est_celui_de_la_formule():
    # entry 100, SL 90 => risque 10 ; TP a 1,8 R => 118
    assert banc.rapport_rr(100.0, 90.0, 118.0) == pytest.approx(1.8)


def test_le_rapport_rr_vaut_pour_les_VENTES_aussi():
    """Le signe ne doit pas changer le rapport : on prend des valeurs absolues."""
    assert banc.rapport_rr(100.0, 110.0, 82.0) == pytest.approx(1.8)


def test_un_risque_NUL_rend_None_et_pas_une_division():
    assert banc.rapport_rr(100.0, 100.0, 118.0) is None


def test_la_tolerance_du_RR_est_bien_celle_pre_inscrite():
    assert banc.rr_conforme(1.80) is True
    assert banc.rr_conforme(1.84) is True
    assert banc.rr_conforme(1.76) is True
    assert banc.rr_conforme(1.86) is False, "0,06 depasse la tolerance de 0,05"
    assert banc.rr_conforme(None) is False


# ─── z_binomial ─────────────────────────────────────────────────────────────


def test_le_z_vaut_zero_quand_la_proportion_EGALE_le_seuil():
    z = banc.z_binomial(357, 1000, 0.357)
    assert z == pytest.approx(0.0, abs=1e-9)


def test_le_z_est_NEGATIF_sous_le_seuil_et_POSITIF_au_dessus():
    assert banc.z_binomial(300, 1000, 0.357) < 0
    assert banc.z_binomial(400, 1000, 0.357) > 0


def test_le_z_a_la_bonne_echelle():
    """Verification a la main : p=0,30 contre p0=0,357 sur n=1000."""
    attendu = (0.300 - 0.357) / math.sqrt(0.357 * 0.643 / 1000)
    assert banc.z_binomial(300, 1000, 0.357) == pytest.approx(attendu)


def test_un_echantillon_VIDE_rend_None_et_PAS_zero():
    """⛔ Rendre 0,0 ferait passer un echantillon vide pour « conforme au
    seuil ». Ne pas savoir n'est pas etre a la barre."""
    assert banc.z_binomial(0, 0, 0.357) is None


# ─── les deux conventions de TIMEOUT ────────────────────────────────────────


def test_la_convention_B_EXCLUT_les_timeout():
    issues = ["TP1", "TP1", "SL", "SL", "SL", "TIMEOUT", "TIMEOUT"]
    succes, n = banc.reussite_convention_B(issues)
    assert (succes, n) == (2, 5), "les TIMEOUT ne doivent pas etre dans la population"


def test_la_convention_A_compte_un_TIMEOUT_GAGNANT_comme_succes():
    lignes = [("TP1", 1.0), ("SL", -1.0), ("TIMEOUT", 0.4), ("TIMEOUT", -0.4)]
    succes, n = banc.reussite_convention_A(lignes)
    assert (succes, n) == (2, 4)


def test_la_convention_A_ne_compte_PAS_un_timeout_a_pnl_inconnu():
    """`None` veut dire non mesure, pas gagnant."""
    lignes = [("TIMEOUT", None), ("TIMEOUT", None)]
    assert banc.reussite_convention_A(lignes) == (0, 2)


# ─── la branche : c'est elle qui publie ─────────────────────────────────────


def test_la_VALIDITE_passe_avant_tout_le_reste():
    """Rejeu invalide : le banc ne conclut RIEN, meme si le taux est net."""
    assert banc.branche(10.0, -9.0, 0.5, valide=False) \
        == "NON_CONCLUANT_VALIDITE"
    assert banc.branche(99.0, +9.0, 0.5, valide=False) \
        == "NON_CONCLUANT_VALIDITE"


def test_des_conventions_qui_DIVERGENT_rendent_INDECIDABLE():
    """Meme avec un taux tres sous le seuil : la reponse dependrait d'une
    convention de cloture arbitraire."""
    assert banc.branche(10.0, -9.0, 7.0, valide=True) \
        == "INDECIDABLE_CONVENTIONS"


def test_le_REJET_exige_le_taux_ET_le_z():
    assert banc.branche(30.0, -3.0, 1.0, valide=True) \
        == "REJET_horizon_1d_ECARTE"


def test_l_ADMISSION_exige_le_taux_ET_le_z():
    assert banc.branche(40.0, +2.0, 1.0, valide=True) \
        == "ADMISSION_horizon_1d_CONSERVE"


def test_un_DESACCORD_entre_taux_et_z_n_est_NI_admission_NI_rejet():
    """⛔ Le piege a eviter : choisir la branche qui arrange.

    Taux sous le seuil mais z au-dessus de -2 (echantillon trop petit pour
    trancher) : ce n'est pas un rejet. Et taux au-dessus avec z sous -2 est
    arithmetiquement impossible, mais le code ne doit pas s'y fier.
    """
    assert banc.branche(34.0, -1.0, 1.0, valide=True) \
        == "NON_CONCLUANT_TAUX_ET_Z_EN_DESACCORD"


def test_une_mesure_ABSENTE_ne_devient_pas_un_rejet():
    assert banc.branche(None, None, 1.0, valide=True) \
        == "NON_CONCLUANT_MESURE_ABSENTE"


# ─── les seuils du banc sont ceux du fichier pre-inscrit ────────────────────


def test_les_seuils_du_banc_sont_ceux_de_la_PRE_INSCRIPTION():
    """⛔ LE TEST QUI COMPTE LE PLUS. Un banc qui recopie ses seuils peut
    deriver du fichier pre-inscrit sans que rien ne le signale -- et le verdict
    serait alors rendu contre un critere que personne n'a engage.
    """
    import pathlib
    import sys
    sys.path.insert(0, ".claude/skills")
    from or_commun import sections

    md = pathlib.Path(
        "docs/preinscriptions/2026-10-26-geometrie-1d.md"
    ).read_text(encoding="utf-8")
    bloc = sections.bloc_machine(md)
    assert bloc, "bloc machine introuvable dans la pre-inscription"

    assert float(bloc["RR_attendu"]) == banc.RR_ATTENDU
    assert float(bloc["RR_tolerance"]) == banc.RR_TOLERANCE
    assert float(bloc["reussite_requise_pct"]) == banc.REUSSITE_REQUISE_PCT
    assert float(bloc["P2_risk_pct_1d_median_min"]) == banc.P2_RISK_PCT_MIN
    assert float(bloc["P2_risk_pct_1d_median_max"]) == banc.P2_RISK_PCT_MAX
    assert float(bloc["P4_controle_4h_RR_conforme_pct_min"]) == banc.P4_RR_PCT_MIN
    # Le seuil de P5 vit DANS l'expression `indecidable`, pas dans une cle a
    # lui. On le lit la ou il est engage -- et surtout on NE REECRIT PAS la
    # pre-inscription commitee pour qu'elle corresponde au banc : ce serait
    # exactement la falsification que tout ce dispositif existe pour empecher.
    import re
    seuil_p5 = re.search(r"([-+]?\d+(?:\.\d+)?)\s*$", bloc["indecidable"])
    assert seuil_p5, bloc["indecidable"]
    assert float(seuil_p5.group(1)) == banc.INDECIDABLE_ECART_PT
    assert int(bloc["cellules"]) == 1
    assert bloc["placebo"] == "NON_EXECUTE"
    # les seuils enfouis dans les expressions d'admission / rejet / validite
    assert "35.71" in bloc["admission"] and "-2.00" in bloc["admission"]
    assert "35.71" in bloc["rejet"] and "-2.00" in bloc["rejet"]
    assert "300" in bloc["validite"] and "99" in bloc["validite"]
    assert str(banc.Z_SEUIL) in bloc["rejet"]
    assert str(banc.VALIDITE_N_MIN) in bloc["validite"]
