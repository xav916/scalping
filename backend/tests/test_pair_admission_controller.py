"""Tests pour backend.services.pair_admission_controller."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Redirige _DB_PATH vers une DB temporaire pour isolation."""
    db_path = tmp_path / "trades.db"
    from backend.services import trade_log_service
    monkeypatch.setattr(trade_log_service, "_DB_PATH", db_path)

    # backtest.db alimente le scoring depuis le 2026-08-04 — l'isoler aussi,
    # sinon les tests liraient (et créeraient) le fichier du dépôt.
    from backend.services import backtest_service
    monkeypatch.setattr(backtest_service, "_DB_PATH", tmp_path / "backtest.db")

    # Reset schema-ensured caches
    from backend.services import (
        pair_admission_controller,
        pair_pnl_regulator,
        ea_closed_trades_service,
    )
    monkeypatch.setattr(pair_admission_controller, "_SCHEMA_ENSURED", False)
    monkeypatch.setattr(pair_pnl_regulator, "_SCHEMA_ENSURED", False)
    monkeypatch.setattr(ea_closed_trades_service, "_SCHEMA_ENSURED", False)

    # Tables sources nécessaires pour scoring
    with sqlite3.connect(db_path) as c:
        c.execute(
            """
            CREATE TABLE personal_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pair TEXT, direction TEXT, entry_price REAL,
                stop_loss REAL, take_profit REAL, size_lot REAL,
                signal_pattern TEXT, signal_confidence REAL,
                checklist_passed INTEGER, notes TEXT,
                status TEXT, exit_price REAL, pnl REAL,
                created_at TEXT, closed_at TEXT, user TEXT,
                post_entry_sl REAL, post_entry_tp REAL, post_entry_size REAL,
                post_entry_alarm TEXT, mt5_ticket TEXT, is_auto INTEGER,
                context_macro TEXT, signal_id TEXT, fill_price REAL,
                slippage_pips REAL, close_reason TEXT, user_id INTEGER
            )
            """
        )
        c.execute(
            """
            CREATE TABLE shadow_setups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                system_id TEXT, pair TEXT, direction TEXT,
                outcome TEXT, exit_at TEXT, pnl_eur REAL
            )
            """
        )
    yield db_path


def _insert_trade(db_path, pair: str, pnl: float, closed_at: str | None = None, direction: str | None = None):
    closed_at = closed_at or datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as c:
        c.execute(
            "INSERT INTO personal_trades (pair, direction, status, pnl, is_auto, closed_at, close_reason) "
            "VALUES (?, ?, 'CLOSED', ?, 1, ?, ?)",
            (pair, direction, pnl, closed_at, "SL" if pnl < 0 else "TP1"),
        )


# ─── State management ──────────────────────────────────────────────────


def test_default_state_is_observed(_isolated_db):
    from backend.services import pair_admission_controller as pac
    assert pac.get_current_state("EUR/USD") == pac.STATE_OBSERVED


def test_set_state_transitions(_isolated_db):
    from backend.services import pair_admission_controller as pac
    pac.set_state("XAU/USD", pac.STATE_AUTO_EXEC, "test setup")
    assert pac.get_current_state("XAU/USD") == pac.STATE_AUTO_EXEC
    pac.set_state("XAU/USD", pac.STATE_PAUSED, "test pause")
    assert pac.get_current_state("XAU/USD") == pac.STATE_PAUSED


def test_set_state_idempotent_if_same(_isolated_db):
    from backend.services import pair_admission_controller as pac
    pac.set_state("XAU/USD", pac.STATE_AUTO_EXEC, "first")
    result = pac.set_state("XAU/USD", pac.STATE_AUTO_EXEC, "same")
    assert result == -1  # signal idempotent


def test_invalid_state_raises(_isolated_db):
    from backend.services import pair_admission_controller as pac
    with pytest.raises(ValueError):
        pac.set_state("XAU/USD", "INVALID_STATE", "test")


# ─── Eligibility ───────────────────────────────────────────────────────


def test_is_auto_exec_eligible(_isolated_db):
    from backend.services import pair_admission_controller as pac
    assert not pac.is_auto_exec_eligible("XAU/USD")
    pac.set_state("XAU/USD", pac.STATE_AUTO_EXEC, "test")
    assert pac.is_auto_exec_eligible("XAU/USD")
    pac.set_state("XAU/USD", pac.STATE_PAUSED, "test")
    assert not pac.is_auto_exec_eligible("XAU/USD")


