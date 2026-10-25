import pathlib
import subprocess
import sys
import tempfile

_ICI = pathlib.Path(__file__).resolve()
sys.path.insert(0, str(_ICI.parents[1]))
sys.path.insert(0, str(_ICI.parents[2]))
sys.path.insert(0, str(_ICI.parents[2] / "or-verdict"))
import preinscrire  # noqa: E402
import verdict  # noqa: E402
from or_commun import sections  # noqa: E402

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
    assert any("prouver" in m.lower() for m in manques), manques


# ── NOUVELLE COUVERTURE : contenu de la condition d'admission ──

def test_refuse_admission_sans_comparaison_numerique():
    md = COMPLETE.replace("admission: t > +2\n", "admission: pas mal\n")
    manques = preinscrire.valider(md, anteriorite=True)
    assert any("admission" in m and "contenu" in m for m in manques), manques


def test_refuse_admission_avec_negation():
    md = COMPLETE.replace("admission: t > +2\n", "admission: pas significativement pire\n")
    manques = preinscrire.valider(md, anteriorite=True)
    assert any("admission" in m and "contenu" in m for m in manques), manques


def test_refuse_sans_rejet():
    md = COMPLETE.replace("rejet: t < -2\n", "")
    manques = preinscrire.valider(md, anteriorite=True)
    assert any("rejet" in m for m in manques), manques


def test_refuse_rejet_sans_comparaison_numerique():
    md = COMPLETE.replace("rejet: t < -2\n", "rejet: t tres negatif\n")
    manques = preinscrire.valider(md, anteriorite=True)
    assert any("rejet" in m and "contenu" in m for m in manques), manques


def test_refuse_rejet_signal_p50():
    md = COMPLETE.replace("rejet: t < -2\n", "rejet: signal p50\n")
    manques = preinscrire.valider(md, anteriorite=True)
    assert any("rejet" in m and "contenu" in m for m in manques), manques


def test_refuse_validite_sans_comparaison_numerique():
    md = COMPLETE.replace("validite: abs(ecart_par_trade) < 0.50\n",
                          "validite: ecart sous p95\n")
    manques = preinscrire.valider(md, anteriorite=True)
    assert any("validite" in m and "contenu" in m for m in manques), manques


def test_refuse_validite_le_rejeu_doit_reproduire_la_realite():
    md = COMPLETE.replace(
        "validite: abs(ecart_par_trade) < 0.50\n",
        "validite: le rejeu doit reproduire la realite\n")
    manques = preinscrire.valider(md, anteriorite=True)
    assert any("validite" in m and "contenu" in m for m in manques), manques


# ── COHERENCE or-preinscription / or-verdict : la MEME fixture aux deux ──
# 🔑 ce que la porte laisse passer doit etre jugeable ; ce qu'elle refuse ne
# doit JAMAIS atteindre le juge sans etre refuse aussi.

RESULTAT_NEUTRE = {"n": 100, "t": 1.0, "ecart_par_trade": 0.1, "valide": True}

# Les six blocs mesures dans la revue : le temoin complet, puis les cinq
# fixtures que l'ancienne porte laissait passer (code 0) alors que or-verdict
# les refusait A PERPETUITE.
FIXTURES_PORTE_JUGE = [
    ("temoin complet", COMPLETE),
    ("rejet absent", COMPLETE.replace("rejet: t < -2\n", "")),
    ("rejet: t tres negatif",
     COMPLETE.replace("rejet: t < -2\n", "rejet: t tres negatif\n")),
    ("rejet: signal p50",
     COMPLETE.replace("rejet: t < -2\n", "rejet: signal p50\n")),
    ("validite: ecart sous p95",
     COMPLETE.replace("validite: abs(ecart_par_trade) < 0.50\n",
                      "validite: ecart sous p95\n")),
    ("validite: le rejeu doit reproduire la realite",
     COMPLETE.replace(
         "validite: abs(ecart_par_trade) < 0.50\n",
         "validite: le rejeu doit reproduire la realite\n")),
]


