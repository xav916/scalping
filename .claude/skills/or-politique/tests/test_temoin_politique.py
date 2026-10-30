"""Temoin a reponse connue d'avance, etablie AVANT la skill et PAS depuis la
table qu'elle lira : mesures des 29 et 30/10 sur la production.

    is_real_money : admin_live True · admin_kraken True · admin_legacy False
    LIVE_WHITELIST_PAIRS   = {XAU/USD}
    LEGACY_WHITELIST_PAIRS = {12 paires}
                             (rien pour kraken)
    admin_kraken /health garde_fous = {}
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import politique as P  # noqa: E402
import regles as R  # noqa: E402

ETAT = {
    "fingerprint_running": "a4d9aedeee17",
    "rem002_allowed": False, "rem002_reason": "DISARMED_MANUALLY",
    "listes_blanches": {"admin_live": ["XAU/USD"],
                        "admin_legacy": ["AUD/USD", "EUR/USD"]},
    "destinations": [
        {"destination_id": "admin_legacy", "bridge_type": "mt5", "reel": False,
         "min_confidence": 42.0, "classes_porte": ["energy", "forex", "metal"],
         "classes_registre": ["energy", "forex", "metal"],
         "connue_du_registre": True, "garde_fous": {"max_open_positions": 10}},
        {"destination_id": "admin_live", "bridge_type": "mt5", "reel": True,
         "min_confidence": 42.0, "classes_porte": ["energy", "forex", "metal"],
         "classes_registre": ["energy", "equity", "forex", "metal"],
         "connue_du_registre": True, "garde_fous": {"max_open_positions": 10}},
        {"destination_id": "admin_kraken", "bridge_type": "kraken",
         "reel": True, "min_confidence": 42.0, "classes_porte": ["crypto"],
         "classes_registre": ["crypto", "metal"],
         "connue_du_registre": True, "garde_fous": {}},
    ],
}


def test_le_verdict_global_est_1_sur_la_config_reelle():
    code, _ = P.juger(ETAT)
    assert code == 1


def test_admin_kraken_est_nomme_sur_DEUX_regles():
    _, lignes = P.juger(ETAT)
    texte = "\n".join(lignes)
    assert "admin_kraken" in texte
    faux = [v for v in R.juger_destination(ETAT["destinations"][2],
                                           ETAT["listes_blanches"])
            if v["verdict"] == R.FAIL]
    assert {v["regle"] for v in faux} == {1, 2}


def test_aucun_FAIL_sur_admin_legacy():
    faux = [v for v in R.juger_destination(ETAT["destinations"][0],
                                           ETAT["listes_blanches"])
            if v["verdict"] == R.FAIL]
    assert faux == []


def test_la_sortie_nomme_l_empreinte_et_l_armement():
    _, lignes = P.juger(ETAT)
    texte = "\n".join(lignes)
    assert "a4d9aedeee17" in texte
    assert "DISARMED_MANUALLY" in texte


def test_la_sortie_dit_qu_elle_juge_la_config_DECLAREE():
    _, lignes = P.juger(ETAT)
    assert "declar" in "\n".join(lignes).lower()


def test_les_trois_destinations_apparaissent():
    _, lignes = P.juger(ETAT)
    texte = "\n".join(lignes)
    for nom in ("admin_legacy", "admin_live", "admin_kraken"):
        assert nom in texte


def test_empreinte_absente_rend_2_et_ne_juge_rien():
    code, lignes = P.juger(dict(ETAT, fingerprint_running=None))
    assert code == 2
    assert "empreinte" in "\n".join(lignes).lower()


def test_aucune_destination_active_rend_2():
    """Une production sans destination active est invraisemblable, donc
    suspecte : on ne rend pas « conforme »."""
    code, _ = P.juger(dict(ETAT, destinations=[]))
    assert code == 2


def test_une_config_entierement_saine_rend_0():
    """Temoin POSITIF : sans lui, un « 1 » permanent passerait pour normal."""
    sain = {
        "fingerprint_running": "abc123", "rem002_allowed": False,
        "rem002_reason": "DISARMED_MANUALLY",
        "listes_blanches": {"admin_live": ["XAU/USD"]},
        "destinations": [
            {"destination_id": "admin_live", "bridge_type": "mt5",
             "reel": True, "min_confidence": 42.0,
             "classes_porte": ["metal"], "classes_registre": ["metal"],
             "connue_du_registre": True,
             "garde_fous": {"max_open_positions": 10}},
        ],
    }
    code, _ = P.juger(sain)
    assert code == 0


def test_ILLISIBLE_compte_comme_echec_et_rend_1():
    """REM-002 (review de la tache 4) : ILLISIBLE est une donnee qu'on n'a
    pas pu interpreter, pas une donnee muette -- elle doit fermer la porte
    exactement comme FAIL, sinon le fail-closed fuit par la nouvelle voie."""
    illisible = {
        "fingerprint_running": "abc123", "rem002_allowed": False,
        "rem002_reason": "DISARMED_MANUALLY",
        "listes_blanches": {"admin_live": ["XAU/USD"]},
        "destinations": [
            {"destination_id": "admin_live", "bridge_type": "mt5",
             "reel": True, "min_confidence": "abc",
             "classes_porte": ["metal"], "classes_registre": ["metal"],
             "connue_du_registre": True,
             "garde_fous": {"max_open_positions": 10}},
        ],
    }
    v = [x for x in R.juger_destination(illisible["destinations"][0], {})
         if x["regle"] == 3][0]
    assert v["verdict"] == R.ILLISIBLE
    code, lignes = P.juger(illisible)
    assert code == 1
    texte = "\n".join(lignes)
    assert "ILLISIBLE" in texte


def test_le_resume_distingue_FAIL_et_ILLISIBLE():
    """La ligne finale doit nommer les deux comptes separement, pas les
    fondre dans un seul total -- sinon un lecteur ne sait pas lequel des deux
    il affronte."""
    illisible = {
        "fingerprint_running": "abc123", "rem002_allowed": False,
        "rem002_reason": "DISARMED_MANUALLY",
        "listes_blanches": {"admin_live": ["XAU/USD"]},
        "destinations": [
            {"destination_id": "admin_live", "bridge_type": "mt5",
             "reel": True, "min_confidence": "abc",
             "classes_porte": ["metal"], "classes_registre": ["metal"],
             "connue_du_registre": True,
             "garde_fous": {"max_open_positions": 10}},
        ],
    }
    _, lignes = P.juger(illisible)
    resume = lignes[-1]
    assert "FAIL" in resume
    assert "ILLISIBLE" in resume
