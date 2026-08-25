"""La porte du banc — ce qui peut passer en argent réel, et ce qui ne peut pas.

⛔ Le test qui compte le plus ici est `destination=None`. Le dépôt a déjà payé ce
défaut exact le 2026-08-04 : `_normalize_destination` repliait une destination
inconnue sur `None`, et comme `None` signifie « toutes les destinations », le
repli **élargissait** les permissions au lieu de les restreindre. Silencieusement.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "trades.db"
    from backend.services import trade_log_service
    monkeypatch.setattr(trade_log_service, "_DB_PATH", db_path)

    from backend.services import (
        ea_closed_trades_service,
        pair_admission_controller,
        research_bench,
    )
    monkeypatch.setattr(research_bench, "_SCHEMA_ENSURED", False)
    monkeypatch.setattr(pair_admission_controller, "_SCHEMA_ENSURED", False)
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


@pytest.fixture
def banc_actif(monkeypatch):
    """La porte n'est armée que si le banc est activé — sinon un dépôt qui ne
    l'a pas installé se retrouverait bloqué par une table absente."""
    import config.settings as st
    monkeypatch.setattr(st, "RESEARCH_BENCH_GATE_ENABLED", True, raising=False)


# ── Ce qui doit être refusé ───────────────────────────────────────────────

def test_refuse_une_promotion_auto_exec_en_argent_reel_non_couverte(banc_actif):
    from backend.services import research_bench as rb

    ok, motif = rb.gate_promotion("XAU/USD", "AUTO_EXEC", direction="sell",
                                  destination="admin_live", transitioned_by="auto")
    assert ok is False
    assert "essai" in motif.lower()


def test_destination_none_est_traitee_comme_de_l_argent_reel(banc_actif):
    """⛔ `None` = « toutes les destinations », donc inclut `admin_live`.
    `destinations_registry.is_real_money(None)` rend False — correct pour son
    usage, béant ici. Une promotion globale ne doit PAS contourner la porte."""
    from backend.services import research_bench as rb

    ok, motif = rb.gate_promotion("XAU/USD", "AUTO_EXEC", direction="sell",
                                  destination=None, transitioned_by="auto")
    assert ok is False, "une promotion globale atteint l'argent réel"
    assert "essai" in motif.lower()


def test_un_essai_ouvert_ne_suffit_pas(banc_actif):
    """Déclarer une hypothèse n'est pas l'avoir vérifiée."""
    from backend.services import research_bench as rb

    rb.declare("h4-or", "…", selector={"pairs": ["XAU/USD"], "direction": "sell",
               "destinations": ["admin_live"]}, variants_declared=1, author="x")
    ok, _ = rb.gate_promotion("XAU/USD", "AUTO_EXEC", direction="sell",
                              destination="admin_live", transitioned_by="auto")
    assert ok is False


def test_un_essai_echoue_ne_couvre_rien(banc_actif, _isolated_db):
    from backend.services import research_bench as rb

    sel = {"pairs": ["XAU/USD"], "direction": "sell", "destinations": ["admin_live"]}
    rb.declare("h4-or", "…", selector=sel, variants_declared=1, author="x", min_sample=2)
    rb._forcer_verdict("h4-or", passed=False)     # utilitaire de test, cf. module
    ok, _ = rb.gate_promotion("XAU/USD", "AUTO_EXEC", direction="sell",
                              destination="admin_live", transitioned_by="auto")
    assert ok is False


# ── Ce qui doit passer ────────────────────────────────────────────────────

def test_un_essai_passe_couvre_la_promotion(banc_actif):
    from backend.services import research_bench as rb

    sel = {"pairs": ["XAU/USD"], "direction": "sell", "destinations": ["admin_live"]}
    rb.declare("h4-or", "…", selector=sel, variants_declared=1, author="x")
    rb._forcer_verdict("h4-or", passed=True)
    ok, motif = rb.gate_promotion("XAU/USD", "AUTO_EXEC", direction="sell",
                                  destination="admin_live", transitioned_by="auto")
    assert ok is True, motif


