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
