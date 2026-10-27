"""L'extension PLACEBO de `or-verdict` : une seconde forme de validite.

Posee le 2026-10-27, apres avoir documente la limite le meme jour. Jusqu'ici
cette skill ne jugeait que les REJEUX : `ecart_par_trade` mesure la fidelite
d'un rejeu a la realite vecue, et un banc compare a un PLACEBO n'a pas cette
quantite.

⛔ LES TROIS CHOIX DE CONCEPTION, ET POURQUOI :

1. **La forme est DECLAREE, jamais devinee.** Inferer « placebo » de
   `ecart_par_trade is None` confondrait « il n'y a pas de rejeu » avec « le
   rejeu est casse ». Un banc placebo doit porter `forme: "placebo"`.

2. **Les clauses sont RECALCULEES, le drapeau du banc ne suffit pas.** C'est
   la raison d'etre de la skill : un banc qui s'auto-declare `valide: true`
   alors que ses propres nombres violent une clause doit etre REFUSE.

3. **Une clause illisible REFUSE**, elle n'est pas ignoree. Passer outre une
   clause non comprise reviendrait a publier sur un critere PARTIEL -- la
   faute exacte que ce dispositif empeche.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import verdict  # noqa: E402

# Le bloc machine du banc d'esperance 1d, tel que commite en `d3cd3fe`.
BLOC = {
    "validite": ("n_reel >= 1000 ET couverture_bougies_pct > 99 ET"
                 " abs(risk_pct_median_placebo - risk_pct_median_reel) < 1.0"
                 " ET tirages_aboutis >= 190"),
    "admission": ("esperance_R_reel > cout_R_median ET t_contre_placebo > 2.00"
                  " ET tirages_battus_pct >= 95.0"),
    "rejet": "esperance_R_reel <= 0 ET t_contre_placebo < 2.00",
}


def _resultat(**surcharges):
    """Le resultat reel du banc du 27/10, surchargeable."""
    base = {
        "forme": "placebo",
        "n": 1362,
        "t": -4.2262,
        "valide": True,
        "n_reel": 1362,
        "couverture_bougies_pct": 100.0,
        "risk_pct_median_placebo": 9.326,
        "risk_pct_median_reel": 9.326,
        "tirages_aboutis": 200,
        "esperance_R_reel": -0.0641,
        "esperance_R_placebo": 0.0413,
        "cout_R_median": 0.0021,
        "t_contre_placebo": -4.2262,
        "tirages_battus_pct": 0.0,
    }
    base.update(surcharges)
    return base


# ─── La forme est declaree, pas devinee ─────────────────────────────────────


def test_un_banc_PLACEBO_n_exige_PLUS_ecart_par_trade():
    """Le refus documente le 27/10 ne doit plus tomber sur cette forme."""
    decision, raisons = verdict.juger(_resultat(), BLOC, critere_intact=True)

    assert "ecart_par_trade" not in " ".join(raisons), raisons


def test_un_banc_SANS_forme_reste_juge_comme_un_REJEU():
    """⛔ Compatibilite : l'absence de `forme` ne doit RIEN changer."""
    r = {"n": 100, "t": 3.0, "ecart_par_trade": 0.1, "valide": True}
    bloc = {"validite": "abs(ecart) < 0.50", "admission": "t > +2",
            "rejet": "t < -2"}

    decision, _ = verdict.juger(r, bloc, critere_intact=True)

    assert decision == verdict.PUBLIABLE


def test_une_forme_INCONNUE_est_REFUSEE_et_pas_prise_pour_un_rejeu():
    """Se tromper doit rendre BAVARD, jamais silencieusement permissif."""
    decision, raisons = verdict.juger(
        _resultat(forme="monte_carlo"), BLOC, critere_intact=True)

    assert decision == verdict.REFUS
    assert any("monte_carlo" in x for x in raisons), raisons


def test_un_ecart_par_trade_NUL_ne_suffit_PAS_a_declarer_un_placebo():
    """⛔ Deviner la forme confondrait « pas de rejeu » et « rejeu casse »."""
    r = {"n": 100, "t": 3.0, "ecart_par_trade": None, "valide": True}

    decision, raisons = verdict.juger(r, BLOC, critere_intact=True)

    assert decision == verdict.REFUS
    assert any("ecart_par_trade" in x for x in raisons), raisons


# ─── Les clauses sont RECALCULEES ───────────────────────────────────────────


def test_le_cas_REEL_du_27_10_rend_le_meme_verdict_que_le_banc():
    """`t = -4,2262`, esperance negative : REJET, et donc publiable."""
    decision, raisons = verdict.juger(_resultat(), BLOC, critere_intact=True)

    assert decision == verdict.PUBLIABLE, raisons


def test_une_clause_de_VALIDITE_violee_REFUSE_en_la_NOMMANT():
    decision, raisons = verdict.juger(
        _resultat(tirages_aboutis=150), BLOC, critere_intact=True)

    assert decision == verdict.REFUS
    joint = " ".join(raisons)
    assert "tirages_aboutis" in joint, raisons
    assert "150" in joint, raisons


def test_la_clause_d_ECART_APPARIE_est_evaluee():
    """`abs(a - b) < 1.0` : la structure du placebo doit coller au reel."""
    decision, raisons = verdict.juger(
        _resultat(risk_pct_median_placebo=14.0), BLOC, critere_intact=True)

    assert decision == verdict.REFUS
    assert any("risk_pct_median_placebo" in x for x in raisons), raisons


