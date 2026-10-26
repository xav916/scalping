import os
import pathlib
import subprocess
import sys
import tempfile

_ICI = pathlib.Path(__file__).resolve()
sys.path.insert(0, str(_ICI.parents[1]))
sys.path.insert(0, str(_ICI.parents[2]))
import verdict  # noqa: E402
from or_commun import sections  # noqa: E402

BLOC = {"admission": "t > +3", "rejet": "t < -1.5",
        "validite": "abs(ecart_par_trade) < 0.25",
        "cellules": "1", "plafond": "permutation_p95"}

# Les chiffres REELS du verdict du 25/10 (ffb150e), rejeu valide.
VALIDE = {"n": 165, "total_reel": -38.05, "total_A": -38.26, "total_B": -15.24,
          "evite": 23.03, "moy_appariee": 0.1396, "t": 0.65,
          "reussite_A": 65.5, "reussite_B": 82.4,
          "ecart_par_trade": -0.0013, "valide": True}


def test_un_rejeu_valide_est_publiable():
    decision, _ = verdict.juger(VALIDE, BLOC, critere_intact=True)
    assert decision == "PUBLIABLE"


def test_le_critere_rend_indecidable_sous_le_seuil():
    _, raisons = verdict.juger(VALIDE, BLOC, critere_intact=True)
    assert any("indecidable" in r for r in raisons), raisons


def test_admission_franchie_au_dessus_du_seuil():
    r = dict(VALIDE, t=3.1)
    _, raisons = verdict.juger(r, BLOC, critere_intact=True)
    assert any("admission" in x for x in raisons), raisons


# ── LES JUMEAUX NEGATIFS ──

def test_refuse_un_rejeu_hors_barre_de_validite():
    # les chiffres REELS du hors echantillon du 25/10 (56ff582) : -0,5731
    r = dict(VALIDE, ecart_par_trade=-0.5731, valide=False)
    decision, raisons = verdict.juger(r, BLOC, critere_intact=True)
    assert decision == "NE PAS PUBLIER"
    assert any("validite" in x for x in raisons), raisons


def test_refuse_un_json_sans_ecart_par_trade():
    r = {k: v for k, v in VALIDE.items() if k != "ecart_par_trade"}
    decision, raisons = verdict.juger(r, BLOC, critere_intact=True)
    assert decision == "NE PAS PUBLIER"
    assert any("ecart_par_trade" in x for x in raisons), raisons


def test_refuse_un_critere_reecrit_apres_coup():
    decision, raisons = verdict.juger(VALIDE, BLOC, critere_intact=False)
    assert decision == "NE PAS PUBLIER"
    assert any("reecrit" in x.lower() for x in raisons), raisons


def test_empreinte_indeterminable_est_un_REFUS():
    # ⛔ FAIL-CLOSED : ne pas pouvoir comparer n'est pas comparer.
    decision, raisons = verdict.juger(VALIDE, BLOC, critere_intact=None)
    assert decision == "NE PAS PUBLIER"
    assert any("comparer" in x.lower() for x in raisons), raisons


def test_refuse_sans_bloc_machine():
    decision, raisons = verdict.juger(VALIDE, None, critere_intact=True)
    assert decision == "NE PAS PUBLIER"
    assert any("bloc machine" in x for x in raisons), raisons


def test_rejet_franchi_sous_le_seuil():
    # La branche elif t < bas doit etre testee aussi.
    r = dict(VALIDE, t=-2.0)
    _, raisons = verdict.juger(r, BLOC, critere_intact=True)
    assert any("rejet" in x for x in raisons), raisons


# ── EXPRESSIONS SANS CHIFFRE : FAIL-CLOSED ──

def test_refuse_admission_sans_chiffre():
    bloc = dict(BLOC, admission="significatif")
    decision, raisons = verdict.juger(VALIDE, bloc, critere_intact=True)
    assert decision == "NE PAS PUBLIER"
    assert any("admission" in x and "indechiffrable" in x for x in raisons), raisons


def test_refuse_rejet_sans_chiffre():
    bloc = dict(BLOC, rejet="t tres negatif")
    decision, raisons = verdict.juger(VALIDE, bloc, critere_intact=True)
    assert decision == "NE PAS PUBLIER"
    assert any("rejet" in x and "indechiffrable" in x for x in raisons), raisons


def test_refuse_validite_sans_chiffre():
    bloc = dict(BLOC, validite="sans chiffre du tout")
    decision, raisons = verdict.juger(VALIDE, bloc, critere_intact=True)
    assert decision == "NE PAS PUBLIER"
    assert any("validite" in x and "indechiffrable" in x for x in raisons), raisons


# ── NOMBRES INCIDENTS : chiffre present mais sans operateur ──

