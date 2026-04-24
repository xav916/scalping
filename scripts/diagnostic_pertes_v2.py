"""Diagnostic v2 — angles supplémentaires :
- Duration bucket (<5min / 5-30 / 30-120 / 2h+)
- Slippage pips bucket
- Macro context multiplier
- Cross direction × session
- Cumul PnL par jour (évolution temporelle)
- Gain/perte moyens par win/loss (edge statistique réel)
"""

from __future__ import annotations

import json
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
        return "Asia"
    if 7 <= h < 12:
        return "London"
    if 12 <= h < 17:
        return "NY_overlap"
    if 17 <= h < 21:
        return "NY_pm"
    return "late"


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


def duration_bucket(start, end):
    if not start or not end:
        return "unknown"
    mins = (end - start).total_seconds() / 60
    if mins < 5:
        return "<5min"
    if mins < 30:
        return "5-30min"
    if mins < 120:
        return "30-120min"
    if mins < 480:
        return "2-8h"
    return "8h+"


def slippage_bucket(v):
    if v is None:
        return "unknown"
    if v <= -3:
        return "severe_neg (<=-3)"
    if v <= -1:
        return "neg (-3 to -1)"
    if v < 1:
        return "near_0 (-1 to 1)"
    if v < 3:
        return "pos (1-3)"
    return "high_pos (3+)"


def macro_multiplier(ctx_json):
    if not ctx_json:
        return "none"
    try:
        ctx = json.loads(ctx_json)
        m = ctx.get("overall_multiplier") or ctx.get("multiplier")
        if m is None:
            return "unknown"
        if m < 0.6:
            return "<0.6 (very_hostile)"
        if m < 0.85:
            return "0.6-0.85 (hostile)"
        if m < 1.0:
            return "0.85-1.0 (slight_neg)"
        if m < 1.15:
            return "1.0-1.15 (slight_pos)"
        return "1.15+ (favorable)"
    except Exception:
        return "parse_err"


def stats(rows):
    n = len(rows)
    if not n:
        return None
    pnls = [r["pnl"] for r in rows if r["pnl"] is not None]
    total = sum(pnls)
    avg = total / n
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = sum(losses) / len(losses) if losses else 0
    wr = len(wins) * 100.0 / n
    return {
        "n": n, "total": total, "avg": avg, "wr": wr,
        "avg_win": avg_win, "avg_loss": avg_loss,
    }


def print_bucket(title, rows, key_fn):
    buckets = defaultdict(list)
    for r in rows:
        k = key_fn(r)
        if k is not None:
            buckets[k].append(r)
    print(f"\n=== {title} ===")
    print(f"{'bucket':<26}{'n':>5}{'wr%':>7}{'avg_W':>9}{'avg_L':>9}{'avg_pnl':>10}{'total':>11}")
    keys_sorted = sorted(buckets.keys(), key=lambda x: stats(buckets[x])["total"])
    for k in keys_sorted:
        s = stats(buckets[k])
        print(
            f"{str(k):<26}{s['n']:>5}{s['wr']:>6.1f}%"
            f"{s['avg_win']:>+9.2f}{s['avg_loss']:>+9.2f}"
            f"{s['avg']:>+10.2f}{s['total']:>+11.2f}"
        )


def main():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    rows = c.execute(
        """
        SELECT pair, direction, signal_pattern, signal_confidence, pnl,
               created_at, closed_at, close_reason, is_auto,
               slippage_pips, context_macro
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
        print("Aucun trade CLOSED.")
        return
    print(
        f"n={g['n']} | winrate={g['wr']:.1f}% | "
        f"avg_win={g['avg_win']:+.2f}€ | avg_loss={g['avg_loss']:+.2f}€ | "
        f"profit_factor={abs(g['avg_win']*g['wr']/(g['avg_loss']*(100-g['wr']))):.2f} | "
        f"total={g['total']:+.2f}€"
    )

    # Break-even winrate nécessaire
    if g["avg_loss"] != 0:
        be_wr = abs(g["avg_loss"]) * 100 / (g["avg_win"] + abs(g["avg_loss"]))
        print(f"break-even winrate nécessaire avec les avg W/L actuels : {be_wr:.1f}%")
        print(f"gap au break-even : {g['wr'] - be_wr:+.1f} pts")

    # Duration bucket
    print_bucket(
        "Duration entre entry et close",
        rows,
        lambda r: duration_bucket(parse_ts(r["created_at"]), parse_ts(r["closed_at"])),
    )

    # Slippage bucket
    print_bucket("Slippage pips (au fill)", rows, lambda r: slippage_bucket(r["slippage_pips"]))

    # Macro multiplier
    print_bucket("Macro multiplier au moment du trade", rows, lambda r: macro_multiplier(r["context_macro"]))

    # Cross direction × session
    print("\n=== CROSS direction × session (total PnL / n) ===")
    cross = defaultdict(lambda: defaultdict(list))
    for r in rows:
        d = r["direction"]
        sess = session_bucket(parse_ts(r["created_at"]))
        cross[d][sess].append(r)
    sessions = ["Asia", "London", "NY_overlap", "NY_pm", "late"]
    header = f"{'dir':<6}" + "".join(f"{s:>13}" for s in sessions)
    print(header)
    for d in sorted(cross.keys()):
        line = f"{d:<6}"
        for sess in sessions:
            rs = cross[d].get(sess, [])
            if not rs:
                line += f"{'-':>13}"
            else:
                s = stats(rs)
                line += f"{s['total']:>+8.1f}/{s['n']:<3}"
        print(line)

    # Temporal evolution (daily cumulative PnL)
    print("\n=== Evolution PnL cumulé par jour ===")
    daily = defaultdict(float)
    daily_n = defaultdict(int)
    for r in rows:
        dt = parse_ts(r["closed_at"]) or parse_ts(r["created_at"])
        if not dt:
            continue
        day = dt.astimezone(timezone.utc).date().isoformat()
        daily[day] += r["pnl"]
        daily_n[day] += 1
    cumul = 0.0
    print(f"{'date':<12}{'n':>5}{'daily_pnl':>12}{'cumul':>12}")
    for day in sorted(daily.keys()):
        cumul += daily[day]
        print(f"{day:<12}{daily_n[day]:>5}{daily[day]:>+12.2f}{cumul:>+12.2f}")

    # Ratio gain/loss par bucket de confidence
    print("\n=== Profit factor par confidence bucket ===")
    conf_buckets = defaultdict(list)
    for r in rows:
        conf = r["signal_confidence"] or 0
        if conf < 60:
            b = "55-60"
        elif conf < 70:
            b = "60-70"
        elif conf < 80:
            b = "70-80"
        elif conf < 90:
            b = "80-90"
        else:
            b = "90+"
        conf_buckets[b].append(r)
    print(f"{'bucket':<10}{'n':>5}{'wr%':>7}{'avg_W':>9}{'avg_L':>9}{'PF':>7}")
    for b in ["55-60", "60-70", "70-80", "80-90", "90+"]:
        rs = conf_buckets.get(b, [])
        if not rs:
            continue
        s = stats(rs)
        pf = (
            abs(s["avg_win"] * s["wr"] / (s["avg_loss"] * (100 - s["wr"])))
            if s["avg_loss"] and s["wr"] < 100
            else float("inf")
        )
        print(f"{b:<10}{s['n']:>5}{s['wr']:>6.1f}%{s['avg_win']:>+9.2f}{s['avg_loss']:>+9.2f}{pf:>7.2f}")


if __name__ == "__main__":
    main()
