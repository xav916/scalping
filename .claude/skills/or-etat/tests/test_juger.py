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


# ── MUTATIONS CRITIQUES RELEVES PAR RELECTEUR ──

def test_champ_None_rend_1():
    """CONSTAT 1 : Une clé présente avec None doit échouer.

    Mutation détectée : collecter() rend des clés avec None si le backend
    manque un champ. L'ancien code vérifiait 'c not in etat', ce qui passe.
    Ce test échouerait si on revenait à vérifier seulement la présence.
    """
    code, lignes = etat.juger(dict(DESARME, rem002_reason=None))
    assert code == 1
    texte = "\n".join(lignes)
    assert "rem002_reason" in texte
    assert "indeterminable" in texte


def test_arme_avec_mirror_et_pending_nest_PAS_incoherent():
    """CONSTAT 2(a) : État légitime = armé + mirror actif + ordres en file.

    Mutation détectée : le relecteur a retiré 'not arme' de la condition
    d'incohérence. Sans cette garde, ce test échouerait car un état armé
    avec mirror ET pending serait marqué incoherent à tort.

    La vraie incohérence est : DESARME avec mirror ou pending > 0.
    """
    code, lignes = etat.juger(dict(DESARME, rem002_allowed=True,
                                   rem002_reason="ARMED",
                                   mirror_active=True,
                                   pending=2))
    assert code == 0, "État armé avec mirror+pending est légitime"
    texte = "\n".join(lignes)
    assert "incoherent" not in texte.lower()


def test_empreintes_egales_pas_de_DIFFERENTES():
    """CONSTAT 2(b) part 1 : Quand empreintes concordent, pas de ligne DIFFERENTES.

    Mutation détectée : le relecteur a remplacé la condition par 'if True:'.
    Sans la vérification de différence, ce test échouerait car une ligne
    "empreintes DIFFERENTES" s'afficherait même quand elles concordent.

    Ce test discrimine : il échouerait si la condition était forcée.
    """
    code, lignes = etat.juger(dict(DESARME,
                                   fingerprint_running="abc123",
                                   fingerprint_armed="abc123"))
    assert code == 0
    texte = "\n".join(lignes)
    assert "DIFFERENTES" not in texte


def test_empreintes_egales_pas_de_decision_neuve():
    """CONSTAT 2(b) part 2 : Quand empreintes concordent, pas de « decision neuve ».

    Mutation détectée : même relecteur 'if True:'. Sans la condition,
    ce test échouerait car une alerte « decision neuve » s'afficherait
    même avec des empreintes concordantes.

    Double vérification : assure qu'aucune ligne ne parle de rearmement
    quand les empreintes sont identiques.
    """
    code, lignes = etat.juger(dict(DESARME,
                                   fingerprint_running="xyz789",
                                   fingerprint_armed="xyz789"))
    assert code == 0
    assert not any("decision neuve" in l for l in lignes), \
        "Aucune alerte rearmement quand empreintes concordent"