def test_refuse_admission_nombre_incident():
    # 'p95 par permutation' contient 95, mais pas apres un operateur.
    bloc = dict(BLOC, admission="p95 par permutation")
    decision, raisons = verdict.juger(VALIDE, bloc, critere_intact=True)
    assert decision == "NE PAS PUBLIER"
    assert any("admission" in x and "indechiffrable" in x for x in raisons), raisons


def test_refuse_rejet_nombre_incident():
    bloc = dict(BLOC, rejet="signal p50 deces")
    decision, raisons = verdict.juger(VALIDE, bloc, critere_intact=True)
    assert decision == "NE PAS PUBLIER"
    assert any("rejet" in x and "indechiffrable" in x for x in raisons), raisons


def test_refuse_validite_nombre_incident():
    bloc = dict(BLOC, validite="ecart sous p95")
    decision, raisons = verdict.juger(VALIDE, bloc, critere_intact=True)
    assert decision == "NE PAS PUBLIER"
    assert any("validite" in x and "indechiffrable" in x for x in raisons), raisons


# ── REQUIS : presence NE SUFFIT PAS, le contenu doit etre du bon type ──
# Les quatre pieges mesures le 25/10 : null sur un champ numerique (TypeError
# nu), chaine non numerique (ValueError nu), et le pire -- "valide": "false"
# (une CHAINE) qui serait PUBLIABLE puisqu'une chaine non vide est vraie en
# Python.

def test_refuse_ecart_par_trade_null():
    r = dict(VALIDE, ecart_par_trade=None)
    decision, raisons = verdict.juger(r, BLOC, critere_intact=True)
    assert decision == "NE PAS PUBLIER"
    assert any("ecart_par_trade" in x and "null" in x for x in raisons), raisons


def test_refuse_t_null():
    r = dict(VALIDE, t=None)
    decision, raisons = verdict.juger(r, BLOC, critere_intact=True)
    assert decision == "NE PAS PUBLIER"
    assert any("t" in x and "null" in x for x in raisons), raisons


def test_refuse_ecart_par_trade_chaine_non_numerique():
    r = dict(VALIDE, ecart_par_trade="abc")
    decision, raisons = verdict.juger(r, BLOC, critere_intact=True)
    assert decision == "NE PAS PUBLIER"
    assert any("ecart_par_trade" in x and "convertible" in x for x in raisons), raisons


def test_refuse_valide_chaine_meme_false_textuel():
    # 🔑 le piege : "false" (une CHAINE non vide) est VRAI en Python.
    r = dict(VALIDE, valide="false")
    decision, raisons = verdict.juger(r, BLOC, critere_intact=True)
    assert decision == "NE PAS PUBLIER"
    assert any("valide" in x and "booleen" in x for x in raisons), raisons


# ── TESTS DISCRIMINANTS : _seuil lit vraiment le bloc, pas un defaut ──
# Ces tests prouvent que les anciennes implementations qui ignoreaient l'expression
# et retombaient sur un defaut code en dur ECHOUERAIENT maintenant.

def test_seuil_admission_lu_dans_le_bloc_et_non_un_defaut():
    # BLOC a admission: "t > +3" (seuil = 3.0).
    # Ancien defaut aurait ete 2.0.
    # t=2.5 est ENTRE les deux : discrimine.
    #
    # Si _seuil ignorait l'expression et retournait 2.0, ce test retournerait
    # "admission franchie" (2.5 > 2.0). Maintenant, ca retourne "indecidable"
    # (2.5 est entre -1.5 et 3.0).
    r = dict(VALIDE, t=2.5)
    decision, raisons = verdict.juger(r, BLOC, critere_intact=True)
    assert decision == "PUBLIABLE", raisons
    assert any("indecidable" in x and "2.50" in x for x in raisons), raisons


# ── empreinte_critere() DEPUIS N'IMPORTE OU : 4 formes d'invocation ──
# Mesure de la revue : A marche, B/C/D rendaient None avant le correctif
# (racine deduite du CWD du processus, chemin passe tel quel a git).
#
# REVISE LE 2026-10-26 : l'empreinte hache desormais le bloc CRITERE-MACHINE,
# plus la section en prose "critere" -- la fixture porte donc un bloc.

_CRITERE_MD = (
    # Un titre NARRATIF qui mentionne "critere" vient AVANT le vrai titre --
    # motif reel du corpus (2026-10-10_surprise_economique_direction.md).
    # Le bloc machine vit dans le vrai titre, pas dans le recit : hacher la
    # mauvaise section (prose) raterait tout changement du bloc.
    "# t\n\n"
    "## Ce qui a change la portee, mesure avant d'ecrire ce critere\n\n"
    "texte du recit, hors de propos\n\n"
    "## LE CRITERE\n\nseuil : t > +2\n\n"
    "<!-- CRITERE-MACHINE\n"
    "admission: t > +2\n"
    "rejet: t < -2\n"
    "validite: abs(ecart_par_trade) < 0.50\n"
    "-->\n"
)

