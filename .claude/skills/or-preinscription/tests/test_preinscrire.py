import pathlib
import sys

_ICI = pathlib.Path(__file__).resolve()
sys.path.insert(0, str(_ICI.parents[1]))
sys.path.insert(0, str(_ICI.parents[2]))
import preinscrire  # noqa: E402

COMPLETE = """# Une mesure

## Ce qu'on mesure

Deux bras apparies.

## ⛔ LE CRITÈRE, POSÉ AVANT DE REGARDER

- `B - A` positif avec `t > +2` ⇒ la regle COUTE, admission ;
- `t < -2` ⇒ elle gagne ;
- entre les deux ⇒ indecidable.

<!-- CRITERE-MACHINE
admission: t > +2
rejet: t < -2
validite: abs(ecart_par_trade) < 0.50
cellules: 5
plafond: permutation_p95
-->

## MES PRÉDICTIONS, posées avant de coder

1. la premiere
2. la deuxieme
3. la troisieme
"""


def test_une_preinscription_complete_ne_manque_de_rien():
    assert preinscrire.valider(COMPLETE, anteriorite=True) == []


# ── LES JUMEAUX NEGATIFS : chaque exigence doit pouvoir ECHOUER ──

def test_refuse_sans_section_critere():
    md = COMPLETE.replace("⛔ LE CRITÈRE, POSÉ AVANT DE REGARDER",
                          "Autre chose")
    manques = preinscrire.valider(md, anteriorite=True)
    assert any("critere" in m for m in manques), manques


def test_refuse_sans_bloc_machine():
    md = COMPLETE.split("<!-- CRITERE-MACHINE")[0] + COMPLETE.split("-->")[1]
    manques = preinscrire.valider(md, anteriorite=True)
    assert any("bloc machine" in m for m in manques), manques


def test_refuse_sans_condition_d_admission():
    md = COMPLETE.replace("admission: t > +2\n", "")
    manques = preinscrire.valider(md, anteriorite=True)
    assert any("admission" in m for m in manques), manques


def test_refuse_sans_plafond_quand_plusieurs_cellules():
    md = COMPLETE.replace("plafond: permutation_p95\n", "")
    manques = preinscrire.valider(md, anteriorite=True)
    assert any("plafond" in m for m in manques), manques


def test_accepte_sans_plafond_sur_une_SEULE_cellule():
    md = (COMPLETE.replace("cellules: 5", "cellules: 1")
                  .replace("plafond: permutation_p95\n", ""))
    assert preinscrire.valider(md, anteriorite=True) == []


def test_refuse_sans_condition_de_validite():
    md = COMPLETE.replace("validite: abs(ecart_par_trade) < 0.50\n", "")
    manques = preinscrire.valider(md, anteriorite=True)
    assert any("validite" in m for m in manques), manques


def test_refuse_moins_de_trois_predictions():
    md = COMPLETE.replace("3. la troisieme\n", "")
    manques = preinscrire.valider(md, anteriorite=True)
    assert any("prediction" in m for m in manques), manques


def test_refuse_un_banc_anterieur_a_sa_preinscription():
    manques = preinscrire.valider(COMPLETE, anteriorite=False)
    assert any("anterieur" in m for m in manques), manques


def test_git_muet_est_un_MANQUE_et_non_un_laissez_passer():
    # ⛔ FAIL-CLOSED : ne pas pouvoir prouver l'anteriorite n'est pas la prouver.
    manques = preinscrire.valider(COMPLETE, anteriorite=None)
    assert any("prouver" in m for m in manques), manques
