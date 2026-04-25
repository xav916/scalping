"""Backtest Daily-natif sur 20 ans — validation profondeur stars Phase 4.

Charge directement les bougies Daily depuis candles_historical interval='1day'
(disponibles 2006-2026 pour XAU/XAG/WTI/XLI/XLK ; 2021-2026 pour ETH).
Détecte patterns V2 puis simule forward sur Daily candles (10 jours
timeout, intra-bar via high/low quotidiens — moins précis qu'5min mais
cohérent pour valider robustesse temporelle).

Régimes couverts (XAU/XAG/WTI/XLI/XLK 20 ans) :
- 2007-2009 crise financière
- 2010-2014 recovery + ZIRP
- 2015-2019 normalisation
- 2020-2022 COVID + Fed hikes
- 2023-2026 bull cycle

Usage :
    python scripts/research/daily_native_backtest.py --pair XAU/USD --filter V2_CORE_LONG
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from math import sqrt
from pathlib import Path
from statistics import mean, stdev

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from backend.models.schemas import Candle, TradeDirection
from backend.services.pattern_detector import calculate_trade_setup, detect_patterns

CANDLES_DB = ROOT / "_macro_veto_analysis" / "backtest_candles.db"

CORE_LONG_PATTERNS = {"momentum_up", "engulfing_bullish", "breakout_up"}
WTI_OPTIMAL_PATTERNS = {"momentum_up", "engulfing_bullish", "range_bounce_up"}
TIGHT_LONG_PATTERNS = {"momentum_up", "engulfing_bullish"}

FILTER_NAMES = {
    "V2_CORE_LONG": CORE_LONG_PATTERNS,
    "V2_WTI_OPTIMAL": WTI_OPTIMAL_PATTERNS,
    "V2_TIGHT_LONG": TIGHT_LONG_PATTERNS,
}

TIMEOUT_DAYS = 10
SPREAD_SLIPPAGE_PCT = 0.0002


def load_daily_candles(pair: str, start: datetime | None = None, end: datetime | None = None) -> list[Candle]:
    sql = """SELECT timestamp, open, high, low, close, volume
             FROM candles_historical WHERE pair=? AND interval='1day'"""
    params: list = [pair]
    if start:
        sql += " AND timestamp >= ?"
        params.append(start.strftime("%Y-%m-%d %H:%M:%S"))
    if end:
        sql += " AND timestamp <= ?"
        params.append(end.strftime("%Y-%m-%d %H:%M:%S"))
    sql += " ORDER BY timestamp"
    with sqlite3.connect(CANDLES_DB) as c:
        rows = c.execute(sql, params).fetchall()
    return [
        Candle(
            timestamp=datetime.fromisoformat(r[0]).replace(tzinfo=timezone.utc),
            open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5] or 0,
        ) for r in rows
    ]


def simulate_forward_daily(
    setup, candles: list[Candle], entry_idx: int, timeout_days: int = TIMEOUT_DAYS,
) -> tuple[str, datetime, float]:
    """Simule l'évolution forward sur N candles Daily.
    Vérifie si TP1 ou SL touché par high/low quotidien (intra-bar approx).
    Retourne (outcome, exit_time, exit_price).
    """
    end_idx = min(entry_idx + 1 + timeout_days, len(candles))
    is_long = setup.direction == TradeDirection.BUY

    for i in range(entry_idx + 1, end_idx):
        c = candles[i]
        if is_long:
            if c.low <= setup.stop_loss:
                return "SL", c.timestamp, setup.stop_loss
            if c.high >= setup.take_profit_1:
                return "TP1", c.timestamp, setup.take_profit_1
        else:
            if c.high >= setup.stop_loss:
                return "SL", c.timestamp, setup.stop_loss
            if c.low <= setup.take_profit_1:
                return "TP1", c.timestamp, setup.take_profit_1

    last = candles[end_idx - 1]
    return "TIMEOUT", last.timestamp, last.close


def compute_pnl_pct(setup, exit_price: float, spread: float = SPREAD_SLIPPAGE_PCT) -> float:
    if setup.direction == TradeDirection.BUY:
        gross = (exit_price - setup.entry_price) / setup.entry_price
    else:
        gross = (setup.entry_price - exit_price) / setup.entry_price
    return (gross - spread) * 100


def backtest_daily(pair: str, filter_patterns: set[str], start: datetime, end: datetime) -> list[dict]:
    candles = load_daily_candles(pair, start, end - timedelta(days=TIMEOUT_DAYS + 2))
    if len(candles) < 50:
        return []

    trades: list[dict] = []
    last_at: datetime | None = None
    dedup = timedelta(days=1)

    for i in range(30, len(candles)):
        if last_at and (candles[i].timestamp - last_at) < dedup:
            continue
        history = candles[: i + 1]
        patterns = detect_patterns(history, pair)
        if not patterns:
            continue
        best = patterns[0]
        pattern_name = best.pattern.value if hasattr(best.pattern, "value") else str(best.pattern)
        if pattern_name not in filter_patterns:
            continue
        setup = calculate_trade_setup(pair, best, history)
        if not setup:
            continue
        if setup.direction != TradeDirection.BUY:
            continue

        full_candles = load_daily_candles(pair, candles[0].timestamp, end)
        idx_in_full = next((k for k, c in enumerate(full_candles) if c.timestamp == candles[i].timestamp), None)
        if idx_in_full is None:
            continue

        outcome, exit_ts, exit_price = simulate_forward_daily(setup, full_candles, idx_in_full)
        pct = compute_pnl_pct(setup, exit_price)

        trades.append({
            "pair": pair,
            "entry_at": candles[i].timestamp,
            "exit_at": exit_ts,
            "entry_price": setup.entry_price,
            "exit_price": exit_price,
            "stop_loss": setup.stop_loss,
            "tp1": setup.take_profit_1,
            "outcome": outcome,
            "pct": pct,
            "pattern": pattern_name,
            "is_win": pct > 0,
        })
        last_at = candles[i].timestamp

    return trades


def stats_full(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0, "pf": None, "sharpe": None, "max_dd_pct": 0.0,
                "wr_pct": None, "pnl_pct": 0.0, "calmar": None}
    n = len(trades)
    wins = sum(1 for t in trades if t["pct"] > 0)
    pnl = sum(t["pct"] for t in trades)
    gw = sum(t["pct"] for t in trades if t["pct"] > 0)
    gl = abs(sum(t["pct"] for t in trades if t["pct"] < 0))
    pf = gw / gl if gl > 0 else None
    wr = wins / n * 100

    # Equity curve + maxDD (1% risk per trade approx)
    sorted_t = sorted(trades, key=lambda t: t["entry_at"])
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for t in sorted_t:
        equity *= (1 + t["pct"] / 100 * 0.01)
        peak = max(peak, equity)
        dd = (peak - equity) / peak
        max_dd = max(max_dd, dd)

    # Monthly returns for Sharpe
    by_month: dict[str, float] = defaultdict(float)
    for t in sorted_t:
        by_month[t["entry_at"].strftime("%Y-%m")] += t["pct"]
    rets = list(by_month.values())
    sharpe = None
    if len(rets) >= 6:
        sd = stdev(rets)
        if sd > 0:
            sharpe = (mean(rets) / sd) * sqrt(12)

    n_months = len(rets)
    annualized_pct = (pnl * 12 / n_months) if n_months > 0 else 0
    calmar = annualized_pct / (max_dd * 100) if max_dd > 0 else None

    return {
        "n": n, "wr_pct": wr, "pf": pf, "sharpe": sharpe,
        "max_dd_pct": max_dd * 100, "calmar": calmar, "pnl_pct": pnl,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pair", required=True)
    parser.add_argument("--filter", default="V2_CORE_LONG", choices=list(FILTER_NAMES))
    args = parser.parse_args()

    patterns = FILTER_NAMES[args.filter]

    # Multi-window analysis
    windows = [
        ("ALL_20y", datetime(2006, 1, 1, tzinfo=timezone.utc), datetime(2026, 4, 26, tzinfo=timezone.utc)),
        ("2007-2009 CRISE", datetime(2007, 1, 1, tzinfo=timezone.utc), datetime(2010, 1, 1, tzinfo=timezone.utc)),
        ("2010-2014 ZIRP", datetime(2010, 1, 1, tzinfo=timezone.utc), datetime(2015, 1, 1, tzinfo=timezone.utc)),
        ("2015-2019 NORM", datetime(2015, 1, 1, tzinfo=timezone.utc), datetime(2020, 1, 1, tzinfo=timezone.utc)),
        ("2020-2022 COVID+HIKES", datetime(2020, 1, 1, tzinfo=timezone.utc), datetime(2023, 1, 1, tzinfo=timezone.utc)),
        ("2023-2026 BULL", datetime(2023, 1, 1, tzinfo=timezone.utc), datetime(2026, 4, 26, tzinfo=timezone.utc)),
        ("12M récent", datetime(2025, 4, 26, tzinfo=timezone.utc), datetime(2026, 4, 26, tzinfo=timezone.utc)),
    ]

    print(f"\n=== Daily-native backtest — {args.pair} {args.filter} ===\n")
    print(f"{'window':<22} {'n':>4} {'WR%':>6} {'PF':>5} {'Sharpe':>7} {'maxDD%':>7} {'Calmar':>7} {'PnL%':>9}")
    print("─" * 80)
    for label, start, end in windows:
        trades = backtest_daily(args.pair, patterns, start, end)
        s = stats_full(trades)
        pf_str = f"{s['pf']:.2f}" if s['pf'] else "  -- "
        sharpe_str = f"{s['sharpe']:.2f}" if s['sharpe'] else "  -- "
        calmar_str = f"{s['calmar']:.2f}" if s['calmar'] else "  -- "
        print(f"{label:<22} {s['n']:>4} {s['wr_pct'] or 0:>5.1f}% {pf_str:>5} {sharpe_str:>7} {s['max_dd_pct']:>6.1f}% {calmar_str:>7} {s['pnl_pct']:>+8.1f}%")


if __name__ == "__main__":
    main()
