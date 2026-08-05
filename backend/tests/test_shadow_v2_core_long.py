"""Tests Phase 4 — module shadow_v2_core_long.

Couvre :
- aggregate_to_h4 (skip bars partiels)
- ensure_schema (idempotent)
- _persist_setup (UNIQUE constraint + risk_pct invalide)
- run_shadow_log (filtrage pattern + direction, no doublons)
- list_setups / summary
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.models.schemas import Candle, TradeDirection
from backend.services import shadow_v2_core_long as shadow


# ─── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """DB SQLite temporaire isolée pour chaque test."""
    db_path = tmp_path / "shadow_test.db"
    monkeypatch.setattr(shadow, "DB_PATH", db_path)
    return db_path


def _h1_candle(ts: datetime, close: float, span: float = 1.0) -> Candle:
    return Candle(
        timestamp=ts,
        open=close - span / 2,
        high=close + span,
        low=close - span,
        close=close,
        volume=100,
    )


def _make_h1_sequence(start: datetime, n: int, base: float = 2000.0,
                      step: float = 0.5) -> list[Candle]:
    """Séquence montante simple pour permettre des patterns LONG."""
    return [
        _h1_candle(start + timedelta(hours=i), base + i * step)
        for i in range(n)
    ]


# ─── aggregate_to_h4 ────────────────────────────────────────────────────────


def test_aggregate_to_h4_skips_partial_bars():
    """Les bars H4 incomplets (<4 H1) sont exclus."""
    start = datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)  # 00 UTC = bucket 0
    # 4 H1 complets pour le bucket 00-04, puis 2 H1 du bucket 04-08 (partiel)
    candles = _make_h1_sequence(start, 6)
    h4 = shadow.aggregate_to_h4(candles)
    assert len(h4) == 1, "Seul le bucket complet 00-04 doit être retenu"
    assert h4[0].timestamp == start
    assert h4[0].open == candles[0].open
    assert h4[0].close == candles[3].close
    assert h4[0].high == max(c.high for c in candles[:4])
    assert h4[0].low == min(c.low for c in candles[:4])


def test_aggregate_to_h4_alignment_buckets():
    """Bars alignés sur 00/04/08/12/16/20 UTC."""
    # Démarrage à 02 UTC (mid-bucket)
    start = datetime(2026, 4, 1, 2, 0, tzinfo=timezone.utc)
    candles = _make_h1_sequence(start, 12)
    h4 = shadow.aggregate_to_h4(candles)
    # Buckets attendus : 00 (incomplet 02-03 = 2 candles, skip),
    # 04 (4 candles complet), 08 (4 candles complet), 12 (2 candles, skip)
    assert len(h4) == 2
    assert h4[0].timestamp.hour == 4
    assert h4[1].timestamp.hour == 8


def test_aggregate_to_h4_empty_input():
    assert shadow.aggregate_to_h4([]) == []


# ─── ensure_schema ──────────────────────────────────────────────────────────


def test_ensure_schema_idempotent(temp_db):
    """Appel multiple ne casse pas la DB."""
    shadow.ensure_schema()
    shadow.ensure_schema()
    shadow.ensure_schema()
    with sqlite3.connect(temp_db) as c:
        # Vérifie que la table existe
        rows = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='shadow_setups'"
        ).fetchall()
        assert len(rows) == 1


# ─── run_shadow_log ─────────────────────────────────────────────────────────


def test_run_shadow_log_empty_input(temp_db, monkeypatch):
    """Pas de candles → 0 nouveaux setups, pas d'exception.

    Stub fetch_candles pour les paires Daily (ETH) afin d'éviter un
    appel API externe en test.
    """
    async def _fake_fetch(*_args, **_kwargs):
        return ([], False)
    monkeypatch.setattr(
        "backend.services.price_service.fetch_candles", _fake_fetch
    )
    result = asyncio.run(shadow.run_shadow_log({}))
    expected = {p: 0 for p in shadow.SHADOW_PAIRS}
    assert result == expected


def test_run_shadow_log_too_few_candles(temp_db):
    """Moins de 30 H1 → skipped, 0 setup."""
    start = datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)
    short_h1 = _make_h1_sequence(start, 20)
    result = asyncio.run(shadow.run_shadow_log({"XAU/USD": short_h1, "XAG/USD": []}))
    assert result["XAU/USD"] == 0
    assert result["XAG/USD"] == 0


def test_run_shadow_log_unique_constraint(temp_db, monkeypatch):
    """Appels successifs sur les mêmes candles → 1 setup max par bar (idempotent).

    Twin filtered désactivé pour ce test (sinon les setups baseline +
    twins doublent le compte ; testé séparément).
    """
    import config.settings as _settings
    monkeypatch.setattr(_settings, "SHADOW_FILTERED_TWIN_ENABLED", False)

    start = datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)
    h1 = _make_h1_sequence(start, 200)  # 200 H1 = 50 H4 buckets
    h1_dict = {"XAU/USD": h1, "XAG/USD": h1}

    # 1er appel
    r1 = asyncio.run(shadow.run_shadow_log(h1_dict))
    n1_xau = r1["XAU/USD"]

    # 2e appel identique → 0 nouveau (UNIQUE bloque)
    r2 = asyncio.run(shadow.run_shadow_log(h1_dict))
    assert r2["XAU/USD"] == 0, "Même bar_timestamp ne doit pas créer de doublon"

    # Total en DB = n1
    with sqlite3.connect(temp_db) as c:
        n_total = c.execute(
            "SELECT COUNT(*) FROM shadow_setups WHERE pair = 'XAU/USD'"
        ).fetchone()[0]
        assert n_total == n1_xau


def test_run_shadow_log_branche_le_snapshot_funding(temp_db, monkeypatch):
    """run_shadow_log doit appeler _capture_funding_snapshot et faire
    parvenir son résultat jusqu'à la ligne persistée — preuve du
    branchement, indépendamment de la logique crypto/non-crypto déjà
    testée au niveau unitaire sur _capture_funding_snapshot elle-même."""
    import config.settings as _settings
    monkeypatch.setattr(_settings, "SHADOW_FILTERED_TWIN_ENABLED", False)

    marker = {"marker": "funding-wiring-proof", "rate": 4.2e-5}
    appels = []

    def _fake_capture(pair, direction):
        appels.append((pair, direction))
        return marker

    monkeypatch.setattr(shadow, "_capture_funding_snapshot", _fake_capture)

    start = datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)
    h1 = _make_h1_sequence(start, 200)
    asyncio.run(shadow.run_shadow_log({"XAU/USD": h1}))

    assert appels, "run_shadow_log n'a jamais appelé _capture_funding_snapshot"

    with sqlite3.connect(temp_db) as c:
        rows = c.execute(
            "SELECT funding_features_json FROM shadow_setups WHERE pair = 'XAU/USD'"
        ).fetchall()
    assert rows, "aucun setup persisté — le test ne prouve rien"
    import json as _json
    for (raw,) in rows:
        assert raw is not None
        assert _json.loads(raw) == marker


def test_run_shadow_log_ne_score_qu_une_fois_par_bougie_reellement_nouvelle(
    temp_db, monkeypatch,
):
    """Le scoring (volatilité + enrichissement + verdict) ne doit tourner
    qu'une fois par bougie qui persiste réellement, pas à chaque cycle de
    5 minutes sur la même bougie 4h/1d inchangée — jusqu'à 48 fois par
    bougie et par paire avant le correctif perf du 2026-08-05, puisque le
    scheduler tourne toutes les 5 min et qu'une seule persistance réussit
    par bougie (contrainte UNIQUE system_id/bar_timestamp).
    """
    import config.settings as _settings
    from backend.services import analysis_engine

    monkeypatch.setattr(_settings, "SHADOW_FILTERED_TWIN_ENABLED", False)

    appels = []
    original = analysis_engine.enrich_trade_setup

    def _compte(setup, *a, **k):
        appels.append(1)
        return original(setup, *a, **k)

    monkeypatch.setattr(analysis_engine, "enrich_trade_setup", _compte)

    start = datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)
    h1 = _make_h1_sequence(start, 200)  # 200 H1 = 50 H4 buckets
    h1_dict = {"XAU/USD": h1, "XAG/USD": h1}

    # 1er cycle : bougie nouvelle, le scoring doit tourner au moins une fois.
    asyncio.run(shadow.run_shadow_log(h1_dict))
    n_apres_1er_cycle = len(appels)
    assert n_apres_1er_cycle > 0, "le premier cycle doit scorer au moins un setup"

    # Cycles suivants sur les MÊMES bougies : la persistance échoue (UNIQUE),
    # le scoring ne doit PAS retourner à chaque fois.
    for _ in range(5):
        asyncio.run(shadow.run_shadow_log(h1_dict))

    assert len(appels) == n_apres_1er_cycle, (
        "le scoring a tourné alors qu'aucune nouvelle bougie n'a été persistée"
    )


# ─── list_setups / summary ──────────────────────────────────────────────────


def test_list_setups_empty_db(temp_db):
    setups = shadow.list_setups()
    assert setups == []


def test_summary_empty_db(temp_db):
    s = shadow.summary()
    assert s == {"systems": []}


def test_summary_with_resolved_setups(temp_db):
    """Insère manuellement quelques setups résolus, vérifie KPIs."""
    shadow.ensure_schema()
    now = datetime.now(timezone.utc)
    rows_to_insert = [
        # (system_id, bar_ts, outcome, pnl_eur)
        ("V2_CORE_LONG_XAUUSD_4H", now - timedelta(days=10), "TP1", 100.0),
        ("V2_CORE_LONG_XAUUSD_4H", now - timedelta(days=8), "SL", -50.0),
        ("V2_CORE_LONG_XAUUSD_4H", now - timedelta(days=5), "TP1", 150.0),
        ("V2_CORE_LONG_XAUUSD_4H", now - timedelta(days=2), "SL", -50.0),
    ]
    with sqlite3.connect(temp_db) as c:
        for sys_id, bar_ts, outcome, pnl in rows_to_insert:
            c.execute(
                """INSERT INTO shadow_setups (
                    cycle_at, bar_timestamp, system_id, pair, timeframe,
                    direction, pattern, entry_price, stop_loss, take_profit_1,
                    risk_pct, rr, sizing_capital_eur, sizing_risk_pct,
                    sizing_position_eur, sizing_max_loss_eur,
                    outcome, exit_at, exit_price, pnl_pct_net, pnl_eur
                ) VALUES (?, ?, ?, 'XAU/USD', '4h', 'buy', 'momentum_up',
                          2000.0, 1980.0, 2050.0, 0.01, 2.5, 10000, 0.005, 5000, 50,
                          ?, ?, 2050.0, 1.0, ?)""",
                (bar_ts.isoformat(), bar_ts.isoformat(), sys_id, outcome,
                 bar_ts.isoformat(), pnl),
            )

    s = shadow.summary()
    assert len(s["systems"]) == 1
    sys_data = s["systems"][0]
    assert sys_data["n_total"] == 4
    assert sys_data["n_tp1"] == 2
    assert sys_data["n_sl"] == 2
    assert sys_data["n_pending"] == 0
    # PF = 250 / 100 = 2.5
    assert sys_data["pf"] == pytest.approx(2.5, rel=0.01)
    # WR = 2/4 = 50%
    assert sys_data["wr_pct"] == pytest.approx(50.0, rel=0.01)
    # KPIs avancés présents
    assert "advanced" in sys_data
    assert sys_data["advanced"]["max_dd_pct"] is not None
    assert len(sys_data["advanced"]["equity_curve"]) == 4


# ─── Geopolitical snapshot capture ──────────────────────────────────────────


def test_capture_geopolitical_snapshot_with_full_data(monkeypatch):
    """Snapshot complet : Polymarket + GDELT + verdict veto."""
    fake_poly = {
        "fetched_at": "2026-05-08T10:00:00Z",
        "n_matched": 50,
        "themes": {
            "geopolitical": [
                {"question": "US x Iran permanent peace deal by June 30?",
                 "yes_prob": 0.52, "end_date": "2026-06-30"},
            ],
            "monetary": [
                {"question": "Will Fed announce a rate cut in May?",
                 "yes_prob": 0.30, "end_date": "2026-05-15"},
            ],
            "economy": [
                {"question": "US recession in 2026?",
                 "yes_prob": 0.18, "end_date": "2026-12-31"},
            ],
        },
    }
    fake_gdelt = {
        "fetched_at": "2026-05-08T10:00:00Z",
        "overall_stress": "elevated",
        "overall_tone": -2.5,
        "themes": {
            "geopolitical": {"stress_level": "high", "avg_tone": -8.0},
            "monetary": {"stress_level": "calm", "avg_tone": -1.0},
        },
    }
    from backend.services import polymarket_service, geopolitical_news_service, geopolitical_veto
    monkeypatch.setattr(polymarket_service, "get_current", lambda: fake_poly)
    monkeypatch.setattr(geopolitical_news_service, "get_current", lambda: fake_gdelt)
    monkeypatch.setattr(geopolitical_veto, "GEOPOLITICAL_VETO_ENABLED", False)  # neutre

    snap = shadow._capture_geopolitical_snapshot("XAU/USD", "buy")

    assert snap is not None
    assert snap["polymarket"]["available"] is True
    assert snap["polymarket"]["iran_peace_max_prob"] == 0.52
    assert snap["polymarket"]["fed_cut_max_prob"] == 0.30
    assert snap["polymarket"]["recession_max_prob"] == 0.18
    assert snap["gdelt"]["available"] is True
    assert snap["gdelt"]["overall_stress"] == "elevated"
    assert snap["gdelt"]["geopolitical_stress"] == "high"
    # Veto désactivé → pas de match
    assert snap["veto_evaluated"]["would_veto"] is False
    assert "rules_evaluated" in snap["veto_evaluated"]


def test_capture_geopolitical_snapshot_handles_missing_sources(monkeypatch):
    """Pas de Polymarket ni GDELT → snapshot avec available=False, pas d'exception."""
    from backend.services import polymarket_service, geopolitical_news_service
    monkeypatch.setattr(polymarket_service, "get_current", lambda: None)
    monkeypatch.setattr(geopolitical_news_service, "get_current", lambda: None)

    snap = shadow._capture_geopolitical_snapshot("XAU/USD", "buy")

    assert snap is not None
    assert snap["polymarket"]["available"] is False
    assert snap["gdelt"]["available"] is False
    assert "veto_evaluated" in snap


