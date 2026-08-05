"""Tests de l'orchestrateur backend.services.macro_history_features —
branchement des deux historiques réels (macro_daily + fear_greed_snapshots)
en accès point-in-time, sans look-ahead, sans constante de repli.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.services import fear_greed_service, macro_data, macro_history_features, trade_log_service


@pytest.fixture
def temp_macro_db(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "macro_test.db"
    monkeypatch.setattr(macro_data, "DB_PATH", db_path)
    return db_path


@pytest.fixture
def temp_trades_db(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "t.db"
    monkeypatch.setattr(trade_log_service, "_DB_PATH", db_path)
    trade_log_service._init_schema()
    fear_greed_service._init_schema()
    return db_path


def _insert_fg(db_path: Path, recorded_at: str, value: float, classification: str) -> None:
    with sqlite3.connect(db_path) as c:
        c.execute(
            "INSERT INTO fear_greed_snapshots (recorded_at, value, classification) "
            "VALUES (?, ?, ?)",
            (recorded_at, value, classification),
        )


# ─── Sources vides → None partout, jamais une constante ────────────────────


def test_all_none_when_both_sources_empty(temp_macro_db, temp_trades_db):
    ts = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    feats = macro_history_features.get_features_at("EUR/USD", ts)

    assert feats == {
        "mh_vix_level": None,
        "mh_vix_delta_1d": None,
        "mh_dxy_level": None,
        "mh_spx_level": None,
        "mh_tnx_level": None,
        "mh_btc_level": None,
        "mh_fear_greed_value": None,
        "mh_fear_greed_code": None,
    }
    # Aucune des valeurs numériques ne doit être une constante de repli
    # (17.0 pour VIX était le défaut historiquement bugué).
    assert feats["mh_vix_level"] != 17.0


# ─── Cas nominal : valeur historique rendue pour une date passée ──────────


def test_returns_historical_values_for_past_date(temp_macro_db, temp_trades_db):
    macro_data.upsert_observations("vix", [
        {"date": "2026-05-28", "close": 22.5},
        {"date": "2026-05-29", "close": 21.0},
    ])
    macro_data.upsert_observations("btc", [
        {"date": "2026-05-29", "close": 61000.0},
    ])
    _insert_fg(temp_trades_db, "2026-05-29T22:30:00+00:00", 38.0, "fear")

    ts = datetime(2026, 5, 30, 9, 0, tzinfo=timezone.utc)  # matin du 30
    feats = macro_history_features.get_features_at("BTC/USD", ts)

    # macro_daily : asof T-1j (le 29, close du 28 disponible avant lui-même
    # via get_macro_features_at qui applique déjà sa propre règle T-1)
    assert feats["mh_vix_level"] == 21.0
    assert feats["mh_btc_level"] == 61000.0
    # fear_greed_snapshots : recorded_at réel <= ts
    assert feats["mh_fear_greed_value"] == 38.0
    assert feats["mh_fear_greed_code"] == 1  # "fear"


# ─── Avant le début de l'historique → None ─────────────────────────────────


def test_before_history_start_returns_none(temp_macro_db, temp_trades_db):
    macro_data.upsert_observations("vix", [{"date": "2026-05-29", "close": 21.0}])
    _insert_fg(temp_trades_db, "2026-05-29T22:30:00+00:00", 38.0, "fear")

    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    feats = macro_history_features.get_features_at("EUR/USD", ts)

    assert feats["mh_vix_level"] is None
    assert feats["mh_fear_greed_value"] is None
    assert feats["mh_fear_greed_code"] is None


# ─── Test de fuite : jamais une valeur postérieure à ts ────────────────────


def test_never_leaks_future_values(temp_macro_db, temp_trades_db):
    macro_data.upsert_observations("vix", [
        {"date": "2026-05-29", "close": 21.0},   # passé
        {"date": "2026-06-02", "close": 55.0},   # futur (spike si visible)
    ])
    _insert_fg(temp_trades_db, "2026-05-29T22:30:00+00:00", 38.0, "fear")
    _insert_fg(temp_trades_db, "2026-06-02T22:30:00+00:00", 95.0, "extreme_greed")  # futur

    ts = datetime(2026, 5, 30, 9, 0, tzinfo=timezone.utc)
    feats = macro_history_features.get_features_at("EUR/USD", ts)

    assert feats["mh_vix_level"] == 21.0  # jamais 55.0
    assert feats["mh_fear_greed_value"] == 38.0  # jamais 95.0
    assert feats["mh_fear_greed_code"] == 1  # jamais 4 (extreme_greed)


# ─── Best-effort : une source cassée ne fait jamais lever ──────────────────


def test_never_raises_when_sources_broken(temp_macro_db, temp_trades_db, monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("DB indisponible")

    monkeypatch.setattr(macro_data, "get_macro_features_at", _boom)
    monkeypatch.setattr(fear_greed_service, "get_value_at", _boom)

    ts = datetime(2026, 5, 30, tzinfo=timezone.utc)
    feats = macro_history_features.get_features_at("EUR/USD", ts)

    assert feats["mh_vix_level"] is None
    assert feats["mh_fear_greed_value"] is None
