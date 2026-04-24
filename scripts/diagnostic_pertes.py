"""Diagnostic des trades CLOSED post-fix pipeline pour identifier les
buckets qui saignent.

Usage (depuis le container) :
    python scripts/diagnostic_pertes.py

Ventile les trades CLOSED depuis 2026-04-20T21:00:00 (cutoff post-fix
pipeline, cf. reference_scalping_paths.md) par direction, asset class,
pair, pattern, confidence, session, close_reason et auto/manual.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import datetime, timezone


CUTOFF = "2026-04-20T21:00:00"
DB_PATH = "/app/data/trades.db"


def parse_ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def session_bucket(dt):
    if not dt:
        return "unknown"
    h = dt.astimezone(timezone.utc).hour
    if 0 <= h < 7:
        return "Asia (00-07 UTC)"
    if 7 <= h < 12:
        return "London (07-12 UTC)"
    if 12 <= h < 17:
        return "NY overlap (12-17)"
    if 17 <= h < 21:
        return "NY pm (17-21)"
    return "late (21-00)"


def conf_bucket(v):
    if v is None:
        return "unknown"
    if v < 60:
        return "55-60"
    if v < 70:
        return "60-70"
    if v < 80:
        return "70-80"
    if v < 90:
        return "80-90"
    return "90+"


def asset_class(pair):
    if pair in ("XAU/USD", "XAG/USD"):
        return "metal"
    if pair in ("BTC/USD", "ETH/USD"):
        return "crypto"
    if pair in ("SPX", "NDX"):
        return "equity_index"
    if pair in ("WTI/USD",):
        return "energy"
    return "forex"


def stats(rows_subset):
    n = len(rows_subset)
    if not n:
        return None
    pnls = [r[4] for r in rows_subset if r[4] is not None]
    total = sum(pnls)
    avg = total / n if n else 0
    wins = sum(1 for p in pnls if p > 0)
    wr = wins * 100.0 / n
    return {"n": n, "total": total, "avg": avg, "wr": wr}


def print_bucket(title, rows, key_fn, sort_by="total_asc"):
    buckets = defaultdict(list)
    for r in rows:
        k = key_fn(r)
        if k is not None:
            buckets[k].append(r)
    print(f"\n=== {title} ===")
    header = f"{'bucket':<24}{'n':>5}{'winrate%':>10}{'avg_pnl':>10}{'total_pnl':>12}"
    print(header)
    keys_sorted = sorted(buckets.keys(), key=lambda x: stats(buckets[x])["total"])
    if sort_by == "total_desc":
        keys_sorted = keys_sorted[::-1]
    for k in keys_sorted:
        s = stats(buckets[k])
        print(f"{str(k):<24}{s['n']:>5}{s['wr']:>9.1f}%{s['avg']:>10.2f}{s['total']:>12.2f}")


def main():
    c = sqlite3.connect(DB_PATH)
    rows = c.execute(
        """
        SELECT pair, direction, signal_pattern, signal_confidence, pnl,
               created_at, closed_at, close_reason, is_auto,
               checklist_passed, context_macro
        FROM personal_trades
        WHERE status = 'CLOSED'
          AND created_at >= ?
          AND pnl IS NOT NULL
        ORDER BY created_at
        """,
        (CUTOFF,),
    ).fetchall()

    print(f"=== GLOBAL (CLOSED depuis {CUTOFF}) ===")
    g = stats(rows)
    if not g:
        print("Aucun trade CLOSED trouvé. Verifier le cutoff.")
        return
    print(
        f"trades={g['n']} | winrate={g['wr']:.1f}% | "
        f"avg_pnl={g['avg']:+.2f}€ | total={g['total']:+.2f}€"
    )

    print_bucket("Direction", rows, lambda r: r[1])
    print_bucket("Asset class", rows, lambda r: asset_class(r[0]))
    print_bucket("Pair", rows, lambda r: r[0])
    print_bucket("Pattern", rows, lambda r: r[2] or "none")
    print_bucket("Confidence bucket", rows, lambda r: conf_bucket(r[3]))
    print_bucket("Session d'entrée", rows, lambda r: session_bucket(parse_ts(r[5])))
    print_bucket("Close reason", rows, lambda r: r[7] or "none")
    print_bucket("Auto vs manual", rows, lambda r: "AUTO" if r[8] else "MANUAL")

    # Cross : asset class x session
    print("\n=== CROSS : asset_class x session (total PnL) ===")
    cross = defaultdict(lambda: defaultdict(list))
    for r in rows:
        ac = asset_class(r[0])
        sess = session_bucket(parse_ts(r[5]))
        cross[ac][sess].append(r)
    sessions_order = [
        "Asia (00-07 UTC)", "London (07-12 UTC)", "NY overlap (12-17)",
        "NY pm (17-21)", "late (21-00)",
    ]
    header = f"{'asset_class':<16}" + "".join(f"{s[:12]:>14}" for s in sessions_order)
    print(header)
    for ac in sorted(cross.keys()):
        line = f"{ac:<16}"
        for sess in sessions_order:
            rs = cross[ac].get(sess, [])
            if not rs:
                line += f"{'-':>14}"
            else:
                s = stats(rs)
                line += f"{s['total']:>+9.2f}/{s['n']:<3}"
        print(line)


if __name__ == "__main__":
    main()
