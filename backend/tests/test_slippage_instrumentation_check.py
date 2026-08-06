"""Le contrôle qui empêche la mesure du glissement de redevenir muette.

Ces tests font tourner la décision sur des bases réelles. Ils vérifient surtout
les trois façons dont ce genre de contrôle échoue en pratique : hurler sur de
l'historique irrécupérable, conclure sur trois trades, ou confondre « pas de
glissement » avec « glissement non observable ».
"""
import sqlite3

import pytest

from backend.services import slippage_instrumentation_check as chk

APRES = "2026-08-06T12:00:00+00:00"   # après le correctif
AVANT = "2026-07-01T12:00:00+00:00"   # avant : vide par construction


@pytest.fixture
def db(tmp_path, monkeypatch):
    f = tmp_path / "trades.db"
    conn = sqlite3.connect(f)
    conn.execute("""
        CREATE TABLE personal_trades (
            id INTEGER PRIMARY KEY, created_at TEXT, is_auto INTEGER,
            fill_price REAL, slippage_pips REAL
        )
    """)
    conn.commit()
    conn.close()
    monkeypatch.setattr(chk, "_db_path", lambda: str(f))
    monkeypatch.delenv("SLIPPAGE_CHECK_SINCE", raising=False)
    monkeypatch.delenv("SLIPPAGE_CHECK_MIN_SAMPLE", raising=False)
    monkeypatch.delenv("SLIPPAGE_CHECK_MIN_COVERAGE", raising=False)
    return str(f)


def _seed(db_path, n, created_at=APRES, fill=None, slip=None, is_auto=1):
    with sqlite3.connect(db_path) as c:
        for _ in range(n):
            c.execute(
                "INSERT INTO personal_trades (created_at, is_auto, fill_price, slippage_pips) "
                "VALUES (?, ?, ?, ?)",
                (created_at, is_auto, fill, slip),
            )


# ── Ne pas conclure trop tôt ──────────────────────────────────────────

def test_aucun_trade_ne_declenche_rien(db):
    r = chk.run()
    assert r["verdict"] == "INSUFFISANT"
    assert r["alerte"] is False


def test_sous_le_seuil_on_ne_conclut_pas(db):
    """3 trades sans mesure ne prouvent rien — la colonne peut se remplir au 4e."""
    _seed(db, 3, fill=None)
    r = chk.run()
    assert r["trades_depuis"] == 3
    assert r["verdict"] == "INSUFFISANT"
    assert r["alerte"] is False


# ── Le cas qui justifie le contrôle ───────────────────────────────────

def test_colonne_morte_declenche_l_alerte(db):
    """20 trades et aucun `fill_price` : c'est exactement l'état qui a duré
    onze mois sans que rien ne le signale."""
    _seed(db, 20, fill=None)
    r = chk.run()
    assert r["verdict"] == "MORTE"
    assert r["alerte"] is True
    assert r["couverture_fill"] == 0.0
    assert "fill_price" in r["message"]


def test_couverture_complete_ne_declenche_rien(db):
    _seed(db, 25, fill=1.1002, slip=-2.0)
    r = chk.run()
    assert r["verdict"] == "OK"
    assert r["alerte"] is False
    assert r["couverture_fill"] == 1.0
    assert r["slippage_moyen_pips"] == pytest.approx(-2.0)


def test_couverture_partielle_alerte(db):
    """Une destination à jour, l'autre pas : 30 % de couverture."""
    _seed(db, 9, fill=1.1002, slip=-2.0)
    _seed(db, 21, fill=None)
    r = chk.run()
    assert r["verdict"] == "PARTIELLE"
    assert r["alerte"] is True
    assert r["couverture_fill"] == pytest.approx(0.3)


# ── Les trois pièges ──────────────────────────────────────────────────

def test_l_historique_irrecuperable_ne_declenche_jamais(db):
    """LE piège principal : 1581 trades antérieurs au correctif sont vides et
    le resteront — le prix demandé n'a jamais été écrit. Les compter ferait
    hurler le contrôle à vie, et on finirait par l'éteindre."""
    _seed(db, 100, created_at=AVANT, fill=None)
    r = chk.run()
    assert r["trades_depuis"] == 0, "les trades d'avant le correctif sont exclus"
    assert r["alerte"] is False


def test_glissement_non_observable_n_est_pas_une_panne(db):
    """`fill_source='requested'` renseigne `fill_price` mais pas
    `slippage_pips`. C'est le comportement voulu — refuser de mesurer plutôt
    que d'inventer un zéro — et ça ne doit surtout pas passer pour une panne."""
    _seed(db, 25, fill=1.1002, slip=None)
    r = chk.run()
    assert r["verdict"] == "OK"
    assert r["alerte"] is False
    assert r["couverture_fill"] == 1.0
    assert r["couverture_slippage"] == 0.0


def test_les_trades_manuels_sont_ignores(db):
    """Seul l'auto passe par le bridge ; un trade saisi à la main n'a pas de
    fill à mesurer et ne dit rien sur l'instrumentation."""
    _seed(db, 30, fill=None, is_auto=0)
    r = chk.run()
    assert r["trades_depuis"] == 0
    assert r["alerte"] is False


# ── Robustesse ────────────────────────────────────────────────────────

def test_base_illisible_alerte_plutot_que_de_planter(db, monkeypatch):
    """Un contrôle qui plante est un contrôle muet — soit le mode de
    défaillance qu'il est censé détecter."""
    monkeypatch.setattr(chk, "_db_path", lambda: "/chemin/inexistant/x.db")
    r = chk.run()
    assert r["verdict"] == "ERREUR"
    assert r["alerte"] is True


def test_seuil_reglable_par_environnement(db, monkeypatch):
    monkeypatch.setenv("SLIPPAGE_CHECK_MIN_SAMPLE", "5")
    _seed(db, 6, fill=None)
    r = chk.run()
    assert r["verdict"] == "MORTE"
    assert r["alerte"] is True


def test_date_de_reference_reglable(db, monkeypatch):
    """Permet de redémarrer la surveillance après un futur redéploiement."""
    monkeypatch.setenv("SLIPPAGE_CHECK_SINCE", "2026-09-01T00:00:00+00:00")
    _seed(db, 40, created_at=APRES, fill=None)
    r = chk.run()
    assert r["trades_depuis"] == 0
    assert r["alerte"] is False