def test_la_clause_d_anteriorite_laisse_passer_l_existant(banc_actif):
    """⚠️ Sans elle, installer le banc arrête tout le trading."""
    from backend.services import research_bench as rb

    rb.grant_legacy("XAU/USD", "sell", "admin_live", "en place au 2026-08-25")
    ok, motif = rb.gate_promotion("XAU/USD", "AUTO_EXEC", direction="sell",
                                  destination="admin_live", transitioned_by="auto")
    assert ok is True, motif


def test_la_porte_ignore_les_etats_qui_ne_sont_pas_auto_exec(banc_actif):
    from backend.services import research_bench as rb

    for etat in ("TELEGRAM", "OBSERVED", "PAUSED", "DEMOTED"):
        ok, _ = rb.gate_promotion("XAU/USD", etat, direction="sell",
                                  destination="admin_live", transitioned_by="auto")
        assert ok is True, f"{etat} n'engage pas d'argent"


def test_la_porte_laisse_passer_les_destinations_fictives(banc_actif):
    from backend.services import research_bench as rb

    ok, _ = rb.gate_promotion("XAU/USD", "AUTO_EXEC", direction="sell",
                              destination="admin_legacy", transitioned_by="auto")
    assert ok is True, "le démo miroir n'engage pas d'argent"


def test_la_derogation_explicite_passe_et_se_voit(banc_actif, caplog):
    """Une porte sans issue documentée est contournée par un UPDATE en base, et
    alors plus personne ne sait qu'elle a été contournée."""
    import logging
    from backend.services import research_bench as rb

    with caplog.at_level(logging.WARNING):
        ok, _ = rb.gate_promotion("XAU/USD", "AUTO_EXEC", direction="sell",
                                  destination="admin_live",
                                  transitioned_by="admin_override")
    assert ok is True
    assert any("override" in r.message.lower() for r in caplog.records)


def test_la_porte_desarmee_ne_bloque_rien(monkeypatch):
    """Un dépôt qui n'a pas installé le banc ne doit pas se retrouver gelé."""
    import config.settings as st
    from backend.services import research_bench as rb

    monkeypatch.setattr(st, "RESEARCH_BENCH_GATE_ENABLED", False, raising=False)
    ok, _ = rb.gate_promotion("XAU/USD", "AUTO_EXEC", direction="sell",
                              destination="admin_live", transitioned_by="auto")
    assert ok is True


# ── Le branchement dans set_state ─────────────────────────────────────────

def test_set_state_refuse_la_promotion_non_couverte(banc_actif):
    from backend.services import pair_admission_controller as pac

    with pytest.raises(PermissionError, match="banc"):
        pac.set_state("XAU/USD", pac.STATE_AUTO_EXEC, "test",
                      direction="sell", destination="admin_live")


def test_set_state_accepte_ce_que_le_banc_couvre(banc_actif):
    from backend.services import pair_admission_controller as pac
    from backend.services import research_bench as rb

    rb.grant_legacy("XAU/USD", "sell", "admin_live", "en place")
    rid = pac.set_state("XAU/USD", pac.STATE_AUTO_EXEC, "test",
                        direction="sell", destination="admin_live")
    assert rid > 0
    assert pac.get_current_state("XAU/USD", "sell", "admin_live") == pac.STATE_AUTO_EXEC


# ── Un refus n'est pas une panne ──────────────────────────────────────────

def test_le_cycle_d_admission_distingue_un_refus_d_une_panne(monkeypatch, caplog):
    """⛔ Une fois la porte armée, le moteur d'auto-promotion se fera refuser des
    transitions toutes les heures. Si ces refus remontent en `logger.exception`,
    les journaux diront « échec » là où le dispositif fait exactement son travail
    — et quelqu'un « réparera » la porte.
    """
    import logging
    from backend.services import pair_admission_controller as pac

    def _refuse(pair, direction=None, **kw):
        raise PermissionError("banc d'essai : aucun essai passé ne couvre ce couple")

    monkeypatch.setattr(pac, "evaluate_pair", _refuse)
    monkeypatch.setattr("config.settings.WATCHED_PAIRS", ["XAU/USD"], raising=False)

    with caplog.at_level(logging.DEBUG):
        r = pac.check_and_regulate()

    refus = [d for d in r["decisions"] if d["action"] == "refused_by_bench"]
    assert refus, "le refus doit apparaître comme une décision, pas disparaître"
    assert not any(rec.levelno >= logging.ERROR for rec in caplog.records), \
        "un refus attendu ne doit pas être journalisé comme une erreur"