def test_persist_setup_stores_geopolitical_features(temp_db):
    """_persist_setup persiste bien geopolitical_features_json en DB."""
    from backend.models.schemas import TradeSetup, TradeDirection, PatternDetection, PatternType
    from datetime import datetime, timezone
    shadow.ensure_schema()

    bar_ts = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)
    cycle_ts = datetime(2026, 5, 8, 12, 5, tzinfo=timezone.utc)

    # Stub setup minimal
    class _S:
        pair = "XAU/USD"
        direction = TradeDirection.BUY
        entry_price = 2000.0
        stop_loss = 1990.0
        take_profit_1 = 2020.0
        take_profit_2 = 2030.0

    geopol = {
        "captured_at": "2026-05-08T12:05:00Z",
        "polymarket": {"available": True, "iran_peace_max_prob": 0.52},
        "veto_evaluated": {"would_veto": True, "rules_matched": ["iran_hormuz"]},
    }

    inserted = shadow._persist_setup(
        _S(), "XAU/USD", "momentum_up", bar_ts, cycle_ts,
        geopolitical_features=geopol,
    )
    assert inserted is True

    # Re-lire la DB pour vérifier que le JSON est bien persisté
    with sqlite3.connect(temp_db) as c:
        row = c.execute(
            "SELECT geopolitical_features_json FROM shadow_setups WHERE pair = ?",
            ("XAU/USD",),
        ).fetchone()
    import json as _json
    assert row is not None
    parsed = _json.loads(row[0])
    assert parsed["polymarket"]["iran_peace_max_prob"] == 0.52
    assert parsed["veto_evaluated"]["would_veto"] is True


