"""Tests Phase 4 — module backend.services.macro_data.

Tests offline (pas de fetch HTTP réel) :
- ensure_schema idempotent
- upsert_observations + get_series + get_close_at_or_before
- get_macro_features_at no look-ahead (asof T-1d)
- _vix_regime classification
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone

import pytest

from backend.services import macro_data


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "macro_test.db"
    monkeypatch.setattr(macro_data, "DB_PATH", db_path)
    return db_path


# ─── Schema ─────────────────────────────────────────────────────────────────


def test_ensure_schema_idempotent(temp_db):
    macro_data.ensure_schema()
    macro_data.ensure_schema()
    with sqlite3.connect(temp_db) as c:
        rows = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='macro_daily'"
        ).fetchall()
        assert len(rows) == 1


# ─── Upsert / lookup ────────────────────────────────────────────────────────


def test_upsert_and_get_series(temp_db):
    obs = [
        {"date": "2026-04-01", "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "volume": 0},
        {"date": "2026-04-02", "open": 101.0, "high": 103.0, "low": 100.0, "close": 102.5, "volume": 0},
    ]
    n = macro_data.upsert_observations("vix", obs)
    assert n == 2

    series = macro_data.get_series("vix")
    assert len(series) == 2
    assert series[0]["close"] == 101.0
    assert series[1]["close"] == 102.5


def test_upsert_idempotent(temp_db):
    obs = [{"date": "2026-04-01", "close": 101.0}]
    macro_data.upsert_observations("vix", obs)
    # Re-insert same observation, should overwrite (UPSERT)
    macro_data.upsert_observations("vix", [{"date": "2026-04-01", "close": 105.0}])
    series = macro_data.get_series("vix")
    assert len(series) == 1
    assert series[0]["close"] == 105.0


def test_get_close_at_or_before(temp_db):
    obs = [
        {"date": "2026-04-01", "close": 100.0},
        {"date": "2026-04-03", "close": 102.0},
        {"date": "2026-04-07", "close": 104.0},
    ]
    macro_data.upsert_observations("vix", obs)

    # Date exacte
    r = macro_data.get_close_at_or_before("vix", date(2026, 4, 3))
    assert r["close"] == 102.0

    # Date entre 2 obs (weekend / holiday)
    r = macro_data.get_close_at_or_before("vix", date(2026, 4, 5))
    assert r["close"] == 102.0  # Plus récent ≤ target

    # Date après dernière obs
    r = macro_data.get_close_at_or_before("vix", date(2026, 4, 10))
    assert r["close"] == 104.0

    # Date avant première obs
    r = macro_data.get_close_at_or_before("vix", date(2026, 3, 30))
    assert r is None


# ─── No look-ahead ──────────────────────────────────────────────────────────


def test_get_macro_features_at_uses_T_minus_1(temp_db):
    """Vérifie que get_macro_features_at(T) utilise des obs strictement
    antérieures à T. Si T = 2026-04-15 14:00, l'obs daily de 2026-04-15
    ne doit PAS être utilisée."""
    # Insère une obs à T (qui ne devrait pas être utilisée) et une à T-1
    obs = [
        {"date": "2026-04-14", "close": 18.0},  # T-1
        {"date": "2026-04-15", "close": 25.0},  # T (futur)
    ]
    macro_data.upsert_observations("vix", obs)

    # Query at T = 2026-04-15 14:00 UTC
    ts = datetime(2026, 4, 15, 14, 0, tzinfo=timezone.utc)
    feats = macro_data.get_macro_features_at(ts)

    # Doit utiliser l'obs T-1 (close 18.0), pas T (close 25.0)
    assert feats["vix_level"] == 18.0
    assert feats["vix_asof"] == "2026-04-14"


def test_get_macro_features_at_returns_features(temp_db):
    """Vérifie que les features dérivées sont calculées correctement."""
    # Insère 60 jours d'obs pour avoir SMA50 + return_5d
    obs = []
    for i in range(60):
        d = date(2026, 1, 1) + (date(2026, 3, 1) - date(2026, 1, 1)) * i / 60
        # Hack simple : prix montant linéairement
        obs.append({
            "date": (date(2026, 2, 1) + (date(2026, 4, 1) - date(2026, 2, 1)) * (i / 60)).isoformat(),
            "close": 100.0 + i * 0.5,
        })
    # Ordre chronologique
    obs.sort(key=lambda x: x["date"])
    macro_data.upsert_observations("vix", obs)

    ts = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)
    feats = macro_data.get_macro_features_at(ts)

    # Doit retourner les features VIX
    assert "vix_level" in feats
    assert "vix_regime" in feats
    assert feats["vix_regime"] in ("low", "normal", "high")
    # delta_1d présent (assez d'obs)
    assert "vix_delta_1d" in feats


# ─── _vix_regime ────────────────────────────────────────────────────────────


def test_vix_regime_classification():
    assert macro_data._vix_regime(10.0) == "low"
    assert macro_data._vix_regime(14.99) == "low"
    assert macro_data._vix_regime(15.0) == "normal"
    assert macro_data._vix_regime(20.0) == "normal"
    assert macro_data._vix_regime(24.99) == "normal"
    assert macro_data._vix_regime(25.0) == "high"
    assert macro_data._vix_regime(50.0) == "high"


# ─── Edge cases ─────────────────────────────────────────────────────────────


def test_get_macro_features_at_empty_db(temp_db):
    """Si DB vide, retourne dict avec asof_date mais pas de features."""
    ts = datetime(2026, 4, 15, 14, 0, tzinfo=timezone.utc)
    feats = macro_data.get_macro_features_at(ts)
    assert "asof_date" in feats
    assert "vix_level" not in feats
    assert "dxy_level" not in feats


def test_upsert_empty_list(temp_db):
    """Upsert d'une liste vide ne plante pas."""
    n = macro_data.upsert_observations("vix", [])
    assert n == 0
