"""La règle d'arrêt de l'or : alerter sans couper, et ne jamais laisser la main
masquer les pertes du code.

## ⛔ CE QUE CES TESTS ÉPINGLENT

Le 2026-10-01, tous les horizons de l'or ont été ouverts sur l'argent réel
(`dc3c067`), contre le laboratoire (0 retenue sur 232 cellules). Aucune règle
d'arrêt n'était posée une semaine plus tard.

🔑 **Le piège propre à l'or**, mesuré le 07/10 à 18h58 UTC. Les chiffres qui
suivent sont ceux de la **journée entière du 01/10** (25 ordres) ; la fenêtre
que la règle applique réellement part de 16h35 UTC et donne −16,78 € / +39,69 €
sur 21 ordres. **Les deux fenêtres disent la même chose.**

    fermetures AUTOMATIQUES  18   −22,25 €   7 gagnants
    fermetures À LA MAIN      6   +72,34 €   6 gagnants
    ─────────────────────────────────────────
    total                         +50,09 €

⇒ Une borne de perte posée sur le **total** ne tomberait **jamais**, alors que
le code perd. C'est l'invariant central ici : `test_la_main_ne_masque_pas`.

⚠️ Et l'or n'est pas le WTI : la main ne ferme que ce que l'algorithme
**ouvre**. Couper l'or couperait les deux. D'où le mode alerte par défaut.
"""
from __future__ import annotations

import sqlite3

import pytest

from backend.services import regle_arret_or as ra


DEPUIS = "2026-10-01T16:35:48+00:00"
APRES = "2026-10-02T10:00:00+00:00"
AVANT = "2026-09-30T10:00:00+00:00"


@pytest.fixture
def base(tmp_path):
    chemin = tmp_path / "trades.db"
    with sqlite3.connect(chemin) as c:
        c.execute("""CREATE TABLE personal_trades (
            id INTEGER PRIMARY KEY, pair TEXT, status TEXT, pnl REAL,
            close_reason TEXT, created_at TEXT, destination_id TEXT)""")
    return chemin


def _trade(chemin, i, pnl=None, close_reason=None, status="CLOSED",
           pair="XAU/USD", dest="admin_live", quand=APRES):
    with sqlite3.connect(chemin) as c:
        c.execute("INSERT INTO personal_trades VALUES (?,?,?,?,?,?,?)",
                  (i, pair, status, pnl, close_reason, quand, dest))


# ─── Le relevé ────────────────────────────────────────────────────────────

def test_separe_l_automatique_de_la_main(base):
    """Les deux sommes sont tenues séparément, chacune avec son compte."""
    _trade(base, 1, pnl=-13.07, close_reason="SL")
    _trade(base, 2, pnl=20.85, close_reason="EXPERT")
    _trade(base, 3, pnl=2.69, close_reason="TRAILING_SL")
    _trade(base, 4, pnl=12.55, close_reason="MANUAL")
    _trade(base, 5, pnl=8.43, close_reason="MANUAL")

    m = ra.releve(base, DEPUIS)
    assert m["ordres"] == 5
    assert m["ordres_auto"] == 3
    assert m["pnl_auto"] == pytest.approx(-13.07 + 20.85 + 2.69)
    assert m["ordres_main"] == 2
    assert m["pnl_main"] == pytest.approx(12.55 + 8.43)


def test_une_position_ouverte_compte_dans_les_ordres_pas_dans_l_argent(base):
    """`close_reason` NULL = encore ouverte. Elle consomme du budget, pas de P&L."""
    _trade(base, 1, pnl=None, close_reason=None, status="OPEN")

    m = ra.releve(base, DEPUIS)
    assert m["ordres"] == 1
    assert m["ordres_auto"] == 0
    assert m["pnl_auto"] == 0.0
    # ⛔ ouverte n'est pas « clôturée sans montant » : la couverture reste intacte
    assert m["sans_pnl"] == 0


