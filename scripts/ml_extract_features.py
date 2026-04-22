#!/usr/bin/env python3
"""Feature engineering pour le training ML.

Parcourt les candles 1h historiques, détecte les patterns avec le
pattern_detector actuel, et pour chaque setup détecté :
1. Extrait un vecteur de features (30-40 colonnes) calculables AU MOMENT T
   (pas de look-ahead).
2. Simule le trade forward sur les 24 × 1h bars suivantes et détermine
   l'outcome (TP1 / SL / TIMEOUT).
3. Écrit tout dans un CSV prêt pour XGBoost.

Le script utilise les candles 1h seulement (pas 5min) pour la simulation
forward → on peut ainsi couvrir 10 ans d'historique sans dépasser le disk.

Usage :
    sudo docker exec scalping-radar python3 /app/scripts/ml_extract_features.py \\
        --db /app/data/backtest_candles.db \\
        --out /app/data/ml_features.csv \\
        --days 3650
"""
from __future__ import annotations
import argparse
import csv
import logging
import math
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, "/app")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.models.schemas import (
    Candle, PatternType, TradeDirection,
)
from backend.services.pattern_detector import (
    detect_patterns, calculate_trade_setup, _calculate_atr,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ml_feat")


DEFAULT_PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "USD/CAD",
    "EUR/JPY", "GBP/JPY", "EUR/GBP",
    "XAU/USD", "XAG/USD",
    "BTC/USD", "ETH/USD",
]  # Skip SPX/NDX (pas assez de data)


# ─── Utilitaires calcul indicateurs (pas de deps numpy/pandas) ───────────────


def _sma(values: list[float], period: int) -> float:
    """Simple moving average. Retourne NaN si pas assez de data."""
    if len(values) < period:
        return float("nan")
    return sum(values[-period:]) / period


def _ema(values: list[float], period: int) -> float:
    """Exponential moving average."""
    if not values or period <= 0:
        return float("nan")
    k = 2 / (period + 1)
    ema = values[0]
    for v in values[1:]:
        ema = v * k + ema * (1 - k)
    return ema


def _rsi(closes: list[float], period: int = 14) -> float:
    """Relative Strength Index. Range 0-100. >70 = surachat, <30 = survente."""
    if len(closes) < period + 1:
        return float("nan")
    gains = []
    losses = []
    for i in range(1, period + 1):
        diff = closes[-i] - closes[-i - 1]
        if diff > 0:
            gains.append(diff)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(-diff)
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _adx(candles: list[Candle], period: int = 14) -> float:
    """Average Directional Index. >25 = trend fort, <20 = range."""
    if len(candles) < period + 1:
        return float("nan")
    # Simplifié : basé sur ATR et direction dominante
    trs = []
    dmp = []
    dmm = []
    for i in range(1, len(candles)):
        prev = candles[i - 1]
        cur = candles[i]
        tr = max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close))
        trs.append(tr)
        up = cur.high - prev.high
        down = prev.low - cur.low
        dmp.append(up if up > down and up > 0 else 0)
        dmm.append(down if down > up and down > 0 else 0)
    if len(trs) < period:
        return float("nan")
    atr = sum(trs[-period:]) / period
    if atr == 0:
        return 0.0
    di_plus = 100 * (sum(dmp[-period:]) / period) / atr
    di_minus = 100 * (sum(dmm[-period:]) / period) / atr
    dx = 100 * abs(di_plus - di_minus) / (di_plus + di_minus) if (di_plus + di_minus) > 0 else 0
    return dx


def _stoch(candles: list[Candle], period: int = 14) -> float:
    """Stochastic %K. 0-100."""
    if len(candles) < period:
        return float("nan")
    recent = candles[-period:]
    hh = max(c.high for c in recent)
    ll = min(c.low for c in recent)
    if hh == ll:
        return 50.0
    close = candles[-1].close
    return 100 * (close - ll) / (hh - ll)


def _body_wick_ratio(candle: Candle) -> float:
    """Ratio body / total range. 1.0 = marubozu, 0 = doji."""
    total = candle.high - candle.low
    if total == 0:
        return 0.0
    body = abs(candle.close - candle.open)
    return body / total


