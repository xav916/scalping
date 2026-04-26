"""Tests des nouveaux filtres mt5_bridge ajoutés après diagnostic 2026-04-24 :
- MT5_BRIDGE_BLOCKED_DIRECTIONS (filtre direction par pair)
- MT5_BRIDGE_AVOID_HOURS_UTC (filtre session horaire)
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.services import mt5_bridge


@pytest.fixture(autouse=True)
def _disable_star_filter(monkeypatch):
    """Tests in this module assert behaviour for non-star pairs (EUR/USD,
    GBP/USD…) relative to BLOCKED_DIRECTIONS / AVOID_HOURS. Neutralize the
    upstream stars filter so those assertions remain meaningful."""
    monkeypatch.setattr(
        mt5_bridge,
        "_STAR_PAIRS_SET",
        frozenset({"EUR/USD", "GBP/USD", "USD/JPY", "XAU/USD", "XAG/USD",
                   "WTI/USD", "ETH/USD", "XLI", "XLK"}),
    )


def _setup(pair="EUR/USD", direction="buy", confidence=80, entry=1.10, sl=1.09, tp=1.11):
    s = SimpleNamespace()
    s.pair = pair
    s.direction = direction
    s.entry_price = entry
    s.stop_loss = sl
    s.take_profit_1 = tp
    s.take_profit_2 = None
    s.confidence_score = confidence
    s.verdict_action = "TAKE"
    s.verdict_blockers = []
    s.is_simulated = False
    return s


class TestBlockedDirections:
    @patch("backend.services.mt5_bridge.MT5_BRIDGE_BLOCKED_DIRECTIONS", {("EUR/USD", "buy")})
    def test_buy_on_eurusd_blocked(self):
        with patch("backend.services.mt5_bridge.is_configured", return_value=True), \
             patch("backend.services.mt5_bridge.is_market_open_for", return_value=True), \
             patch("backend.services.mt5_bridge._count_open_trades_for_pair", return_value=0), \
             patch("backend.services.mt5_bridge.MT5_BRIDGE_MIN_CONFIDENCE", 0):
            reason = mt5_bridge._check_rejection(_setup(pair="EUR/USD", direction="buy"))
            assert reason == "direction_blocked_for_pair"

    @patch("backend.services.mt5_bridge.MT5_BRIDGE_BLOCKED_DIRECTIONS", {("EUR/USD", "buy")})
    def test_sell_on_eurusd_allowed(self):
        with patch("backend.services.mt5_bridge.is_configured", return_value=True), \
             patch("backend.services.mt5_bridge.is_market_open_for", return_value=True), \
             patch("backend.services.mt5_bridge._count_open_trades_for_pair", return_value=0), \
             patch("backend.services.mt5_bridge.MT5_BRIDGE_MIN_CONFIDENCE", 0):
            reason = mt5_bridge._check_rejection(_setup(pair="EUR/USD", direction="sell"))
            assert reason is None

    @patch("backend.services.mt5_bridge.MT5_BRIDGE_BLOCKED_DIRECTIONS", {("*", "buy")})
    def test_global_buy_block(self):
        with patch("backend.services.mt5_bridge.is_configured", return_value=True), \
             patch("backend.services.mt5_bridge.is_market_open_for", return_value=True), \
             patch("backend.services.mt5_bridge._count_open_trades_for_pair", return_value=0), \
             patch("backend.services.mt5_bridge.MT5_BRIDGE_MIN_CONFIDENCE", 0):
            reason = mt5_bridge._check_rejection(_setup(pair="GBP/USD", direction="buy"))
            assert reason == "direction_blocked_global"

    @patch("backend.services.mt5_bridge.MT5_BRIDGE_BLOCKED_DIRECTIONS", set())
    def test_empty_blocklist_allows_all(self):
        with patch("backend.services.mt5_bridge.is_configured", return_value=True), \
             patch("backend.services.mt5_bridge.is_market_open_for", return_value=True), \
             patch("backend.services.mt5_bridge._count_open_trades_for_pair", return_value=0), \
             patch("backend.services.mt5_bridge.MT5_BRIDGE_MIN_CONFIDENCE", 0):
            assert mt5_bridge._check_rejection(_setup(direction="buy")) is None
            assert mt5_bridge._check_rejection(_setup(direction="sell")) is None


class TestAvoidHoursUTC:
    @patch("backend.services.mt5_bridge.MT5_BRIDGE_AVOID_HOURS_UTC", {17, 18, 19, 20, 21})
    def test_skip_during_avoid_hour(self):
        fake_now = datetime(2026, 4, 24, 19, 30, tzinfo=timezone.utc)
        with patch("backend.services.mt5_bridge.is_configured", return_value=True), \
             patch("backend.services.mt5_bridge.is_market_open_for", return_value=True), \
             patch("backend.services.mt5_bridge._count_open_trades_for_pair", return_value=0), \
             patch("backend.services.mt5_bridge.MT5_BRIDGE_MIN_CONFIDENCE", 0), \
             patch("backend.services.mt5_bridge.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            reason = mt5_bridge._check_rejection(_setup())
            assert reason == "hour_in_avoid_list"

    @patch("backend.services.mt5_bridge.MT5_BRIDGE_AVOID_HOURS_UTC", {17, 18, 19, 20, 21})
    def test_allow_outside_avoid_hour(self):
        fake_now = datetime(2026, 4, 24, 10, 30, tzinfo=timezone.utc)
        with patch("backend.services.mt5_bridge.is_configured", return_value=True), \
             patch("backend.services.mt5_bridge.is_market_open_for", return_value=True), \
             patch("backend.services.mt5_bridge._count_open_trades_for_pair", return_value=0), \
             patch("backend.services.mt5_bridge.MT5_BRIDGE_MIN_CONFIDENCE", 0), \
             patch("backend.services.mt5_bridge.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            assert mt5_bridge._check_rejection(_setup()) is None

    @patch("backend.services.mt5_bridge.MT5_BRIDGE_AVOID_HOURS_UTC", set())
    def test_empty_avoidlist_allows_all(self):
        with patch("backend.services.mt5_bridge.is_configured", return_value=True), \
             patch("backend.services.mt5_bridge.is_market_open_for", return_value=True), \
             patch("backend.services.mt5_bridge._count_open_trades_for_pair", return_value=0), \
             patch("backend.services.mt5_bridge.MT5_BRIDGE_MIN_CONFIDENCE", 0):
            # Quelle que soit l'heure actuelle, si la liste est vide, pas de skip.
            assert mt5_bridge._check_rejection(_setup()) is None
