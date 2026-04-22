"""Tests du moteur de backtest — fonctions pures (pas de DB, pas de net)."""
from datetime import datetime, timedelta, timezone

import pytest

from backend.models.schemas import (
    Candle, MarketTrend, PatternDetection, PatternType, TradeDirection,
    TradeSetup, TrendDirection, VolatilityData, VolatilityLevel,
)
from backend.services import backtest_engine as bt


def _mk_candle(ts: datetime, close: float, span: float = 0.0010) -> Candle:
    return Candle(
        timestamp=ts,
        open=close - span / 2,
        high=close + span,
        low=close - span,
        close=close,
        volume=0,
    )


def _mk_setup(pair="EUR/USD", direction=TradeDirection.BUY,
              entry=1.1000, sl=1.0950, tp1=1.1100, conf=0.7) -> TradeSetup:
    pattern = PatternDetection(
        pattern=PatternType.BREAKOUT_UP,
        strength=0.8,
        confidence=conf,
        description="test",
        detected_at=datetime.now(timezone.utc),
    )
    return TradeSetup(
        pair=pair,
        direction=direction,
        entry_price=entry,
        stop_loss=sl,
        take_profit_1=tp1,
        take_profit_2=tp1 + (tp1 - entry) * 0.5,
        risk_pips=50.0,
        reward_pips_1=100.0,
        reward_pips_2=150.0,
        risk_reward_1=2.0,
        risk_reward_2=3.0,
        pattern=pattern,
        message="test",
        timestamp=datetime.now(timezone.utc),
    )


# ─── compute_volatility ──────────────────────────────────────────────────────


def test_compute_volatility_insufficient_candles_returns_neutral():
    candles = [_mk_candle(datetime(2026, 1, 1, tzinfo=timezone.utc), 1.1)]
    vol = bt.compute_volatility(candles, "EUR/USD")
    assert vol.level == VolatilityLevel.MEDIUM


def test_compute_volatility_high_when_recent_spike():
    # 40 candles low-volatility, puis 15 high-volatility → ratio élevé
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles = []
    # 40 bars calmes (span 0.0005)
    for i in range(40):
        candles.append(_mk_candle(base + timedelta(hours=i), 1.10 + i * 0.0001, span=0.0005))
    # 15 bars agités (span 0.0020)
    for i in range(15):
        candles.append(_mk_candle(base + timedelta(hours=40 + i), 1.10 + (40 + i) * 0.0001, span=0.0020))
    vol = bt.compute_volatility(candles, "EUR/USD")
    assert vol.volatility_ratio > 1.3
    assert vol.level == VolatilityLevel.HIGH


# ─── compute_trend ───────────────────────────────────────────────────────────


def test_compute_trend_neutral_with_insufficient_data():
    candles = [_mk_candle(datetime(2026, 1, 1, tzinfo=timezone.utc), 1.1)]
    trend = bt.compute_trend(candles, "EUR/USD")
    assert trend.direction == TrendDirection.NEUTRAL
    assert trend.strength == 0.0


def test_compute_trend_bullish_on_rising_series():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # Série fortement haussière
    candles = [
        _mk_candle(base + timedelta(hours=i), 1.10 + i * 0.0005)
        for i in range(30)
    ]
    trend = bt.compute_trend(candles, "EUR/USD")
    assert trend.direction == TrendDirection.BULLISH
    assert trend.strength > 0


def test_compute_trend_bearish_on_falling_series():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles = [
        _mk_candle(base + timedelta(hours=i), 1.15 - i * 0.0005)
        for i in range(30)
    ]
    trend = bt.compute_trend(candles, "EUR/USD")
    assert trend.direction == TrendDirection.BEARISH


# ─── score_setup ─────────────────────────────────────────────────────────────


def test_score_setup_high_conf_aligned_trend_medium_vol():
    setup = _mk_setup(conf=0.9)
    vol = VolatilityData(
        pair="EUR/USD", current_volatility=10, average_volatility=10,
        volatility_ratio=1.0, level=VolatilityLevel.MEDIUM,
        updated_at=datetime.now(timezone.utc),
    )
    trend = MarketTrend(
        pair="EUR/USD", direction=TrendDirection.BULLISH, strength=0.8,
        description="strong bull", updated_at=datetime.now(timezone.utc),
    )
    score = bt.score_setup(setup, vol, trend)
    # 40 (pattern) + 20 (trend 0.8 × 25) + 12 (vol medium) + 10 (R:R 2.0 × 5)
    assert 75 <= score <= 90


def test_score_setup_low_when_trend_against():
    setup = _mk_setup(direction=TradeDirection.BUY, conf=0.9)
    vol = VolatilityData(
        pair="EUR/USD", current_volatility=10, average_volatility=10,
        volatility_ratio=1.0, level=VolatilityLevel.HIGH,
        updated_at=datetime.now(timezone.utc),
    )
    trend = MarketTrend(
        pair="EUR/USD", direction=TrendDirection.BEARISH, strength=1.0,
        description="strong bear", updated_at=datetime.now(timezone.utc),
    )
    score = bt.score_setup(setup, vol, trend)
    # Pas de bonus trend (opposite direction) → plus bas
    assert score < 75


