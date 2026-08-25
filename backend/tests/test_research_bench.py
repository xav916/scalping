"""Banc d'essai hors-échantillon — registre, compteur, frontière, verdict.

Ce que ces tests verrouillent tient en une phrase : **une hypothèse ne peut pas
être jugée sur des données que son auteur avait déjà vues.** Tout le reste en
découle — le hachage de la déclaration, la borne temporelle, l'irréversibilité
du compteur.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "trades.db"
    from backend.services import trade_log_service
    monkeypatch.setattr(trade_log_service, "_DB_PATH", db_path)

    from backend.services import ea_closed_trades_service, research_bench
    monkeypatch.setattr(research_bench, "_SCHEMA_ENSURED", False)
    monkeypatch.setattr(ea_closed_trades_service, "_SCHEMA_ENSURED", False)

    with sqlite3.connect(db_path) as c:
        c.execute("""
            CREATE TABLE personal_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pair TEXT, direction TEXT, status TEXT, pnl REAL,
                signal_confidence REAL, closed_at TEXT, is_auto INTEGER,
                close_reason TEXT, mt5_ticket TEXT, destination_id TEXT
            )
        """)
    yield db_path


def _clore(db, pnl, quand, pair="XAU/USD", direction="sell", conf=70.0,
           dest="admin_live", ticket=None):
    with sqlite3.connect(db) as c:
        c.execute(
            "INSERT INTO personal_trades (pair, direction, status, pnl, signal_confidence,"
            " closed_at, is_auto, close_reason, mt5_ticket, destination_id)"
            " VALUES (?,?,'CLOSED',?,?,?,1,?,?,?)",
            (pair, direction, pnl, conf, quand.isoformat(),
             "SL" if pnl < 0 else "TP1", str(ticket or int(quand.timestamp() * 1000) % 10**9), dest),
        )


SEL = {"pairs": ["XAU/USD"], "direction": "sell", "destinations": ["admin_live"]}


# ── Le calcul lui-même ────────────────────────────────────────────────────

def test_le_dsr_reproduit_la_valeur_de_reference_du_25_aout():
    """Ancre numérique. Si ce test bouge, c'est la formule qui a bougé, et tout
    ce qui a été publié avec devient incomparable."""
    from backend.services import research_bench as rb

    o = rb.deflated_sharpe(sr=0.1703, T=128, skew=4.439, kurt=25.356,
                           var_sr=0.006286, n_trials=75)
    assert o["sr0"] == pytest.approx(0.19248, abs=1e-4)
    assert o["dsr"] == pytest.approx(0.3500, abs=1e-3)
    assert o["passed"] is False


def test_le_plafond_du_hasard_monte_avec_le_nombre_d_essais():
    """C'est toute la raison d'être du compteur : plus on cherche, plus il faut
    trouver fort pour que ça compte."""
    from backend.services import research_bench as rb

    seuils = [rb.deflated_sharpe(0.1703, 128, 4.439, 25.356, 0.006286, n)["sr0"]
              for n in (50, 75, 250, 1000)]
    assert seuils == sorted(seuils), "le plafond doit être monotone croissant en N"
    assert seuils[-1] == pytest.approx(0.25808, abs=1e-4)


# ── Déclaration ───────────────────────────────────────────────────────────

def test_declarer_ouvre_un_essai_et_le_scelle():
    from backend.services import research_bench as rb

    rb.declare("h4-or-vente", "Le 4h sur l'or à la vente porte un edge",
               selector=SEL, variants_declared=6, author="xavier")
    t = rb.get_trial("h4-or-vente")
    assert t["status"] == "open"
    assert t["variants_declared"] == 6
    assert len(t["declaration_hash"]) == 64
    assert t["verdict"] is None


def test_un_slug_ne_peut_pas_etre_redeclare():
    """Sinon on redéclare après coup avec la date du jour et la frontière
    temporelle ne veut plus rien dire."""
    from backend.services import research_bench as rb

    rb.declare("h4-or", "…", selector=SEL, variants_declared=1, author="x")
    with pytest.raises(ValueError, match="existe"):
        rb.declare("h4-or", "…", selector=SEL, variants_declared=1, author="x")


def test_un_selecteur_modifie_apres_coup_invalide_l_essai(_isolated_db):
    """⛔ Le cœur du dispositif. Sans ce contrôle, on ajuste le filtre après
    avoir vu les données — exactement le défaut qu'on prétend corriger."""
    from backend.services import research_bench as rb

    rb.declare("h4-or", "…", selector=SEL, variants_declared=1, author="x", min_sample=2)
    maintenant = datetime.now(timezone.utc)
    for i in range(4):
        _clore(_isolated_db, 10.0, maintenant + timedelta(minutes=i + 1))

    with sqlite3.connect(_isolated_db) as c:      # falsification directe en base
        c.execute("UPDATE bench_trials SET selector = ? WHERE slug = 'h4-or'",
                  ('{"pairs": ["EUR/USD"]}',))

    with pytest.raises(rb.DeclarationAlteree):
        rb.evaluate("h4-or")