def test_ensure_schema_idempotent_with_geopol_column(temp_db):
    """ensure_schema doit ajouter geopolitical_features_json à une table préexistante."""
    # Crée une table sans la colonne (état pré-migration)
    with sqlite3.connect(temp_db) as c:
        c.execute("""
            CREATE TABLE shadow_setups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                detected_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                cycle_at TIMESTAMP NOT NULL,
                bar_timestamp TIMESTAMP NOT NULL,
                system_id TEXT NOT NULL,
                pair TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                direction TEXT NOT NULL,
                pattern TEXT NOT NULL,
                entry_price REAL NOT NULL,
                stop_loss REAL NOT NULL,
                take_profit_1 REAL NOT NULL,
                take_profit_2 REAL,
                risk_pct REAL NOT NULL,
                rr REAL NOT NULL,
                sizing_capital_eur REAL NOT NULL DEFAULT 10000,
                sizing_risk_pct REAL NOT NULL DEFAULT 0.005,
                sizing_position_eur REAL NOT NULL,
                sizing_max_loss_eur REAL NOT NULL,
                macro_features_json TEXT,
                outcome TEXT,
                exit_at TIMESTAMP,
                exit_price REAL,
                pnl_pct_net REAL,
                pnl_eur REAL,
                UNIQUE (system_id, bar_timestamp)
            )
        """)

    # ensure_schema doit ajouter la colonne sans erreur
    shadow.ensure_schema()
    shadow.ensure_schema()  # 2e appel = no-op (idempotent)

    with sqlite3.connect(temp_db) as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(shadow_setups)").fetchall()]
    assert "geopolitical_features_json" in cols


