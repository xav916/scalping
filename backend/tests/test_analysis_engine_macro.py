"""Integration-level tests: enrich_trade_setup applies macro scoring correctly."""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from backend.models.macro_schemas import (
    MacroContext,
    MacroDirection,
    RiskRegime,
    VixLevel,
)
from backend.models.schemas import (
    PatternDetection,
    PatternType,
    TradeDirection,
    TradeSetup,
)
from backend.services.analysis_engine import enrich_trade_setup


def _neutral_ctx() -> MacroContext:
    return MacroContext(
        fetched_at=datetime.now(timezone.utc),
        dxy_direction=MacroDirection.NEUTRAL,
        spx_direction=MacroDirection.NEUTRAL,
        vix_level=VixLevel.NORMAL,
        vix_value=17.0,
        us10y_trend=MacroDirection.NEUTRAL,
        de10y_trend=MacroDirection.NEUTRAL,
        us_de_spread_trend="flat",
        oil_direction=MacroDirection.NEUTRAL,
        nikkei_direction=MacroDirection.NEUTRAL,
        gold_direction=MacroDirection.NEUTRAL,
        risk_regime=RiskRegime.NEUTRAL,
        raw_values={},
    )


def _dxy_against_ctx() -> MacroContext:
    ctx = _neutral_ctx()
    ctx.dxy_direction = MacroDirection.STRONG_UP
    return ctx


def _basic_setup(pair: str = "EUR/USD", direction: TradeDirection = TradeDirection.BUY) -> TradeSetup:
    return TradeSetup(
        pair=pair,
        direction=direction,
        pattern=PatternDetection(
            pattern=PatternType.BREAKOUT_UP,
            confidence=0.8,
            description="test_pattern",
            detected_at=datetime.now(timezone.utc),
        ),
        entry_price=1.1000,
        stop_loss=1.0950,
        take_profit_1=1.1050,
        take_profit_2=1.1100,
        risk_pips=50.0,
        reward_pips_1=50.0,
        reward_pips_2=100.0,
        risk_reward_1=1.0,
        risk_reward_2=2.0,
        message="test",
        timestamp=datetime.now(timezone.utc),
    )


class TestFeatureFlagOff:
    def test_no_macro_factor_added_when_flag_off(self):
        with patch("backend.services.analysis_engine.MACRO_SCORING_ENABLED", False):
            with patch(
                "backend.services.macro_context_service.get_macro_snapshot",
                return_value=_neutral_ctx(),
            ):
                setup = _basic_setup()
                enriched = enrich_trade_setup(setup, volatility=None, trend=None, events=[])

        macro_factors = [f for f in enriched.confidence_factors if f.source == "macro"]
        assert macro_factors == []


class TestFeatureFlagOn:
    def test_macro_factor_added_when_flag_on(self):
        with patch("backend.services.analysis_engine.MACRO_SCORING_ENABLED", True):
            with patch(
                "backend.services.macro_context_service.get_macro_snapshot",
                return_value=_dxy_against_ctx(),
            ):
                setup = _basic_setup(pair="EUR/USD", direction=TradeDirection.BUY)
                enriched = enrich_trade_setup(setup, volatility=None, trend=None, events=[])

        macro_factors = [f for f in enriched.confidence_factors if f.source == "macro"]
        assert len(macro_factors) == 1
        assert macro_factors[0].positive is False

    def test_stale_cache_falls_back_to_neutral(self):
        stale_ctx = _dxy_against_ctx()
        stale_ctx.fetched_at = datetime.now(timezone.utc).replace(year=2020)

        with patch("backend.services.analysis_engine.MACRO_SCORING_ENABLED", True):
            with patch(
                "backend.services.macro_context_service.get_macro_snapshot",
                return_value=stale_ctx,
            ):
                setup = _basic_setup()
                enriched = enrich_trade_setup(setup, volatility=None, trend=None, events=[])

        macro_factors = [f for f in enriched.confidence_factors if f.source == "macro"]
        assert macro_factors == []
