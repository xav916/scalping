import pathlib
import sys

_ICI = pathlib.Path(__file__).resolve()
sys.path.insert(0, str(_ICI.parents[1]))
sys.path.insert(0, str(_ICI.parents[2]))
import verdict  # noqa: E402

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


# ── AMBIGUITE DE TITRE : or-verdict doit le DIRE, jamais le taire ──

def test_critere_ambigu_est_mentionne_dans_les_raisons_sans_bloquer():
    # Plusieurs titres contiennent "critere" : le choix est une heuristique,
    # l'humain qui lit le verdict doit le savoir -- ce n'est pas en soi un
    # refus (le rejeu reste PUBLIABLE si tout le reste tient).
    decision, raisons = verdict.juger(VALIDE, BLOC, critere_intact=True,
                                      critere_ambigu=True)
    assert decision == "PUBLIABLE"
    assert any("ATTENTION" in r and "heuristique" in r for r in raisons), raisons


def test_sans_ambiguite_aucune_mention_n_apparait():
    decision, raisons = verdict.juger(VALIDE, BLOC, critere_intact=True,
                                      critere_ambigu=False)
    assert decision == "PUBLIABLE"
    assert not any("ATTENTION" in r for r in raisons), raisons


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
