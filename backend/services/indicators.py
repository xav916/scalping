"""Indicateurs techniques purs : RSI, MACD, Bollinger Bands.

Toutes les fonctions prennent une liste de prix de cloture en entree.
Implementations sans dependance externe (pas besoin de pandas/numpy).
"""

from backend.models.schemas import Candle


def _closes(candles: list[Candle]) -> list[float]:
    return [c.close for c in candles]


def sma(values: list[float], period: int) -> list[float | None]:
    """Simple Moving Average."""
    out: list[float | None] = []
    total = 0.0
    for i, v in enumerate(values):
        total += v
        if i >= period:
            total -= values[i - period]
        out.append(total / period if i >= period - 1 else None)
    return out


def ema(values: list[float], period: int) -> list[float | None]:
    """Exponential Moving Average."""
    if not values:
        return []
    out: list[float | None] = [None] * len(values)
    k = 2.0 / (period + 1)
    # Seed avec la SMA des premieres valeurs
    if len(values) < period:
        return out
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    prev = seed
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi(candles: list[Candle], period: int = 14) -> float | None:
    """Relative Strength Index (Wilder's smoothing)."""
    closes = _closes(candles)
    if len(closes) < period + 1:
        return None
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period
    for i in range(period + 1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gain = max(diff, 0)
        loss = max(-diff, 0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def macd(candles: list[Candle], fast: int = 12, slow: int = 26, signal: int = 9) -> dict | None:
    """MACD : difference EMA(fast) - EMA(slow), signal = EMA du MACD."""
    closes = _closes(candles)
    if len(closes) < slow + signal:
        return None
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    macd_line: list[float | None] = [
        (f - s) if (f is not None and s is not None) else None
        for f, s in zip(ema_fast, ema_slow)
    ]
    # Signal = EMA du MACD, on doit rebuild une sequence sans None pour calculer l'EMA
    macd_values = [v for v in macd_line if v is not None]
    if len(macd_values) < signal:
        return None
    signal_values = ema(macd_values, signal)

    last_macd = macd_line[-1]
    last_signal = signal_values[-1] if signal_values else None
    if last_macd is None or last_signal is None:
        return None
    return {
        "macd": last_macd,
        "signal": last_signal,
        "histogram": last_macd - last_signal,
    }


def bollinger(candles: list[Candle], period: int = 20, num_std: float = 2.0) -> dict | None:
    """Bandes de Bollinger : SMA(20) +/- 2 ecart-types."""
    closes = _closes(candles)
    if len(closes) < period:
        return None
    window = closes[-period:]
    mean = sum(window) / period
    variance = sum((x - mean) ** 2 for x in window) / period
    std = variance ** 0.5
    last_close = closes[-1]
    upper = mean + num_std * std
    lower = mean - num_std * std
    # Position du prix dans les bandes (0 = lower, 1 = upper)
    band_position = (last_close - lower) / (upper - lower) if upper != lower else 0.5
    return {
        "middle": mean,
        "upper": upper,
        "lower": lower,
        "position": max(0.0, min(1.0, band_position)),
    }


def compute_all(candles: list[Candle]) -> dict:
    """Retourne RSI, MACD et Bollinger pour une liste de bougies."""
    return {
        "rsi": rsi(candles),
        "macd": macd(candles),
        "bollinger": bollinger(candles),
    }