def test_une_cloture_sans_montant_est_comptee_comme_telle(base):
    """Le trou de couverture doit être VU, parce que sum() l'avale en silence."""
    _trade(base, 1, pnl=None, close_reason="SL", status="CLOSED")
    _trade(base, 2, pnl=-5.0, close_reason="SL", status="CLOSED")

    m = ra.releve(base, DEPUIS)
    assert m["sans_pnl"] == 1
    assert m["couverture"] == pytest.approx(0.5)
    assert m["pnl_auto"] == pytest.approx(-5.0)


def test_ignore_les_autres_paires_destinations_et_l_avant(base):
    """La fenêtre de l'expérience, et elle seule."""
    _trade(base, 1, pnl=-99.0, close_reason="SL", pair="XAG/USD")
    _trade(base, 2, pnl=-99.0, close_reason="SL", dest="admin_demo")
    _trade(base, 3, pnl=-99.0, close_reason="SL", quand=AVANT)
    _trade(base, 4, pnl=-1.0, close_reason="SL")

    m = ra.releve(base, DEPUIS)
    assert m["ordres"] == 1
    assert m["pnl_auto"] == pytest.approx(-1.0)


def test_base_injoignable_rend_none_pas_un_zero(base, tmp_path):
    """⛔ « Je n'ai pas pu regarder » n'est pas « rien à signaler »."""
    assert ra.releve(tmp_path / "inexistante.db", DEPUIS) is None


# ─── Le verdict ───────────────────────────────────────────────────────────

def test_la_main_ne_masque_pas_les_pertes_du_code(base):
    """🔑 L'INVARIANT CENTRAL — chiffres réels, journée entière du 01/10.

    Total +50,09 € mais automatique −22,25 €. Une borne posée sur le total ne
    tomberait jamais ; posée sur l'automatique, elle voit la perte.
    """
    _trade(base, 1, pnl=-80.74, close_reason="SL")
    _trade(base, 2, pnl=52.98, close_reason="EXPERT")
    _trade(base, 3, pnl=5.51, close_reason="TRAILING_SL")
    _trade(base, 4, pnl=72.34, close_reason="MANUAL")

    m = ra.releve(base, DEPUIS)
    assert m["pnl_auto"] + m["pnl_main"] == pytest.approx(50.09)  # le total trompe
    assert m["pnl_auto"] == pytest.approx(-22.25)                 # la vérité du code

    v = ra.verdict(m)
    assert v["borne_atteinte"] is False          # −22,25 € est au-dessus de −50
    assert "-22.25" in v["motif"] or "−22" in v["motif"].replace("−", "−")
    # la main est DITE, et l'avertissement sur ce qu'un arrêt coûterait aussi
    assert "+72.34" in v["motif"]
    assert "couper l'or la couperait aussi" in v["motif"]


def test_borne_de_perte_sur_l_automatique_seul(base, monkeypatch):
    monkeypatch.setattr(ra, "MAX_PERTE_EUR", -50.0)
    _trade(base, 1, pnl=-51.0, close_reason="SL")
    _trade(base, 2, pnl=500.0, close_reason="MANUAL")  # la main ne sauve rien

    v = ra.verdict(ra.releve(base, DEPUIS))
    assert v["borne_atteinte"] is True
    assert "sous la borne" in v["motif"]


def test_le_budget_d_ordres_compte_TOUTES_les_sorties(base, monkeypatch):
    """Chaque ordre est une décision d'OUVERTURE de l'algorithme."""
    monkeypatch.setattr(ra, "MAX_ORDRES", 3)
    for i in range(3):
        _trade(base, i + 1, pnl=10.0, close_reason="MANUAL")  # que des gains, à la main

    v = ra.verdict(ra.releve(base, DEPUIS))
    assert v["borne_atteinte"] is True
    assert "3 ordres atteints" in v["motif"]


def test_le_compteur_d_ordres_passe_avant_l_argent(base, monkeypatch):
    """Il ne dépend d'aucune valeur manquante : c'est le déclencheur principal."""
    monkeypatch.setattr(ra, "MAX_ORDRES", 2)
    monkeypatch.setattr(ra, "MAX_PERTE_EUR", -1.0)
    _trade(base, 1, pnl=-99.0, close_reason="SL")
    _trade(base, 2, pnl=-99.0, close_reason="SL")

    v = ra.verdict(ra.releve(base, DEPUIS))
    assert v["borne_atteinte"] is True
    assert "ordres atteints" in v["motif"]      # et pas le motif de perte


