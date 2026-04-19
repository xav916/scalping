"""Tests for MacroContext schemas and enum thresholds."""
import pytest
from datetime import datetime, timezone

from backend.models.macro_schemas import (
    MacroDirection,
    VixLevel,
    RiskRegime,
    MacroContext,
    direction_from_zscore,
    vix_level_from_value,
)


class TestDirectionFromZscore:
    @pytest.mark.parametrize("z,expected", [
        (2.0, MacroDirection.STRONG_UP),
        (1.5, MacroDirection.STRONG_UP),
        (1.0, MacroDirection.UP),
        (0.5, MacroDirection.UP),
        (0.2, MacroDirection.NEUTRAL),
        (0.0, MacroDirection.NEUTRAL),
        (-0.2, MacroDirection.NEUTRAL),
        (-0.5, MacroDirection.DOWN),
        (-1.0, MacroDirection.DOWN),
        (-1.5, MacroDirection.STRONG_DOWN),
        (-2.0, MacroDirection.STRONG_DOWN),
    ])
    def test_direction_boundaries(self, z, expected):
        assert direction_from_zscore(z) == expected


class TestVixLevelFromValue:
    @pytest.mark.parametrize("v,expected", [
        (10.0, VixLevel.LOW),
        (14.9, VixLevel.LOW),
        (15.0, VixLevel.NORMAL),
        (19.9, VixLevel.NORMAL),
        (20.0, VixLevel.ELEVATED),
        (29.9, VixLevel.ELEVATED),
        (30.0, VixLevel.HIGH),
        (50.0, VixLevel.HIGH),
    ])
    def test_vix_boundaries(self, v, expected):
        assert vix_level_from_value(v) == expected


class TestMacroContextConstruction:
    def test_can_build_minimal(self):
        ctx = MacroContext(
            fetched_at=datetime.now(timezone.utc),
            dxy_direction=MacroDirection.UP,
            spx_direction=MacroDirection.NEUTRAL,
            vix_level=VixLevel.NORMAL,
            vix_value=17.5,
            us10y_trend=MacroDirection.NEUTRAL,
            de10y_trend=MacroDirection.NEUTRAL,
            us_de_spread_trend="flat",
            oil_direction=MacroDirection.NEUTRAL,
            nikkei_direction=MacroDirection.UP,
            gold_direction=MacroDirection.NEUTRAL,
            risk_regime=RiskRegime.NEUTRAL,
            raw_values={"DXY": 103.2},
        )
        assert ctx.vix_value == 17.5
        assert ctx.risk_regime == RiskRegime.NEUTRAL
