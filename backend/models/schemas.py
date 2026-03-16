"""Data models for the scalping decision tool."""

from datetime import datetime
from enum import Enum
from pydantic import BaseModel


class VolatilityLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TrendDirection(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class EventImpact(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SignalStrength(str, Enum):
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"


class VolatilityData(BaseModel):
    pair: str
    current_volatility: float  # pips
    average_volatility: float  # pips
    volatility_ratio: float  # current / average
    level: VolatilityLevel
    timeframe: str = "1H"
    updated_at: datetime


class EconomicEvent(BaseModel):
    time: str
    currency: str
    impact: EventImpact
    event_name: str
    forecast: str | None = None
    previous: str | None = None
    actual: str | None = None


class MarketTrend(BaseModel):
    pair: str
    direction: TrendDirection
    strength: float  # 0 to 1
    description: str
    updated_at: datetime


class ScalpingSignal(BaseModel):
    pair: str
    signal_strength: SignalStrength
    volatility: VolatilityData
    trend: MarketTrend
    nearby_events: list[EconomicEvent]
    message: str
    timestamp: datetime


class MarketOverview(BaseModel):
    volatility_data: list[VolatilityData]
    economic_events: list[EconomicEvent]
    trends: list[MarketTrend]
    signals: list[ScalpingSignal]
    last_update: datetime