# ─── simulate_trade_forward ──────────────────────────────────────────────────


def test_simulate_trade_tp_hit_buy():
    entry_time = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    setup = _mk_setup(entry=1.1000, sl=1.0950, tp1=1.1050)
    candles_5min = [
        _mk_candle(entry_time + timedelta(minutes=5 * i), 1.1000 + i * 0.002)
        for i in range(15)
    ]
    # 3e candle à close=1.1040 + span=0.001 → high=1.1045 < TP
    # 4e candle close=1.1060 + span → high=1.1070 >= TP1=1.1050
    outcome, _, exit_price = bt.simulate_trade_forward(setup, candles_5min, entry_time)
    assert outcome == "TP1"
    assert exit_price == 1.1050


def test_simulate_trade_sl_hit_buy():
    entry_time = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    setup = _mk_setup(entry=1.1000, sl=1.0950, tp1=1.1050)
    # Série qui plonge
    candles_5min = [
        _mk_candle(entry_time + timedelta(minutes=5 * i), 1.1000 - i * 0.002)
        for i in range(15)
    ]
    outcome, _, exit_price = bt.simulate_trade_forward(setup, candles_5min, entry_time)
    assert outcome == "SL"
    assert exit_price == 1.0950


def test_simulate_trade_timeout():
    entry_time = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    setup = _mk_setup(entry=1.1000, sl=1.0950, tp1=1.1050)
    # Prix stable autour de 1.1010, ni SL ni TP touchés
    candles_5min = [
        _mk_candle(entry_time + timedelta(minutes=5 * i), 1.1010, span=0.0001)
        for i in range(12 * 25)  # > 24h
    ]
    outcome, _, _ = bt.simulate_trade_forward(setup, candles_5min, entry_time, timeout_hours=24)
    assert outcome == "TIMEOUT"


def test_simulate_trade_sl_before_tp_same_bar_worst_case():
    """Si SL et TP touchés dans la même bar, on prend SL (conservateur)."""
    entry_time = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    setup = _mk_setup(entry=1.1000, sl=1.0950, tp1=1.1050)
    # Une bar avec high=1.1060 et low=1.0940 → les deux touchés
    wild_candle = Candle(
        timestamp=entry_time + timedelta(minutes=5),
        open=1.1000, high=1.1060, low=1.0940, close=1.1020, volume=0,
    )
    outcome, _, exit_price = bt.simulate_trade_forward(setup, [wild_candle], entry_time)
    assert outcome == "SL"
    assert exit_price == 1.0950


# ─── compute_pnl ──────────────────────────────────────────────────────────────


def test_compute_pnl_tp_buy_forex():
    setup = _mk_setup(entry=1.1000, sl=1.0950, tp1=1.1100)
    pips, pct = bt.compute_pnl(setup, exit_price=1.1100)
    # Gross +100 pips mais on retire ~2 pips de slippage → ~98 pips nets
    assert pips == 100.0  # pips bruts
    assert 0.88 < pct < 0.92  # +0.9% brut - 0.02% = 0.88%


def test_compute_pnl_sl_sell_forex():
    setup = _mk_setup(direction=TradeDirection.SELL, entry=1.1000, sl=1.1050, tp1=1.0900)
    pips, pct = bt.compute_pnl(setup, exit_price=1.1050)
    assert pips == -50.0
    assert pct < -0.45


def test_compute_pnl_jpy_pair_pips_factor():
    """Pairs JPY ont un pip factor 100, pas 10000."""
    setup = _mk_setup(pair="USD/JPY", entry=150.00, sl=149.50, tp1=151.00)
    pips, _ = bt.compute_pnl(setup, exit_price=151.00)
    assert pips == 100.0  # +100 pips sur JPY


# ─── summarize ────────────────────────────────────────────────────────────────


def test_summarize_empty():
    out = bt.summarize([])
    assert out["n"] == 0


def test_summarize_basic_stats():
    trades = [
        bt.SimulatedTrade(
            pair="EUR/USD", direction="buy",
            entry_at="2026-01-01T10:00:00+00:00", entry_price=1.10,
            stop_loss=1.09, take_profit=1.11,
            exit_at="2026-01-01T12:00:00+00:00", exit_price=1.11,
            outcome="TP1", pnl_pips=100, pnl_pct=0.9,
            confidence=70, pattern="breakout_up",
        ),
        bt.SimulatedTrade(
            pair="EUR/USD", direction="sell",
            entry_at="2026-01-02T10:00:00+00:00", entry_price=1.10,
            stop_loss=1.11, take_profit=1.09,
            exit_at="2026-01-02T11:00:00+00:00", exit_price=1.11,
            outcome="SL", pnl_pips=-100, pnl_pct=-0.9,
            confidence=65, pattern="momentum_down",
        ),
    ]
    out = bt.summarize(trades)
    assert out["n"] == 2
    assert out["wins"] == 1
    assert out["losses"] == 1
    assert out["win_rate_pct"] == 50.0
    assert abs(out["pnl_total_pct"]) < 0.01  # break even à 0.02 près