def test_is_telegram_eligible(_isolated_db):
    from backend.services import pair_admission_controller as pac
    # OBSERVED → pas eligible Telegram
    assert not pac.is_telegram_eligible("XAU/USD")
    # TELEGRAM/AUTO_EXEC/PAUSED → eligible
    pac.set_state("XAU/USD", pac.STATE_TELEGRAM, "test")
    assert pac.is_telegram_eligible("XAU/USD")
    pac.set_state("XAU/USD", pac.STATE_AUTO_EXEC, "test")
    assert pac.is_telegram_eligible("XAU/USD")
    pac.set_state("XAU/USD", pac.STATE_PAUSED, "test")
    assert pac.is_telegram_eligible("XAU/USD")
    # DEMOTED → pas eligible
    pac.set_state("XAU/USD", pac.STATE_DEMOTED, "test")
    assert not pac.is_telegram_eligible("XAU/USD")


# ─── Score composite ───────────────────────────────────────────────────


def test_compute_promotion_score_no_data(_isolated_db):
    """Sans AUCUNE donnée (ni trade réel, ni signal simulé résolu), le score
    est INDÉCIDABLE — cf. section « garde-fou échantillon réel » plus bas.

    Avant le 2026-08-05, ce cas rendait ``eligible_for == STATE_OBSERVED``,
    la même valeur qu'une pair dont on SAIT qu'elle est mauvaise. Le nouveau
    comportement distingue explicitement « on ne sait pas » de « on sait que
    c'est mauvais ».
    """
    from backend.services import pair_admission_controller as pac
    score = pac.compute_promotion_score("EUR/USD")
    assert score["sample"] == 0
    assert score["eligible_for"] == pac.STATE_INDETERMINATE


def test_compute_promotion_score_meets_threshold(_isolated_db, monkeypatch):
    monkeypatch.setenv("TRADING_CAPITAL", "10000")
    import importlib
    from config import settings
    importlib.reload(settings)
    from backend.services import pair_admission_controller as pac
    importlib.reload(pac)

    # 30 trades, 18 wins de +20€, 12 losses de -10€ → sum=240€=2.4%pct, WR=60%, PF=3.0
    for i in range(30):
        pnl = 20.0 if i % 5 < 3 else -10.0
        _insert_trade(
            _isolated_db, "XAU/USD", pnl,
            closed_at=(datetime.now(timezone.utc) + timedelta(minutes=i)).isoformat(),
        )
    score = pac.compute_promotion_score("XAU/USD")
    assert score["sample"] == 30
    assert score["wr"] >= 45.0
    assert score["pnl_pct"] >= 2.0
    assert score["pf"] >= 1.3
    assert score["eligible_for"] == pac.AUTO_PROMOTE_TARGET


# ─── shadow_setups n'alimente plus le scoring (2026-08-04) ─────────────
#
# Ces deux tests vérifiaient auparavant que le fallback shadow filtrait bien
# `system_id LIKE 'V1_SHADOW_%'`, pour éviter que les shadows V2_CORE_LONG
# (TF H4, SL/TP différents) ne contaminent le scoring V1. La préoccupation
# reste valide mais est désormais structurelle : la source est
# `backtest.db.trades`, qui ne contient que des signaux du radar V1.
#
# Le fallback shadow a été retiré parce que la table était corrompue — sa
# déduplication ne mordait pas, cf. test_admission_backtest_source.py.


def _insert_shadow(db_path, pair: str, direction: str, pnl: float, system_id: str, idx: int = 0):
    exit_at = (datetime.now(timezone.utc) + timedelta(minutes=idx)).isoformat()
    with sqlite3.connect(db_path) as c:
        c.execute(
            "INSERT INTO shadow_setups (system_id, pair, direction, exit_at, outcome, pnl_eur) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (system_id, pair, direction, exit_at, "TP1" if pnl > 0 else "SL", pnl),
        )


def test_shadow_setups_nalimente_plus_le_scoring(_isolated_db):
    """Même gorgé de shadows résolus, le scoring doit rester vide."""
    from backend.services import pair_admission_controller as pac

    for i in range(20):
        _insert_shadow(_isolated_db, "XAU/USD", "buy", 50.0, "V1_SHADOW_XAUUSD_buy", idx=i)
    for i in range(20):
        _insert_shadow(_isolated_db, "XAU/USD", "buy", -50.0, "V2_CORE_LONG_XAUUSD_4H", idx=100 + i)

    assert pac._fetch_trades_for_pair("XAU/USD", window=30, direction="buy") == []
    assert pac._fetch_trades_for_pair("XAU/USD", window=30, direction=None) == []


