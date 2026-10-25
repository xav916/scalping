import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import etat  # noqa: E402

# L'etat REEL releve le 25/10 au soir, apres verification des trois voies.
DESARME = {
    "rem002_allowed": False, "rem002_reason": "DISARMED_MANUALLY",
    "mirror_active": False, "pending": 0,
    "equity": 461.22, "positions": 0,
    "pont_live": 200, "pont_demo": 200,
    "fingerprint_running": "5b1b07b55a64", "fingerprint_armed": "0e8a1ae31e1b",
}


def test_desarme_sur_les_trois_voies_rend_0():
    code, lignes = etat.juger(DESARME)
    assert code == 0
    texte = "\n".join(lignes)
    assert "DISARMED_MANUALLY" in texte
    assert "3 voies" in texte or "trois voies" in texte


def test_signale_que_le_rearmement_exige_une_decision_neuve():
    _, lignes = etat.juger(DESARME)
    assert any("decision neuve" in l for l in lignes)


# ── LES JUMEAUX NEGATIFS ──

def test_arme_rend_0_mais_le_DIT_fort():
    code, lignes = etat.juger(dict(DESARME, rem002_allowed=True,
                                   rem002_reason="ARMED"))
    assert code == 0
    # CORRECTION: remplacer "ARME" par "=> ARME," pour que le test
    # discrimine vraiment entre ARME et DESARME
    assert any("=> ARME," in l for l in lignes)


def test_incoherence_rend_1_desarme_mais_file_non_vide():
    code, lignes = etat.juger(dict(DESARME, pending=3))
    assert code == 1
    assert any("incoherent" in l for l in lignes)


def test_information_manquante_rend_1():
    # ⛔ Jamais code 0 sur une information absente.
    code, lignes = etat.juger({k: v for k, v in DESARME.items()
                               if k != "mirror_active"})
    assert code == 1
    assert any("mirror_active" in l for l in lignes)


def test_pont_live_muet_rend_1():
    code, lignes = etat.juger(dict(DESARME, pont_live=0))
    assert code == 1
    assert any("pont live" in l for l in lignes)


def test_pont_demo_muet_ne_fait_PAS_echouer():
    code, lignes = etat.juger(dict(DESARME, pont_demo=0))
    assert code == 0
    assert any("informatif" in l for l in lignes)