def _session_utc(hour: int) -> str:
    """Session UTC. 5 buckets."""
    if 0 <= hour < 8:
        return "tokyo"
    if 8 <= hour < 13:
        return "london"
    if 13 <= hour < 17:
        return "london_ny"
    if 17 <= hour < 22:
        return "ny"
    return "sydney"


# ─── Feature extraction par candle/trade ────────────────────────────────────


PATTERN_TYPES = [
    "breakout_up", "breakout_down", "momentum_up", "momentum_down",
    "range_bounce_up", "range_bounce_down", "mean_reversion_up",
    "mean_reversion_down", "engulfing_bullish", "engulfing_bearish",
    "pin_bar_up", "pin_bar_down",
]


def extract_features(
    candles_before: list[Candle], pattern_type: str, direction: str,
    entry: float, sl: float, tp: float, pair: str,
) -> dict[str, Any]:
    """Features connues AU MOMENT T (pas de look-ahead)."""
    if len(candles_before) < 30:
        return {}
    closes = [c.close for c in candles_before]
    last = candles_before[-1]

    atr14 = _calculate_atr(candles_before, period=14)
    atr50 = _calculate_atr(candles_before[-50:], period=14) if len(candles_before) >= 50 else atr14
    atr_ratio = atr14 / atr50 if atr50 > 0 else 1.0

    sma20 = _sma(closes, 20)
    sma50 = _sma(closes, 50)
    sma200 = _sma(closes, 200)
    ema10 = _ema(closes[-30:], 10)
    ema30 = _ema(closes[-30:], 30)

    # Distance relative aux SMAs (en ATR units)
    dist_sma20 = (last.close - sma20) / atr14 if atr14 > 0 and not math.isnan(sma20) else 0
    dist_sma50 = (last.close - sma50) / atr14 if atr14 > 0 and not math.isnan(sma50) else 0
    dist_sma200 = (last.close - sma200) / atr14 if atr14 > 0 and not math.isnan(sma200) else 0

    ema_spread = (ema10 - ema30) / ema30 if ema30 > 0 else 0

    rsi14 = _rsi(closes, 14)
    adx14 = _adx(candles_before, 14)
    stoch_k = _stoch(candles_before, 14)

    # Candle shape (last 3 bars)
    bw_last = _body_wick_ratio(last)
    bw_prev = _body_wick_ratio(candles_before[-2]) if len(candles_before) >= 2 else 0
    bw_prev2 = _body_wick_ratio(candles_before[-3]) if len(candles_before) >= 3 else 0

    # Trade geometry
    risk = abs(entry - sl) / entry if entry > 0 else 0
    reward = abs(tp - entry) / entry if entry > 0 else 0
    rr = reward / risk if risk > 0 else 0

    # Time context
    ts = last.timestamp
    hour = ts.hour
    dow = ts.weekday()
    session = _session_utc(hour)

    # Pattern one-hot
    pattern_onehot = {f"pat_{p}": 1 if p == pattern_type else 0 for p in PATTERN_TYPES}

    # Session one-hot
    sessions = ["tokyo", "london", "london_ny", "ny", "sydney"]
    session_onehot = {f"ses_{s}": 1 if s == session else 0 for s in sessions}

    return {
        "pair": pair,
        "timestamp": ts.isoformat(),
        "direction": direction,
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "risk_pct": risk,
        "reward_pct": reward,
        "rr": rr,
        "atr14": atr14,
        "atr_ratio": atr_ratio,
        "dist_sma20_atr": dist_sma20,
        "dist_sma50_atr": dist_sma50,
        "dist_sma200_atr": dist_sma200,
        "ema_spread": ema_spread,
        "rsi14": rsi14 if not math.isnan(rsi14) else 50,
        "adx14": adx14 if not math.isnan(adx14) else 20,
        "stoch_k": stoch_k if not math.isnan(stoch_k) else 50,
        "bw_last": bw_last,
        "bw_prev": bw_prev,
        "bw_prev2": bw_prev2,
        "hour_sin": math.sin(2 * math.pi * hour / 24),
        "hour_cos": math.cos(2 * math.pi * hour / 24),
        "dow": dow,
        **pattern_onehot,
        **session_onehot,
    }


