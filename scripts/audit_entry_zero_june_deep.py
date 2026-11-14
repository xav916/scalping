"""Diagnostic approfondi du pic de bugs entry=0.0 en juin 2026.

## Contexte

audit_entry_zero_bug.py (PR #46) a révélé **190 trades entry=0/null en
juin 2026** sur 217 cas totaux (87% du bug concentré sur 1 mois).
L'impact PnL est modeste pour juin (crypto surtout, neutre), mais le
pattern suggère un bug systémique côté bridge Windows pendant cette
période.

## Ce que ce script fait

1. Fetch tous les deals /audit
2. Isole les ouvertures avec entry=0 en juin 2026
3. Breakdown **par jour calendaire** : combien chaque jour ?
4. Breakdown **par heure UTC** : concentration sur une session ?
5. Breakdown **par paire** : crypto dominant ou autre ?
6. Pour les 5 jours les plus affectés, liste les tickets avec timestamp
   précis → permet de corréler avec un éventuel incident Lightsail /
   Gateway / MT5 terminal cette période

## Usage

    docker exec scalping-radar python -m scripts.audit_entry_zero_june_deep \\
        > /tmp/audit_june_deep.json 2> /tmp/audit_june_deep.stderr
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime

import httpx


BRIDGE_URL = os.getenv("MT5_BRIDGE_LIVE_URL", "").rstrip("/")
API_KEY = os.getenv("MT5_BRIDGE_LIVE_API_KEY", "")


def _fetch_all() -> list[dict]:
    if not BRIDGE_URL or not API_KEY:
        print("ERREUR : env vars manquantes", file=sys.stderr)
        sys.exit(2)
    headers = {"X-API-Key": API_KEY}
    all_orders: list[dict] = []
    since_id = 0
    with httpx.Client(timeout=30.0) as c:
        while True:
            r = c.get(
                f"{BRIDGE_URL}/audit?since_id={since_id}&limit=500",
                headers=headers,
            )
            if r.status_code != 200:
                break
            data = r.json()
            orders = data.get("orders") or []
            if not orders:
                break
            all_orders.extend(orders)
            mid = max((int(o.get("id") or 0) for o in orders), default=since_id)
            if mid <= since_id:
                break
            since_id = mid
            if len(orders) < 500:
                break
    return all_orders


def main() -> int:
    print(f"Fetch /audit sur {BRIDGE_URL}", file=sys.stderr)
    orders = _fetch_all()
    print(f"Total : {len(orders)} entries", file=sys.stderr)

    # Isoler les ouvertures scalping-radar avec entry buggé en JUIN 2026
    june_bugged = []
    for o in orders:
        comment = (o.get("client_comment") or "").lower()
        if "scalping-radar" not in comment:
            continue
        direction = (o.get("direction") or "").lower()
        if direction not in ("buy", "sell"):
            continue
        entry = o.get("entry")
        if entry is not None:
            try:
                if float(entry) != 0.0:
                    continue
            except (TypeError, ValueError):
                pass
        # Check mois
        ts = o.get("created_at") or ""
        try:
            dt = datetime.fromisoformat(ts)
        except ValueError:
            continue
        if not (dt.year == 2026 and dt.month == 6):
            continue
        june_bugged.append((o, dt))

    print(
        f"\nOuvertures buggées juin 2026 : {len(june_bugged)}",
        file=sys.stderr,
    )

    by_day: Counter = Counter()
    by_hour: Counter = Counter()
    by_pair: Counter = Counter()
    by_fill_source: Counter = Counter()
    by_retcode: Counter = Counter()
    by_message_short: Counter = Counter()
    details_by_day: defaultdict[str, list] = defaultdict(list)

    for o, dt in june_bugged:
        day = dt.date().isoformat()
        by_day[day] += 1
        by_hour[dt.hour] += 1
        by_pair[(o.get("pair") or "?").upper()] += 1
        by_fill_source[o.get("fill_source") or "null"] += 1
        by_retcode[o.get("retcode")] += 1
        msg = (o.get("message") or "")[:60]
        by_message_short[msg] += 1
        details_by_day[day].append({
            "id": o.get("id"),
            "ticket": o.get("ticket"),
            "pair": o.get("pair"),
            "direction": o.get("direction"),
            "lots": o.get("lots"),
            "time_utc": dt.isoformat(),
            "entry": o.get("entry"),
            "fill_price": o.get("fill_price"),
            "fill_source": o.get("fill_source"),
            "message": o.get("message"),
            "retcode": o.get("retcode"),
        })

    # Top 5 jours les plus affectés : sort details par timestamp
    top5_days = [d for d, _ in by_day.most_common(5)]
    samples_top5 = {
        d: sorted(details_by_day[d], key=lambda x: x["time_utc"])[:15]
        for d in top5_days
    }

    report = {
        "total_bugged_june": len(june_bugged),
        "by_day": dict(sorted(by_day.items())),
        "by_hour_utc": dict(sorted(by_hour.items())),
        "by_pair": dict(by_pair.most_common()),
        "by_fill_source": dict(by_fill_source.most_common()),
        "by_retcode": {str(k): v for k, v in by_retcode.most_common()},
        "by_message_short": dict(by_message_short.most_common(10)),
        "top_5_jours": {
            d: {
                "count": by_day[d],
                "first_15_tickets": samples_top5[d],
            } for d in top5_days
        },
    }
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