def test_releve_absent_ne_conclut_rien(base):
    """⛔ Annoncer une borne franchie sur une mesure absente, c'est inventer."""
    v = ra.verdict(None)
    assert v["borne_atteinte"] is False
    assert "indisponible" in v["motif"]


def test_la_couverture_est_annoncee_quand_elle_est_trouee(base):
    _trade(base, 1, pnl=None, close_reason="SL", status="CLOSED")
    _trade(base, 2, pnl=-1.0, close_reason="SL", status="CLOSED")

    v = ra.verdict(ra.releve(base, DEPUIS))
    assert "sans montant vérifié" in v["motif"]
    assert "50 %" in v["motif"]


def test_base_vide_ne_declenche_rien(base):
    m = ra.releve(base, DEPUIS)
    assert m["ordres"] == 0
    assert ra.verdict(m)["borne_atteinte"] is False


# ═════════════════════════════════════════════════════════════════════════
# ⛔ 2026-10-09 — L'ADOPTION A CONTAMINÉ LA RÈGLE
# ═════════════════════════════════════════════════════════════════════════
#
# L'adoption des positions du courtier (`ac2823b`, déployée le 2026-10-09) fait
# entrer dans `personal_trades` les trades que Xavier ouvre **dans le terminal
# MT5**, marqués `notes = 'MANUEL-TERM'`.
#
# 🔑 La règle sépare « automatique » et « main » par `close_reason`, c'est-à-dire
# par **qui a FERMÉ**. Or un trade né dans le terminal et fermé par son stop a
# `close_reason = 'SL'` : il atterrit donc dans la jambe **AUTOMATIQUE**, qui
# borne l'expérience.
#
# Mesuré le soir du déploiement, fenêtre de la règle :
#
#     jambe "auto"   RADAR     n=48    −6,96 €
#     jambe "auto"   TERMINAL  n= 7   −45,42 €   <- les stops de Xavier
#     ─────────────────────────────────────────
#     ce que la borne de −50 € regardait          −52,38 €
#
#     compteur d'ordres : RADAR 59 + TERMINAL 43 = 102, contre un budget de 60
#
# ⇒ **87 % de la « perte de l'automatique » étaient les stops de Xavier**, et la
# règle a franchi ses DEUX bornes le jour même du déploiement, par artefact.
#
# La séparation doit donc se faire sur **QUI A OUVERT**, pas seulement sur qui a
# fermé. Quatre populations, et seule la première borne quoi que ce soit.

def _base_avec_notes(tmp_path):
    """⛔ Le schéma de production porte `notes`. Un gabarit sans cette colonne
    rendrait ces tests verts pour une mauvaise raison — c'est exactement le
    défaut qui a fait croire, le matin du 09/10, que l'adoption marchait."""
    chemin = tmp_path / "trades_notes.db"
    with sqlite3.connect(chemin) as c:
        c.execute("""CREATE TABLE personal_trades (
            id INTEGER PRIMARY KEY, pair TEXT, status TEXT, pnl REAL,
            close_reason TEXT, created_at TEXT, destination_id TEXT,
            notes TEXT)""")
    return chemin


def _t(chemin, i, pnl=None, close_reason=None, notes=None, status="CLOSED",
       pair="XAU/USD", dest="admin_live", quand=APRES):
    with sqlite3.connect(chemin) as c:
        c.execute("INSERT INTO personal_trades VALUES (?,?,?,?,?,?,?,?)",
                  (i, pair, status, pnl, close_reason, quand, dest, notes))


@pytest.fixture
def base_n(tmp_path):
    return _base_avec_notes(tmp_path)


def test_un_stop_de_XAVIER_ne_compte_pas_dans_la_jambe_AUTOMATIQUE(base_n):
    """⛔ LE DÉFAUT DU 09/10. Un trade né dans le terminal et fermé par son
    stop a `close_reason='SL'` : il tombait dans la jambe automatique et
    bornait l'expérience du radar."""
    _t(base_n, 1, pnl=-45.42, close_reason="SL", notes="MANUEL-TERM")
    _t(base_n, 2, pnl=-6.96, close_reason="SL", notes="Auto-exec via bridge MT5")

    m = ra.releve(base_n)

    assert m["pnl_auto"] == pytest.approx(-6.96), (
        "les stops de Xavier sont comptes comme des pertes du radar")
    assert m["ordres_auto"] == 1


