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


def test_le_cli_rend_le_compteur_et_ses_plafonds(_isolated_db, capsys):
    """Le plafond n'est plus un nombre unique : il dépend de la longueur
    d'échantillon. Le CLI doit le montrer, sinon un lecteur croira à une barre
    fixe et jugera le banc infranchissable."""
    import re
    from backend.services import research_bench as rb
    from scripts.research import bench

    rb.seed_legacy("journal", variants_declared=1226, note="dépouillement du 26/08")
    bench.main(["counter"])
    sortie = capsys.readouterr().out

    assert "N = 1226" in sortie
    plafonds = [float(x) for x in re.findall(r"^\s+\d+\s+([\d.]+)", sortie, re.M)]
    assert len(plafonds) >= 4, "plusieurs longueurs d'échantillon doivent être montrées"
    assert plafonds == sorted(plafonds, reverse=True),         "le plafond doit décroître quand l'échantillon s'allonge"


# ── var_sr : le plafond doit dépendre de la longueur d'échantillon ────────
#
# ⛔ Le défaut trouvé le 26/08 en dépouillant le journal. `VAR_SR_REFERENCE` était
# mesurée sur des fenêtres de 128 jours et servait à TOUS les essais. À N = 1 226,
# elle exigeait un Sharpe annualisé de 5,0 — infranchissable, et pour une raison
# qui n'a rien à voir avec le marché.

def test_la_variance_sous_h0_decroit_en_un_sur_t():
    """Sous H₀, la variance du Sharpe estimé vaut ~1/T. C'est ce qui rend le
    plafond dépendant de la longueur d'échantillon, comme il doit l'être."""
    from backend.services import research_bench as rb

    assert rb.var_sr_h0(128) == pytest.approx(1 / 128, rel=1e-9)
    assert rb.var_sr_h0(730) == pytest.approx(1 / 730, rel=1e-9)
    assert rb.var_sr_h0(128) > rb.var_sr_h0(730)


def test_la_valeur_theorique_est_de_l_ordre_de_celle_mesuree_a_128_jours():
    """🔑 À T=128, 1/T vaut 0,0078 quand la grille du 25/08 mesurait 0,006286.
    Que la dispersion observée entre variantes coïncide avec ce que le pur bruit
    prédit est une confirmation de plus de l'absence d'edge — et la garantie que
    le repli théorique ne sort pas de nulle part."""
    from backend.services import research_bench as rb

    assert rb.var_sr_h0(128) == pytest.approx(rb.VAR_SR_REFERENCE, rel=0.30)
    assert rb.var_sr_h0(128) > rb.VAR_SR_REFERENCE, \
        "le repli théorique doit être le plus SÉVÈRE des deux"


def test_le_plafond_decroit_en_racine_de_t():
    """Un essai jugé sur deux ans ne doit pas affronter la barre calibrée pour
    quatre mois."""
    from backend.services import research_bench as rb

    court = rb.sharpe_attendu_sous_h0(rb.var_sr_h0(128), 1226)
    long_ = rb.sharpe_attendu_sous_h0(rb.var_sr_h0(730), 1226)
    assert long_ < court
    assert long_ / court == pytest.approx((128 / 730) ** 0.5, rel=1e-6)


def test_un_essai_long_est_juge_sur_sa_propre_longueur(_isolated_db):
    """Le cœur du correctif : `evaluate` ne doit plus figer la variance."""
    from backend.services import research_bench as rb

    rb.declare("long", "…", selector=SEL, variants_declared=1, author="x", min_sample=40)
    depart = datetime.now(timezone.utc)
    for i in range(60):
        _clore(_isolated_db, 4.0 if i % 3 else -3.0, depart + timedelta(days=i + 1))

    r = rb.evaluate("long")
    assert r["var_sr"] == pytest.approx(rb.var_sr_h0(r["T"]), rel=1e-9)
    assert r["var_sr"] != rb.VAR_SR_REFERENCE


def test_un_essai_peut_declarer_sa_propre_variance(_isolated_db):
    """Quand un essai mesure la dispersion entre ses variantes, elle prime sur le
    repli théorique — c'est une observation, elle vaut mieux qu'un modèle."""
    from backend.services import research_bench as rb

    rb.declare("mesure", "…", selector=SEL, variants_declared=12, author="x",
               min_sample=3, var_sr=0.0021)
    apres = datetime.now(timezone.utc)
    for i in range(8):
        _clore(_isolated_db, 6.0, apres + timedelta(days=i + 1))

    r = rb.evaluate("mesure")
    assert r["var_sr"] == pytest.approx(0.0021)


def test_la_variance_declaree_est_scellee_avec_la_declaration(_isolated_db):
    """Sinon on la baisse après coup pour faire passer un essai."""
    from backend.services import research_bench as rb

    rb.declare("mesure", "…", selector=SEL, variants_declared=3, author="x",
               min_sample=2, var_sr=0.0080)
    apres = datetime.now(timezone.utc)
    for i in range(5):
        _clore(_isolated_db, 6.0, apres + timedelta(days=i + 1))

    with sqlite3.connect(_isolated_db) as c:
        c.execute("UPDATE bench_trials SET var_sr = 0.00001 WHERE slug = 'mesure'")

    with pytest.raises(rb.DeclarationAlteree):
        rb.evaluate("mesure")