# Meme pre-inscription, mais SANS bloc machine -- pour les tests fail-closed
# du mouvement 1 (bloc absent dans la version commitee).
_SANS_BLOC_MD = "# t\n\n## LE CRITERE\n\nseuil : t > +2\n"


def _depot_avec_fichier(contenu: str):
    """Cree un depot git temporaire avec un fichier `pred.md` commite.

    Rend `(tmpdir, chemin_absolu_du_fichier, chemin_du_sous_repertoire)`.
    """
    tmpdir = pathlib.Path(tempfile.mkdtemp())
    subprocess.run(["git", "init"], cwd=tmpdir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"],
                   cwd=tmpdir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"],
                   cwd=tmpdir, check=True, capture_output=True)
    fichier = tmpdir / "pred.md"
    fichier.write_text(contenu, encoding="utf-8")
    subprocess.run(["git", "add", "pred.md"], cwd=tmpdir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "pred"], cwd=tmpdir, check=True, capture_output=True)
    sousrep = tmpdir / "sub"
    sousrep.mkdir()
    return tmpdir, fichier, sousrep


def _depot_avec_critere():
    return _depot_avec_fichier(_CRITERE_MD)


def _depuis(cwd: pathlib.Path, chemin):
    """Appelle empreinte_critere(chemin) avec le processus EXECUTE dans `cwd`."""
    avant = pathlib.Path.cwd()
    os.chdir(cwd)
    try:
        return verdict.empreinte_critere(str(chemin))
    finally:
        os.chdir(avant)


def test_empreinte_A_racine_plus_chemin_relatif():
    tmpdir, fichier, _sousrep = _depot_avec_critere()
    assert _depuis(tmpdir, "pred.md") is True


def test_empreinte_B_racine_plus_chemin_absolu():
    tmpdir, fichier, _sousrep = _depot_avec_critere()
    assert _depuis(tmpdir, fichier) is True


def test_empreinte_C_sous_repertoire_plus_chemin_relatif():
    tmpdir, fichier, sousrep = _depot_avec_critere()
    # Chemin relatif au CWD reel du processus (le sous-repertoire), pas a la
    # racine -- c'est la forme naturelle d'invocation depuis un sous-dossier.
    assert _depuis(sousrep, "../pred.md") is True


def test_empreinte_D_sous_repertoire_plus_chemin_absolu():
    tmpdir, fichier, sousrep = _depot_avec_critere()
    assert _depuis(sousrep, fichier) is True


def test_racine_et_chemin_relatif_rend_None_hors_depot():
    with tempfile.TemporaryDirectory() as tmp:
        fichier = pathlib.Path(tmp) / "x.md"
        fichier.write_text("# t\n")
        assert verdict._racine_et_chemin_relatif(str(fichier)) is None


def test_raison_indeterminable_personnalisee_remplace_le_message_generique():
    # "chemin non resolu au depot" doit se distinguer de "empreinte non
    # comparable" -- un chemin mal resolu n'accuse pas d'une falsification.
    decision, raisons = verdict.juger(
        VALIDE, BLOC, critere_intact=None,
        raison_indeterminable="chemin non resolu a un depot git")
    assert decision == "NE PAS PUBLIER"
    assert any("chemin non resolu" in r for r in raisons), raisons
    assert not any("comparer" in r.lower() for r in raisons), raisons


def test_empreinte_critere_reecrit_est_detecte_depuis_le_sous_repertoire():
    # Les quatre formes rendent un booleen : prouver qu'il est aussi JUSTE
    # (pas seulement "pas None") en reecrivant le SEUIL DANS LE BLOC MACHINE
    # sur le disque -- c'est lui qui engage, plus la prose.
    tmpdir, fichier, sousrep = _depot_avec_critere()
    fichier.write_text(
        "# t\n\n## LE CRITERE\n\nseuil : t > +2\n\n"
        "<!-- CRITERE-MACHINE\n"
        "admission: t > +999\n"
        "rejet: t < -2\n"
        "validite: abs(ecart_par_trade) < 0.50\n"
        "-->\n", encoding="utf-8")
    assert _depuis(sousrep, fichier) is False


# ── MOUVEMENT 1 : l'empreinte hache le BLOC MACHINE, plus la prose ──
# Les quatre tests exiges par la revue du 2026-10-26.

