"""Tests des horaires d'ouverture par asset class."""
from datetime import datetime, timezone

import pytest

from backend.services.market_hours import (
    is_market_open_for,
    is_market_open_for_destination,
)


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


# --- Equity individual (AAPL/TSLA/NVDA...) : NYSE core session ---
def test_equity_open_weekday_nyse_core():
    # 2026-04-20 lundi 14:00 UTC = NYSE ouvert (13:30-20:00 UTC)
    assert is_market_open_for("AAPL", _dt(2026, 4, 20, 14))


def test_equity_closed_weekday_pre_market():
    # 2026-04-20 lundi 13:00 UTC = pre-market NYSE fermé
    assert not is_market_open_for("AAPL", _dt(2026, 4, 20, 13))


def test_equity_closed_weekday_after_hours():
    # 2026-04-20 lundi 20:30 UTC = after-hours NYSE fermé
    assert not is_market_open_for("TSLA", _dt(2026, 4, 20, 20, 30))


def test_equity_closed_weekend():
    # 2026-04-19 dimanche = fermé même en journée
    assert not is_market_open_for("NVDA", _dt(2026, 4, 19, 14))


# --- Gap 5 : destination-aware pour xStocks Kraken 24/7 opt-in ---
def test_dest_kraken_stocks_default_respects_nyse(monkeypatch):
    """Sans flag, admin_kraken_stocks respecte les heures NYSE strictes."""
    monkeypatch.delenv("KRAKEN_STOCKS_ALLOW_24_7", raising=False)
    # dimanche 3h UTC = NYSE fermé
    assert not is_market_open_for_destination("AAPL", "admin_kraken_stocks", _dt(2026, 4, 19, 3))


def test_dest_kraken_stocks_247_when_flag_enabled(monkeypatch):
    """Avec KRAKEN_STOCKS_ALLOW_24_7=true, admin_kraken_stocks accepte 24/7."""
    monkeypatch.setenv("KRAKEN_STOCKS_ALLOW_24_7", "true")
    # dimanche 3h UTC (NYSE fermé) → OK pour Kraken 24/7
    assert is_market_open_for_destination("AAPL", "admin_kraken_stocks", _dt(2026, 4, 19, 3))
    # lundi 20:30 (NYSE fermé) → OK aussi
    assert is_market_open_for_destination("TSLA", "admin_kraken_stocks", _dt(2026, 4, 20, 20, 30))


def test_dest_admin_live_always_respects_nyse_even_with_flag(monkeypatch):
    """Le flag 24/7 ne concerne QUE admin_kraken_stocks — admin_live reste NYSE strict."""
    monkeypatch.setenv("KRAKEN_STOCKS_ALLOW_24_7", "true")
    # dimanche 3h UTC = fermé pour admin_live même si flag Kraken activé
    assert not is_market_open_for_destination("AAPL", "admin_live", _dt(2026, 4, 19, 3))


def test_dest_non_equity_unaffected_by_flag(monkeypatch):
    """Le flag ne concerne QUE equity — crypto/forex/etc restent régis par leurs règles standard."""
    monkeypatch.setenv("KRAKEN_STOCKS_ALLOW_24_7", "true")
    # crypto reste 24/7 (comme avant)
    assert is_market_open_for_destination("BTC/USD", "admin_kraken", _dt(2026, 4, 19, 3))
    # forex reste fermé weekend
    assert not is_market_open_for_destination("EUR/USD", "admin_live", _dt(2026, 4, 18, 14))


def test_dest_empty_destination_id_falls_back_to_standard(monkeypatch):
    """Sans destination_id, comportement identique à is_market_open_for."""
    monkeypatch.setenv("KRAKEN_STOCKS_ALLOW_24_7", "true")
    # equity hors NYSE reste fermé si destination_id vide
    assert not is_market_open_for_destination("AAPL", "", _dt(2026, 4, 19, 3))