# ─── Filtered twin systems (V2_CORE_LONG_*_FILTERED) ────────────────────────


def test_persist_setup_with_system_id_override(temp_db):
    """system_id_override permet de logger un twin filtered sans collision."""
    from backend.models.schemas import TradeDirection
    from datetime import datetime, timezone
    shadow.ensure_schema()

    bar_ts = datetime(2026, 5, 8, 16, 0, tzinfo=timezone.utc)
    cycle_ts = datetime(2026, 5, 8, 16, 5, tzinfo=timezone.utc)

    class _S:
        pair = "XAU/USD"
        direction = TradeDirection.BUY
        entry_price = 2400.0
        stop_loss = 2390.0
        take_profit_1 = 2418.0
        take_profit_2 = 2425.0

    # Baseline insert
    inserted_base = shadow._persist_setup(
        _S(), "XAU/USD", "momentum_up", bar_ts, cycle_ts,
    )
    assert inserted_base is True

    # Twin avec override : même bar_ts MAIS system_id différent → pas de collision
    inserted_twin = shadow._persist_setup(
        _S(), "XAU/USD", "momentum_up", bar_ts, cycle_ts,
        system_id_override="V2_CORE_LONG_XAUUSD_4H_FILTERED",
    )
    assert inserted_twin is True

    # Vérifier qu'on a bien 2 rows distincts
    with sqlite3.connect(temp_db) as c:
        rows = c.execute(
            "SELECT system_id FROM shadow_setups WHERE bar_timestamp = ?",
            (bar_ts.isoformat(),),
        ).fetchall()
    system_ids = sorted(r[0] for r in rows)
    assert system_ids == [
        "V2_CORE_LONG_XAUUSD_4H",
        "V2_CORE_LONG_XAUUSD_4H_FILTERED",
    ]


