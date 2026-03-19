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


class PatternType(str, Enum):
    BREAKOUT_UP = "breakout_up"          # Cassure de résistance
    BREAKOUT_DOWN = "breakout_down"      # Cassure de support
    MOMENTUM_UP = "momentum_up"          # Momentum haussier
    MOMENTUM_DOWN = "momentum_down"      # Momentum baissier
    RANGE_BOUNCE_UP = "range_bounce_up"  # Rebond sur support
    RANGE_BOUNCE_DOWN = "range_bounce_down"  # Rejet sur résistance
    MEAN_REVERSION_UP = "mean_reversion_up"  # Retour à la moyenne (achat)
    MEAN_REVERSION_DOWN = "mean_reversion_down"  # Retour à la moyenne (vente)
    ENGULFING_BULLISH = "engulfing_bullish"  # Englobante haussière
    ENGULFING_BEARISH = "engulfing_bearish"  # Englobante baissière
    PIN_BAR_UP = "pin_bar_up"            # Pin bar haussière
    PIN_BAR_DOWN = "pin_bar_down"        # Pin bar baissière
    SIBI = "sibi"                        # Sell-side Imbalance, Buy-side Inefficiency (FVG baissier)
    BISI = "bisi"                        # Buy-side Imbalance, Sell-side Inefficiency (FVG haussier)
    SIBI_DISCUSSION = "sibi_discussion"  # Prix revient tester la zone SIBI
    BISI_DISCUSSION = "bisi_discussion"  # Prix revient tester la zone BISI


class TradeDirection(str, Enum):
    BUY = "buy"
    SELL = "sell"


class Candle(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


class PatternDetection(BaseModel):
    pattern: PatternType
    confidence: float  # 0 à 1
    description: str
    detected_at: datetime


class TradeSetup(BaseModel):
    pair: str
    direction: TradeDirection
    pattern: PatternDetection
    entry_price: float
    stop_loss: float
    take_profit_1: float  # TP1 conservateur
    take_profit_2: float  # TP2 agressif
    risk_pips: float
    reward_pips_1: float
    reward_pips_2: float
    risk_reward_1: float  # Ratio risque/récompense TP1
    risk_reward_2: float  # Ratio risque/récompense TP2
    message: str
    timestamp: datetime
    is_simulated: bool = False  # True si données simulées (pas de clé API ou rate limit)


class ScalpingSignal(BaseModel):
    pair: str
    signal_strength: SignalStrength
    volatility: VolatilityData
    trend: MarketTrend
    nearby_events: list[EconomicEvent]
    trade_setup: TradeSetup | None = None
    message: str
    timestamp: datetime


class MarketOverview(BaseModel):
    volatility_data: list[VolatilityData]
    economic_events: list[EconomicEvent]
    trends: list[MarketTrend]
    signals: list[ScalpingSignal]
    candles: list[Candle] = []
    patterns: list[PatternDetection] = []
    trade_setups: list[TradeSetup] = []
    last_update: datetime
