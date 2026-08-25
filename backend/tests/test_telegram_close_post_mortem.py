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


def test_une_perte_SUPERIEURE_au_risque_annonce_est_une_anomalie():
    """Là il s'est passé quelque chose : glissement, trou de cotation, stop non
    respecté. C'est le seul cas où « anticipable » a une vraie réponse."""
    texte = ts._format_close(_trade(pnl=-48.0, exit_price=4200.0), "admin_live")

    assert "⚠️" in texte
    assert "au-delà" in texte.lower() or "supérieur" in texte.lower()


# ─── Le chemin du prix ──────────────────────────────────────────────────


def test_un_trade_monte_puis_rendu_est_appele_un_GAIN_RENDU(monkeypatch):
    monkeypatch.setattr(ts, "_parcours_en_R",
                        lambda *a, **k: {"mfe_R": 0.83, "mae_R": -1.0})
    texte = ts._format_close(_trade(), "admin_live")

    assert "0,83" in texte or "0.83" in texte
    assert "rendu" in texte.lower()


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
