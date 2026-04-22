#!/usr/bin/env python3
"""Lance un backtest sur l'historique déjà fetché.

Prérequis : scripts/fetch_historical_backtest.py a été exécuté, la DB
/opt/scalping/data/backtest_candles.db contient des candles 1h + 5min.

Usage (dans le container Docker — le script importe les services backend) :
    sudo docker exec scalping-radar python3 /app/scripts/run_backtest.py \\
        --pair EUR/USD --threshold 55

    # Multi-pair :
    sudo docker exec scalping-radar python3 /app/scripts/run_backtest.py \\
        --all --threshold 55

    # Walk-forward par trimestre sur 3 ans :
    sudo docker exec scalping-radar python3 /app/scripts/run_backtest.py \\
        --all --walk-forward quarterly
"""
from __future__ import annotations
import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, "/app")  # dans le container
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # local dev

from backend.services.backtest_engine import (  # noqa: E402
    DEFAULT_DB, SCORING_THRESHOLD,
    run_backtest, summarize,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("backtest_cli")


DEFAULT_PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "USD/CAD",
    "EUR/JPY", "GBP/JPY", "EUR/GBP",
    "XAU/USD", "XAG/USD",
    "BTC/USD", "ETH/USD",
    "SPX", "NDX",
]


def iter_quarters(start: datetime, end: datetime):
    """Itère sur les bornes trimestrielles pour walk-forward."""
    cur = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # Aligner au début de trimestre (jan/avr/jul/oct)
    cur = cur.replace(month=((cur.month - 1) // 3) * 3 + 1)
    while cur < end:
        next_month = cur.month + 3
        if next_month > 12:
            nxt = cur.replace(year=cur.year + 1, month=next_month - 12)
        else:
            nxt = cur.replace(month=next_month)
        yield cur, min(nxt, end)
        cur = nxt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--pair", help="une seule pair (EUR/USD)")
    ap.add_argument("--all", action="store_true", help="toutes les pairs par défaut")
    ap.add_argument("--threshold", type=float, default=SCORING_THRESHOLD)
    ap.add_argument("--days", type=int, default=1095, help="nb jours depuis now (défaut 3 ans)")
    ap.add_argument("--walk-forward", choices=["quarterly"], help="split temporel")
    ap.add_argument("--json", action="store_true", help="output JSON au lieu de texte")
    args = ap.parse_args()

    db = Path(args.db)
    if not db.exists():
        log.error(f"DB absente : {db}. Lance d'abord fetch_historical_backtest.py.")
        sys.exit(1)

    pairs = DEFAULT_PAIRS if args.all else [args.pair or "EUR/USD"]
    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=args.days)

    log.info(f"Backtest : {len(pairs)} pair(s), {start.date()} → {end.date()}, "
             f"threshold={args.threshold}")

    results: dict[str, dict] = {}

    for pair in pairs:
        log.info(f"═══ {pair} ═══")
        if args.walk_forward == "quarterly":
            per_quarter = {}
            all_trades = []
            for q_start, q_end in iter_quarters(start, end):
                q_label = f"{q_start.year}Q{((q_start.month - 1) // 3) + 1}"
                trades = run_backtest(
                    db, pair, q_start, q_end, threshold=args.threshold,
                    run_id=f"wf-{pair.replace('/', '')}-{q_label}",
                )
                summary = summarize(trades)
                per_quarter[q_label] = summary
                all_trades.extend(trades)
                log.info(
                    f"  {q_label}: n={summary.get('n', 0)} "
                    f"wr={summary.get('win_rate_pct', 0)}% "
                    f"pnl={summary.get('pnl_total_pct', 0)}%"
                )
            overall = summarize(all_trades)
            results[pair] = {"overall": overall, "by_quarter": per_quarter}
        else:
            trades = run_backtest(
                db, pair, start, end, threshold=args.threshold,
                run_id=f"bt-{pair.replace('/', '')}-full",
            )
            summary = summarize(trades)
            results[pair] = summary
            log.info(
                f"  n={summary.get('n', 0)} wr={summary.get('win_rate_pct', 0)}% "
                f"pnl={summary.get('pnl_total_pct', 0)}% "
                f"sharpe={summary.get('sharpe_approx', 0)} "
                f"dd={summary.get('max_drawdown_pct', 0)}%"
            )

    log.info("═══ GLOBAL ═══")
    if args.json:
        print(json.dumps(results, indent=2, default=str))
    else:
        # Résumé texte table
        print(f"\n{'Pair':<10} {'N':>5} {'Win%':>6} {'PnL%':>7} {'Sharpe':>7} {'DD%':>6}")
        print("─" * 52)
        for pair, data in results.items():
            s = data.get("overall", data)
            print(
                f"{pair:<10} {s.get('n', 0):>5} "
                f"{s.get('win_rate_pct', 0):>5.1f}% "
                f"{s.get('pnl_total_pct', 0):>6.2f}% "
                f"{s.get('sharpe_approx', 0):>7.2f} "
                f"{s.get('max_drawdown_pct', 0):>5.2f}%"
            )


if __name__ == "__main__":
    main()
