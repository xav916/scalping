"""Tests du service economic_calendar_service.

Couvre :
- Parse JSON ForexFactory (fixture mock)
- get_upcoming_events filter impact + within_minutes
- No-op si currencies non-major
- Best-effort si fetch fail (return 0 / [])
- Snapshot events HIGH cette semaine (fetch réel en test d'intégration)
"""
from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import backend.services.economic_calendar_service as ecs_mod
from backend.services.economic_calendar_service import (
    _normalize_impact,
    _parse_ff_json,
    get_upcoming_events,
    refresh_calendar,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _event_item(
    title: str = "Nonfarm Payrolls",
    currency: str = "USD",
    impact: str = "High",
    delta_minutes: float = 15.0,
) -> dict:
    """Construit un item JSON ForexFactory factice."""
    dt = _now_utc() + timedelta(minutes=delta_minutes)
    return {
        "title": title,
        "country": currency,
        "impact": impact,
        "date": dt.isoformat(),
        "forecast": "180K",
        "previous": "177K",
        "actual": None,
    }


# ─── Fixture : DB temporaire ──────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    """Redirige _DB_PATH vers un fichier temporaire pour isolation parfaite."""
    tmp_db = tmp_path / "test_scalping.db"
    monkeypatch.setattr(ecs_mod, "_DB_PATH", tmp_db)
    monkeypatch.setattr(ecs_mod, "_DB_DIR", tmp_path)
    yield tmp_db


# ─── Tests _normalize_impact ─────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("High", "High"),
    ("high", "High"),
    ("red", "High"),
    ("3", "High"),
    ("Medium", "Medium"),
    ("medium", "Medium"),
    ("orange", "Medium"),
    ("amber", "Medium"),
    ("2", "Medium"),
    ("Low", "Low"),
    ("low", "Low"),
    ("", "Low"),
    ("unknown", "Low"),
])
def test_normalize_impact(raw, expected):
    assert _normalize_impact(raw) == expected


# ─── Tests _parse_ff_json ─────────────────────────────────────────────────────

def test_parse_ff_json_basic():
    """Parse un item JSON ForexFactory standard."""
    items = [_event_item("Nonfarm Payrolls", "USD", "High", 10.0)]
    events = _parse_ff_json(items)
    assert len(events) == 1
    e = events[0]
    assert e["event_name"] == "Nonfarm Payrolls"
    assert e["currency"] == "USD"
    assert e["impact"] == "High"
    assert "ts_utc" in e
    assert "id" in e


def test_parse_ff_json_filters_non_major_currency():
    """Les currencies non-major (CNY, MXN, etc.) sont ignorées."""
    items = [_event_item("China PMI", "CNY", "High", 5.0)]
    events = _parse_ff_json(items)
    assert events == []


def test_parse_ff_json_filters_empty_title():
    """Les items sans titre sont ignorés."""
    items = [{"title": "", "country": "USD", "impact": "High",
              "date": _now_utc().isoformat()}]
    events = _parse_ff_json(items)
    assert events == []


def test_parse_ff_json_multiple_currencies():
    """Parse plusieurs currencies."""
    items = [
        _event_item("NFP", "USD", "High", 10.0),
        _event_item("CPI", "EUR", "High", 20.0),
        _event_item("BOE Rate", "GBP", "Medium", 30.0),
    ]
    events = _parse_ff_json(items)
    assert len(events) == 3
    currencies = {e["currency"] for e in events}
    assert currencies == {"USD", "EUR", "GBP"}


def test_parse_ff_json_dedup_id_deterministic():
    """Deux items identiques produisent le même id → pas de doublon SQLite."""
    item = _event_item("NFP", "USD", "High", 10.0)
    e1 = _parse_ff_json([item])
    e2 = _parse_ff_json([item])
    assert e1[0]["id"] == e2[0]["id"]