def test_le_cycle_d_admission_signale_toujours_les_vraies_pannes(monkeypatch, caplog):
    """Le pendant du test précédent : distinguer le refus ne doit pas rendre le
    cycle muet sur les défauts réels."""
    import logging
    from backend.services import pair_admission_controller as pac

    def _casse(pair, direction=None, **kw):
        raise RuntimeError("base corrompue")

    monkeypatch.setattr(pac, "evaluate_pair", _casse)
    monkeypatch.setattr("config.settings.WATCHED_PAIRS", ["XAU/USD"], raising=False)

    with caplog.at_level(logging.DEBUG):
        pac.check_and_regulate()

    assert any(rec.levelno >= logging.ERROR for rec in caplog.records)


def test_le_moteur_de_promotion_distingue_lui_aussi(monkeypatch, caplog):
    """Le même défaut existe dans les deux cycles. Corriger l'un et pas l'autre,
    c'est la leçon que ce dépôt a déjà payée trois fois : une parade posée sur un
    chemin n'est pas posée sur les autres."""
    import logging
    from backend.services import promotion_engine as pe

    def _refuse(*a, **kw):
        raise PermissionError("banc d'essai : aucun essai passé ne couvre ce couple")

    monkeypatch.setattr(pe.pac, "get_current_state", _refuse)
    monkeypatch.setattr("config.settings.WATCHED_PAIRS", ["XAU/USD"], raising=False)
    monkeypatch.setattr(pe, "check_demotion", lambda *a, **k: None)
    monkeypatch.setattr(pe, "_notify_telegram_infra", lambda *a, **k: None)

    with caplog.at_level(logging.DEBUG):
        pe.run_promotion_cycle()

    assert not any(r.levelno >= logging.ERROR for r in caplog.records), \
        "un refus du banc ne doit pas remonter en erreur"
    assert any("refusé par le banc" in r.getMessage() for r in caplog.records)


# ── L'antériorité ne doit pas ÉLARGIR ─────────────────────────────────────

def test_une_anteriorite_etroite_ne_couvre_pas_une_promotion_large(banc_actif):
    """⛔ Le même défaut d'élargissement, une troisième fois.

    Une antériorité accordée à `sell @admin_live` ne doit PAS couvrir une
    promotion `tous sens @toutes destinations` : celle-ci est strictement plus
    large, elle atteint le `buy` et les autres comptes réels. Accorder l'étroit
    puis laisser passer le large, c'est exactement ce que faisait
    `_normalize_destination` le 2026-08-04.
    """
    from backend.services import research_bench as rb

    rb.grant_legacy("XAU/USD", "sell", "admin_live", "en place")

    ok, _ = rb.gate_promotion("XAU/USD", "AUTO_EXEC", direction=None,
                              destination="admin_live", transitioned_by="auto")
    assert ok is False, "tous sens est plus large que sell"

    ok, _ = rb.gate_promotion("XAU/USD", "AUTO_EXEC", direction="sell",
                              destination=None, transitioned_by="auto")
    assert ok is False, "toutes destinations est plus large que admin_live"

    ok, _ = rb.gate_promotion("XAU/USD", "AUTO_EXEC", direction="buy",
                              destination="admin_live", transitioned_by="auto")
    assert ok is False, "buy n'a pas été accordé"


def test_une_anteriorite_large_couvre_bien_l_etroit(banc_actif):
    """Le pendant : accorder « tous sens, toutes destinations » couvre tout ce
    qui est plus étroit. Sinon la clause d'antériorité serait inapplicable."""
    from backend.services import research_bench as rb

    rb.grant_legacy("XAU/USD", None, None, "ligne globale en place")

    for sens in (None, "buy", "sell"):
        for dest in (None, "admin_live", "admin_kraken"):
            ok, motif = rb.gate_promotion("XAU/USD", "AUTO_EXEC", direction=sens,
                                          destination=dest, transitioned_by="auto")
            assert ok is True, f"{sens}@{dest} : {motif}"
