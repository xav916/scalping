#!/usr/bin/env python3
"""One-shot : remplit `close_reason` pour les trades CLOSED qui l'ont NULL.

Utilise la même heuristique que mt5_sync._derive_close_reason_from_exit
(compare exit_price aux SL/TP avec tolerance par asset class).

Run sur EC2 :
    cd /home/ec2-user/scalping
    sudo python3 scripts/backfill_close_reasons.py --dry-run
    # si OK :
    sudo python3 scripts/backfill_close_reasons.py
"""
from __future__ import annotations
import argparse
import sqlite3
import sys
from pathlib import Path

# Ajoute le repo au sys.path pour importer le service
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DB_PATH = "/opt/scalping/data/trades.db"


def _tolerance_for_pair(pair: str | None) -> float:
    base = pair.split("/")[0].upper() if pair and "/" in pair else (pair or "").upper()
    if base == "XAU":
        return 0.3
    if base == "XAG":
        return 0.02
    if base in {"BTC", "ETH"}:
        return 15.0
    if base in {"SPX", "NDX"}:
        return 2.0
    if base == "WTI":
        return 0.05
    return 0.0002  # 2 pips forex


def derive_reason(exit_price: float | None, sl: float | None,
                  tp: float | None, pair: str) -> str | None:
    if exit_price is None:
        return None
    if sl is None and tp is None:
        return None
    tol = _tolerance_for_pair(pair)
    if sl is not None and abs(exit_price - sl) <= tol:
        return "SL"
    if tp is not None and abs(exit_price - tp) <= tol:
        return "TP1"
    return "MANUAL"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--db", default=DB_PATH)
    args = ap.parse_args()

    with sqlite3.connect(args.db) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute("""
            SELECT id, pair, stop_loss, take_profit, exit_price, close_reason, pnl
              FROM personal_trades
             WHERE status = 'CLOSED'
               AND exit_price IS NOT NULL
               AND close_reason IS NULL
        """).fetchall()

    print(f"Found {len(rows)} closed trades with NULL close_reason", file=sys.stderr)

    updates = []
    for r in rows:
        reason = derive_reason(r["exit_price"], r["stop_loss"], r["take_profit"], r["pair"])
        if reason:
            updates.append((r["id"], reason, r["pair"], r["pnl"]))

    # Distribution preview
    from collections import Counter
    cnt = Counter(u[1] for u in updates)
    for reason, n in cnt.most_common():
        print(f"  {reason}: {n}", file=sys.stderr)

    if args.dry_run:
        print("DRY RUN — no writes. First 10 updates:", file=sys.stderr)
        for u in updates[:10]:
            print(f"  id={u[0]} pair={u[2]} pnl={u[3]} → {u[1]}", file=sys.stderr)
        return

    with sqlite3.connect(args.db) as c:
        for trade_id, reason, _pair, _pnl in updates:
            c.execute(
                "UPDATE personal_trades SET close_reason = ? WHERE id = ?",
                (reason, trade_id),
            )
    print(f"Updated {len(updates)} rows", file=sys.stderr)


if __name__ == "__main__":
    main()
