"""Le message de clôture doit ANALYSER la sortie, pas seulement l'annoncer.

Demande de Xavier le 2026-08-25 : aligner la clôture sur l'ouverture, dire
pourquoi la position s'est fermée, si c'est dû à un stop remonté, et si la
perte était anticipable.

⛔ **La contrainte qui structure tout ce fichier.** Le contrôle aléatoire a
mesuré Δ = +0,004 R sur 29 000 trades : **il n'y a pas d'edge à la sélection
d'entrée**, et le score de confiance est anti-prédictif dans la bande 60-65.
Écrire « le score était bas, on aurait pu se méfier » fabriquerait une
causalité rétrospective — la 7ᵉ occurrence de « une valeur par défaut qui se
fait passer pour une mesure ». La réponse honnête à « anticipable ? » est
souvent **non, et c'est mesuré**.

Cf. [[project_controle_aleatoire_verdict_2026_08_05]] ·
    [[feedback_v1_score_anti_predictive_60_65]] ·
    [[project_edge_gestion_sorties_2026_08_11]]
"""
import pytest

from backend.services import telegram_service as ts

# ⚠️ Capturee AVANT que la fixture `_pas_de_reseau` ne la remplace. Sans ca,
# les deux tests qui veulent executer la vraie fonction appellent le stub —
# et concluent « None » quoi qu'il arrive, y compris sur un `NameError`.
# La fixture qui protege les autres tests cachait justement celui-la.
_VRAI_PARCOURS = ts._parcours_en_R


def _trade(**kw):
    base = {
        "pair": "XAU/USD", "direction": "sell",
        "entry_price": 4145.37, "exit_price": 4164.48,
        "stop_loss": 4164.48, "take_profit": 4105.90,
        "sl_at_close": None, "tp_at_close": None, "niveaux_source": None,
        "pnl": -16.40, "size_lot": 0.01, "close_reason": "SL",
        "mt5_ticket": 1356789012, "slippage_pips": None,
        "created_at": "2026-08-25T04:17:00+00:00",
        "closed_at": "2026-08-25T06:18:00+00:00",
        "signal_pattern": "breakout_down", "signal_confidence": 72.4,
    }
    base.update(kw)
    return base


@pytest.fixture(autouse=True)
def _pas_de_reseau(monkeypatch):
    """Par défaut aucun appel au bridge : les tests qui veulent un parcours
    le posent explicitement. Un test qui touche le réseau sans le vouloir
    mesurerait autre chose que ce qu'il croit."""
    monkeypatch.setattr(ts, "_parcours_en_R", lambda *a, **k: None)


# ─── La forme : miroir de l'ouverture ───────────────────────────────────


def test_la_ligne_miroir_compare_le_prevu_au_realise():
    """L'ouverture annonce « Risque −16,55 € → Objectif +34,17 € ». La clôture
    doit répondre sur la même ligne, sinon les deux messages ne se lisent pas
    ensemble."""
    texte = ts._format_close(_trade(), "admin_live")

    assert "Prévu" in texte and "Réalisé" in texte
    assert "16,40" in texte, "le montant réalisé, en euros et au format FR"


def test_le_pave_pourquoi_ce_trade_disparait_de_la_cloture():
    """Il est déjà dans le message d'ouverture, juste au-dessus dans le même
    fil. Le recopier à l'identique était du remplissage."""
    texte = ts._format_close(_trade(), "admin_live")

    assert "Pourquoi ce trade" not in texte


def test_un_gain_n_ouvre_pas_de_post_mortem_de_perte():
    """« Anticipable ? » n'a de sens que sur une perte."""
    texte = ts._format_close(
        _trade(pnl=34.17, close_reason="TP1", exit_price=4105.90), "admin_live")

    assert "Anticipable" not in texte


# ─── Le stop déplacé : trois cas, pas deux ──────────────────────────────


def test_stop_inchange_est_dit_explicitement():
    texte = ts._format_close(
        _trade(sl_at_close=4164.48, niveaux_source="monitor"), "admin_live")

    assert "n'avait pas bougé" in texte


