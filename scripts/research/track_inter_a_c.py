"""Intersection Track A ∩ Track C — Expérience #6.

Question : V2_CORE_LONG (Track A patterns) **filtré** par le régime TF
(Track C "long") donne-t-il un PF significativement supérieur à chacun
des deux tracks pris isolément ?

Logique :
  - On ré-utilise la backtest_pair de Track A (avec V2_CORE_LONG)
  - Au moment de chaque trade détecté, on calcule le régime TF (Track C
    EMA cross + filter) sur le même bar
  - On garde le trade SEULEMENT si TF regime == "long" au bar d'entrée

Trois sorties chiffrées :
  - V2_CORE_LONG seul (Track A)
  - V2_CORE_LONG ∩ TF=long (intersection)
  - Track C TF LONG seul (référence)
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import scripts.research.track_a_backtest as ta
from scripts.research.track_a_backtest import (
    load_h1_candles,
    load_5min_candles,
    aggregate_to_h4,
    aggregate_to_daily,
    backtest_pair,
    filter_v2_core_long,
    stats,
)
from scripts.research.track_c_trend_following import (
    generate_tf_signals,
    backtest_tf_pair,
    DEFAULT_EMA_FAST,
    DEFAULT_EMA_SLOW,
    DEFAULT_EMA_FILTER,
)


def get_tf_regime_map(
    pair: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    ema_fast: int = DEFAULT_EMA_FAST,
    ema_slow: int = DEFAULT_EMA_SLOW,
    ema_filter: int = DEFAULT_EMA_FILTER,
) -> dict:
    """Retourne {timestamp -> regime} pour les bars du timeframe demandé,
    sur la fenêtre start→end."""
    ta.START = start
    ta.END = end
    candles_h1 = load_h1_candles(pair)

    if timeframe == "1h":
        candles = candles_h1
    elif timeframe == "4h":
        candles = aggregate_to_h4(candles_h1)
    elif timeframe == "1d":
        candles = aggregate_to_daily(candles_h1)
    else:
        raise ValueError(f"Unknown timeframe: {timeframe}")

    signals = generate_tf_signals(candles, ema_fast, ema_slow, ema_filter)
    return {s["timestamp"]: s["regime"] for s in signals}


def run_intersection(
    pair: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    spread: float = 0.0002,
) -> None:
    """Lance les 3 mesures et imprime un comparatif synthétique."""
    print(f"\n=== {pair} {timeframe} {start.date()} → {end.date()} ===\n")

    # 1. Track A — V2_CORE_LONG seul
    ta.START = start
    ta.END = end
    a_trades = backtest_pair(pair, timeframe, spread)
    a_core_long = [t for t in a_trades if filter_v2_core_long(t)]

    # 2. Map des régimes TF par timestamp
    tf_map = get_tf_regime_map(pair, timeframe, start, end)

    # 3. Intersection — V2_CORE_LONG seulement quand TF=long sur le même bar
    intersection = [
        t for t in a_core_long if tf_map.get(t["entry_at"]) == "long"
    ]

    # 4. Track C TF LONG seul (référence)
    c_trades = backtest_tf_pair(pair, start=start, end=end, timeframe=timeframe)
    c_long = [t for t in c_trades if t["direction"] == "long"]

    # Adapter les dicts Track C pour la fonction stats() qui attend `is_win` et `pct`
    # (Track C utilise la même clé `pct` et `is_win`)

    stats("Track A V2_CORE_LONG", a_core_long)
    stats("INTERSECTION (A ∩ C)", intersection)
    stats("Track C TF LONG", c_long)


def main() -> None:
    parser = argparse.ArgumentParser(description="Intersection Track A ∩ C")
    parser.add_argument("--pair", required=True)
    parser.add_argument("--timeframe", "-t", default="4h")
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    args = parser.parse_args()

    start = (datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
             if args.start else datetime(2025, 4, 25, tzinfo=timezone.utc))
    end = (datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
           if args.end else datetime(2026, 4, 25, tzinfo=timezone.utc))

    run_intersection(args.pair, args.timeframe, start, end)


if __name__ == "__main__":
    main()