def test_un_trade_du_TERMINAL_ne_mange_pas_le_budget_D_ORDRES(base_n):
    """⛔ 43 trades du terminal avaient pousse le compteur de 59 a 102 contre
    un budget de 60 : la borne tombait sur le VOLUME DE XAVIER."""
    for i in range(5):
        _t(base_n, 100 + i, pnl=1.0, close_reason="TP",
           notes="Auto-exec via bridge MT5")
    for i in range(40):
        _t(base_n, 200 + i, pnl=-1.0, close_reason="SL", notes="MANUEL-TERM")

    m = ra.releve(base_n)

    assert m["ordres"] == 5, "le budget d'ordres compte les trades du terminal"


def test_les_trades_du_TERMINAL_sont_DITS_a_part_jamais_tus(base_n):
    """⚠️ Les exclure de la borne ne doit pas les faire DISPARAITRE : c'est de
    l'argent reel. Ils se lisent, ils ne bornent rien."""
    _t(base_n, 1, pnl=-45.42, close_reason="SL", notes="MANUEL-TERM")
    _t(base_n, 2, pnl=23.04, close_reason="MANUAL", notes="MANUEL-TERM")

    m = ra.releve(base_n)

    assert m["ordres_terminal"] == 2
    assert m["pnl_terminal"] == pytest.approx(-22.38)


def test_la_MAIN_est_celle_qui_ferme_les_positions_DU_RADAR(base_n):
    """🔑 C'est CETTE main-la que << couper l'or couperait aussi >> : elle vit
    des positions que le code ouvre. Mesure du 09/10 : +42,35 EUR sur 11
    fermetures, soit 65 % du gain total de la main."""
    _t(base_n, 1, pnl=42.35, close_reason="MANUAL",
       notes="Auto-exec via bridge MT5")
    _t(base_n, 2, pnl=23.04, close_reason="MANUAL", notes="MANUEL-TERM")

    m = ra.releve(base_n)

    assert m["pnl_main"] == pytest.approx(42.35)
    assert m["ordres_main"] == 1


def test_le_verdict_ne_tombe_PLUS_sur_le_volume_de_Xavier(base_n):
    """⛔ L'invariant complet : 48 fermetures du radar a -6,96 EUR et 43 trades
    du terminal a -45,42 EUR ne doivent franchir AUCUNE borne."""
    for i in range(48):
        _t(base_n, 100 + i, pnl=-6.96 / 48, close_reason="SL",
           notes="Auto-exec via bridge MT5")
    for i in range(43):
        _t(base_n, 300 + i, pnl=-45.42 / 43, close_reason="SL",
           notes="MANUEL-TERM")

    v = ra.verdict(ra.releve(base_n))

    assert v["borne_atteinte"] is False, v["motif"]


def test_une_base_SANS_colonne_notes_ne_fait_pas_LEVER(base):
    """⚠️ Toutes les bases ne portent pas `notes`. Une requete qui leve rendrait
    `None`, et un releve absent ne conclut sur RIEN -- la regle deviendrait
    muette au lieu de se degrader."""
    _trade(base, 1, pnl=-10.0, close_reason="SL")

    m = ra.releve(base)

    assert m is not None, "la regle est devenue muette sur un schema sans notes"
    assert m["ordres"] == 1


