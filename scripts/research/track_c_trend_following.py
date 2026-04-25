"""Track C — Trend-following systématique MVP — Phase 1.

Spec : `docs/superpowers/specs/2026-04-25-track-c-trend-following.md`
Hypothèse : un trend-following Carver-style basique (EMA cross + ATR stop)
sans pattern detection peut générer un edge sur retail multi-asset à
H4/Daily.

MVP minimaliste :
- Signal LONG  : close > EMA(close, ema_filter) AND EMA(close, ema_fast) > EMA(close, ema_slow)
- Signal SHORT : close < EMA(close, ema_filter) AND EMA(close, ema_fast) < EMA(close, ema_slow)
- Entrée à la clôture du bar où la condition devient vraie
- Sortie : (a) EMA cross inverse (fast vs slow change de signe),
          (b) stop ATR×K touché en intra-bar (5min)
- Sizing : 1% risk fixe par trade (pour comparabilité — vol target plus tard)
- Pas de TP — laisser courir le gagnant jusqu'au signal opposé ou stop

Comparaison avec Track A V2_CORE_LONG sur les *mêmes assets/périodes*
(XAU H4 + XAG H4 sur 12M et 24M).

Usage :
    python scripts/research/track_c_trend_following.py --pair XAU/USD --start 2024-04-25
    python scripts/research/track_c_trend_following.py --pair XAG/USD
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from backend.models.schemas import Candle

# Import des helpers depuis Track A (aggregation + DB load)
from scripts.research.track_a_backtest import (
    load_h1_candles,
    load_5min_candles,
    aggregate_to_h4,
    aggregate_to_daily,
)


# Paramètres par défaut Carver/Faith style
DEFAULT_EMA_FAST = 12
DEFAULT_EMA_SLOW = 48
DEFAULT_EMA_FILTER = 100  # filtre régime "trend > 100 bars"
DEFAULT_ATR_PERIOD = 14
DEFAULT_ATR_MULT = 3.0
DEFAULT_SPREAD_PCT = 0.0002


def ema(values: list[float], period: int) -> list[float]:
    """EMA progressive — retourne la série complète (NaN au début)."""
    if not values or period <= 0:
        return []
    k = 2 / (period + 1)
    out: list[float] = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def atr(candles: list[Candle], period: int) -> list[float]:
    """ATR progressive — Wilder smoothing."""
    if len(candles) < 2:
        return [0.0] * len(candles)
    trs: list[float] = [candles[0].high - candles[0].low]
    for i in range(1, len(candles)):
        prev = candles[i - 1]
        cur = candles[i]
        tr = max(
            cur.high - cur.low,
            abs(cur.high - prev.close),
            abs(cur.low - prev.close),
        )
        trs.append(tr)
    out = [trs[0]]
    for i in range(1, len(trs)):
        if i < period:
            out.append(sum(trs[: i + 1]) / (i + 1))
        else:
            # Wilder : ((period-1) * prev + tr) / period
            out.append((out[-1] * (period - 1) + trs[i]) / period)
    return out


def generate_tf_signals(
    candles: list[Candle],
    ema_fast: int,
    ema_slow: int,
    ema_filter: int,
) -> list[dict]:
    """Génère la liste de "régimes" (long / short / flat) bar par bar.

    Régime LONG : close > EMA_filter ET EMA_fast > EMA_slow
    Régime SHORT : close < EMA_filter ET EMA_fast < EMA_slow
    Sinon : FLAT

    Retourne une liste de dicts {timestamp, close, regime} pour chaque bar.
    Les régimes sont calculés "au close du bar" (pas de look-ahead).
    """
    if len(candles) < max(ema_fast, ema_slow, ema_filter) + 5:
        return []

    closes = [c.close for c in candles]
    ema_f = ema(closes, ema_fast)
    ema_s = ema(closes, ema_slow)
    ema_t = ema(closes, ema_filter)

    out: list[dict] = []
    for i, c in enumerate(candles):
        if i < ema_filter:
            regime = "flat"
        elif c.close > ema_t[i] and ema_f[i] > ema_s[i]:
            regime = "long"
        elif c.close < ema_t[i] and ema_f[i] < ema_s[i]:
            regime = "short"
        else:
            regime = "flat"
        out.append({"timestamp": c.timestamp, "close": c.close, "regime": regime})
    return out


def simulate_tf_trade(
    entry: dict,
    direction: str,
    candles_5min: list[Candle],
    atr_at_entry: float,
    atr_mult: float,
    forward_signals: list[dict],
    spread_pct: float,
) -> dict | None:
    """Simule un trade TF entré au close du bar `entry`, sorti soit :
    - sur cross inverse (signal change de "long" à autre chose, ou "short" à autre chose)
    - soit sur stop ATR×K touché en intra-bar 5min

    Retourne dict avec entry_at, exit_at, exit_reason, pct, peak_excursion, etc.
    """
    entry_price = entry["close"]
    entry_ts = entry["timestamp"]

    if direction == "long":
        stop = entry_price - atr_mult * atr_at_entry
    else:
        stop = entry_price + atr_mult * atr_at_entry

    # Cherche le bar de sortie sur signal — le premier forward_signal après entry
    # qui n'est pas dans le même régime
    signal_exit_ts: datetime | None = None
    signal_exit_price: float | None = None
    for fs in forward_signals:
        if fs["timestamp"] <= entry_ts:
            continue
        if fs["regime"] != direction:
            signal_exit_ts = fs["timestamp"]
            signal_exit_price = fs["close"]
            break

    # Cherche un hit ATR-stop dans les 5min entre entry et signal_exit
    end_check = signal_exit_ts if signal_exit_ts else (entry_ts + timedelta(days=60))
    stop_hit_ts: datetime | None = None
    stop_hit_price: float | None = None
    for c5 in candles_5min:
        if c5.timestamp <= entry_ts:
            continue
        if c5.timestamp > end_check:
            break
        if direction == "long" and c5.low <= stop:
            stop_hit_ts = c5.timestamp
            stop_hit_price = stop
            break
        if direction == "short" and c5.high >= stop:
            stop_hit_ts = c5.timestamp
            stop_hit_price = stop
            break

    # Choisir la sortie qui arrive en premier
    if stop_hit_ts and (not signal_exit_ts or stop_hit_ts < signal_exit_ts):
        exit_ts = stop_hit_ts
        exit_price = stop_hit_price
        exit_reason = "atr_stop"
    elif signal_exit_ts:
        exit_ts = signal_exit_ts
        exit_price = signal_exit_price
        exit_reason = "signal_reverse"
    else:
        # Pas de signal de sortie dans la fenêtre — open trade, on l'ignore
        return None

    # PnL pct
    if direction == "long":
        gross_pct = (exit_price - entry_price) / entry_price
    else:
        gross_pct = (entry_price - exit_price) / entry_price
    net_pct = (gross_pct - spread_pct) * 100  # en %

    return {
        "entry_at": entry_ts,
        "entry_price": entry_price,
        "direction": direction,
        "stop": stop,
        "exit_at": exit_ts,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "pct": net_pct,
        "is_win": net_pct > 0,
        "duration_h": (exit_ts - entry_ts).total_seconds() / 3600,
    }


def backtest_tf_pair(
    pair: str,
    start: datetime,
    end: datetime,
    timeframe: str = "4h",
    ema_fast: int = DEFAULT_EMA_FAST,
    ema_slow: int = DEFAULT_EMA_SLOW,
    ema_filter: int = DEFAULT_EMA_FILTER,
    atr_period: int = DEFAULT_ATR_PERIOD,
    atr_mult: float = DEFAULT_ATR_MULT,
    spread_pct: float = DEFAULT_SPREAD_PCT,
) -> list[dict]:
    """Backtest TF sur une paire. Charge H1 → aggrège selon timeframe →
    génère signaux → simule trades.
    """
    # Patcher temporairement les START/END de track_a pour les loaders
    import scripts.research.track_a_backtest as ta
    ta.START = start
    ta.END = end

    candles_h1 = load_h1_candles(pair)
    candles_5min = load_5min_candles(pair)
    if len(candles_h1) < 200:
        return []

    if timeframe == "1h":
        signal_candles = candles_h1
    elif timeframe == "4h":
        signal_candles = aggregate_to_h4(candles_h1)
    elif timeframe == "1d":
        signal_candles = aggregate_to_daily(candles_h1)
    else:
        raise ValueError(f"Unknown timeframe: {timeframe}")

    if len(signal_candles) < ema_filter + 10:
        return []

    signals = generate_tf_signals(signal_candles, ema_fast, ema_slow, ema_filter)
    atrs = atr(signal_candles, atr_period)

    trades: list[dict] = []
    last_regime = "flat"
    for i, sig in enumerate(signals):
        regime = sig["regime"]
        if regime != last_regime and regime in ("long", "short"):
            # Nouveau trade — entrée au close du bar
            t = simulate_tf_trade(
                entry=sig,
                direction=regime,
                candles_5min=candles_5min,
                atr_at_entry=atrs[i],
                atr_mult=atr_mult,
                forward_signals=signals[i + 1:],
                spread_pct=spread_pct,
            )
            if t is not None:
                t["pair"] = pair
                trades.append(t)
        last_regime = regime

    return trades


def stats(label: str, trades: list[dict]) -> None:
    if not trades:
        print(f"  {label:<28} (vide)")
        return
    n = len(trades)
    wins = sum(1 for t in trades if t["is_win"])
    wr = wins / n * 100
    total_pct = sum(t["pct"] for t in trades)
    avg = total_pct / n
    gw = sum(t["pct"] for t in trades if t["pct"] > 0)
    gl = abs(sum(t["pct"] for t in trades if t["pct"] < 0))
    pf = gw / gl if gl > 0 else float("inf")
    avg_dur = sum(t["duration_h"] for t in trades) / n
    n_long = sum(1 for t in trades if t["direction"] == "long")
    n_short = n - n_long
    n_atr = sum(1 for t in trades if t["exit_reason"] == "atr_stop")

    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in sorted(trades, key=lambda x: x["entry_at"]):
        equity += t["pct"]
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd

    pf_str = f"{pf:>4.2f}" if pf != float("inf") else "  ∞ "
    print(
        f"  {label:<28} n={n:>4}  L/S={n_long:>3}/{n_short:>3}  wr={wr:>5.1f}%  "
        f"PnL={total_pct:>+8.2f}%  avg={avg:>+5.3f}%  PF={pf_str}  "
        f"maxDD={max_dd:>5.1f}%  dur~{avg_dur:>4.0f}h  ATRstops={n_atr}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Track C MVP — TF systématique")
    parser.add_argument("--pair", required=True, help="Paire à tester (ex XAU/USD)")
    parser.add_argument("--timeframe", "-t", default="4h", choices=["1h", "4h", "1d"])
    parser.add_argument("--start", default="2025-04-25", help="Date début YYYY-MM-DD")
    parser.add_argument("--end", default="2026-04-25", help="Date fin YYYY-MM-DD")
    parser.add_argument("--ema-fast", type=int, default=DEFAULT_EMA_FAST)
    parser.add_argument("--ema-slow", type=int, default=DEFAULT_EMA_SLOW)
    parser.add_argument("--ema-filter", type=int, default=DEFAULT_EMA_FILTER)
    parser.add_argument("--atr-period", type=int, default=DEFAULT_ATR_PERIOD)
    parser.add_argument("--atr-mult", type=float, default=DEFAULT_ATR_MULT)
    parser.add_argument("--no-costs", action="store_true")
    args = parser.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    spread = 0.0 if args.no_costs else DEFAULT_SPREAD_PCT

    print(f"=== Track C MVP — {args.pair} {args.timeframe} ===")
    print(f"Fenêtre : {start.date()} → {end.date()}")
    print(f"Signal : EMA({args.ema_fast}/{args.ema_slow}) cross filtré par EMA({args.ema_filter})")
    print(f"Stop : ATR({args.atr_period})×{args.atr_mult}")
    print(f"Coûts : {spread*100:.3f}%")
    print()

    trades = backtest_tf_pair(
        pair=args.pair,
        start=start,
        end=end,
        timeframe=args.timeframe,
        ema_fast=args.ema_fast,
        ema_slow=args.ema_slow,
        ema_filter=args.ema_filter,
        atr_period=args.atr_period,
        atr_mult=args.atr_mult,
        spread_pct=spread,
    )

    print(f"Trades simulés : {len(trades)}")
    print()
    stats("ALL", trades)
    stats("LONG only", [t for t in trades if t["direction"] == "long"])
    stats("SHORT only", [t for t in trades if t["direction"] == "short"])
    stats("ATR-stopped", [t for t in trades if t["exit_reason"] == "atr_stop"])
    stats("Signal-reverse", [t for t in trades if t["exit_reason"] == "signal_reverse"])


if __name__ == "__main__":
    main()