def test_persist_setup_unique_constraint_per_system_id(temp_db):
    """L'UNIQUE constraint est sur (system_id, bar_timestamp) — un même
    system_id avec le même bar_ts est skip silencieusement (idempotent)."""
    from backend.models.schemas import TradeDirection
    from datetime import datetime, timezone
    shadow.ensure_schema()

    bar_ts = datetime(2026, 5, 8, 16, 0, tzinfo=timezone.utc)
    cycle_ts = datetime(2026, 5, 8, 16, 5, tzinfo=timezone.utc)

    class _S:
        pair = "XAU/USD"
        direction = TradeDirection.BUY
        entry_price = 2400.0
        stop_loss = 2390.0
        take_profit_1 = 2418.0
        take_profit_2 = 2425.0

    # 1er insert
    assert shadow._persist_setup(_S(), "XAU/USD", "momentum_up", bar_ts, cycle_ts) is True
    # 2nd insert même (system_id, bar_ts) → skip silencieux
    assert shadow._persist_setup(_S(), "XAU/USD", "momentum_up", bar_ts, cycle_ts) is False

    with sqlite3.connect(temp_db) as c:
        n = c.execute("SELECT COUNT(*) FROM shadow_setups").fetchone()[0]
    assert n == 1


# ─── Funding snapshot capture ───────────────────────────────────────────────
#
# Le veto funding Kraken (soft veto ×0.85) est une hypothèse dosée sur une
# fréquence de déclenchement plausible (p95 mesuré), jamais démontrée
# prédictive. `_capture_funding_snapshot` persiste le taux + le seuil en
# vigueur + le verdict contrefactuel pour rendre cette question tranchable
# a posteriori (cf. backend/services/kraken_funding_scoring.py, section
# "Non-livrables" / commentaire sur `_DEFAULT_EXTREME_THRESHOLD`).


def test_capture_funding_snapshot_crypto_pair_full(monkeypatch):
    """Paire crypto, taux au-dessus du seuil → snapshot complet + veto=True."""
    from backend.services import kraken_funding_scoring as kfs

    monkeypatch.setattr(kfs, "get_funding_rate_for_pair", lambda pair: 5.0e-5)
    monkeypatch.setattr(kfs, "_EXTREME_THRESHOLD", 2.0e-5)

    snap = shadow._capture_funding_snapshot("BTC/USD", "buy")

    assert snap is not None
    assert snap["rate"] == pytest.approx(5.0e-5)
    assert snap["symbol"] == "PF_XBTUSD"
    assert snap["extreme_threshold"] == pytest.approx(2.0e-5)
    assert snap["would_veto"] is True
    assert "captured_at" in snap


def test_capture_funding_snapshot_non_crypto_pair_returns_none(monkeypatch):
    """Une paire non-crypto rend None — pas un dict vide.

    On fait échouer volontairement `get_funding_rate_for_pair` (exception)
    pour prouver que la fonction ne l'appelle même pas sur une paire
    non-crypto : si le guard `is_crypto_pair` était contourné, ce test
    lèverait au lieu de rendre None silencieusement.
    """
    from backend.services import kraken_funding_scoring as kfs

    def _boom(pair):
        raise AssertionError("get_funding_rate_for_pair ne doit pas être appelé pour une paire non-crypto")

    monkeypatch.setattr(kfs, "get_funding_rate_for_pair", _boom)

    assert shadow._capture_funding_snapshot("XAU/USD", "buy") is None
    assert shadow._capture_funding_snapshot("EUR/USD", "sell") is None


def test_capture_funding_snapshot_rate_unavailable_yields_none_not_zero(monkeypatch):
    """Taux Kraken indisponible → rate=None (jamais 0.0), would_veto=None,
    et la capture ne lève pas."""
    from backend.services import kraken_funding_scoring as kfs

    monkeypatch.setattr(kfs, "get_funding_rate_for_pair", lambda pair: None)
    monkeypatch.setattr(kfs, "_EXTREME_THRESHOLD", 2.0e-5)

    snap = shadow._capture_funding_snapshot("ETH/USD", "buy")

    assert snap is not None
    assert snap["rate"] is None
    assert snap["rate"] != 0.0
    assert snap["would_veto"] is None
    # Le seuil, lui, reste connu même si le taux ne l'est pas.
    assert snap["extreme_threshold"] == pytest.approx(2.0e-5)


def test_capture_funding_snapshot_exception_does_not_raise(monkeypatch):
    """Une exception dans le fetch du taux ne doit pas remonter — best-effort."""
    from backend.services import kraken_funding_scoring as kfs

    def _raise(pair):
        raise RuntimeError("Kraken API down")

    monkeypatch.setattr(kfs, "get_funding_rate_for_pair", _raise)

    snap = shadow._capture_funding_snapshot("BTC/USD", "buy")

    assert snap is not None  # toujours un dict (paire crypto), jamais de raise
    assert snap["rate"] is None
    assert snap["would_veto"] is None