# ── La frontière temporelle ───────────────────────────────────────────────

def test_les_clotures_anterieures_a_la_declaration_sont_refusees(_isolated_db):
    """⛔ La borne est en SQL, pas dans un avertissement."""
    from backend.services import research_bench as rb

    avant = datetime.now(timezone.utc) - timedelta(days=10)
    for i in range(50):
        _clore(_isolated_db, 25.0, avant + timedelta(minutes=i))

    rb.declare("h4-or", "…", selector=SEL, variants_declared=1, author="x", min_sample=5)
    r = rb.evaluate("h4-or")

    assert r["status"] == "open"
    assert r["n_obs"] == 0, "50 clôtures antérieures ne doivent PAS être servies"


def test_seules_les_clotures_posterieures_comptent(_isolated_db):
    from backend.services import research_bench as rb

    avant = datetime.now(timezone.utc) - timedelta(days=10)
    for i in range(20):
        _clore(_isolated_db, -50.0, avant + timedelta(minutes=i))

    rb.declare("h4-or", "…", selector=SEL, variants_declared=1, author="x", min_sample=3)
    apres = datetime.now(timezone.utc)
    for i in range(6):
        _clore(_isolated_db, 5.0, apres + timedelta(minutes=i + 1))

    r = rb.evaluate("h4-or")
    assert r["n_obs"] == 6
    assert r["sum_pnl"] == pytest.approx(30.0)


def test_sous_le_seuil_d_echantillon_aucun_chiffre_n_est_rendu(_isolated_db):
    """Un chiffre indicatif est un chiffre qui sera lu."""
    from backend.services import research_bench as rb

    rb.declare("h4-or", "…", selector=SEL, variants_declared=1, author="x", min_sample=30)
    apres = datetime.now(timezone.utc)
    for i in range(5):
        _clore(_isolated_db, 8.0, apres + timedelta(minutes=i + 1))

    r = rb.evaluate("h4-or")
    assert r["status"] == "open"
    assert r["n_obs"] == 5
    assert "dsr" not in r and "sr" not in r


# ── Le verdict ────────────────────────────────────────────────────────────

def test_le_verdict_est_ecrit_une_seule_fois(_isolated_db):
    from backend.services import research_bench as rb

    rb.declare("h4-or", "…", selector=SEL, variants_declared=1, author="x", min_sample=3)
    apres = datetime.now(timezone.utc)
    for i in range(8):
        _clore(_isolated_db, -3.0, apres + timedelta(hours=i + 1))

    r1 = rb.evaluate("h4-or")
    assert r1["status"] == "spent"
    assert r1["passed"] is False
    with pytest.raises(rb.EssaiDepense):
        rb.evaluate("h4-or")