def test_stop_deplace_en_ta_faveur_designe_le_MECANISME_pas_le_marche():
    """Un stop remonté qui se fait toucher, c'est un geste du système. Le
    ranger avec « le marché s'est retourné » masquerait la cause."""
    texte = ts._format_close(
        _trade(sl_at_close=4155.00, exit_price=4155.00, pnl=-8.30,
               niveaux_source="monitor"), "admin_live")

    assert "4155" in texte
    assert "remonté" in texte or "déplacé" in texte


def test_stop_AU_DELA_de_l_entree_n_est_PAS_une_perte():
    """Le cas qui porte toute la mesure de la gestion de sortie : un stop
    remonté au-delà de l'entrée neutralise la position AVANT qu'elle ait payé.
    C'est le coût exact qu'on soupçonne (−0,329 R sur l'or). Le ranger avec les
    stops ordinaires effacerait ce qu'on cherche.
    """
    texte = ts._format_close(
        _trade(sl_at_close=4140.00, exit_price=4140.00, pnl=4.30,
               niveaux_source="monitor"), "admin_live")

    assert "neutralis" in texte.lower()


def test_sans_niveau_capture_on_ne_dit_RIEN_du_stop():
    """Avant le 25/08 les niveaux vivants n'existaient pas. Affirmer « le stop
    n'avait pas bougé » sur cette base serait faux dans 44 % des cas."""
    texte = ts._format_close(_trade(sl_at_close=None, niveaux_source=None),
                             "admin_live")

    assert "n'avait pas bougé" not in texte


# ─── La perte était-elle dans le contrat ? ──────────────────────────────


def test_une_perte_conforme_au_risque_annonce_est_dite_normale():
    texte = ts._format_close(_trade(), "admin_live")

    assert "conforme" in texte.lower()


def test_une_perte_SUPERIEURE_au_risque_annonce_est_une_anomalie(monkeypatch):
    """Là il s'est passé quelque chose : glissement, trou de cotation, stop non
    respecté. C'est le seul cas où « anticipable » a une vraie réponse."""
    monkeypatch.setattr(ts, "_frais_de_portage", lambda t: None)
    texte = ts._format_close(_trade(pnl=-48.0, exit_price=4200.0), "admin_live")

    assert "⚠️" in texte
    assert "au-delà" in texte.lower() or "supérieur" in texte.lower()


def test_un_depassement_EXPLIQUE_par_le_swap_n_est_pas_une_anomalie(monkeypatch):
    """⛔ Constaté sur un vrai trade le 25/08 : EUR/GBP tenu 4j19h, perte
    −4,64 € contre −3,30 € annoncés. Annoncer « glissement ou trou de
    cotation » aurait été FAUX — l'écart est le coût de portage, accumulé nuit
    après nuit. Un mécanisme normal présenté comme une anomalie ferait chercher
    un défaut qui n'existe pas.
    """
    # Risque annoncé ≈ 16,55 € ; perte 20,00 € ⇒ dépassement 3,45 €, dont
    # 2,50 € de portage : le mécanisme couvre l'essentiel de l'écart.
    monkeypatch.setattr(ts, "_frais_de_portage", lambda t: -2.50)
    texte = ts._format_close(_trade(pnl=-20.00), "admin_live")

    assert "portage" in texte.lower() or "swap" in texte.lower()
    assert "glissement" not in texte.lower()


def test_un_depassement_NON_explique_par_le_swap_reste_une_anomalie(monkeypatch):
    """Le swap ne doit pas devenir l'excuse universelle : s'il ne couvre qu'une
    fraction de l'écart, l'alerte reste."""
    monkeypatch.setattr(ts, "_frais_de_portage", lambda t: -0.20)
    texte = ts._format_close(_trade(pnl=-48.0, exit_price=4200.0), "admin_live")

    assert "⚠️" in texte
    assert "glissement" in texte.lower()


# ─── Le chemin du prix ──────────────────────────────────────────────────


def test_un_trade_monte_puis_rendu_est_appele_un_GAIN_RENDU(monkeypatch):
    monkeypatch.setattr(ts, "_parcours_en_R",
                        lambda *a, **k: {"mfe_R": 0.83, "mae_R": -1.0})
    texte = ts._format_close(_trade(), "admin_live")

    assert "0,83" in texte or "0.83" in texte
    assert "rendu" in texte.lower()


