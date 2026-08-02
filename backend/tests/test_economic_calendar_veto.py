"""Tests du module economic_calendar_veto.

Couvre :
- Veto ×0.70 si event NFP dans 15 min (EUR/USD, XAU/USD, WTI/USD)
- No veto si event <High impact
- No-op crypto (BTC/USD, ETH/USD)
- No-op equity/equity_index (AAPL, SPX)
- No-op si DB vide (best-effort)
- Score toujours dans [0, 100]
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

import backend.services.economic_calendar_service as ecs_mod
from backend.services.economic_calendar_veto import apply_economic_veto, _currencies_for_pair


# ─── Fixtures ────────────────────────────────────────────────────────────────

def _event(
    currency: str = "USD",
    event_name: str = "Nonfarm Payrolls",
    impact: str = "High",
    minutes_delta: float = 15.0,
) -> dict:
    """Construit un event dict tel que retourné par get_upcoming_events."""
    return {
        "id": f"test_{currency}_{event_name[:10]}",
        "ts_utc": (datetime.now(timezone.utc) + timedelta(minutes=minutes_delta)).isoformat(),
        "currency": currency,
        "event_name": event_name,
        "impact": impact,
        "actual": None,
        "forecast": "180K",
        "previous": "177K",
        "minutes_delta": minutes_delta,
    }


# ─── Tests _currencies_for_pair ──────────────────────────────────────────────

@pytest.mark.parametrize("pair,expected", [
    ("EUR/USD", {"EUR", "USD"}),
    ("GBP/USD", {"GBP", "USD"}),
    ("USD/JPY", {"USD", "JPY"}),
    ("EUR/GBP", {"EUR", "GBP"}),
    ("XAU/USD", {"USD"}),      # XAU n'est pas une currency forex
    ("XAG/USD", {"USD"}),
    ("WTI/USD", {"USD"}),
    ("BTC/USD", {"BTC", "USD"}),   # non-exclus via pair parsing
    ("SPX", set()),             # pas de slash → vide
])
def test_currencies_for_pair(pair, expected):
    result = _currencies_for_pair(pair)
    assert set(result) == expected


# ─── Tests no-op asset classes exclues ───────────────────────────────────────

@pytest.mark.parametrize("pair", [
    "BTC/USD", "ETH/USD",           # crypto
    "AAPL", "TSLA", "NVDA",         # equity
    "SPX", "NDX",                    # equity_index
])
def test_excluded_asset_class_is_noop(pair):
    """Les asset classes crypto/equity/equity_index retournent score inchangé + meta vide."""
    # Pas de mock get_upcoming_events : si appelé → test failera
    new_score, meta = apply_economic_veto(pair, "buy", 75.0)
    assert new_score == 75.0
    assert meta == {}


# ─── Tests veto ×0.70 ────────────────────────────────────────────────────────

def test_veto_nfp_15min_eurusd():
    """NFP USD dans 15 min → veto ×0.70 sur EUR/USD."""
    events = [_event("USD", "Nonfarm Payrolls", "High", 15.0)]
    with patch("backend.services.economic_calendar_service.get_upcoming_events", return_value=events):
        new_score, meta = apply_economic_veto("EUR/USD", "buy", 80.0)

    assert new_score == round(80.0 * 0.70, 1)
    assert meta["eco_veto_applied"] is True
    assert meta["eco_multiplier"] == 0.70
    assert "Nonfarm" in meta["eco_event_name"]
    assert meta["eco_minutes_delta"] == 15.0
    assert meta["eco_currency_matched"] == "USD"


def test_veto_nfp_15min_xauusd():
    """NFP USD dans 15 min → veto ×0.70 sur XAU/USD (USD impacte l'or)."""
    events = [_event("USD", "Nonfarm Payrolls", "High", 15.0)]
    with patch("backend.services.economic_calendar_service.get_upcoming_events", return_value=events):
        new_score, meta = apply_economic_veto("XAU/USD", "buy", 70.0)

    assert new_score == round(70.0 * 0.70, 1)
    assert meta["eco_veto_applied"] is True


def test_veto_nfp_15min_wtiusd():
    """NFP USD dans 15 min → veto ×0.70 sur WTI/USD (coté en USD)."""
    events = [_event("USD", "Nonfarm Payrolls", "High", 15.0)]
    with patch("backend.services.economic_calendar_service.get_upcoming_events", return_value=events):
        new_score, meta = apply_economic_veto("WTI/USD", "sell", 65.0)

    assert new_score == round(65.0 * 0.70, 1)
    assert meta["eco_veto_applied"] is True


def test_veto_ecb_15min_eurusd():
    """ECB Rate Decision EUR dans 15 min → veto ×0.70 sur EUR/USD."""
    events = [_event("EUR", "ECB Rate Decision", "High", 15.0)]
    with patch("backend.services.economic_calendar_service.get_upcoming_events", return_value=events):
        new_score, meta = apply_economic_veto("EUR/USD", "buy", 75.0)

    assert new_score == round(75.0 * 0.70, 1)
    assert meta["eco_veto_applied"] is True
    assert meta["eco_currency_matched"] == "EUR"


def test_veto_boe_gbpusd():
    """BoE Rate Decision GBP → veto sur GBP/USD."""
    events = [_event("GBP", "BOE Rate Decision", "High", 10.0)]
    with patch("backend.services.economic_calendar_service.get_upcoming_events", return_value=events):
        new_score, meta = apply_economic_veto("GBP/USD", "sell", 72.0)

    assert new_score == round(72.0 * 0.70, 1)


def test_veto_past_event_within_window():
    """Event passé de -20 min (dans la fenêtre) → veto appliqué."""
    events = [_event("USD", "CPI", "High", -20.0)]
    with patch("backend.services.economic_calendar_service.get_upcoming_events", return_value=events):
        new_score, meta = apply_economic_veto("EUR/USD", "buy", 80.0)

    assert new_score == round(80.0 * 0.70, 1)
    assert meta["eco_veto_applied"] is True
    assert meta["eco_minutes_delta"] == -20.0


# ─── Tests no-veto ───────────────────────────────────────────────────────────

def test_no_veto_if_medium_impact():
    """Event MEDIUM impact → pas de veto (get_upcoming_events filtre High)."""
    # get_upcoming_events appelé avec min_impact='High' → retourne [] si Medium
    with patch("backend.services.economic_calendar_service.get_upcoming_events", return_value=[]):
        new_score, meta = apply_economic_veto("EUR/USD", "buy", 80.0)

    assert new_score == 80.0
    assert not meta.get("eco_veto_applied")


def test_no_veto_if_currency_not_matched():
    """Event JPY dans 15 min → pas de veto sur EUR/USD."""
    events = [_event("JPY", "BOJ Rate Decision", "High", 15.0)]
    with patch("backend.services.economic_calendar_service.get_upcoming_events", return_value=events):
        new_score, meta = apply_economic_veto("EUR/USD", "buy", 80.0)

    assert new_score == 80.0
    assert not meta.get("eco_veto_applied")


def test_no_veto_if_db_empty_best_effort():
    """DB vide → score inchangé + meta vide (best-effort)."""
    with patch("backend.services.economic_calendar_service.get_upcoming_events", return_value=[]):
        new_score, meta = apply_economic_veto("EUR/USD", "buy", 75.0)

    assert new_score == 75.0
    assert not meta.get("eco_veto_applied")


def test_no_veto_on_get_events_exception_best_effort():
    """Exception dans get_upcoming_events → score inchangé (best-effort)."""
    with patch("backend.services.economic_calendar_service.get_upcoming_events",
               side_effect=RuntimeError("DB locked")):
        new_score, meta = apply_economic_veto("EUR/USD", "buy", 72.0)

    assert new_score == 72.0
    assert not meta.get("eco_veto_applied")


# ─── Tests score boundaries ───────────────────────────────────────────────────

def test_veto_score_never_below_zero():
    """Le score vetoé ne peut pas être négatif."""
    events = [_event("USD", "NFP", "High", 5.0)]
    with patch("backend.services.economic_calendar_service.get_upcoming_events", return_value=events):
        new_score, _ = apply_economic_veto("EUR/USD", "buy", 0.0)

    assert new_score == 0.0


def test_veto_score_clamped_at_100():
    """Le score vetoé est plafonné à 100 (ne peut pas dépasser)."""
    events = [_event("USD", "NFP", "High", 5.0)]
    with patch("backend.services.economic_calendar_service.get_upcoming_events", return_value=events):
        new_score, _ = apply_economic_veto("EUR/USD", "buy", 100.0)

    # 100 × 0.70 = 70.0
    assert new_score == 70.0
    assert new_score <= 100.0


# ─── Test import lazy ────────────────────────────────────────────────────────

def test_no_import_error_on_crypto():
    """Import du module ne lève pas d'erreur + no-op crypto ne touche pas EC."""
    # BTC/USD est crypto : le service EC ne doit pas être importé
    new_score, meta = apply_economic_veto("BTC/USD", "buy", 65.0)
    assert new_score == 65.0
    assert meta == {}


# ─── Test sell direction veto ─────────────────────────────────────────────────

def test_veto_applies_on_sell_direction():
    """Le veto s'applique aussi côté SELL (pas seulement BUY)."""
    events = [_event("USD", "FOMC Rate Decision", "High", 5.0)]
    with patch("backend.services.economic_calendar_service.get_upcoming_events", return_value=events):
        new_score, meta = apply_economic_veto("USD/JPY", "sell", 78.0)

    assert new_score == round(78.0 * 0.70, 1)
    assert meta["eco_veto_applied"] is True


# ─── Test XAG/USD (métal) ────────────────────────────────────────────────────

def test_veto_xagusd_usd_event():
    """XAG/USD coté en USD → veto si event USD."""
    events = [_event("USD", "GDP q/q", "High", 20.0)]
    with patch("backend.services.economic_calendar_service.get_upcoming_events", return_value=events):
        new_score, meta = apply_economic_veto("XAG/USD", "buy", 68.0)

    assert new_score == round(68.0 * 0.70, 1)
    assert meta["eco_veto_applied"] is True