# ─── Auto transitions ──────────────────────────────────────────────────


def test_evaluate_observed_promotes_to_target_if_criteria_met(_isolated_db):
    from backend.services import pair_admission_controller as pac

    # 30 winning trades clean
    for i in range(30):
        _insert_trade(
            _isolated_db, "XAU/USD", 50.0,
            closed_at=(datetime.now(timezone.utc) + timedelta(minutes=i)).isoformat(),
        )
    d = pac.evaluate_pair("XAU/USD")
    assert d["action"] == "transition"
    # Target dépend de AUTO_PROMOTE_TARGET env (default TELEGRAM ; AUTO_EXEC si full-auto).
    assert d["to_state"] == pac.AUTO_PROMOTE_TARGET
    assert pac.get_current_state("XAU/USD") == pac.AUTO_PROMOTE_TARGET


def test_evaluate_auto_exec_demotes_to_paused_on_drawdown(_isolated_db):
    from backend.services import pair_admission_controller as pac

    # Initial state AUTO_EXEC
    pac.set_state("XAG/USD", pac.STATE_AUTO_EXEC, "test init")
    # 30 trades pertes : -50€ chacun → -1500€ sur 10k = -15% > seuil -3%
    for i in range(30):
        _insert_trade(
            _isolated_db, "XAG/USD", -50.0,
            closed_at=(datetime.now(timezone.utc) + timedelta(minutes=i)).isoformat(),
        )
    d = pac.evaluate_pair("XAG/USD")
    assert d["action"] == "transition"
    assert d["to_state"] == pac.STATE_PAUSED


def test_demoted_requires_manual_transition(_isolated_db):
    from backend.services import pair_admission_controller as pac

    pac.set_state("XYZ/ABC", pac.STATE_DEMOTED, "test demote")
    d = pac.evaluate_pair("XYZ/ABC")
    assert d["action"] == "keep"
    assert pac.get_current_state("XYZ/ABC") == pac.STATE_DEMOTED


# ─── Backfill ──────────────────────────────────────────────────────────


def test_backfill_initial_states_idempotent(_isolated_db):
    from backend.services import pair_admission_controller as pac

    result1 = pac.backfill_initial_states()
    n1 = result1["applied"]
    assert n1 > 0
    # Second run : déjà des rows, donc 0 nouvelle transition
    result2 = pac.backfill_initial_states()
    assert result2["applied"] == 0


# ─── Destination-aware (2026-07-29 Sprint 1) ──────────────────────────
# Une même (pair, direction) peut avoir des états distincts par destination.
# Ex : XAU/USD sell = AUTO_EXEC sur admin_legacy (Demo tradable) et
# TELEGRAM sur admin_live (Live observation). Permet le workflow test-then-promote.


def test_destination_specific_state_overrides_legacy_row(_isolated_db):
    """Row (pair, dir, dest) doit primer sur row (pair, dir, dest IS NULL)."""
    from backend.services import pair_admission_controller as pac

    # Legacy : XAU/USD sell = AUTO_EXEC sur toutes destinations
    pac.set_state("XAU/USD", pac.STATE_AUTO_EXEC, "legacy", direction="sell")
    # Override : sur admin_live seulement, on veut TELEGRAM (observation)
    pac.set_state("XAU/USD", pac.STATE_TELEGRAM, "live obs", direction="sell", destination="admin_live")

    # Résolution destination-specific
    assert pac.get_current_state("XAU/USD", direction="sell", destination="admin_live") == pac.STATE_TELEGRAM
    # Legacy row s'applique quand pas d'override (admin_legacy sans row propre)
    assert pac.get_current_state("XAU/USD", direction="sell", destination="admin_legacy") == pac.STATE_AUTO_EXEC


def test_two_destinations_independent_states(_isolated_db):
    """WTI/USD buy = AUTO_EXEC sur admin_legacy + TELEGRAM sur admin_live."""
    from backend.services import pair_admission_controller as pac

    pac.set_state("WTI/USD", pac.STATE_AUTO_EXEC, "demo trad",
                  direction="buy", destination="admin_legacy")
    pac.set_state("WTI/USD", pac.STATE_TELEGRAM, "live obs",
                  direction="buy", destination="admin_live")

    assert pac.get_current_state("WTI/USD", direction="buy", destination="admin_legacy") == pac.STATE_AUTO_EXEC
    assert pac.get_current_state("WTI/USD", direction="buy", destination="admin_live") == pac.STATE_TELEGRAM