def test_un_GAIN_ne_se_dit_pas_retourne(monkeypatch):
    """⛔ Constaté sur un vrai trade : un TP1 atteint affichait « monté à
    +1,86 R avant de se retourner ». Il ne s'est pas retourné, il a touché sa
    cible. Sur un gain, le point haut se dit sans récit — il mesure ce qui
    restait sur la table, pas un échec."""
    monkeypatch.setattr(ts, "_parcours_en_R",
                        lambda *a, **k: {"mfe_R": 1.86, "mae_R": -0.2})
    texte = ts._format_close(
        _trade(pnl=34.17, close_reason="TP1", exit_price=4105.90), "admin_live")

    assert "1,86" in texte
    assert "se retourner" not in texte
    assert "rendu" not in texte.lower()


def test_un_trade_jamais_passe_au_vert_est_dit_contre_le_marche(monkeypatch):
    monkeypatch.setattr(ts, "_parcours_en_R",
                        lambda *a, **k: {"mfe_R": 0.02, "mae_R": -1.0})
    texte = ts._format_close(_trade(), "admin_live")

    assert "jamais" in texte.lower()


def test_un_bridge_muet_ne_produit_AUCUNE_supposition(monkeypatch):
    """`_parcours_en_R` rend None quand `/rates` ne répond pas. Le bloc doit
    disparaître, jamais être remplacé par une valeur par défaut."""
    monkeypatch.setattr(ts, "_parcours_en_R", lambda *a, **k: None)
    texte = ts._format_close(_trade(), "admin_live")

    assert "rendu" not in texte.lower()
    assert "jamais passé" not in texte.lower()
    assert "0,00 R" not in texte, "un zéro par défaut serait lu comme une mesure"


# ─── ⛔ Le refus de fabriquer une causalité ─────────────────────────────


def test_le_score_est_affiche_MAIS_desarme():
    """Mesuré Δ=+0,004 R sur 29 000 trades : le score ne prédit rien. L'afficher
    sans le dire inviterait à en tirer un signal."""
    texte = ts._format_close(_trade(), "admin_live")

    assert "72" in texte
    assert "prédictif" in texte or "prédit" in texte


# ─── La fonction reseau elle-meme, VRAIMENT executee ────────────────────


def test_parcours_en_R_s_execute_pour_de_vrai(monkeypatch):
    """⛔ Trouvé en production le 2026-08-25 : `_parcours_en_R` levait
    `NameError: json is not defined`, et son `except Exception` l'avalait. Le
    bloc disparaissait du message exactement comme si le bridge était muet.

    **Tous les autres tests de ce fichier remplacent `_parcours_en_R`** — donc
    aucun ne l'exécutait, et un nom non défini pouvait survivre au vert. Celui-ci
    la fait tourner de bout en bout, avec le réseau seul remplacé.

    > Un garde-fou qui transforme un bug de programmation en « donnée
    > indisponible » ne protège pas : il cache. Il faut un test qui passe DANS
    > la fonction. Cf. [[feedback_source_inspection_tests_weak]].
    """
    import io
    import json as _json

    class _Reponse(io.StringIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setenv("MT5_BRIDGE_LIVE_URL", "http://bridge-de-test:8788")
    monkeypatch.setenv("MT5_BRIDGE_LIVE_API_KEY", "cle")
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **k: _Reponse(_json.dumps(
            {"bougies": [{"h": 4150.0, "l": 4120.0}, {"h": 4170.0, "l": 4140.0}]})))

    r = _VRAI_PARCOURS(_trade(), "admin_live")

    assert r is not None, "la fonction n'a pas abouti — regarde le log DEBUG"
    assert r["mfe_R"] > 0


def test_frais_de_portage_s_execute_pour_de_vrai(tmp_path, monkeypatch):
    """Même exigence que pour `_parcours_en_R` : cette fonction a elle aussi un
    `except Exception` qui rendrait un `NameError` indiscernable d'une donnée
    absente. Elle doit être exécutée, pas seulement remplacée."""
    import sqlite3

    db = tmp_path / "trades.db"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE broker_close_snapshots ("
                  "ticket INTEGER PRIMARY KEY, swap REAL, commission REAL, fee REAL)")
        c.execute("INSERT INTO broker_close_snapshots VALUES (42, -1.20, -0.15, 0)")
    monkeypatch.setattr("backend.services.trade_log_service._DB_PATH", db)

    assert ts._frais_de_portage(42) == pytest.approx(-1.35)
    assert ts._frais_de_portage(999) is None, "ticket absent : on ne suppose pas 0"
    assert ts._frais_de_portage(None) is None


