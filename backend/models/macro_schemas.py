"""Schemas for the macro context scoring layer.

- MacroDirection / VixLevel / RiskRegime: enums capturing normalized state
- MacroContext: a full snapshot of the 8 macro indicators at a point in time
- direction_from_zscore / vix_level_from_value: pure helpers used by the
  fetcher to build a MacroContext from raw price data
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from config.settings import (
    MACRO_VIX_ELEVATED,
    MACRO_VIX_HIGH,
    MACRO_VIX_LOW,
    MACRO_ZSCORE_STRONG,
    MACRO_ZSCORE_WEAK,
)


class MacroDirection(str, Enum):
    STRONG_UP = "strong_up"
    UP = "up"
    NEUTRAL = "neutral"
    DOWN = "down"
    STRONG_DOWN = "strong_down"


class VixLevel(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    ELEVATED = "elevated"
    HIGH = "high"


class RiskRegime(str, Enum):
    RISK_ON = "risk_on"
    NEUTRAL = "neutral"
    RISK_OFF = "risk_off"


@dataclass
class MacroContext:
    fetched_at: datetime
    dxy_direction: MacroDirection
    spx_direction: MacroDirection
    vix_level: VixLevel
    vix_value: float
    us10y_trend: MacroDirection
    de10y_trend: MacroDirection
    us_de_spread_trend: str  # widening | flat | narrowing
    oil_direction: MacroDirection
    nikkei_direction: MacroDirection
    gold_direction: MacroDirection
    risk_regime: RiskRegime
    raw_values: dict[str, float] = field(default_factory=dict)
    dxy_intraday_sigma: float = 0.0  # used for veto condition only


def direction_from_zscore(z: float) -> MacroDirection:
    """Maps a z-score to a MacroDirection using thresholds from settings."""
    if z >= MACRO_ZSCORE_STRONG:
        return MacroDirection.STRONG_UP
    if z >= MACRO_ZSCORE_WEAK:
        return MacroDirection.UP
    if z <= -MACRO_ZSCORE_STRONG:
        return MacroDirection.STRONG_DOWN
    if z <= -MACRO_ZSCORE_WEAK:
        return MacroDirection.DOWN
    return MacroDirection.NEUTRAL


def vix_level_from_value(v: float) -> VixLevel:
    """Maps a VIX raw value to a VixLevel using absolute thresholds."""
    if v >= MACRO_VIX_HIGH:
        return VixLevel.HIGH
    if v >= MACRO_VIX_ELEVATED:
        return VixLevel.ELEVATED
    if v >= MACRO_VIX_LOW:
        return VixLevel.NORMAL
    return VixLevel.LOW