def test_destination_none_uses_legacy_cascade(_isolated_db):
    """destination=None ne matche PAS les rows destination-specific."""
    from backend.services import pair_admission_controller as pac

    # Row destination-specific uniquement
    pac.set_state("EUR/USD", pac.STATE_AUTO_EXEC, "live only",
                  direction="buy", destination="admin_live")

    # Query sans destination → tombe sur DEFAULT_STATE (rien en cascade legacy)
    assert pac.get_current_state("EUR/USD", direction="buy") == pac.DEFAULT_STATE


def test_is_auto_exec_eligible_respects_destination(_isolated_db):
    """XAU/USD = AUTO_EXEC sur admin_legacy uniquement → seul admin_legacy éligible."""
    from backend.services import pair_admission_controller as pac

    pac.set_state("XAU/USD", pac.STATE_AUTO_EXEC, "demo",
                  direction="sell", destination="admin_legacy")
    pac.set_state("XAU/USD", pac.STATE_TELEGRAM, "live obs",
                  direction="sell", destination="admin_live")

    assert pac.is_auto_exec_eligible("XAU/USD", direction="sell", destination="admin_legacy") is True
    assert pac.is_auto_exec_eligible("XAU/USD", direction="sell", destination="admin_live") is False


def test_has_explicit_state_matches_via_cascade(_isolated_db):
    """Row destination-agnostic (dest IS NULL) satisfait check destination-specific."""
    from backend.services import pair_admission_controller as pac

    pac.set_state("BTC/USD", pac.STATE_AUTO_EXEC, "legacy", direction="buy")

    # Row (dir, dest=NULL) → check (dir, dest="admin_legacy") True via cascade
    assert pac.has_explicit_state("BTC/USD", direction="buy", destination="admin_legacy") is True
    assert pac.has_explicit_state("BTC/USD", direction="buy", destination="admin_live") is True


def test_destination_normalization_invalid_returns_none(_isolated_db):
    """Destination invalide → fallback rétro-compat (comportement legacy)."""
    from backend.services import pair_admission_controller as pac

    pac.set_state("ETH/USD", pac.STATE_AUTO_EXEC, "legacy", direction="sell")

    # Destination invalide traitée comme None → matche row legacy
    assert pac.get_current_state("ETH/USD", direction="sell", destination="ADMIN_BINANCE_FUTURES") == pac.STATE_AUTO_EXEC


def test_get_full_state_includes_destination(_isolated_db):
    """get_full_state doit exposer le champ destination dans le dict retourné."""
    from backend.services import pair_admission_controller as pac

    pac.set_state("XAU/USD", pac.STATE_AUTO_EXEC, "demo trad",
                  direction="sell", destination="admin_legacy")

    full = pac.get_full_state("XAU/USD", direction="sell", destination="admin_legacy")
    assert full["state"] == pac.STATE_AUTO_EXEC
    assert full["destination"] == "admin_legacy"
    assert full["direction"] == "sell"


# ─── Garde-fou échantillon réel (2026-08-05) ───────────────────────────
#
# Neutralise la promotion/rétrogradation automatique sur un échantillon
# majoritairement (voire entièrement) simulé. Avant ce correctif, `n_real <
# window` déclenchait un complément par `_fetch_signal_pnls` (signaux résolus
# du radar, jamais tradés) et `evaluate_pair` décidait sur ce mélange comme
# s'il s'agissait de résultats réels — c'est ce qui a verrouillé 28 pairs en
# DEMOTED le 2026-08-04 sur des métriques mathématiquement impossibles.
#
# `config.settings.PAC_MIN_REAL_TRADES` (défaut 30) fixe le plancher de
# trades réels sous lequel `compute_promotion_score` rend
# `eligible_for = STATE_INDETERMINATE` plutôt que de statuer, et
# `evaluate_pair` ne transitionne alors jamais (ni promotion, ni
# rétrogradation).