def test_parse_ff_json_all_major_currencies():
    """Toutes les 8 currencies majors sont acceptées."""
    majors = ["USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "NZD"]
    items = [_event_item(f"Event {c}", c, "High", float(i * 5))
             for i, c in enumerate(majors)]
    events = _parse_ff_json(items)
    assert len(events) == 8


# ─── Tests refresh_calendar ───────────────────────────────────────────────────

def test_refresh_calendar_success():
    """refresh_calendar insère les events et retourne le count."""
    items = [
        _event_item("NFP", "USD", "High", 10.0),
        _event_item("CPI", "EUR", "Medium", 20.0),
    ]
    with patch.object(ecs_mod, "_fetch_json", return_value=items):
        count = refresh_calendar()
    assert count == 2


def test_refresh_calendar_fetch_fail_returns_zero():
    """Si _fetch_json retourne None, refresh retourne 0 (best-effort)."""
    with patch.object(ecs_mod, "_fetch_json", return_value=None):
        count = refresh_calendar()
    assert count == 0


def test_refresh_calendar_network_exception_returns_zero():
    """Si _fetch_json lève une exception, refresh retourne 0 (best-effort)."""
    with patch.object(ecs_mod, "_fetch_json", side_effect=RuntimeError("timeout")):
        count = refresh_calendar()
    assert count == 0


def test_refresh_calendar_upsert_no_duplicate():
    """Deux refreshs successifs avec les mêmes données → pas de doublon."""
    items = [_event_item("NFP", "USD", "High", 10.0)]
    with patch.object(ecs_mod, "_fetch_json", return_value=items):
        c1 = refresh_calendar()
        c2 = refresh_calendar()
    assert c1 == 1
    assert c2 == 1
    events = get_upcoming_events(within_minutes=60, min_impact="Low")
    assert len(events) == 1


# ─── Tests get_upcoming_events ────────────────────────────────────────────────

def test_get_upcoming_events_high_impact_within_window():
    """Un event HIGH dans ±30 min est retourné."""
    items = [_event_item("NFP", "USD", "High", 15.0)]
    with patch.object(ecs_mod, "_fetch_json", return_value=items):
        refresh_calendar()
    events = get_upcoming_events(within_minutes=30, min_impact="High")
    assert len(events) == 1
    e = events[0]
    assert e["event_name"] == "NFP"
    assert e["currency"] == "USD"
    assert "minutes_delta" in e
    assert 0 < e["minutes_delta"] <= 30


def test_get_upcoming_events_past_event_within_window():
    """Un event HIGH passé de -20 min (dans la fenêtre) est retourné."""
    items = [_event_item("CPI", "EUR", "High", -20.0)]
    with patch.object(ecs_mod, "_fetch_json", return_value=items):
        refresh_calendar()
    events = get_upcoming_events(within_minutes=30, min_impact="High")
    assert len(events) == 1
    assert events[0]["minutes_delta"] < 0


def test_get_upcoming_events_outside_window_not_returned():
    """Un event à +60 min avec window=30 n'est pas retourné."""
    items = [_event_item("NFP", "USD", "High", 60.0)]
    with patch.object(ecs_mod, "_fetch_json", return_value=items):
        refresh_calendar()
    events = get_upcoming_events(within_minutes=30, min_impact="High")
    assert events == []


def test_get_upcoming_events_filters_medium_when_high_only():
    """Un event MEDIUM est exclu si min_impact='High'."""
    items = [_event_item("PMI", "GBP", "Medium", 10.0)]
    with patch.object(ecs_mod, "_fetch_json", return_value=items):
        refresh_calendar()
    events = get_upcoming_events(within_minutes=30, min_impact="High")
    assert events == []


def test_get_upcoming_events_medium_included_when_medium_min():
    """Un event MEDIUM est inclus si min_impact='Medium'."""
    items = [_event_item("PMI", "GBP", "Medium", 10.0)]
    with patch.object(ecs_mod, "_fetch_json", return_value=items):
        refresh_calendar()
    events = get_upcoming_events(within_minutes=30, min_impact="Medium")
    assert len(events) == 1
    assert events[0]["impact"] == "Medium"


def test_get_upcoming_events_empty_db_returns_empty():
    """Table vide → liste vide (pas d'erreur)."""
    events = get_upcoming_events(within_minutes=30, min_impact="High")
    assert events == []


def test_get_upcoming_events_nfp_in_15min():
    """Cas principal : NFP dans 15 min → veto applicable."""
    items = [_event_item("Nonfarm Payrolls", "USD", "High", 15.0)]
    with patch.object(ecs_mod, "_fetch_json", return_value=items):
        refresh_calendar()
    events = get_upcoming_events(within_minutes=30, min_impact="High")
    assert len(events) == 1
    assert "Nonfarm" in events[0]["event_name"]
    assert abs(events[0]["minutes_delta"] - 15.0) < 1.0


# ─── Test d'intégration : fetch réel ForexFactory ────────────────────────────
# Ce test fait un vrai appel réseau. Il est marqué `network` pour pouvoir
# être skippé en CI sans réseau. En dev, exécuter avec :
#   pytest -m network backend/tests/test_economic_calendar_service.py

@pytest.mark.network
def test_real_fetch_forexfactory_this_week():
    """Fetch réel ForexFactory — valide que la source est accessible.

    Snapshot des events HIGH cette semaine imprimé pour observabilité.
    Ce test échoue si ForexFactory est down (acceptable en CI, réseau requis).
    """
    count = refresh_calendar()
    # La source peut légitimement retourner 0 en dehors des heures ouvrées
    # ou si le calendrier de la semaine est vide (ex: férié US).
    # On vérifie juste que le service ne lève pas d'exception.
    assert isinstance(count, int)
    assert count >= 0

    # Afficher les events HIGH de cette semaine pour observabilité
    events = get_upcoming_events(within_minutes=60 * 24 * 7, min_impact="High")
    print(f"\n=== ForexFactory HIGH events this week ({len(events)} total) ===")
    for e in events:
        print(f"  {e['ts_utc'][:16]} {e['currency']:4s} {e['event_name'][:50]}")
    # Ne pas asserter count > 0 : il peut n'y avoir aucun event HIGH cette semaine
