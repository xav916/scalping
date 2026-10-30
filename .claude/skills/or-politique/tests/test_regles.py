import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import regles as R  # noqa: E402

# admin_kraken, releve REEL du 2026-10-30.
KRAKEN = {
    "destination_id": "admin_kraken", "bridge_type": "kraken", "reel": True,
    "min_confidence": 42.0, "classes_porte": ["crypto"],
    "classes_registre": ["crypto", "metal"], "connue_du_registre": True,
    "garde_fous": {},
}
# admin_live, releve REEL du 2026-10-30.
LIVE = {
    "destination_id": "admin_live", "bridge_type": "mt5", "reel": True,
    "min_confidence": 42.0, "classes_porte": ["energy", "forex", "metal"],
    "classes_registre": ["energy", "equity", "forex", "metal"],
    "connue_du_registre": True,
    "garde_fous": {"max_open_positions": 10, "max_daily_loss_pct": 10.0},
}
LEGACY = dict(LIVE, destination_id="admin_legacy", reel=False,
              classes_registre=["energy", "forex", "metal"])
BLANCHES = {"admin_live": ["XAU/USD"], "admin_legacy": ["AUD/USD"]}


def _regle(dest, n, blanches=BLANCHES):
    return next(v for v in R.juger_destination(dest, blanches)
                if v["regle"] == n)


def test_cinq_verdicts_un_par_regle():
    v = R.juger_destination(KRAKEN, BLANCHES)
    assert [x["regle"] for x in v] == [1, 2, 3, 4, 5]


def test_regle1_FAIL_sur_argent_reel_sans_filtre():
    v = _regle(KRAKEN, 1)
    assert v["verdict"] == R.FAIL
    assert "admin_kraken" in v["valeur"] or "aucun" in v["valeur"].lower()


def test_regle1_CONFORME_quand_une_liste_existe():
    assert _regle(LIVE, 1)["verdict"] == R.CONFORME


def test_regle1_NON_APPLICABLE_sans_argent_reel():
    assert _regle(LEGACY, 1)["verdict"] == R.NON_APPLICABLE


def test_regle2_FAIL_quand_garde_fous_vide_et_argent_reel():
    assert _regle(KRAKEN, 2)["verdict"] == R.FAIL


def test_regle2_CONFORME_quand_le_pont_publie_ses_gardes():
    assert _regle(LIVE, 2)["verdict"] == R.CONFORME


def test_regle3_FAIL_sur_seuil_nul_ou_absent():
    for mauvais in (0, 0.0, None):
        assert _regle(dict(LIVE, min_confidence=mauvais), 3)["verdict"] == R.FAIL
    assert _regle(LIVE, 3)["verdict"] == R.CONFORME


def test_regle4_FAIL_si_inconnue_du_registre():
    v = _regle(dict(LIVE, connue_du_registre=False), 4)
    assert v["verdict"] == R.FAIL


def test_regle5_une_porte_plus_ETROITE_est_CONFORME():
    """CORRIGE le 2026-10-30. Cette regle criait sur toute difference, d'ou
    deux WARN permanents sur les deux destinations en argent reel.

    Or `asset_classes` du registre est une CAPACITE (« classes que ce broker
    ACCEPTE ») et `allowed_asset_classes` une PERMISSION. Le registre le dit
    lui-meme pour `metal` sur Kraken : « cette ligne ne suffit PAS a les
    faire trader ». Une porte plus etroite est donc la prudence NORMALE.
    """
    assert _regle(LIVE, 5)["verdict"] == R.CONFORME
    assert _regle(KRAKEN, 5)["verdict"] == R.CONFORME


def test_regle5_dit_quand_meme_ce_que_le_courtier_accepte_en_PLUS():
    """L'information n'est pas perdue : on arrete de l'appeler alarme, on ne
    cesse pas de la publier."""
    v = _regle(KRAKEN, 5)
    assert "crypto" in v["valeur"]
    assert "metal" in v["valeur"], "la capacite excedentaire doit rester lisible"


def test_regle5_WARN_quand_la_PORTE_DEPASSE_la_capacite():
    """LE sens qui compte : une classe autorisee que le courtier n'accepte
    pas. Le flux est alors « simplement refuse, en silence »."""
    trop = dict(KRAKEN, classes_porte=["crypto", "equity"],
                classes_registre=["crypto", "metal"])
    v = _regle(trop, 5)
    assert v["verdict"] == R.WARN
    assert "equity" in v["valeur"]
    assert "metal" not in v["valeur"], (
        "seule la classe EN TROP doit etre nommee, pas la capacite inutilisee")