def _emit_signal(pair: str, direction: str, rr: float, idx: int = 0, outcome: str | None = None):
    """Insère un signal *simulé* résolu dans `backtest.db.trades`.

    Jamais un euro réel engagé — sert uniquement à vérifier que le
    contrôleur refuse désormais de décider dessus tant que le plancher
    `PAC_MIN_REAL_TRADES` n'est pas atteint en trades RÉELS.
    """
    from backend.services import backtest_service as bs
    bs._init_schema()
    outcome = outcome or ("WIN_TP1" if rr > 0 else "LOSS")
    checked_at = (datetime.now(timezone.utc) + timedelta(minutes=idx)).isoformat()
    with bs._conn() as c:
        c.execute(
            """
            INSERT INTO trades (pair, direction, entry_price, stop_loss,
                                take_profit_1, take_profit_2, emitted_at,
                                checked_at, outcome, rr_realized)
            VALUES (?, ?, 1.0, 0.9, 1.2, 1.4, ?, ?, ?, ?)
            """,
            (pair, direction, checked_at, checked_at, outcome, rr),
        )


def test_no_data_at_all_is_indeterminate_not_observed(_isolated_db):
    """Zéro trade réel ET zéro signal résolu → INDÉCIDABLE, pas OBSERVED.

    « On ne sait rien » doit être distinguable de « on sait que c'est
    mauvais » — les deux rendaient STATE_OBSERVED avant ce correctif.
    """
    from backend.services import pair_admission_controller as pac

    score = pac.compute_promotion_score("GBP/JPY", direction="buy")
    assert score["sample"] == 0
    assert score["eligible_for"] == pac.STATE_INDETERMINATE
    assert "donnée" in score["reason"].lower()


def test_only_simulated_data_is_indeterminate_not_observed_nor_eligible(_isolated_db):
    """0 trade réel + 30 signaux simulés gagnants → toujours INDÉCIDABLE.

    Distinct du cas précédent : ici il y a un échantillon (mixte), mais pas
    assez de trades RÉELS pour s'y fier. La raison doit le dire explicitement
    (≠ « pas de données du tout »).
    """
    from backend.services import pair_admission_controller as pac

    for i in range(30):
        rr = 0.2 if i % 5 < 3 else -0.1  # 18 gagnants / 12 perdants, PF>1.3, WR=60%
        _emit_signal("GBP/JPY", "buy", rr, idx=i)

    score = pac.compute_promotion_score("GBP/JPY", direction="buy")
    assert score["sample"] == 30
    assert score["eligible_for"] == pac.STATE_INDETERMINATE
    # La raison doit parler de trades réels manquants, pas d'absence totale de données.
    assert "réel" in score["reason"].lower()
    assert "donnée" not in score["reason"].lower() or "pas de données du tout" not in score["reason"].lower()


def test_indeterminate_is_distinct_from_every_real_state(_isolated_db):
    """STATE_INDETERMINATE n'est ni un état DB valide, ni confondu avec eux."""
    from backend.services import pair_admission_controller as pac

    assert pac.STATE_INDETERMINATE not in pac.VALID_STATES
    assert pac.STATE_INDETERMINATE not in (
        pac.STATE_OBSERVED, pac.STATE_TELEGRAM, pac.STATE_AUTO_EXEC,
        pac.STATE_PAUSED, pac.STATE_DEMOTED,
    )


def test_evaluate_observed_zero_real_thirty_simulated_ne_touche_pas_l_argent_reel(
    _isolated_db,
):
    """0 trade réel, 30 signaux simulés gagnants — le scénario qui permettait
    « la promotion auto from scratch ».

    ⚠️ Assertion révisée le 2026-08-06. Ce test exigeait auparavant que la
    paire reste `OBSERVED`. C'était trop fort : `OBSERVED` n'exécutant rien,
    la paire n'accumulait jamais de trade réel et ne pouvait donc PLUS JAMAIS
    être promue — une porte à sens unique qui a fermé l'admission
    (11 couples le 04/08, 8 le 05/08). Cf.
    `test_admission_porte_sens_unique.py`.

    Ce que le test protège reste intact et c'est le seul point qui comptait :
    **des signaux simulés ne donnent pas accès à l'argent réel.** La paire
    monte d'un cran vers `TELEGRAM`, qui n'engage aucun argent ; le passage à
    `AUTO_EXEC` reste soumis au palier temporel de la branche TELEGRAM.
    """
    from backend.services import pair_admission_controller as pac

    for i in range(30):
        rr = 0.2 if i % 5 < 3 else -0.1
        _emit_signal("GBP/JPY", "buy", rr, idx=i)

    d = pac.evaluate_pair("GBP/JPY", direction="buy")
    # L'échantillon reste honnêtement étiqueté « indécidable »…
    assert d["score"]["eligible_for"] == pac.STATE_INDETERMINATE
    # …et surtout : aucun accès à l'argent réel sur du simulé.
    assert d.get("to_state") != pac.STATE_AUTO_EXEC
    assert pac.get_current_state("GBP/JPY", direction="buy") != pac.STATE_AUTO_EXEC


