"""La forme `seuil` : un banc SANS second bras, et qui le DIT dans sa sortie.

Posee le 2026-10-27. Le banc de la geometrie 1d compare un taux de reussite a
un seuil ARITHMETIQUE (35,71 % = 1/(1+1,8)) : il n'a ni rejeu, ni placebo, ni
aucun controle aleatoire.

⛔ POURQUOI UNE DECISION DISTINCTE, ET PAS `PUBLIABLE`. Un banc sans controle ne
peut pas dire s'il existe une information : il dit seulement si une geometrie
atteint son propre seuil. Lui rendre `PUBLIABLE` effacerait cette difference
dans la seule sortie que quelqu'un lit vraiment. `PUBLIABLE_SANS_CONTROLE`
la garde visible.

🔑 CE QUE CETTE FORME APPORTE MALGRE L'ABSENCE DE CONTROLE : la skill verifie
l'empreinte du critere ET relie, NOM PAR NOM, les champs que le critere engage
aux champs que le banc emet. Mesure du 27/10 sur le banc de la geometrie :
**cinq noms sur cinq divergeaient** (`z_binomial` contre `P3_z_binomial`, etc.)
et rien ne l'avait vu, parce que le banc evaluait ses branches en interne avec
des constantes recopiees.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import verdict  # noqa: E402

# Le bloc machine du banc de la geometrie 1d, tel que commite en `ecbe33c`.
BLOC = {
    "validite": ("n_resolus_1d >= 300 ET part_mfe_non_nul_pct > 99"
                 " ET part_rows_RR_conforme_pct > 95"),
    "admission": "reussite_1d_resolus_pct >= 35.71 ET z_binomial >= -2.00",
    "rejet": "reussite_1d_resolus_pct < 35.71 ET z_binomial < -2.00",
}


def _resultat(**surcharges):
    """Le resultat reel du banc du 26/10, sous les noms du CRITERE."""
    base = {
        "forme": "seuil",
        "n": 728,
        "t": -3.2463,
        "valide": True,
        "n_resolus_1d": 728,
        "part_mfe_non_nul_pct": 100.0,
        "part_rows_RR_conforme_pct": 100.0,
        "reussite_1d_resolus_pct": 29.945,
        "z_binomial": -3.2463,
    }
    base.update(surcharges)
    return base


# ─── La decision est DISTINCTE de PUBLIABLE ─────────────────────────────────


def test_un_banc_SEUIL_rend_PUBLIABLE_SANS_CONTROLE():
    decision, raisons = verdict.juger(_resultat(), BLOC, critere_intact=True)

    assert decision == verdict.PUBLIABLE_SANS_CONTROLE, (decision, raisons)
    assert decision != verdict.PUBLIABLE


def test_la_sortie_DIT_l_absence_de_controle():
    """🔑 La documentation ne suffit pas : ca doit etre dans la SORTIE."""
    _, raisons = verdict.juger(_resultat(), BLOC, critere_intact=True)

    joint = " ".join(raisons).lower()
    assert "controle" in joint, raisons
    assert "placebo" in joint or "hasard" in joint or "aleatoire" in joint, raisons


def test_le_code_de_sortie_de_la_CLI_vaut_ZERO(tmp_path, monkeypatch, capsys):
    """Publiable sans controle reste PUBLIABLE : le code doit valoir 0."""
    import json

    pre = tmp_path / "pre.md"
    pre.write_text("# critere\n", encoding="utf-8")
    res = tmp_path / "r.json"
    res.write_text(json.dumps(_resultat()), encoding="utf-8")
    monkeypatch.setattr(verdict.sections, "bloc_machine", lambda _t: BLOC)
    monkeypatch.setattr(verdict, "empreinte_critere", lambda _p: True)

    code = verdict.main([str(pre), str(res)])

    assert code == 0
    assert "SANS CONTROLE" in capsys.readouterr().out


# ─── Le lien NOM PAR NOM, qui est l'apport reel ─────────────────────────────


def test_un_nom_du_CRITERE_absent_du_resultat_REFUSE():
    """LE TEST CENTRAL : c'est le defaut trouve le 27/10 sur ce banc meme.

    Le critere engageait `z_binomial`, le banc emettait `P3_z_binomial`. Cinq
    noms sur cinq divergeaient, et rien ne le signalait.
    """
    r = _resultat()
    r["P3_z_binomial"] = r.pop("z_binomial")

    decision, raisons = verdict.juger(r, BLOC, critere_intact=True)

    assert decision == verdict.REFUS
    assert any("z_binomial" in x for x in raisons), raisons


def test_une_clause_de_validite_violee_REFUSE():
    decision, raisons = verdict.juger(
        _resultat(n_resolus_1d=120), BLOC, critere_intact=True)

    assert decision == verdict.REFUS
    assert any("n_resolus_1d" in x for x in raisons), raisons


def test_les_DEUX_branches_sont_evaluees_en_entier():
    """Admission tenue sur le taux mais pas sur le z : ni l'un ni l'autre."""
    decision, raisons = verdict.juger(
        _resultat(reussite_1d_resolus_pct=40.0, z_binomial=-3.0),
        BLOC, critere_intact=True)

    assert decision == verdict.REFUS


def test_une_ADMISSION_complete_rend_aussi_SANS_CONTROLE():
    """⛔ Meme favorable, un banc sans controle ne devient pas PUBLIABLE."""
    decision, raisons = verdict.juger(
        _resultat(reussite_1d_resolus_pct=40.0, z_binomial=1.0, t=1.0),
        BLOC, critere_intact=True)

    assert decision == verdict.PUBLIABLE_SANS_CONTROLE, (decision, raisons)


def test_un_banc_qui_s_auto_declare_valide_a_tort_est_REFUSE():
    decision, raisons = verdict.juger(
        _resultat(valide=True, part_mfe_non_nul_pct=50.0),
        BLOC, critere_intact=True)

    assert decision == verdict.REFUS
    assert any("part_mfe_non_nul_pct" in x for x in raisons), raisons


def test_l_empreinte_REECRITE_refuse_meme_sur_cette_forme():
    """L'absence de controle n'exonere pas de l'integrite du critere."""
    decision, raisons = verdict.juger(_resultat(), BLOC, critere_intact=False)

    assert decision == verdict.REFUS
    assert any("REECRIT" in x for x in raisons), raisons


# ─── Les trois formes coexistent ────────────────────────────────────────────


def test_les_trois_formes_sont_reconnues():
    assert set(verdict.FORMES) == {"rejeu", "placebo", "seuil"}


def test_une_forme_toujours_inconnue_reste_REFUSEE():
    decision, raisons = verdict.juger(
        _resultat(forme="bootstrap"), BLOC, critere_intact=True)

    assert decision == verdict.REFUS
    assert any("bootstrap" in x for x in raisons), raisons