@pytest.mark.parametrize(
    "direction,rate,threshold,expected_veto",
    [
        ("buy", 5.0e-5, 2.0e-5, True),   # funding positif extrême + BUY → veto
        ("buy", 1.0e-5, 2.0e-5, False),  # funding positif sous le seuil → neutre
        ("sell", -5.0e-5, 2.0e-5, True),  # funding négatif extrême + SELL → veto
        ("sell", -1.0e-5, 2.0e-5, False),  # funding négatif sous le seuil → neutre
        ("sell", 5.0e-5, 2.0e-5, False),  # funding positif extrême + SELL → pas surcrowdé
        ("buy", -5.0e-5, 2.0e-5, False),  # funding négatif extrême + BUY → pas surcrowdé
    ],
)
def test_capture_funding_snapshot_veto_consistent_with_rate_and_threshold(
    monkeypatch, direction, rate, threshold, expected_veto
):
    """Le verdict contrefactuel stocké doit être recalculable à partir du
    taux et du seuil enregistrés dans le MÊME instantané — c'est ce qui
    rend la donnée durable plutôt que jetable (cf. spec)."""
    from backend.services import kraken_funding_scoring as kfs

    monkeypatch.setattr(kfs, "get_funding_rate_for_pair", lambda pair: rate)
    monkeypatch.setattr(kfs, "_EXTREME_THRESHOLD", threshold)

    snap = shadow._capture_funding_snapshot("BTC/USD", direction)

    assert snap["would_veto"] is expected_veto
    # Recalcul indépendant à partir des seuls champs persistés du snapshot :
    recomputed = (
        (snap["rate"] > snap["extreme_threshold"]) if direction == "buy"
        else (snap["rate"] < -snap["extreme_threshold"])
    )
    assert recomputed == expected_veto


def test_persist_setup_stores_funding_features(temp_db):
    """_persist_setup persiste bien funding_features_json en DB, avec le
    taux, le seuil et le verdict contrefactuel tous présents ensemble."""
    from backend.models.schemas import TradeDirection
    shadow.ensure_schema()

    bar_ts = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)
    cycle_ts = datetime(2026, 8, 5, 12, 5, tzinfo=timezone.utc)

    class _S:
        pair = "ETH/USD"
        direction = TradeDirection.BUY
        entry_price = 3000.0
        stop_loss = 2950.0
        take_profit_1 = 3100.0
        take_profit_2 = 3150.0

    funding = {
        "captured_at": "2026-08-05T12:05:00Z",
        "symbol": "PF_ETHUSD",
        "rate": 3.5e-5,
        "extreme_threshold": 2.0e-5,
        "would_veto": True,
    }

    inserted = shadow._persist_setup(
        _S(), "ETH/USD", "momentum_up", bar_ts, cycle_ts,
        funding_features=funding,
    )
    assert inserted is True

    with sqlite3.connect(temp_db) as c:
        row = c.execute(
            "SELECT funding_features_json FROM shadow_setups WHERE pair = ?",
            ("ETH/USD",),
        ).fetchone()
    import json as _json
    assert row is not None
    parsed = _json.loads(row[0])
    assert parsed["rate"] == pytest.approx(3.5e-5)
    assert parsed["extreme_threshold"] == pytest.approx(2.0e-5)
    assert parsed["would_veto"] is True
    assert parsed["symbol"] == "PF_ETHUSD"


def test_persist_setup_funding_features_none_stores_null(temp_db):
    """Une paire non-crypto (funding_features=None) ne doit PAS écrire de
    dict vide en JSON — la colonne doit rester NULL (mesure absente ≠
    question sans objet)."""
    from backend.models.schemas import TradeDirection
    shadow.ensure_schema()

    bar_ts = datetime(2026, 8, 5, 13, 0, tzinfo=timezone.utc)
    cycle_ts = datetime(2026, 8, 5, 13, 5, tzinfo=timezone.utc)

    class _S:
        pair = "XAU/USD"
        direction = TradeDirection.BUY
        entry_price = 2400.0
        stop_loss = 2390.0
        take_profit_1 = 2418.0
        take_profit_2 = 2425.0

    inserted = shadow._persist_setup(
        _S(), "XAU/USD", "momentum_up", bar_ts, cycle_ts,
        funding_features=None,
    )
    assert inserted is True

    with sqlite3.connect(temp_db) as c:
        row = c.execute(
            "SELECT funding_features_json FROM shadow_setups WHERE pair = ?",
            ("XAU/USD",),
        ).fetchone()
    assert row is not None
    assert row[0] is None


def test_ensure_schema_idempotent_with_funding_column(temp_db):
    """ensure_schema doit ajouter funding_features_json à une table
    préexistante (qui a déjà geopolitical_features_json) sans erreur."""
    with sqlite3.connect(temp_db) as c:
        c.execute("""
            CREATE TABLE shadow_setups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                detected_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                cycle_at TIMESTAMP NOT NULL,
                bar_timestamp TIMESTAMP NOT NULL,
                system_id TEXT NOT NULL,
                pair TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                direction TEXT NOT NULL,
                pattern TEXT NOT NULL,
                entry_price REAL NOT NULL,
                stop_loss REAL NOT NULL,
                take_profit_1 REAL NOT NULL,
                take_profit_2 REAL,
                risk_pct REAL NOT NULL,
                rr REAL NOT NULL,
                sizing_capital_eur REAL NOT NULL DEFAULT 10000,
                sizing_risk_pct REAL NOT NULL DEFAULT 0.005,
                sizing_position_eur REAL NOT NULL,
                sizing_max_loss_eur REAL NOT NULL,
                macro_features_json TEXT,
                geopolitical_features_json TEXT,
                outcome TEXT,
                exit_at TIMESTAMP,
                exit_price REAL,
                pnl_pct_net REAL,
                pnl_eur REAL,
                UNIQUE (system_id, bar_timestamp)
            )
        """)

    shadow.ensure_schema()
    shadow.ensure_schema()  # 2e appel = no-op idempotent

    with sqlite3.connect(temp_db) as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(shadow_setups)").fetchall()]
    assert "funding_features_json" in cols