def test_parcours_en_R_avale_une_panne_reseau_sans_casser(monkeypatch):
    """Le seul cas où rendre None est légitime : le bridge ne répond pas.
    Cet appel entre dans le flux de clôture, il ne doit jamais propager."""
    monkeypatch.setenv("MT5_BRIDGE_LIVE_URL", "http://bridge-de-test:8788")

    def _boum(*a, **k):
        raise OSError("connexion refusée")
    monkeypatch.setattr("urllib.request.urlopen", _boum)

    assert _VRAI_PARCOURS(_trade(), "admin_live") is None


# ─── Precision : la troncature et le spread ─────────────────────────────
#
# Mesure du 2026-08-25 sur 35 trades du demo :
#   bougies M1 AMBIGUES (SL et TP dans la meme minute)   0 / 35
#   fenetres TRONQUEES silencieusement                   3 / 35
#   spread max de la fenetre, en % du risque      mediane 1 % · pire 29 %
#
# ⇒ Passer aux ticks ne servirait a RIEN : l'ordre intra-bougie ne se pose
#   jamais. En revanche la troncature et le spread mordent pour de vrai.


def _repondeur(reponses):
    """Rend un faux `urlopen` qui repond selon le `timeframe` demande."""
    import io
    import json as _json

    class _R(io.StringIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def _ouvrir(requete, *a, **k):
        url = requete.full_url if hasattr(requete, "full_url") else str(requete)
        tf = next((t for t in ("M15", "M5", "M1") if f"timeframe={t}" in url), "M1")
        return _R(_json.dumps(reponses[tf]))
    return _ouvrir


def _payload(n, tronque, bougies=None):
    return {"n": n, "tronque": tronque, "point": 0.01,
            "bougies": bougies or [{"h": 4150.0, "l": 4120.0, "s": 20}]}


def test_une_fenetre_TRONQUEE_fait_passer_a_un_pas_plus_large(monkeypatch):
    """⛔ Le bridge coupe a 5 000 bougies et le DIT (`tronque`). Ignorer ce
    drapeau, c'est mesurer le DEBUT du trade et presenter le resultat comme
    s'il portait sur toute sa vie. Mesure : 3 trades sur 35 — des positions
    crypto tenues 40 jours, pour lesquelles M15 suffit.
    """
    monkeypatch.setenv("MT5_BRIDGE_LIVE_URL", "http://bridge-de-test:8788")
    monkeypatch.setattr("urllib.request.urlopen", _repondeur({
        "M1": _payload(5000, True),
        "M5": _payload(5000, True),
        "M15": _payload(3897, False,
                        [{"h": 4200.0, "l": 4100.0, "s": 20}]),
    }))

    r = _VRAI_PARCOURS(_trade(), "admin_live")

    assert r is not None
    assert r["pas"] == "M15", "il faut remonter jusqu'au pas qui couvre tout"


def test_si_AUCUN_pas_ne_couvre_la_fenetre_on_ne_conclut_pas(monkeypatch):
    """Mieux vaut pas de mesure qu'une mesure partielle presentee comme
    entiere. Cf. [[feedback_detection_par_absence]]."""
    monkeypatch.setenv("MT5_BRIDGE_LIVE_URL", "http://bridge-de-test:8788")
    monkeypatch.setattr("urllib.request.urlopen", _repondeur({
        "M1": _payload(5000, True), "M5": _payload(5000, True),
        "M15": _payload(5000, True)}))

    assert _VRAI_PARCOURS(_trade(), "admin_live") is None


def test_sur_une_VENTE_le_spread_est_retire_du_gain(monkeypatch):
    """Les bougies MT5 sont en BID. Sur une vente, on entre au bid mais on
    rachete a l'ASK : le meilleur point atteignable est `plus bas + spread`.
    Compter le bid nu surestime le gain — d'autant plus que le spread explose
    justement quand les stops se font toucher (jusqu'a 29 % du risque).
    """
    bougies = [{"h": 4150.0, "l": 4120.0, "s": 100}]   # 100 pts x 0,01 = 1,00
    sans = ts._mfe_mae(bougies, entry=4145.37, risque=19.11, achat=False, point=0)
    avec = ts._mfe_mae(bougies, entry=4145.37, risque=19.11, achat=False, point=0.01)

    assert avec["mfe_R"] < sans["mfe_R"], "le spread doit reduire le gain"
    assert avec["mfe_R"] == pytest.approx((4145.37 - (4120.0 + 1.0)) / 19.11, abs=0.01)


def test_sur_un_ACHAT_le_spread_ne_se_paie_pas_deux_fois():
    """L'entree etait deja a l'ask (c'est le fill enregistre) et la sortie se
    fait au bid, que les bougies donnent directement. Retirer encore un spread
    facturerait le cout deux fois."""
    bougies = [{"h": 4150.0, "l": 4120.0, "s": 100}]
    sans = ts._mfe_mae(bougies, entry=4145.37, risque=19.11, achat=True, point=0)
    avec = ts._mfe_mae(bougies, entry=4145.37, risque=19.11, achat=True, point=0.01)

    assert avec["mfe_R"] == sans["mfe_R"]


def test_le_spread_pris_est_celui_de_la_bougie_de_l_EXTREME():
    """Un spread moyen lisserait justement le pic qui compte. Le point haut se
    paie au spread de SA minute, pas a celui du reste du trade."""
    bougies = [
        {"h": 4150.0, "l": 4130.0, "s": 1},      # spread calme
        {"h": 4150.0, "l": 4120.0, "s": 200},    # l'extreme, spread ecarte
    ]
    r = ts._mfe_mae(bougies, entry=4145.37, risque=19.11, achat=False, point=0.01)

    assert r["mfe_R"] == pytest.approx((4145.37 - (4120.0 + 2.0)) / 19.11, abs=0.01)


# ─── Le calcul du parcours ──────────────────────────────────────────────

_BOUGIES = [{"h": 4150.0, "l": 4120.0}, {"h": 4170.0, "l": 4140.0}]


def test_sur_un_ACHAT_le_meilleur_point_est_le_plus_haut():
    r = ts._mfe_mae(_BOUGIES, entry=4145.37, risque=19.11, achat=True)

    assert r["mfe_R"] == pytest.approx((4170.0 - 4145.37) / 19.11, abs=0.01)
    assert r["mae_R"] == pytest.approx((4120.0 - 4145.37) / 19.11, abs=0.01)


def test_sur_une_VENTE_le_meilleur_point_est_le_plus_BAS():
    """L'inversion est le seul endroit où l'erreur serait silencieuse : prendre
    le plus haut sur une vente rendrait un MFE négatif, qu'on lirait comme
    « jamais passé au vert » — donc une conclusion inversée."""
    r = ts._mfe_mae(_BOUGIES, entry=4145.37, risque=19.11, achat=False)

    assert r["mfe_R"] == pytest.approx((4145.37 - 4120.0) / 19.11, abs=0.01)
    assert r["mfe_R"] > 0, "la vente a bien été gagnante à un moment"
    assert r["mae_R"] < 0


@pytest.mark.parametrize("bougies,risque", [
    ([], 19.11),                                  # bridge muet
    ([{"h": None, "l": None}], 19.11),            # bougies inexploitables
    (_BOUGIES, 0),                                # pas de distance au stop
])
def test_sans_matiere_le_parcours_rend_None_jamais_zero(bougies, risque):
    assert ts._mfe_mae(bougies, 4145.37, risque, False) is None


@pytest.mark.parametrize("interdit", [
    "on aurait pu", "aurait dû", "il fallait", "signal faible",
    "score bas", "se méfier",
])
def test_aucune_causalite_retrospective_n_est_ecrite(interdit):
    """Le contrôle aléatoire dit qu'il n'y a rien à anticiper à l'entrée.
    Toute phrase qui suggère le contraire est une mesure inventée."""
    for conf in (18.0, 62.0, 95.0):
        texte = ts._format_close(_trade(signal_confidence=conf), "admin_live")
        assert interdit not in texte.lower(), f"score {conf} : « {interdit} »"