def test_un_banc_qui_s_AUTO_DECLARE_valide_a_tort_est_REFUSE():
    """⛔ LE CŒUR DE LA SKILL. On recalcule, on ne croit pas le drapeau."""
    decision, raisons = verdict.juger(
        _resultat(valide=True, couverture_bougies_pct=42.0),
        BLOC, critere_intact=True)

    assert decision == verdict.REFUS
    assert any("couverture_bougies_pct" in x for x in raisons), raisons


def test_un_banc_qui_se_declare_INVALIDE_est_refuse_meme_si_les_nombres_passent():
    decision, raisons = verdict.juger(
        _resultat(valide=False), BLOC, critere_intact=True)

    assert decision == verdict.REFUS


# ─── Admission et rejet sont evalues EN ENTIER ──────────────────────────────


def test_l_ADMISSION_exige_TOUTES_ses_clauses():
    """⛔ Le defaut a eviter : publier ADMISSION sur le seul `t`.

    `t_contre_placebo > 2` passe, mais `tirages_battus_pct >= 95` echoue et
    l'esperance reste sous le cout. Un seuil extrait au premier nombre aurait
    donne un feu vert sur un critere PARTIEL.
    """
    decision, raisons = verdict.juger(
        _resultat(t=3.0, t_contre_placebo=3.0, esperance_R_reel=0.30,
                  tirages_battus_pct=60.0),
        BLOC, critere_intact=True)

    assert decision == verdict.REFUS
    assert any("tirages_battus_pct" in x for x in raisons), raisons


def test_une_ADMISSION_complete_est_PUBLIABLE():
    decision, raisons = verdict.juger(
        _resultat(t=3.0, t_contre_placebo=3.0, esperance_R_reel=0.30,
                  tirages_battus_pct=99.0),
        BLOC, critere_intact=True)

    assert decision == verdict.PUBLIABLE, raisons


def test_ni_admission_ni_rejet_est_REFUSE_et_le_DIT():
    """Un entre-deux n'est pas un verdict."""
    decision, raisons = verdict.juger(
        _resultat(t=0.5, t_contre_placebo=0.5, esperance_R_reel=0.30,
                  tirages_battus_pct=60.0),
        BLOC, critere_intact=True)

    assert decision == verdict.REFUS


# ─── Fail-closed sur ce qui n'est pas comprehensible ────────────────────────


def test_une_clause_ILLISIBLE_refuse_au_lieu_d_etre_IGNOREE():
    """⛔ Ignorer une clause non comprise = publier sur un critere PARTIEL."""
    bloc = dict(BLOC, validite="n_reel >= 1000 ET le placebo est credible")

    decision, raisons = verdict.juger(_resultat(), bloc, critere_intact=True)

    assert decision == verdict.REFUS
    assert any("credible" in x or "illisible" in x.lower()
               or "indechiffrable" in x.lower() for x in raisons), raisons


def test_un_champ_CITE_mais_ABSENT_du_resultat_refuse():
    bloc = dict(BLOC, validite="n_reel >= 1000 ET jamais_emis > 5")

    decision, raisons = verdict.juger(_resultat(), bloc, critere_intact=True)

    assert decision == verdict.REFUS
    assert any("jamais_emis" in x for x in raisons), raisons


def test_un_champ_cite_NON_NUMERIQUE_refuse():
    bloc = dict(BLOC, validite="n_reel >= 1000 ET forme > 5")

    decision, raisons = verdict.juger(_resultat(), bloc, critere_intact=True)

    assert decision == verdict.REFUS
    assert any("forme" in x for x in raisons), raisons


def test_les_champs_de_base_restent_exiges_sur_la_forme_placebo():
    """`n`, `t` et `valide` restent necessaires -- seul `ecart_par_trade` sort."""
    r = _resultat()
    del r["t"]

    decision, raisons = verdict.juger(r, BLOC, critere_intact=True)

    assert decision == verdict.REFUS
    assert any("[t]" in x for x in raisons), raisons


def test_une_clause_abs_a_UN_SEUL_CHAMP_est_lisible():
    """⛔ LACUNE TROUVEE LE 2026-10-27, et le contexte de sa correction importe.

    `abs(t_contre_placebo) < 2.00` etait declare ILLISIBLE : seul `abs(a - b)`
    etait reconnu. Deux verdicts ont ete refuses sur cette FORME, pas sur leur
    substance.

    🔑 J'ai refuse de corriger quand le resultat concerne etait douteux -- et le
    corriger seulement quand un resultat m'arrange serait PIRE. La correction
    est donc appliquee aux DEUX, et elle ne change aucun chiffre : elle laisse
    seulement le juge lire une forme qu'il aurait toujours du lire.
    """
    d = verdict.evaluer_clauses("abs(t_contre_placebo) < 2.00",
                                {"t_contre_placebo": -0.98})
    assert d == (True, []), d

    d = verdict.evaluer_clauses("abs(t_contre_placebo) < 2.00",
                                {"t_contre_placebo": 4.32})
    assert d[0] is False, d
    assert any("t_contre_placebo" in x for x in d[1]), d

    # la forme a DEUX champs continue de marcher
    d = verdict.evaluer_clauses("abs(a - b) < 1.0", {"a": 5.0, "b": 5.5})
    assert d == (True, []), d
