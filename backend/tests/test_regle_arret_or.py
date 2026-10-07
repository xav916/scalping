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