# ─── Actions US individuelles (AAPL/TSLA/NVDA/MSFT), ajout 2026-08-05 ───────
#
# Ouvre la mesure d'edge pour la route DMA "actions US à coût fixe" (porte de
# coût bloquée sur edge=None faute d'observation). Les 4 titres sont ajoutés
# à l'horizon 4h, patterns par analogie avec XLK (déjà couvert) — cf.
# commentaire `US_EQUITY_TECH_PATTERNS` dans shadow_v2_core_long.py.


_US_EQUITY_TECH_PAIRS = ("AAPL", "TSLA", "NVDA", "MSFT")


def test_shadow_config_includes_us_equities_at_4h():
    """Les 4 actions US sont dans SHADOW_CONFIG, à l'horizon 4h (pas 1d)."""
    for pair in _US_EQUITY_TECH_PAIRS:
        assert pair in shadow.SHADOW_CONFIG, f"{pair} absent de SHADOW_CONFIG"
        assert shadow.SHADOW_CONFIG[pair]["tf"] == "4h", (
            f"{pair} doit être à l'horizon 4h (aggrégation H1 scheduler), "
            "pas 1d (qui déclencherait un fetch Daily direct non voulu)"
        )
        assert pair in shadow.SHADOW_PAIRS


def test_us_equities_use_xlk_analogy_patterns_not_core_long():
    """Patterns par analogie avec XLK (WTI_OPTIMAL_PATTERNS), PAS
    CORE_LONG_PATTERNS ni TIGHT_LONG_PATTERNS — le choix documenté dans le
    code doit se retrouver dans la config réellement chargée."""
    for pair in _US_EQUITY_TECH_PAIRS:
        cfg_patterns = shadow.SHADOW_CONFIG[pair]["patterns"]
        assert cfg_patterns == shadow.WTI_OPTIMAL_PATTERNS
        assert cfg_patterns == shadow.SHADOW_CONFIG["XLK"]["patterns"]
        assert cfg_patterns != shadow.CORE_LONG_PATTERNS
        assert "breakout_up" not in cfg_patterns


def test_us_equities_derived_mappings_consistent():
    """PATTERNS_BY_PAIR / SYSTEM_ID_BY_PAIR / RISK_PCT_BY_PAIR /
    TIMEFRAME_BY_PAIR restent dérivés fidèlement de SHADOW_CONFIG pour les 4
    nouveaux titres (pas de valeur codée en dur qui diverge)."""
    for pair in _US_EQUITY_TECH_PAIRS:
        cfg = shadow.SHADOW_CONFIG[pair]
        assert shadow.PATTERNS_BY_PAIR[pair] == cfg["patterns"]
        assert shadow.SYSTEM_ID_BY_PAIR[pair] == cfg["system_id"]
        assert shadow.RISK_PCT_BY_PAIR[pair] == cfg["risk_pct"]
        assert shadow.TIMEFRAME_BY_PAIR[pair] == cfg["tf"]
        # system_id suit la convention V2_WTI_OPTIMAL_<PAIR>_4H
        assert cfg["system_id"] == f"V2_WTI_OPTIMAL_{pair}_4H"
        # risk_pct non nul, non mesuré mais explicitement choisi (pas 0.0)
        assert cfg["risk_pct"] is not None
        assert cfg["risk_pct"] > 0


def test_existing_pairs_config_unchanged_after_us_equities_addition():
    """Régression : XAU/XAG/WTI/ETH/XLI/XLK gardent EXACTEMENT leur config
    d'avant l'ajout des actions US (patterns, system_id, risk_pct, tf)."""
    assert shadow.SHADOW_CONFIG["XAU/USD"] == {
        "tf": "4h",
        "patterns": shadow.CORE_LONG_PATTERNS,
        "system_id": "V2_CORE_LONG_XAUUSD_4H",
        "risk_pct": 0.005,
    }
    assert shadow.SHADOW_CONFIG["XAG/USD"] == {
        "tf": "4h",
        "patterns": shadow.CORE_LONG_PATTERNS,
        "system_id": "V2_CORE_LONG_XAGUSD_4H",
        "risk_pct": 0.003,
    }
    assert shadow.SHADOW_CONFIG["WTI/USD"] == {
        "tf": "4h",
        "patterns": shadow.WTI_OPTIMAL_PATTERNS,
        "system_id": "V2_WTI_OPTIMAL_WTIUSD_4H",
        "risk_pct": 0.003,
    }
    assert shadow.SHADOW_CONFIG["ETH/USD"] == {
        "tf": "1d",
        "patterns": shadow.CORE_LONG_PATTERNS,
        "system_id": "V2_CORE_LONG_ETHUSD_1D",
        "risk_pct": 0.0025,
    }
    assert shadow.SHADOW_CONFIG["XLI"] == {
        "tf": "1d",
        "patterns": shadow.TIGHT_LONG_PATTERNS,
        "system_id": "V2_TIGHT_LONG_XLI_1D",
        "risk_pct": 0.004,
    }
    assert shadow.SHADOW_CONFIG["XLK"] == {
        "tf": "1d",
        "patterns": shadow.WTI_OPTIMAL_PATTERNS,
        "system_id": "V2_WTI_OPTIMAL_XLK_1D",
        "risk_pct": 0.004,
    }
    # Le set complet des paires observées = les 6 historiques + les 4 nouvelles
    assert set(shadow.SHADOW_PAIRS) == {
        "XAU/USD", "XAG/USD", "WTI/USD", "ETH/USD", "XLI", "XLK",
        "AAPL", "TSLA", "NVDA", "MSFT",
    }