# ═════════════════════════════════════════════════════════════════════════
# 2026-10-09 — LE BUDGET D'ORDRES, RECALIBRÉ SUR LE NOUVEAU RYTHME
# ═════════════════════════════════════════════════════════════════════════
#
# Demande de Xavier le 2026-10-09, après l'ouverture de l'or sur toute la
# fenêtre hebdomadaire : *« Je veux recalibrer le budget d'ordre au nouveau
# rythme. »*
#
# ## L'arithmétique, explicite
#
# Les 60 ordres venaient d'un rythme de **25 ordres en 6 jours** (4,2/jour).
# Deux choses ont changé depuis :
#
# 1. l'objectif court de 2 € rend les trades **consécutifs** — mesuré le 09/10
#    sur les trois dernières heures pleinement armées : **5,0 ordres/h** ;
# 2. la fenêtre est passée de **70,0 h à 114,6 h par semaine** (+64 %), soit
#    **22,9 h par jour de marché** au lieu de 14,0.
#
#     taux bas  (32 ordres / 14 h = 2,3/h)  ->  53 ordres/jour
#     taux haut (15 ordres /  3 h = 5,0/h)  -> 115 ordres/jour
#
# Pour **10 jours de marché** d'observation — l'intention d'origine était
# « ~9 jours » — cela donne entre **530 et 1 150**. On retient **800**, soit
# ~7 jours au taux haut et ~15 au taux bas.
#
# ⚠️ La borne d'ARGENT (−50 €) tombera probablement bien avant : au −0,145 €
# par trade mesuré sur le radar seul, 115 ordres/jour font ~−17 €/jour.
# C'est voulu — « le premier atteint ».
#
# ⛔ Et 800 reste très au-dessus du plancher statistique qui justifiait 60
# (en dessous, 39 % de gagnants ne se distinguent pas du hasard).


def test_le_budget_d_ordres_est_recalibre_sur_le_nouveau_rythme():
    """⛔ 60 correspondait a 4,2 ordres/jour. Le rythme mesure est de 53 a 115
    par jour : 60 serait franchi en moins d'une journee, et la regle ne dirait
    plus rien d'autre que << il a trade >>."""
    assert ra.MAX_ORDRES >= 500, (
        f"budget {ra.MAX_ORDRES} : moins de 5 jours de marche au rythme mesure")
    assert ra.MAX_ORDRES <= 1200, (
        f"budget {ra.MAX_ORDRES} : plus de 10 jours, l'experience ne conclut "
        f"jamais")


def test_le_budget_reste_REGLABLE_sans_redeploiement(monkeypatch):
    """Une experience bornee doit pouvoir voir ses bornes bouger quand Xavier
    le decide, pas quand une image se reconstruit."""
    import importlib
    monkeypatch.setenv("OR_ARRET_MAX_ORDRES", "123")
    importlib.reload(ra)
    try:
        assert ra.MAX_ORDRES == 123
    finally:
        monkeypatch.delenv("OR_ARRET_MAX_ORDRES", raising=False)
        importlib.reload(ra)


def test_la_borne_d_ARGENT_reste_inchangee():
    """⚠️ Xavier a demande de recalibrer le BUDGET D'ORDRES. La borne d'argent
    n'etait pas dans sa demande : la bouger serait decider a sa place."""
    assert ra.MAX_PERTE_EUR == -50.0


def test_le_motif_DIT_la_jambe_terminal_jamais_tue(base_n):
    """⛔ Exclure les trades du terminal de la borne ne doit pas les faire
    disparaitre du message : -45,42 EUR de stops reels, c'est de l'argent."""
    _t(base_n, 1, pnl=-6.96, close_reason="SL",
       notes="Auto-exec via bridge MT5")
    _t(base_n, 2, pnl=-45.42, close_reason="SL", notes="MANUEL-TERM")

    motif = ra.verdict(ra.releve(base_n))["motif"]

    assert "terminal" in motif.lower(), motif
    assert "-45.42" in motif or "45,42" in motif, motif


def test_le_motif_de_FRANCHISSEMENT_dit_aussi_le_terminal(base_n):
    """Le message qui alerte doit porter la meme decomposition : sinon la
    lecture d'une alerte et celle d'un releve calme ne concordent pas."""
    for i in range(3):
        _t(base_n, 10 + i, pnl=-30.0, close_reason="SL",
           notes="Auto-exec via bridge MT5")
    _t(base_n, 99, pnl=-45.42, close_reason="SL", notes="MANUEL-TERM")

    v = ra.verdict(ra.releve(base_n))

    assert v["borne_atteinte"] is True
    assert "terminal" in v["motif"].lower(), v["motif"]
