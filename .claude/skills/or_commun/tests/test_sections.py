import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import sections  # noqa: E402

# Les titres REELS du depot, releves le 25/10 : le critere apparait sous six
# formes et les predictions sous sept, avec et sans accents. Un validateur a
# correspondance exacte rejetterait des fichiers valides.
TITRES_CRITERE = [
    "## ⛔ LE CRITÈRE",
    "## ⛔ LE CRITÈRE, POSÉ AVANT DE REGARDER",
    "## ⛔ LE CRITÈRE, posé d'avance",
    "## ⛔ LE CRITERE",
]


def test_trouve_la_section_critere_sous_ses_six_titres():
    for titre in TITRES_CRITERE:
        md = "# t\n\n%s\n\nseuil : t > +2\n\n## Autre\n\nhors sujet\n" % titre
        trouve = sections.section(md, "critere")
        assert trouve is not None, titre
        assert "t > +2" in trouve, titre
        assert "hors sujet" not in trouve, titre


def test_section_absente_rend_None():
    assert sections.section("# rien\n\ntexte\n", "critere") is None


# ── ORDRE DU DOCUMENT : plusieurs titres contiennent le mot-cle ──
# REVISE LE 2026-10-26 : l'heuristique "position la plus precoce du mot-cle"
# a ete retiree (voir le docstring du module). La regle est redevenue le
# premier titre qui correspond, dans l'ordre du document -- stable par ajout
# en fin de fichier, ce que l'heuristique n'etait pas.

def test_section_retient_le_premier_titre_meme_si_un_titre_plus_tard_correspond_mieux():
    """Le premier titre du document gagne, meme si un titre plus loin fait
    correspondre le mot-cle plus tot dans son propre texte.

    Avec l'heuristique retiree (position la plus precoce du mot-cle), ce test
    echouerait : le corps rendu serait celui du second titre ("t > +999"),
    pas celui du premier ("t > +2").
    """
    md = (
        "# t\n\n"
        "## Ce qui a change la portee, mesure avant d'ecrire ce critere\n\n"
        "seuil : t > +2\n\n"
        "## LE CRITERE, pose d'avance\n\n"
        "seuil : t > +999\n\n"
        "## Autre\n\nhors sujet\n"
    )
    trouve = sections.section(md, "critere")
    assert trouve is not None
    assert "t > +2" in trouve
    assert "t > +999" not in trouve


def test_compte_les_predictions_numerotees():
    md = ("## MES PRÉDICTIONS, posées avant de coder\n\n"
          "1. la premiere\n2. la deuxieme\n3. la troisieme\n")
    assert sections.compter_predictions(md) == 3


def test_ne_compte_pas_les_puces_comme_des_predictions():
    md = "## MES PREDICTIONS\n\n- une puce\n- une autre\n"
    assert sections.compter_predictions(md) == 0


def test_lit_le_bloc_machine():
    md = ("texte\n\n<!-- CRITERE-MACHINE\n"
          "admission: t > +2\nrejet: t < -2\n"
          "validite: abs(ecart_par_trade) < 0.50\ncellules: 5\n"
          "plafond: permutation_p95\n-->\n")
    b = sections.bloc_machine(md)
    assert b == {"admission": "t > +2", "rejet": "t < -2",
                 "validite": "abs(ecart_par_trade) < 0.50",
                 "cellules": "5", "plafond": "permutation_p95"}


def test_bloc_machine_absent_rend_None():
    assert sections.bloc_machine("# sans bloc\n") is None


def test_compter_predictions_ignore_les_lignes_numerotees_ailleurs():
    """Prouve que compter_predictions n'extrait QUE la section prediction.

    Le decoy (une autre section avec plus de lignes numerotees) doit rester
    hors du compte. Une implementation fautive qui compterait tout le
    document echouerait sur ce test (8 au lieu de 3).
    """
    md = (
        "## Autre section avec un decoy\n\n"
        "1. decoy numero 1\n"
        "2. decoy numero 2\n"
        "3. decoy numero 3\n"
        "4. decoy numero 4\n"
        "5. decoy numero 5\n"
        "\n"
        "## MES PREDICTIONS\n\n"
        "1. la premiere\n"
        "2. la deuxieme\n"
        "3. la troisieme\n"
    )
    assert sections.compter_predictions(md) == 3