def test_run_shadow_log_persists_us_equity_setup_with_correct_horizon(
    temp_db, monkeypatch,
):
    """Un setup détecté sur AAPL (H4, patterns XLK-analogie) doit produire
    une ligne persistée avec system_id `V2_WTI_OPTIMAL_AAPL_4H` et
    timeframe `4h` — preuve bout-en-bout que la config se traduit
    correctement dans la table `shadow_setups`, pas seulement dans le dict
    Python.

    Stub `price_service.fetch_candles` (jamais de réseau en test) : les
    autres paires de SHADOW_CONFIG à horizon 1d (ETH/XLI/XLK) déclenchent
    un fetch Daily direct dans `run_shadow_log` même si on ne fournit que
    des H1 pour AAPL — ce stub coupe court avant toute tentative réseau.
    """
    import config.settings as _settings
    monkeypatch.setattr(_settings, "SHADOW_FILTERED_TWIN_ENABLED", False)

    async def _fake_fetch(*_args, **_kwargs):
        return ([], False)
    monkeypatch.setattr(
        "backend.services.price_service.fetch_candles", _fake_fetch
    )

    start = datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)
    h1 = _make_h1_sequence(start, 200)  # même séquence montante que XAU/XAG

    result = asyncio.run(shadow.run_shadow_log({"AAPL": h1}))
    assert result["AAPL"] > 0, "aucun setup détecté sur AAPL — le test ne prouve rien"

    with sqlite3.connect(temp_db) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT system_id, pair, timeframe, direction FROM shadow_setups "
            "WHERE pair = 'AAPL'"
        ).fetchall()

    assert rows, "aucune ligne persistée pour AAPL"
    for r in rows:
        assert r["system_id"] == "V2_WTI_OPTIMAL_AAPL_4H"
        assert r["timeframe"] == "4h"
        assert r["direction"] == "buy"


def test_ensure_schema_migration_safe_on_populated_table(temp_db):
    """La migration doit être sûre rejouée sur une table DÉJÀ PEUPLÉE de
    données : les rows existantes doivent survivre intactes, la nouvelle
    colonne doit apparaître NULL sur ces rows, et un nouvel insert avec
    funding doit fonctionner ensuite."""
    from backend.models.schemas import TradeDirection

    # Étape 1 : schéma pré-migration (avant funding_features_json), avec une
    # row déjà présente — reproduit le schéma de prod qui tourne avec des
    # données AVANT que cette migration ne soit déployée.
    shadow.ensure_schema()  # état actuel (a déjà macro + geopol, pas funding)

    class _S:
        pair = "XAU/USD"
        direction = TradeDirection.BUY
        entry_price = 2400.0
        stop_loss = 2390.0
        take_profit_1 = 2418.0
        take_profit_2 = 2425.0

    bar_ts_old = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    cycle_ts_old = datetime(2026, 8, 1, 12, 5, tzinfo=timezone.utc)
    assert shadow._persist_setup(_S(), "XAU/USD", "momentum_up", bar_ts_old, cycle_ts_old) is True

    # Étape 2 : rejouer la migration (simule un redéploiement / restart) —
    # ne doit ni lever, ni toucher la row existante.
    shadow.ensure_schema()
    shadow.ensure_schema()

    with sqlite3.connect(temp_db) as c:
        row = c.execute(
            "SELECT entry_price, funding_features_json FROM shadow_setups WHERE bar_timestamp = ?",
            (bar_ts_old.isoformat(),),
        ).fetchone()
    assert row is not None
    assert row[0] == pytest.approx(2400.0)  # la row pré-existante est intacte
    assert row[1] is None  # NULL sur les rows antérieures à la migration

    # Étape 3 : un nouvel insert avec funding fonctionne normalement après.
    bar_ts_new = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)
    cycle_ts_new = datetime(2026, 8, 5, 12, 5, tzinfo=timezone.utc)
    funding = {"rate": 3.0e-5, "extreme_threshold": 2.0e-5, "would_veto": True}
    assert shadow._persist_setup(
        _S(), "XAU/USD", "momentum_up", bar_ts_new, cycle_ts_new,
        funding_features=funding,
    ) is True

    with sqlite3.connect(temp_db) as c:
        n = c.execute("SELECT COUNT(*) FROM shadow_setups").fetchone()[0]
    assert n == 2