def test_la_porte_et_le_juge_s_accordent_sur_les_memes_fixtures():
    for nom, md in FIXTURES_PORTE_JUGE:
        porte_ok = preinscrire.valider(md, anteriorite=True) == []
        bloc = sections.bloc_machine(md)
        decision, raisons = verdict.juger(RESULTAT_NEUTRE, bloc,
                                          critere_intact=True)
        juge_ok = decision == verdict.PUBLIABLE

        if nom == "temoin complet":
            assert porte_ok, (nom, "la porte doit laisser passer le temoin")
            assert juge_ok, (nom, raisons)
        else:
            # ⛔ Avant le correctif, la porte disait OK ici (porte_ok=True)
            # alors que le juge refusait a perpetuite (juge_ok=False) : les
            # deux doivent maintenant s'accorder sur un REFUS.
            assert not porte_ok, (nom, "la porte doit refuser", porte_ok)
            assert not juge_ok, (nom, "le juge doit refuser", raisons)


def test_refuse_cellules_absent():
    md = COMPLETE.replace("cellules: 5\n", "")
    manques = preinscrire.valider(md, anteriorite=True)
    assert any("cellules" in m for m in manques), manques


# ── COUVERTURE GIT : anteriorite_git avec dépôt temporaire ──

def test_anteriorite_git_preinscription_avant_banc():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = pathlib.Path(tmpdir)

        # Creer un repo git
        subprocess.run(["git", "init"], cwd=tmpdir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"],
                      cwd=tmpdir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"],
                      cwd=tmpdir, check=True, capture_output=True)

        # Commit preinscription
        (tmpdir / "preins.md").write_text("# Pre")
        subprocess.run(["git", "add", "preins.md"], cwd=tmpdir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "pre"], cwd=tmpdir, check=True, capture_output=True)

        # Commit banc plus tard
        (tmpdir / "banc.py").write_text("# Banc")
        subprocess.run(["git", "add", "banc.py"], cwd=tmpdir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "banc"], cwd=tmpdir, check=True, capture_output=True)

        result = preinscrire.anteriorite_git(
            str(tmpdir / "preins.md"),
            str(tmpdir / "banc.py"))
        assert result is True, f"Attendu True, obtenu {result}"


def test_anteriorite_git_banc_avant_preinscription():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = pathlib.Path(tmpdir)

        subprocess.run(["git", "init"], cwd=tmpdir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"],
                      cwd=tmpdir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"],
                      cwd=tmpdir, check=True, capture_output=True)

        # Commit banc d'abord
        (tmpdir / "banc.py").write_text("# Banc")
        subprocess.run(["git", "add", "banc.py"], cwd=tmpdir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "banc"], cwd=tmpdir, check=True, capture_output=True)

        # Commit preinscription plus tard
        (tmpdir / "preins.md").write_text("# Pre")
        subprocess.run(["git", "add", "preins.md"], cwd=tmpdir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "pre"], cwd=tmpdir, check=True, capture_output=True)

        result = preinscrire.anteriorite_git(
            str(tmpdir / "preins.md"),
            str(tmpdir / "banc.py"))
        assert result is False, f"Attendu False, obtenu {result}"


def test_anteriorite_git_banc_non_suivi():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = pathlib.Path(tmpdir)

        subprocess.run(["git", "init"], cwd=tmpdir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"],
                      cwd=tmpdir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"],
                      cwd=tmpdir, check=True, capture_output=True)

        # Commit preinscription
        (tmpdir / "preins.md").write_text("# Pre")
        subprocess.run(["git", "add", "preins.md"], cwd=tmpdir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "pre"], cwd=tmpdir, check=True, capture_output=True)

        # Banc existe mais n'est PAS suivi par git
        (tmpdir / "banc.py").write_text("# Banc")

        result = preinscrire.anteriorite_git(
            str(tmpdir / "preins.md"),
            str(tmpdir / "banc.py"))
        assert result is None, f"Attendu None (banc non suivi), obtenu {result}"


def test_anteriorite_git_pas_un_depot():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = pathlib.Path(tmpdir)

        # PAS de git init - ce n'est pas un repo
        (tmpdir / "preins.md").write_text("# Pre")
        (tmpdir / "banc.py").write_text("# Banc")

        result = preinscrire.anteriorite_git(
            str(tmpdir / "preins.md"),
            str(tmpdir / "banc.py"))
        assert result is None, f"Attendu None (pas un depot), obtenu {result}"
