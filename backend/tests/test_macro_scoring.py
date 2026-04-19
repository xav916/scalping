"""Table-driven tests for macro_scoring.apply()."""
from datetime import datetime, timezone

import pytest

from backend.models.macro_schemas import (
    MacroContext,
    MacroDirection,
    RiskRegime,
    VixLevel,
)
from backend.services.macro_scoring import apply


def _make_ctx(
    dxy=MacroDirection.NEUTRAL,
    spx=MacroDirection.NEUTRAL,
    vix_level=VixLevel.NORMAL,
    vix_value=17.0,
    us10y=MacroDirection.NEUTRAL,
    de10y=MacroDirection.NEUTRAL,
    spread_trend="flat",
    oil=MacroDirection.NEUTRAL,
    nikkei=MacroDirection.NEUTRAL,
    gold=MacroDirection.NEUTRAL,
    risk=RiskRegime.NEUTRAL,
    dxy_intraday_sigma=0.0,
) -> MacroContext:
    return MacroContext(
        fetched_at=datetime.now(timezone.utc),
        dxy_direction=dxy,
        spx_direction=spx,
        vix_level=vix_level,
        vix_value=vix_value,
        us10y_trend=us10y,
        de10y_trend=de10y,
        us_de_spread_trend=spread_trend,
        oil_direction=oil,
        nikkei_direction=nikkei,
        gold_direction=gold,
        risk_regime=risk,
        raw_values={},
        dxy_intraday_sigma=dxy_intraday_sigma,
    )


class TestUsdMajors:
    def test_eurusd_sell_aligned_with_dxy_strong_up_gets_boost(self):
        ctx = _make_ctx(dxy=MacroDirection.STRONG_UP)
        mult, veto, reasons = apply("EUR/USD", "sell", ctx)
        assert mult == 1.2
        assert veto is False

    def test_eurusd_buy_against_dxy_strong_up_gets_penalty(self):
        ctx = _make_ctx(dxy=MacroDirection.STRONG_UP)
        mult, veto, reasons = apply("EUR/USD", "buy", ctx)
        assert mult == 0.75
        assert veto is False

    def test_usdjpy_buy_aligned_with_dxy_up_and_risk_on_gets_boost(self):
        ctx = _make_ctx(
            dxy=MacroDirection.UP,
            nikkei=MacroDirection.UP,
            vix_level=VixLevel.LOW,
            risk=RiskRegime.RISK_ON,
        )
        mult, veto, reasons = apply("USD/JPY", "buy", ctx)
        assert mult >= 1.1


class TestVetoConditions:
    def test_vix_above_30_and_setup_against_risk_off_vetoes(self):
        ctx = _make_ctx(
            vix_value=32.0,
            vix_level=VixLevel.HIGH,
            risk=RiskRegime.RISK_OFF,
        )
        mult, veto, reasons = apply("AUD/USD", "buy", ctx)
        assert veto is True
        assert any("vix" in r.lower() for r in reasons)

    def test_dxy_intraday_sigma_above_2_and_setup_against_vetoes(self):
        ctx = _make_ctx(
            dxy=MacroDirection.STRONG_UP,
            dxy_intraday_sigma=2.5,
        )
        mult, veto, reasons = apply("EUR/USD", "buy", ctx)
        assert veto is True
        assert any("dxy" in r.lower() for r in reasons)


class TestCommodityCurrencies:
    def test_audusd_buy_with_risk_on_gold_up_gets_boost(self):
        ctx = _make_ctx(
            dxy=MacroDirection.DOWN,
            spx=MacroDirection.STRONG_UP,
            gold=MacroDirection.UP,
            risk=RiskRegime.RISK_ON,
        )
        mult, _, _ = apply("AUD/USD", "buy", ctx)
        assert mult >= 1.1


class TestCADPair:
    def test_usdcad_sell_with_oil_strong_up_gets_boost(self):
        ctx = _make_ctx(oil=MacroDirection.STRONG_UP, dxy=MacroDirection.NEUTRAL)
        mult, _, _ = apply("USD/CAD", "sell", ctx)
        assert mult >= 1.1


class TestGold:
    def test_xauusd_buy_with_refuge_activated_gets_strong_boost(self):
        ctx = _make_ctx(
            vix_level=VixLevel.ELEVATED,
            vix_value=22.0,
            dxy=MacroDirection.DOWN,
            us10y=MacroDirection.DOWN,
        )
        mult, _, _ = apply("XAU/USD", "buy", ctx)
        assert mult >= 1.1


class TestEURSpread:
    def test_eurusd_buy_with_spread_narrowing_adds_to_alignment(self):
        ctx = _make_ctx(
            dxy=MacroDirection.NEUTRAL,
            spread_trend="narrowing",
        )
        mult, _, reasons = apply("EUR/USD", "buy", ctx)
        assert mult >= 1.0
        assert any("spread" in r.lower() or "eur" in r.lower() for r in reasons)


class TestNeutralNoEffect:
    def test_fully_neutral_context_gives_multiplier_1(self):
        ctx = _make_ctx()
        mult, veto, reasons = apply("EUR/USD", "buy", ctx)
        assert mult == 1.0
        assert veto is False