def test_evaluate_observed_with_enough_real_trades_unchanged_behavior(_isolated_db):
    """Avec 30 trades RÉELS gagnants, le comportement reste STRICTEMENT celui
    d'avant : promotion vers AUTO_PROMOTE_TARGET.
    """
    from backend.services import pair_admission_controller as pac

    for i in range(30):
        _insert_trade(
            _isolated_db, "GBP/JPY", 50.0,
            closed_at=(datetime.now(timezone.utc) + timedelta(minutes=i)).isoformat(),
            direction="buy",
        )
    d = pac.evaluate_pair("GBP/JPY", direction="buy")
    assert d["action"] == "transition"
    assert d["to_state"] == pac.AUTO_PROMOTE_TARGET
    assert pac.get_current_state("GBP/JPY", direction="buy") == pac.AUTO_PROMOTE_TARGET


def test_evaluate_auto_exec_not_demoted_on_insufficient_real_sample(_isolated_db):
    """LE test qui mord : rejoue le mécanisme exact du -251% du 2026-08-04.

    Pair déjà AUTO_EXEC (argent réel engagé), 0 trade réel dans la fenêtre,
    30 signaux SIMULÉS massivement perdants (-90% de pnl_pct, très en dessous
    du seuil -3%). Sans le correctif, ceci rétrograde la pair en PAUSED sur
    une donnée entièrement fictive. Avec le correctif, aucune décision.
    """
    from backend.services import pair_admission_controller as pac

    pac.set_state("NZD/USD", pac.STATE_AUTO_EXEC, "test init", direction="buy")
    for i in range(30):
        _emit_signal("NZD/USD", "buy", -3.0, idx=i)  # -300€/trade à 10k capital = -90%

    d = pac.evaluate_pair("NZD/USD", direction="buy")
    assert d["action"] == "keep"
    assert d["score"]["eligible_for"] == pac.STATE_INDETERMINATE
    assert pac.get_current_state("NZD/USD", direction="buy") == pac.STATE_AUTO_EXEC


def test_evaluate_auto_exec_demote_unchanged_with_enough_real_trades(_isolated_db):
    """Avec assez de trades RÉELS perdants, la rétrogradation reste
    STRICTEMENT celle d'avant (déjà couvert par
    ``test_evaluate_auto_exec_demotes_to_paused_on_drawdown`` ci-dessus,
    reproduit ici dans le contexte du garde-fou pour lisibilité)."""
    from backend.services import pair_admission_controller as pac

    pac.set_state("NZD/USD", pac.STATE_AUTO_EXEC, "test init", direction="buy")
    for i in range(30):
        _insert_trade(
            _isolated_db, "NZD/USD", -50.0,
            closed_at=(datetime.now(timezone.utc) + timedelta(minutes=i)).isoformat(),
            direction="buy",
        )
    d = pac.evaluate_pair("NZD/USD", direction="buy")
    assert d["action"] == "transition"
    assert d["to_state"] == pac.STATE_PAUSED


def test_permissive_setting_restores_prior_promote_behavior(_isolated_db, monkeypatch):
    """PAC_MIN_REAL_TRADES=0 doit restaurer EXACTEMENT le comportement
    antérieur au 2026-08-05 : promotion possible sur échantillon 100% simulé.

    Vérifie que le réglage est bien lu au point d'appel (`compute_promotion_score`
    / `evaluate_pair`), pas seulement au chargement du module.
    """
    import config.settings as st
    from backend.services import pair_admission_controller as pac
    monkeypatch.setattr(st, "PAC_MIN_REAL_TRADES", 0)

    for i in range(30):
        rr = 0.2 if i % 5 < 3 else -0.1
        _emit_signal("GBP/JPY", "buy", rr, idx=i)

    d = pac.evaluate_pair("GBP/JPY", direction="buy")
    assert d["action"] == "transition"
    assert d["to_state"] == pac.AUTO_PROMOTE_TARGET
    assert pac.get_current_state("GBP/JPY", direction="buy") == pac.AUTO_PROMOTE_TARGET