def test_1_empreinte_stable_par_ajout_dune_section_verdict_titree_critere():
    """Le flux ajoute le verdict AU FICHIER de la pre-inscription. Un titre
    de verdict qui COMMENCE PAR "Critere" ne doit JAMAIS faire accuser le
    fichier de falsification -- c'est precisement ce que l'ancienne
    heuristique de section() (retiree au mouvement 2) aurait casse : son
    titre aurait une position de mot-cle plus precoce que "LE CRITERE" et
    aurait hijacke la section hachee.
    """
    tmpdir, fichier, _sousrep = _depot_avec_critere()
    avant = verdict.empreinte_critere(str(fichier))
    assert avant is True

    with open(fichier, "a", encoding="utf-8") as f:
        f.write("\n## Critere du verdict : PUBLIABLE\n\nle rejeu est valide\n")

    apres = verdict.empreinte_critere(str(fichier))
    assert apres is True, (
        "ajouter un titre de verdict commencant par Critere en fin de "
        "fichier a change l'empreinte -- fausse accusation de falsification")


def test_2_empreinte_detecte_une_valeur_modifiee_dans_le_bloc_machine_et_juger_refuse():
    """Modifier une valeur A L'INTERIEUR du bloc machine doit changer
    l'empreinte, et le verdict bout-en-bout doit refuser.

    `.replace()` sur le texte commite : SEULE la valeur bouge, la structure
    (titres, prose) reste identique -- la preuve porte sur la valeur, pas sur
    un changement de structure qui ferait coincidentallement diverger les
    hachages.
    """
    tmpdir, fichier, _sousrep = _depot_avec_critere()
    reecrit = _CRITERE_MD.replace("admission: t > +2", "admission: t > +777")
    assert reecrit != _CRITERE_MD  # garde-fou : le replace a bien agi
    fichier.write_text(reecrit, encoding="utf-8")

    critere_intact = verdict.empreinte_critere(str(fichier))
    assert critere_intact is False

    decision, raisons = verdict.juger(VALIDE, BLOC, critere_intact=critere_intact)
    assert decision == "NE PAS PUBLIER"
    assert any("reecrit" in x.lower() for x in raisons), raisons


def test_3_compter_predictions_rend_6_sur_les_deux_fichiers_reels():
    """Non-regression mesuree sur le corpus REEL de docs/predictions.

    Avec l'heuristique retiree au mouvement 2 (section() revenue a la regle
    d'ordre du document), compter_predictions() doit retrouver les 6
    predictions numerotees de chacun de ces deux fichiers -- l'heuristique
    les faisait tomber a 0 (section "PREDICTION n5/n3" choisie au lieu de
    "MES PREDICTIONS, posees avant de coder").
    """
    depot = pathlib.Path(__file__).resolve().parents[4]
    for nom in ("2026-10-12_bancs_refaits_au_cout_reel.md",
                "2026-10-14_declencheur_sur_la_vitesse.md"):
        chemin = depot / "docs" / "predictions" / nom
        assert chemin.exists(), "fichier reel introuvable : %s" % chemin
        texte = chemin.read_text(encoding="utf-8")
        assert sections.compter_predictions(texte) == 6, nom


def test_4a_empreinte_indeterminable_bloc_absent_sur_le_disque():
    """Fail-closed : le bloc machine est absent du fichier SUR LE DISQUE
    (meme si la version commitee en avait un) -> None, jamais un booleen.
    """
    tmpdir, fichier, _sousrep = _depot_avec_critere()
    fichier.write_text("# t\n\n## LE CRITERE\n\nseuil : t > +2\n",
                       encoding="utf-8")  # bloc machine retire, non commite
    assert verdict.empreinte_critere(str(fichier)) is None


def test_4b_empreinte_indeterminable_bloc_absent_dans_la_version_commitee():
    """Fail-closed : le bloc machine est absent de la version COMMITEE
    (meme si le disque en a un desormais) -> None, jamais un booleen.
    """
    tmpdir, fichier, _sousrep = _depot_avec_fichier(_SANS_BLOC_MD)
    fichier.write_text(_CRITERE_MD, encoding="utf-8")  # ajoute, non commite
    assert verdict.empreinte_critere(str(fichier)) is None


def test_barre_validite_lue_dans_le_bloc_et_non_un_defaut():
    # BLOC a validite: "abs(ecart_par_trade) < 0.25" (barre = 0.25).
    # Ancien defaut aurait ete 0.50.
    # ecart=0.35 est ENTRE les deux : discrimine.
    #
    # Si _seuil ignorait l'expression et retournait 0.50, ce test accepterait
    # (0.35 < 0.50). Maintenant, ca refuse (0.35 > 0.25).
    r = dict(VALIDE, ecart_par_trade=-0.35, valide=True)
    decision, raisons = verdict.juger(r, BLOC, critere_intact=True)
    assert decision == "NE PAS PUBLIER", raisons
    assert any("validite" in x and "0.3500" in x for x in raisons), raisons
