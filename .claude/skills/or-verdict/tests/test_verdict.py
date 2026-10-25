import pathlib
import sys

_ICI = pathlib.Path(__file__).resolve()
sys.path.insert(0, str(_ICI.parents[1]))
sys.path.insert(0, str(_ICI.parents[2]))
import verdict  # noqa: E402

BLOC = {"admission": "t > +2", "rejet": "t < -2",
        "validite": "abs(ecart_par_trade) < 0.50",
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
    r = dict(VALIDE, t=2.4)
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