def test_permissive_setting_restores_prior_demote_behavior(_isolated_db, monkeypatch):
    """PAC_MIN_REAL_TRADES=0 restaure aussi la rétrogradation auto sur
    échantillon 100% simulé — symétrique du test de promotion ci-dessus.
    """
    import config.settings as st
    from backend.services import pair_admission_controller as pac
    monkeypatch.setattr(st, "PAC_MIN_REAL_TRADES", 0)

    pac.set_state("NZD/USD", pac.STATE_AUTO_EXEC, "test init", direction="buy")
    for i in range(30):
        _emit_signal("NZD/USD", "buy", -3.0, idx=i)

    d = pac.evaluate_pair("NZD/USD", direction="buy")
    assert d["action"] == "transition"
    assert d["to_state"] == pac.STATE_PAUSED


def test_reason_distinguishes_no_data_from_not_enough_real_trades(_isolated_db):
    """Les deux motifs d'indécision doivent être textuellement différenciables
    (diagnostic actionnable dans 6 mois, sans avoir à relire le code)."""
    from backend.services import pair_admission_controller as pac

    no_data = pac.compute_promotion_score("CAD/CHF", direction="sell")
    for i in range(30):
        _emit_signal("CAD/CHF", "sell", 0.1, idx=i)
    padded = pac.compute_promotion_score("CAD/CHF", direction="sell")

    assert no_data["eligible_for"] == pac.STATE_INDETERMINATE
    assert padded["eligible_for"] == pac.STATE_INDETERMINATE
    assert no_data["reason"] != padded["reason"]


def test_metriques_de_signaux_ne_sont_pas_affichees(_isolated_db):
    """Un score bâti sur des signaux ne doit exposer AUCUNE métrique chiffrée.

    `backtest.db` détermine ses issues par un sondage du prix courant toutes
    les ~3 min, sans rejouer les bougies : 55 à 65 % de ses gagnants avaient
    déjà touché leur stop (mesuré le 2026-08-13). Un `wr` de 45 % y vaut
    ~18 % réels.

    Le garde-fou `PAC_MIN_REAL_TRADES` empêche déjà ces chiffres de DÉCIDER.
    Il ne les empêchait pas d'être LUS — `/api/admin/pair-admission` les
    affiche, et 47 transitions de l'historique sont `admin_manual`.

    ⚠️ On masque, on ne supprime pas : `sample`, `n_real` et `n_simulated`
    restent, sinon l'écran dirait « pas de données » là où il y en a — des
    mauvaises. Nommer la borne plutôt que laisser un trou.
    """
    from backend.services import pair_admission_controller as pac

    for i in range(30):
        rr = 0.2 if i % 5 < 3 else -0.1        # WR 60 %, PF > 1,3 : flatteur
        _emit_signal("GBP/JPY", "buy", rr, idx=i)

    score = pac.compute_promotion_score("GBP/JPY", direction="buy")

    assert score["eligible_for"] == pac.STATE_INDETERMINATE
    for cle in ("sum_pnl", "pnl_pct", "wr", "pf", "max_dd_pct"):
        assert score[cle] is None, f"{cle} ne doit pas etre chiffre : {score[cle]}"
    # Ce qui décrit la situation reste lisible.
    assert score["sample"] == 30
    assert score["n_real"] == 0
    assert score["n_simulated"] == 30
    assert score["pnl_source"] == "backtest_trades"


def test_metriques_reelles_restent_affichees(_isolated_db):
    """Aucune régression : sur des trades RÉELS, les chiffres restent chiffrés."""
    from backend.services import pair_admission_controller as pac
    import config.settings as st

    st.PAC_MIN_REAL_TRADES = 3
    try:
        for i in range(4):
            _insert_trade(_isolated_db, "GBP/JPY", 10.0 if i < 3 else -5.0,
                          direction="buy")
        score = pac.compute_promotion_score("GBP/JPY", direction="buy", window=4)
        assert score["n_real"] == 4
        assert score["eligible_for"] != pac.STATE_INDETERMINATE
        for cle in ("sum_pnl", "pnl_pct", "wr", "pf", "max_dd_pct"):
            assert score[cle] is not None, f"{cle} doit rester chiffre"
    finally:
        st.PAC_MIN_REAL_TRADES = 30