def test_regle5_ne_rend_JAMAIS_un_FAIL():
    """Choix d'origine conserve : ce defaut bloque le flux, il n'expose pas
    d'argent. Il merite un WARN, pas l'arret du rapport."""
    for d in (LIVE, KRAKEN, LEGACY,
              dict(KRAKEN, classes_porte=["crypto", "equity"]),
              dict(KRAKEN, classes_porte=[]),
              dict(KRAKEN, classes_porte=[], classes_registre=[])):
        assert _regle(d, 5)["verdict"] != R.FAIL


def test_regle5_WARN_sur_une_porte_VIDE():
    """Une porte vide n'est pas une divergence, c'est un blocage TOTAL : il
    merite d'etre vu plutot que lu comme un « conforme »."""
    v = _regle(dict(KRAKEN, classes_porte=[]), 5)
    assert v["verdict"] == R.WARN
    assert "AUCUNE" in v["valeur"]

def test_chaque_verdict_nomme_sa_SOURCE_et_sa_VALEUR():
    for v in R.juger_destination(KRAKEN, BLANCHES):
        assert v["source"], "regle %d sans source" % v["regle"]
        assert v["valeur"] != "", "regle %d sans valeur lue" % v["regle"]


def test_argent_reel_sans_filtre_ET_sans_garde_rend_DEUX_fail():
    """Les deux disent la meme inquietude par deux chemins : les fondre en un
    seul motif ferait croire qu'il n'y a qu'un probleme."""
    faux = [v for v in R.juger_destination(KRAKEN, BLANCHES)
            if v["verdict"] == R.FAIL]
    assert len(faux) == 2
    assert {v["regle"] for v in faux} == {1, 2}


def test_admin_legacy_ne_declenche_AUCUN_fail():
    """Une skill qui alerte sur un compte papier crie au loup."""
    assert not [v for v in R.juger_destination(LEGACY, BLANCHES)
                if v["verdict"] == R.FAIL]


def test_regle3_ILLISIBLE_sur_min_confidence_non_numerique():
    """min_confidence non interpretable -> ILLISIBLE, pas d'exception."""
    for mauvais in ("abc", "string", [], {}):
        v = _regle(dict(LIVE, min_confidence=mauvais), 3)
        assert v["verdict"] == R.ILLISIBLE, "min_confidence=%r devrait donner ILLISIBLE, pas %s" % (mauvais, v["verdict"])


def test_regle2_ILLISIBLE_sur_garde_fous_non_sizable():
    """garde_fous non sizable (ex: int) -> ILLISIBLE, pas d'exception."""
    v = _regle(dict(LIVE, garde_fous=42), 2)
    assert v["verdict"] == R.ILLISIBLE


def test_regle2_FAIL_quand_garde_fous_est_dict_vide():
    """garde_fous={} est une reponse valide (rien publie) -> FAIL, pas ILLISIBLE."""
    v = _regle(dict(LIVE, garde_fous={}), 2)
    assert v["verdict"] == R.FAIL


def test_juger_destination_ne_leve_jamais_sur_dest_malformee():
    """juger_destination accepte les donnees malformees, ne leve pas."""
    malformees = [
        dict(LIVE, min_confidence="not_a_number"),
        dict(LIVE, garde_fous=123),
        dict(LIVE, garde_fous=None),
        dict(LIVE, classes_porte=None),
        dict(LIVE, classes_registre=None),
        {},  # dest vide
        dict(LIVE, destination_id=None),
    ]
    for dest in malformees:
        verdicts = R.juger_destination(dest, BLANCHES)
        assert len(verdicts) == 5, "dest %r devrait rendre 5 verdicts" % dest
        # Ne doit pas lever, verification basique
        for v in verdicts:
            assert "regle" in v
            assert "verdict" in v


# --- deux mecanismes de filtre, deux semantiques du VIDE ------------------
# Pose le 2026-10-30 avec le filtre backend d'`admin_kraken`.
#
# 🔑 La meme absence veut dire l'INVERSE des deux cotes :
#   - liste blanche MT5 vide  -> `if LIVE_WHITELIST_PAIRS and ...` -> AUCUN
#     filtrage, donc FAIL ;
#   - filtre backend Kraken vide -> RIEN ne passe, donc protection MAXIMALE.
# La regle 1 ne doit pas deduire laquelle s'applique du nom de la
# destination : la semantique est portee par la MAP ou elle apparait.

