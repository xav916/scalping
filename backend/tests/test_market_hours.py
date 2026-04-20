"""Tests des horaires d'ouverture par asset class."""
from datetime import datetime, timezone

import pytest

from backend.services.market_hours import is_market_open_for


def _dt(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


# --- Crypto : 24/7 ---
def test_crypto_always_open():
    assert is_market_open_for("BTC/USD", _dt(2026, 4, 18, 15))   # samedi
    assert is_market_open_for("ETH/USD", _dt(2026, 4, 19, 3))    # dimanche matin
    assert is_market_open_for("BTC/USD", _dt(2026, 4, 20, 21, 30))  # daily break hour


# --- Forex ---
def test_forex_closed_saturday():
    # 2026-04-18 samedi
    assert not is_market_open_for("EUR/USD", _dt(2026, 4, 18, 14))


def test_forex_closed_sunday_before_22h_utc():
    # 2026-04-19 dimanche 21:59 UTC
    assert not is_market_open_for("EUR/USD", _dt(2026, 4, 19, 21, 59))


def test_forex_open_sunday_22h_utc():
    # 2026-04-19 dimanche 22:00 UTC = ouverture Sydney
    assert is_market_open_for("EUR/USD", _dt(2026, 4, 19, 22))


def test_forex_open_weekday():
    # 2026-04-20 lundi 14:00 UTC = London active
    assert is_market_open_for("EUR/USD", _dt(2026, 4, 20, 14))


def test_forex_closed_friday_after_22h():
    # 2026-04-17 vendredi 22:01 UTC
    assert not is_market_open_for("EUR/USD", _dt(2026, 4, 17, 22, 1))


# --- Metal (XAU/XAG) ---
def test_metal_closed_saturday():
    assert not is_market_open_for("XAU/USD", _dt(2026, 4, 18, 14))


def test_metal_closed_during_daily_break():
    # lundi 21:30 UTC = daily break
    assert not is_market_open_for("XAU/USD", _dt(2026, 4, 20, 21, 30))


def test_metal_open_before_daily_break():
    # lundi 20:59 UTC = avant break
    assert is_market_open_for("XAU/USD", _dt(2026, 4, 20, 20, 59))


def test_metal_reopens_after_22h_weekday():
    # mardi 22:00 UTC = réouverture après daily break
    assert is_market_open_for("XAU/USD", _dt(2026, 4, 21, 22))


def test_metal_closed_friday_after_21h():
    # vendredi 21:00 UTC = fermeture weekend
    assert not is_market_open_for("XAU/USD", _dt(2026, 4, 17, 21))


# --- Indices ---
def test_equity_index_closed_saturday():
    assert not is_market_open_for("SPX", _dt(2026, 4, 18, 14))


def test_equity_index_daily_break():
    # lundi 21:30 UTC = break
    assert not is_market_open_for("NDX", _dt(2026, 4, 20, 21, 30))


# --- Energy (WTI) ---
def test_energy_closed_during_22h_23h_break():
    # lundi 22:30 UTC = break pétrole
    assert not is_market_open_for("WTI/USD", _dt(2026, 4, 20, 22, 30))


def test_energy_open_weekday():
    assert is_market_open_for("WTI/USD", _dt(2026, 4, 20, 14))


def test_energy_closed_saturday():
    assert not is_market_open_for("WTI/USD", _dt(2026, 4, 18, 14))
