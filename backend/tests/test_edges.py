"""Tests : session_service, event_blackout, sizing avec session integree."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.services import event_blackout, session_service, sizing


# ─── Session service ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "hour_utc,expected",
    [
        (2, "asian"),      # Tokyo + Sydney
        (8, "london"),     # London seul
        (13, "london_ny_overlap"),  # Sweet spot
        (18, "new_york"),  # NY seul
        (23, "sydney"),    # Sydney ouvre, Tokyo pas encore
    ],
)
def test_session_label_at_key_hours(hour_utc: int, expected: str):
    # Choix d'un mardi pour eviter le cas weekend.
    dt = datetime(2026, 4, 21, hour_utc, 0, tzinfo=timezone.utc)
    assert session_service.label(dt) == expected


def test_session_weekend_detected():
    # Samedi 12h UTC
    dt = datetime(2026, 4, 18, 12, 0, tzinfo=timezone.utc)
    assert session_service.is_weekend(dt) is True
    assert session_service.label(dt) == "weekend"
    assert session_service.activity_multiplier(dt) == 0.0


def test_session_activity_multipliers():
    mul = session_service.activity_multiplier
    dt = lambda h: datetime(2026, 4, 21, h, 0, tzinfo=timezone.utc)
    assert mul(dt(13)) == 1.2   # London/NY overlap
    assert mul(dt(8)) == 1.0    # London seul
    assert mul(dt(2)) == 0.7    # Asian


# ─── Sizing avec session ───────────────────────────────────────────


def test_compute_risk_money_includes_session_multiplier(tmp_path, monkeypatch):
    from backend.services import trade_log_service

    monkeypatch.setattr(trade_log_service, "_DB_PATH", tmp_path / "t.db")
    trade_log_service._init_schema()

    setup = SimpleNamespace(confidence_score=85)
    with patch.object(session_service, "activity_multiplier", return_value=1.2), \
         patch.object(session_service, "label", return_value="london_ny_overlap"):
        result = sizing.compute_risk_money(setup)

    assert result["session_mult"] == 1.2
    assert result["session"] == "london_ny_overlap"
    # final_mult = conf_mult * pnl_mult * session_mult (a 2 decimales pres,
    # les multiplicateurs individuels sont arrondis avant multiplication).
    expected_final = result["conf_mult"] * result["pnl_mult"] * result["session_mult"]
    assert abs(result["final_mult"] - expected_final) < 0.01


def test_compute_risk_money_weekend_zeroes_out(tmp_path, monkeypatch):
    from backend.services import trade_log_service

    monkeypatch.setattr(trade_log_service, "_DB_PATH", tmp_path / "t.db")
    trade_log_service._init_schema()

    setup = SimpleNamespace(confidence_score=95)
    with patch.object(session_service, "activity_multiplier", return_value=0.0), \
         patch.object(session_service, "label", return_value="weekend"):
        result = sizing.compute_risk_money(setup)
    assert result["risk_money"] == 0.0


# ─── Event blackout ────────────────────────────────────────────────


def _event(currency: str, impact: str, when: datetime, name: str = "CPI"):
    return SimpleNamespace(
        currency=currency,
        impact=SimpleNamespace(value=impact),
        time=when.isoformat(),
        event_name=name,
    )


def test_blackout_triggered_for_high_impact_within_window():
    now = datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc)
    events = [_event("USD", "high", now.replace(hour=13, minute=10))]
    status = event_blackout.is_blackout_for("EUR/USD", events=events, now=now)
    assert status["active"] is True
    assert "USD" in status["reason"]


def test_blackout_not_triggered_outside_window():
    now = datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc)
    # Event dans 45min → hors fenetre 15min
    events = [_event("USD", "high", now.replace(hour=13, minute=45))]
    status = event_blackout.is_blackout_for("EUR/USD", events=events, now=now)
    assert status["active"] is False


def test_blackout_ignored_for_low_impact():
    now = datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc)
    events = [_event("USD", "low", now.replace(hour=13, minute=5))]
    status = event_blackout.is_blackout_for("EUR/USD", events=events, now=now)
    assert status["active"] is False


def test_blackout_scoped_to_relevant_currency():
    """Un event GBP ne blackoute pas EUR/USD (aucune devise commune)."""
    now = datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc)
    events = [_event("GBP", "high", now.replace(hour=13, minute=5))]
    status = event_blackout.is_blackout_for("EUR/USD", events=events, now=now)
    assert status["active"] is False

    # En revanche GBP/JPY doit etre blackout.
    status2 = event_blackout.is_blackout_for("GBP/JPY", events=events, now=now)
    assert status2["active"] is True


def test_blackout_index_mapped_to_usd():
    """SPX / NDX sont indexes sur USD, un CPI USD doit les blackout."""
    now = datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc)
    events = [_event("USD", "high", now.replace(hour=13, minute=5))]
    status = event_blackout.is_blackout_for("SPX", events=events, now=now)
    assert status["active"] is True
