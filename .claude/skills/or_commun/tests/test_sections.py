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
