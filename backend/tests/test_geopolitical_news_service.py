"""Tests pour `geopolitical_news_service` — focus sur le fallback per-theme
quand un fetch GDELT échoue.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from backend.services import geopolitical_news_service as g


@pytest.fixture(autouse=True)
def _reset_cache():
    """Reset module cache entre tests pour isolation."""
    g._cache = None
    yield
    g._cache = None


def _ok_reading(theme: str, tone: float = -1.0) -> g.ThemeReading:
    return g.ThemeReading(
        theme=theme,
        avg_tone=tone,
        volume=50,
        stress_level=g._classify_stress(tone),
        samples=50,
    )


def test_fallback_per_theme_on_partial_fetch_failure(monkeypatch):
    """Si 1 thème fail mais on a un snapshot persisté précédent → fallback."""
    # Snapshot précédent persisté avec les 4 thèmes (high stress geopolitical)
    prev = {
        "fetched_at": "2026-05-08T08:00:00+00:00",
        "timespan": "24h",
        "overall_stress": "high",
        "overall_tone": -3.5,
        "themes": {
            "monetary": {"theme": "monetary", "avg_tone": -1.0, "volume": 50, "stress_level": "calm", "samples": 50},
            "geopolitical": {"theme": "geopolitical", "avg_tone": -8.5, "volume": 80, "stress_level": "high", "samples": 80},
            "energy": {"theme": "energy", "avg_tone": -2.0, "volume": 40, "stress_level": "calm", "samples": 40},
            "trade": {"theme": "trade", "avg_tone": -4.0, "volume": 60, "stress_level": "elevated", "samples": 60},
        },
    }
    monkeypatch.setattr(g, "_load_latest_persisted", lambda: prev)

    # Skip persist + side effects
    monkeypatch.setattr(g, "_persist", lambda snap: None)

    # Mock _fetch_theme_tone : 3 thèmes OK, geopolitical FAIL (None)
    async def fake_fetch(client, theme, query, timespan):
        if theme == "geopolitical":
            return None  # 429 simulé
        return _ok_reading(theme, tone=-1.5)

    monkeypatch.setattr(g, "_fetch_theme_tone", fake_fetch)

    snap = asyncio.run(g.refresh_snapshot())

    assert snap is not None
    assert "geopolitical" in snap.themes  # fallback appliqué
    assert snap.themes["geopolitical"]["stress_level"] == "high"
    assert snap.themes["geopolitical"]["avg_tone"] == -8.5
    # Les 3 autres thèmes ont les valeurs fraîches (-1.5)
    assert snap.themes["monetary"]["avg_tone"] == -1.5
    assert snap.themes["energy"]["avg_tone"] == -1.5
    assert snap.themes["trade"]["avg_tone"] == -1.5


def test_no_fallback_without_previous_snapshot(monkeypatch):
    """Pas de snapshot persisté précédent → thème skip silencieusement."""
    monkeypatch.setattr(g, "_load_latest_persisted", lambda: None)
    monkeypatch.setattr(g, "_persist", lambda snap: None)

    async def fake_fetch(client, theme, query, timespan):
        if theme == "geopolitical":
            return None
        return _ok_reading(theme, tone=-1.0)

    monkeypatch.setattr(g, "_fetch_theme_tone", fake_fetch)

    snap = asyncio.run(g.refresh_snapshot())

    assert snap is not None
    assert "geopolitical" not in snap.themes  # skip
    assert len(snap.themes) == 3


def test_all_fetches_fail_returns_none(monkeypatch):
    """Si TOUS les fetchs fail ET pas de snapshot persisté → None."""
    monkeypatch.setattr(g, "_load_latest_persisted", lambda: None)
    monkeypatch.setattr(g, "_persist", lambda snap: None)

    async def fake_fetch(client, theme, query, timespan):
        return None

    monkeypatch.setattr(g, "_fetch_theme_tone", fake_fetch)

    snap = asyncio.run(g.refresh_snapshot())
    assert snap is None


def test_all_fetches_fail_with_prev_snapshot_uses_all_fallbacks(monkeypatch):
    """Si tous fail mais snapshot persisté disponible → reconstruire 4/4."""
    prev = {
        "themes": {
            "monetary": {"theme": "monetary", "avg_tone": -1.0, "volume": 50, "stress_level": "calm", "samples": 50},
            "geopolitical": {"theme": "geopolitical", "avg_tone": -7.0, "volume": 80, "stress_level": "high", "samples": 80},
            "energy": {"theme": "energy", "avg_tone": -2.0, "volume": 40, "stress_level": "calm", "samples": 40},
            "trade": {"theme": "trade", "avg_tone": -4.0, "volume": 60, "stress_level": "elevated", "samples": 60},
        },
    }
    monkeypatch.setattr(g, "_load_latest_persisted", lambda: prev)
    monkeypatch.setattr(g, "_persist", lambda snap: None)

    async def fake_fetch(client, theme, query, timespan):
        return None

    monkeypatch.setattr(g, "_fetch_theme_tone", fake_fetch)

    snap = asyncio.run(g.refresh_snapshot())
    assert snap is not None
    assert len(snap.themes) == 4  # 4/4 via fallback


def test_fallback_handles_malformed_prev_snapshot_gracefully(monkeypatch):
    """Si la valeur précédente est corrompue, skip ce thème silencieusement."""
    prev = {
        "themes": {
            "geopolitical": {"avg_tone": "not-a-float"},  # corruption
        },
    }
    monkeypatch.setattr(g, "_load_latest_persisted", lambda: prev)
    monkeypatch.setattr(g, "_persist", lambda snap: None)

    async def fake_fetch(client, theme, query, timespan):
        if theme == "geopolitical":
            return None
        return _ok_reading(theme)

    monkeypatch.setattr(g, "_fetch_theme_tone", fake_fetch)

    snap = asyncio.run(g.refresh_snapshot())
    assert snap is not None
    assert "geopolitical" not in snap.themes  # corruption → skip safe
    assert len(snap.themes) == 3
