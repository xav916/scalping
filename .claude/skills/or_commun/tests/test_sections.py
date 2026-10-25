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


# ── AMBIGUITE : plusieurs titres contiennent le mot-cle (corpus reel : 5/38) ──

def test_section_choisit_le_titre_ou_le_mot_cle_est_le_plus_precoce():
    """Un titre de recit qui MENTIONNE le mot-cle en fin de phrase doit perdre
    face a un titre qui EST la section, meme s'il vient apres dans le document.

    Avec l'ancienne regle (premier titre trouve), ce test echoue : le corps
    rendu serait celui du recit ("texte du recit, hors de propos"), pas celui
    du vrai critere ("t > +2").
    """
    md = (
        "# t\n\n"
        "## Ce qui a change la portee, mesure avant d'ecrire ce critere\n\n"
        "texte du recit, hors de propos\n\n"
        "## LE CRITERE, pose d'avance\n\n"
        "seuil : t > +2\n\n"
        "## Autre\n\nhors sujet\n"
    )
    trouve = sections.section(md, "critere")
    assert trouve is not None
    assert "t > +2" in trouve
    assert "hors de propos" not in trouve


def test_section_vrai_fichier_critere_et_non_le_recit():
    """Preuve sur un fichier REEL du depot (pas un fixture construit).

    `docs/predictions/2026-10-10_surprise_economique_direction.md` contient
    TROIS titres ou "critere" apparait normalise :
      - ligne 23 : '## ... mesure avant d'ecrire ce critere' (recit, pos=56)
      - ligne 81 : '## LE CRITERE, POSE AVANT DE REGARDER'   (le vrai, pos=3)
      - ligne 167: '## Le reste du critere est INCHANGE'     (pos=12)
    La regle de la position la plus precoce doit retenir la ligne 81.
    Ce test echoue sur l'ancienne regle (premier titre trouve = ligne 23).
    """
    depot = pathlib.Path(__file__).resolve().parents[4]
    chemin = depot / "docs" / "predictions" / "2026-10-10_surprise_economique_direction.md"
    assert chemin.exists(), "fichier reel introuvable : %s" % chemin
    texte = chemin.read_text(encoding="utf-8")

    assert sections.nombre_titres_correspondants(texte, "critere") == 3

    trouve = sections.section(texte, "critere")
    assert trouve is not None
    norm = sections.normaliser(trouve)
    assert "2 730" in norm and "les cinq" in norm, norm[:200]
    assert "mesure avant d ecrire ce critere" not in norm
    assert "le reste du critere est inchange" not in norm


def test_nombre_titres_correspondants_compte_toutes_les_correspondances():
    md = "# t\n\n## critere A\n\ntexte\n\n## autre\n\ntexte\n\n## critere B\n\ntexte\n"
    assert sections.nombre_titres_correspondants(md, "critere") == 2
    assert sections.nombre_titres_correspondants(md, "absent") == 0


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
