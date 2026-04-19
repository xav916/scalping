"""Tests for macro_context_service: fetch, cache, stale fallback."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from backend.models.macro_schemas import MacroContext, MacroDirection, VixLevel, RiskRegime
from backend.services import macro_context_service as svc


@pytest.fixture(autouse=True)
def reset_cache():
    """Ensure each test starts with a clean cache."""
    svc._cache_snapshot = None
    yield
    svc._cache_snapshot = None


def _fake_candles(values: list[float]) -> list[dict]:
    """Mock Twelve Data time_series response shape."""
    return [{"close": str(v)} for v in values]


class TestZScoreComputation:
    def test_zscore_zero_when_price_equals_mean(self):
        closes = [100.0] * 20
        assert svc._compute_zscore(100.0, closes) == 0.0

    def test_zscore_positive_when_price_above_mean(self):
        closes = [100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0,
                  101.0, 101.0, 101.0, 101.0, 101.0, 101.0, 101.0, 101.0, 101.0, 101.0]
        z = svc._compute_zscore(102.0, closes)
        assert z > 0

    def test_zscore_zero_when_series_is_flat(self):
        # stddev=0 — should return 0 instead of dividing by zero
        closes = [50.0] * 20
        assert svc._compute_zscore(55.0, closes) == 0.0


class TestRiskRegimeDerivation:
    def test_risk_off_when_vix_high_and_spx_down(self):
        regime = svc._derive_risk_regime(VixLevel.ELEVATED, MacroDirection.DOWN)
        assert regime == RiskRegime.RISK_OFF

    def test_risk_on_when_vix_low_and_spx_up(self):
        regime = svc._derive_risk_regime(VixLevel.LOW, MacroDirection.UP)
        assert regime == RiskRegime.RISK_ON

    def test_neutral_otherwise(self):
        regime = svc._derive_risk_regime(VixLevel.NORMAL, MacroDirection.NEUTRAL)
        assert regime == RiskRegime.NEUTRAL


class TestCache:
    def test_get_returns_none_before_first_fetch(self):
        assert svc.get_macro_snapshot() is None

    def test_get_returns_cached_after_set(self):
        ctx = MacroContext(
            fetched_at=datetime.now(timezone.utc),
            dxy_direction=MacroDirection.UP,
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
        svc._cache_snapshot = ctx
        assert svc.get_macro_snapshot() is ctx

    def test_is_fresh_returns_false_when_older_than_max_age(self):
        old = datetime.now(timezone.utc) - timedelta(hours=3)
        assert svc.is_fresh(old) is False

    def test_is_fresh_returns_true_when_recent(self):
        recent = datetime.now(timezone.utc) - timedelta(minutes=30)
        assert svc.is_fresh(recent) is True


class TestRefreshFromMockedTwelveData:
    @pytest.mark.asyncio
    async def test_refresh_populates_cache_on_success(self):
        fake_candles = _fake_candles([100.0] * 19 + [102.0])
        with patch("backend.services.macro_context_service.MACRO_SCORING_ENABLED", True):
            with patch("backend.services.macro_context_service._fetch_candles_for_symbol",
                       new=AsyncMock(return_value=fake_candles)):
                ok = await svc.refresh_macro_context()
        assert ok is True
        assert svc.get_macro_snapshot() is not None

    @pytest.mark.asyncio
    async def test_refresh_returns_false_when_all_symbols_fail(self):
        with patch("backend.services.macro_context_service.MACRO_SCORING_ENABLED", True):
            with patch("backend.services.macro_context_service._fetch_candles_for_symbol",
                       new=AsyncMock(return_value=[])):
                ok = await svc.refresh_macro_context()
        assert ok is False

    @pytest.mark.asyncio
    async def test_refresh_preserves_existing_cache_on_failure(self):
        existing = MacroContext(
            fetched_at=datetime.now(timezone.utc) - timedelta(minutes=30),
            dxy_direction=MacroDirection.UP,
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
        svc._cache_snapshot = existing

        with patch("backend.services.macro_context_service.MACRO_SCORING_ENABLED", True):
            with patch("backend.services.macro_context_service._fetch_candles_for_symbol",
                       new=AsyncMock(return_value=[])):
                await svc.refresh_macro_context()

        assert svc.get_macro_snapshot() is existing