def test_le_selecteur_filtre_ce_qui_n_est_pas_declare(_isolated_db):
    from backend.services import research_bench as rb

    rb.declare("h4-or", "…", selector=SEL, variants_declared=1, author="x", min_sample=2)
    apres = datetime.now(timezone.utc)
    for i in range(4):
        _clore(_isolated_db, 10.0, apres + timedelta(minutes=i + 1))
    for i in range(9):                                    # hors sélecteur
        _clore(_isolated_db, 999.0, apres + timedelta(minutes=i + 20), pair="EUR/USD")
        _clore(_isolated_db, 999.0, apres + timedelta(minutes=i + 40), direction="buy")
        _clore(_isolated_db, 999.0, apres + timedelta(minutes=i + 60), dest="admin_legacy")

    r = rb.evaluate("h4-or")
    assert r["n_obs"] == 4
    assert r["sum_pnl"] == pytest.approx(40.0)


# ── Le compteur ───────────────────────────────────────────────────────────

def test_le_compteur_somme_les_variantes_declarees():
    from backend.services import research_bench as rb

    rb.declare("a", "…", selector=SEL, variants_declared=6, author="x")
    rb.declare("b", "…", selector=SEL, variants_declared=12, author="x")
    assert rb.counter() == 18


def test_abandonner_un_essai_ne_rend_pas_ses_variantes():
    """⛔ Le compteur est un cliquet. Sinon il suffit d'abandonner ce qui ne
    marche pas pour faire redescendre le plafond du hasard."""
    from backend.services import research_bench as rb

    rb.declare("a", "…", selector=SEL, variants_declared=9, author="x")
    avant = rb.counter()
    rb.abandon("a", "piste sans intérêt")

    assert rb.get_trial("a")["status"] == "abandoned"
    assert rb.counter() == avant == 9


def test_le_compteur_inclut_l_heritage_du_journal():
    """Les 65 entrées du journal ne s'effacent pas parce qu'un nouveau registre
    commence."""
    from backend.services import research_bench as rb

    rb.seed_legacy("journal-2026-04-08", variants_declared=180,
                   note="65 entrées, variantes estimées à la main")
    rb.declare("a", "…", selector=SEL, variants_declared=4, author="x")
    assert rb.counter() == 184


def test_un_essai_abandonne_ne_peut_plus_etre_juge():
    from backend.services import research_bench as rb

    rb.declare("a", "…", selector=SEL, variants_declared=1, author="x")
    rb.abandon("a", "…")
    with pytest.raises(rb.EssaiDepense):
        rb.evaluate("a")


# ── Le CLI ────────────────────────────────────────────────────────────────

def test_le_cli_refuse_proprement_de_rejouer_un_essai(_isolated_db, capsys):
    """Un refus attendu n'est pas un plantage. Une trace d'exécution dit « le
    programme est cassé » quand le programme fait exactement son travail."""
    from backend.services import research_bench as rb
    from scripts.research import bench

    rb.declare("h4-or", "…", selector=SEL, variants_declared=1, author="x", min_sample=2)
    apres = datetime.now(timezone.utc)
    for i in range(4):
        _clore(_isolated_db, -2.0, apres + timedelta(hours=i + 1))

    with pytest.raises(SystemExit):
        bench.main(["evaluate", "h4-or"])
    capsys.readouterr()

    with pytest.raises(SystemExit) as sortie:
        bench.main(["evaluate", "h4-or"])

    assert sortie.value.code == 1
    err = capsys.readouterr().err
    assert "rejoue" in err
    assert "Traceback" not in err


def test_le_cli_rend_le_compteur(_isolated_db, capsys):
    from backend.services import research_bench as rb
    from scripts.research import bench

    rb.seed_legacy("journal", variants_declared=75, note="grille du 25/08")
    bench.main(["counter"])
    sortie = capsys.readouterr().out
    assert "N = 75" in sortie
    assert "+0.19" in sortie, "le plafond du hasard doit être affiché avec N"