def simulate_outcome_1h(
    candles_after: list[Candle], direction: str, sl: float, tp: float,
    timeout_bars: int = 24,
) -> tuple[str, float]:
    """Simule le forward avec candles 1h (moins précis que 5min mais
    acceptable pour training ML sur 10 ans).

    Returns (outcome, exit_price). outcome ∈ {TP1, SL, TIMEOUT}.
    """
    is_buy = direction == "buy"
    bars_used = 0
    for c in candles_after[:timeout_bars]:
        bars_used += 1
        sl_hit = c.low <= sl if is_buy else c.high >= sl
        tp_hit = c.high >= tp if is_buy else c.low <= tp
        if sl_hit and tp_hit:
            return "SL", sl  # worst-case
        if sl_hit:
            return "SL", sl
        if tp_hit:
            return "TP1", tp
    if candles_after and bars_used > 0:
        return "TIMEOUT", candles_after[bars_used - 1].close
    return "TIMEOUT", tp  # no data after entry


# ─── Main loop ──────────────────────────────────────────────────────────────


def load_pair_candles(db_path: Path, pair: str, start: datetime, end: datetime) -> list[Candle]:
    with sqlite3.connect(db_path) as c:
        rows = c.execute(
            """
            SELECT timestamp, open, high, low, close, volume
              FROM candles_historical
             WHERE pair = ? AND interval = '1h'
               AND timestamp >= ? AND timestamp <= ?
             ORDER BY timestamp ASC
            """,
            (pair, start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")),
        ).fetchall()
    return [
        Candle(
            timestamp=datetime.fromisoformat(r[0]).replace(tzinfo=timezone.utc),
            open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5] or 0,
        )
        for r in rows
    ]


def direction_value(d) -> str:
    return d.value if hasattr(d, "value") else str(d)


def pattern_value(p) -> str:
    return p.value if hasattr(p, "value") else str(p)


def process_pair(
    db_path: Path, pair: str, start: datetime, end: datetime, dedup_bars: int = 1,
):
    """Yield feature rows + outcome pour chaque trade détecté."""
    candles = load_pair_candles(db_path, pair, start, end)
    if len(candles) < 250:
        log.warning(f"[{pair}] trop peu de candles ({len(candles)}), skip")
        return
    log.info(f"[{pair}] {len(candles)} candles 1h sur {start.date()}..{end.date()}")

    last_trade_idx = -dedup_bars - 1
    yielded = 0
    for i in range(200, len(candles) - 25):  # 200 warm-up, laisser 25 bars forward
        if i - last_trade_idx < dedup_bars:
            continue
        history = candles[: i + 1]
        patterns = detect_patterns(history, pair)
        if not patterns:
            continue
        best = patterns[0]
        setup = calculate_trade_setup(pair, best, history)
        if not setup:
            continue

        direction = direction_value(setup.direction)
        feats = extract_features(
            history, pattern_value(best.pattern), direction,
            setup.entry_price, setup.stop_loss, setup.take_profit_1, pair,
        )
        if not feats:
            continue

        # Simulate forward avec 24 × 1h bars
        candles_after = candles[i + 1:]
        outcome, exit_price = simulate_outcome_1h(
            candles_after, direction, setup.stop_loss, setup.take_profit_1,
            timeout_bars=24,
        )
        feats["outcome"] = outcome
        feats["pattern_confidence"] = best.confidence
        feats["pair_name"] = pair

        yielded += 1
        last_trade_idx = i
        yield feats

    log.info(f"[{pair}] {yielded} trades extraits")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="/app/data/backtest_candles.db")
    ap.add_argument("--out", default="/app/data/ml_features.csv")
    ap.add_argument("--days", type=int, default=3650)
    ap.add_argument("--pair")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        log.error(f"DB absente : {db_path}")
        sys.exit(1)

    pairs = [args.pair] if args.pair else DEFAULT_PAIRS
    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=args.days)

    log.info(f"Extraction features : {len(pairs)} pairs, {start.date()} → {end.date()}")

    total = 0
    fieldnames: list[str] | None = None
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = None
        for pair in pairs:
            for row in process_pair(db_path, pair, start, end):
                if writer is None:
                    fieldnames = list(row.keys())
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                writer.writerow(row)
                total += 1

    log.info(f"═══ TERMINÉ ═══ {total} rows → {args.out}")


if __name__ == "__main__":
    main()