def test_un_filtre_backend_VIDE_est_CONFORME_car_il_bloque_tout():
    v = next(x for x in R.juger_destination(
        KRAKEN, BLANCHES, filtres_backend={"admin_kraken": []})
        if x["regle"] == 1)
    assert v["verdict"] == R.CONFORME
    assert "bloque" in v["valeur"].lower() or "aucune" in v["valeur"].lower()


def test_un_filtre_backend_NON_vide_est_CONFORME_et_nomme_ses_paires():
    v = next(x for x in R.juger_destination(
        KRAKEN, BLANCHES, filtres_backend={"admin_kraken": ["BTC/USD"]})
        if x["regle"] == 1)
    assert v["verdict"] == R.CONFORME
    assert "BTC/USD" in v["valeur"]


def test_sans_AUCUN_mecanisme_la_regle_1_reste_FAIL():
    """L'etat d'`admin_kraken` AVANT le 30/10 : rien ne filtre."""
    v = next(x for x in R.juger_destination(KRAKEN, BLANCHES,
                                            filtres_backend={})
             if x["regle"] == 1)
    assert v["verdict"] == R.FAIL


def test_une_liste_blanche_MT5_VIDE_reste_FAIL():
    """Semantique inverse : cote MT5, vide signifie « pas de filtrage »."""
    v = next(x for x in R.juger_destination(
        dict(LIVE, destination_id="admin_live"), {"admin_live": []},
        filtres_backend={}) if x["regle"] == 1)
    assert v["verdict"] == R.FAIL


def test_filtres_backend_est_OPTIONNEL_et_vaut_absence():
    """Compatibilite : les appels existants ne le passent pas."""
    v = next(x for x in R.juger_destination(KRAKEN, BLANCHES)
             if x["regle"] == 1)
    assert v["verdict"] == R.FAIL


def test_la_charge_n_inscrit_PAS_un_filtre_absent():
    """FAUX-SUR trouve le 2026-10-30 : la charge inscrivait `admin_kraken`
    dans `filtres_backend` des que le MODULE s'importait, sans verifier que
    la CONSTANTE existe. Sur un conteneur ou le filtre n'est pas deploye,
    elle rapportait donc regle 1 CONFORME -- une protection affirmee qui
    n'existe pas. C'est le pire defaut que cette skill puisse produire.

    La distinction est subtile et doit rester explicite : `absent` n'est pas
    `vide`. Vide = tout bloque (CONFORME). Absent = rien ne filtre (FAIL).
    """
    import pathlib
    src = pathlib.Path(
        pathlib.Path(__file__).resolve().parents[1] / "politique.py"
    ).read_text(encoding="utf-8")
    assert "_SENTINELLE" in src or "hasattr(_kbc" in src, (
        "la charge doit distinguer « constante ABSENTE » de « liste VIDE » : "
        "sans sentinelle, un filtre non deploye passe pour une protection")
    assert 'BACKEND["admin_kraken"] = sorted(\n' not in src.replace(" ", ""), \
        "l'inscription ne doit pas etre inconditionnelle"


# --- Minor de la revue finale : `len(gf)` est un FAUX-SUR ------------------

def test_un_garde_fous_NON_DICT_est_ILLISIBLE_et_non_CONFORME():
    """La regle 2 testait la lisibilite par `len(gf)`. Un `garde_fous` publie
    comme CHAINE non vide (ou comme liste) a donc un `len()` et sortait
    `CONFORME « N champ(s) »` -- en annoncant N garde-fous la ou il n'y en a
    aucun. Faux-sur releve par la revue finale du 30/10."""
    for faux in ("garde_fous", ["a", "b"], ("x",), 7, 3.5):
        v = next(x for x in R.juger_destination(
            dict(KRAKEN, garde_fous=faux), BLANCHES,
            filtres_backend={"admin_kraken": []}) if x["regle"] == 2)
        assert v["verdict"] == R.ILLISIBLE, (
            "garde_fous=%r (%s) doit etre ILLISIBLE, pas %s"
            % (faux, type(faux).__name__, v["verdict"]))


def test_un_vrai_dict_de_garde_fous_reste_CONFORME():
    """Temoin POSITIF : sans lui, un `isinstance` trop strict rendrait tout
    ILLISIBLE et la regle 2 ne dirait plus jamais rien d'utile."""
    v = next(x for x in R.juger_destination(
        dict(KRAKEN, garde_fous={"max_open_positions": 10}), BLANCHES,
        filtres_backend={"admin_kraken": []}) if x["regle"] == 2)
    assert v["verdict"] == R.CONFORME
    assert "1" in v["valeur"]
