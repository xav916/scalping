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


def test_destination_fautive_ne_bloque_pas_les_autres():
    """Round 1 de revue : une destination dont la collecte a leve sur un
    champ doit revenir marquee ILLISIBLE sur les regles 2 et 3 (jamais
    CONFORME muet, jamais omise), contribuer a l'echec global, et ne pas
    empecher les autres destinations d'etre jugees."""
    etat = {
        "fingerprint_running": "abc123", "rem002_allowed": False,
        "rem002_reason": "DISARMED_MANUALLY",
        "listes_blanches": {"admin_live": ["XAU/USD"]},
        "destinations": [
            {"destination_id": "admin_live", "bridge_type": "mt5",
             "reel": True, "min_confidence": 42.0,
             "classes_porte": ["metal"], "classes_registre": ["metal"],
             "connue_du_registre": True,
             "garde_fous": {"max_open_positions": 10}},
            # tel que _CHARGE le produit quand un champ a leve en collecte.
            {"destination_id": "admin_fautive", "bridge_type": "mt5",
             "reel": True, "min_confidence": "ILLISIBLE: champ non lu",
             "classes_porte": [], "classes_registre": [],
             "connue_du_registre": False, "garde_fous": True,
             "erreur": "registre=AttributeError"},
            {"destination_id": "admin_kraken", "bridge_type": "kraken",
             "reel": True, "min_confidence": 42.0,
             "classes_porte": ["crypto"], "classes_registre": ["crypto"],
             "connue_du_registre": True, "garde_fous": {}},
        ],
    }
    fautive = etat["destinations"][1]
    par_regle = {v["regle"]: v
                for v in R.juger_destination(fautive, etat["listes_blanches"])}
    assert par_regle[2]["verdict"] == R.ILLISIBLE
    assert par_regle[3]["verdict"] == R.ILLISIBLE

    code, lignes = P.juger(etat)
    assert code == 1
    texte = "\n".join(lignes)
    for nom in ("admin_live", "admin_fautive", "admin_kraken"):
        assert nom in texte


def test_un_fait_non_lu_ne_doit_pas_sortir_en_0():
    """Finding 1 de la revue finale (`juger()` ne lisait jamais `erreur`) :
    `_CHARGE` peut poser `erreur` sur une destination dont un champ n'a pas
    pu etre lu, meme quand les defauts fail-closed font revenir les cinq
    regles CONFORME. Le code de sortie doit rester 1, jamais 0, et le fait
    non lu doit apparaitre dans le corps ET au pied du rapport."""
    etat = {
        "fingerprint_running": "abc123", "rem002_allowed": False,
        "rem002_reason": "DISARMED_MANUALLY",
        "listes_blanches": {"admin_live": ["XAU/USD"]},
        "destinations": [
            {"destination_id": "admin_live", "bridge_type": "mt5",
             "reel": True, "min_confidence": 42.0,
             "classes_porte": ["metal"], "classes_registre": ["metal"],
             "connue_du_registre": True,
             "garde_fous": {"max_open_positions": 10},
             "erreur": "registre=AttributeError"},
        ],
    }
    # Prise seule, chaque regle revient CONFORME -- rien ne la retient.
    verdicts = R.juger_destination(etat["destinations"][0],
                                   etat["listes_blanches"])
    assert all(v["verdict"] == R.CONFORME for v in verdicts)

    code, lignes = P.juger(etat)
    assert code == 1, "un fait non lu doit fermer la porte, jamais sortir en 0"
    texte = "\n".join(lignes)
    assert "registre=AttributeError" in texte

    pied = "\n".join(lignes[-5:])
    assert "admin_live" in pied and "AttributeError" in pied, (
        "le pied doit NOMMER le fait non lu, pas seulement le compter")


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


# --- Minor de la revue finale : les deux chemins vers le code 2 ------------

def test_une_collecte_qui_LEVE_rend_2(monkeypatch):
    """Chemin non couvert, releve le 30/10. Une collecte qui leve doit rendre
    2 (« je n'ai pas pu juger »), jamais 1 (« quelque chose a bloque ») : sur
    une decision de rearmement, ces deux phrases ne disent pas la meme chose."""
    def _boom(_depot):
        raise RuntimeError("pont injoignable")
    monkeypatch.setattr(P, "collecter", _boom)
    assert P.main([]) == 2


def test_un_JUGE_qui_LEVE_rend_2(monkeypatch):
    """Meme exigence de l'autre cote : si `juger` leve, on ne conclut RIEN."""
    monkeypatch.setattr(P, "collecter", lambda _d: dict(ETAT))

    def _boom(_etat):
        raise ValueError("juge casse")
    monkeypatch.setattr(P, "juger", _boom)
    assert P.main([]) == 2


def test_le_mode_json_porte_le_caveat_de_configuration_DECLAREE(monkeypatch,
                                                                capsys):
    """Un consommateur machine perdait l'avertissement « seule la
    configuration DECLAREE est jugee ». Le code de sortie restait juste, mais
    la reserve disparaissait -- et c'est elle qui dit ce que l'outil NE prouve
    pas."""
    monkeypatch.setattr(P, "collecter", lambda _d: dict(ETAT))
    code = P.main(["--json"])
    sortie = capsys.readouterr().out
    assert code == 1
    import json as _j
    charge = _j.loads(sortie)          # doit rester lisible par json.loads
    texte = _j.dumps(charge).lower()
    assert "declaree" in texte or "declare" in texte, \
        "le JSON doit porter le caveat de configuration DECLAREE"
