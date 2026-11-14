"""Audit temporel : PnL par heure UTC, jour de semaine, et session de marché.

## Pourquoi

Le script audit_compte_reel_pnl_matcher.py (PR #45) a agrégé par jour
calendaire et par paire. Ce v3 fouille plus profond : à quelles HEURES
de la journée et quels JOURS de la semaine les trades ont gagné/perdu ?

Hypothèses à tester :
- Les pertes sont concentrées sur une session (ex: Londres ouverture,
  NY after-hours, Asie illiquide) ?
- Vendredi soir pré-close = pires trades ?
- Weekend / holiday gaps mal gérés ?

## Usage

    docker exec scalping-radar python -m scripts.audit_temporal_patterns \\
        > /tmp/audit_temporal.json 2> /tmp/audit_temporal.stderr
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

import httpx


BRIDGE_URL = os.getenv("MT5_BRIDGE_LIVE_URL", "").rstrip("/")
API_KEY = os.getenv("MT5_BRIDGE_LIVE_API_KEY", "")
EUR_USD_RATE = float(os.getenv("EUR_USD_FIXED", "1.07"))


DAYS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def _session_label(hour_utc: int) -> str:
    """Session de marché approximative basée sur l'heure UTC.

    Sydney  : 22h-07h UTC (ouverture Sydney/Tokyo)
    Tokyo   : 00h-09h UTC
    Londres : 07h-16h UTC
    NY      : 12h-21h UTC
    Overlap principal Londres/NY : 12h-16h UTC (liquidité max)
    """
    if 12 <= hour_utc < 16:
        return "overlap_londres_ny"
    if 7 <= hour_utc < 12:
        return "londres_matin"
    if 16 <= hour_utc < 21:
        return "ny_apres_londres"
    if 21 <= hour_utc or hour_utc < 7:
        return "asie_illiquide"
    return "autre"


def _fetch_all() -> list[dict]:
    if not BRIDGE_URL or not API_KEY:
        print("ERREUR : env vars manquantes", file=sys.stderr)
        sys.exit(2)
    headers = {"X-API-Key": API_KEY}
    all_orders: list[dict] = []
    since_id = 0
    page = 0
    with httpx.Client(timeout=30.0) as c:
        while True:
            page += 1
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
            print(f"  page {page}: +{len(orders)}", file=sys.stderr)
            all_orders.extend(orders)
            mid = max((int(o.get("id") or 0) for o in orders), default=since_id)
            if mid <= since_id:
                break
            since_id = mid
            if len(orders) < 500:
                break
    return all_orders


def _is_our_open(o: dict) -> bool:
    c = (o.get("client_comment") or "").lower()
    d = (o.get("direction") or "").lower()
    return "scalping-radar" in c and d in ("buy", "sell")


def _is_close(o: dict) -> bool:
    d = (o.get("direction") or "").lower()
    return d in ("close-buy", "close-sell") or o.get("pnl") is not None


def _get_time(o: dict) -> datetime | None:
    v = o.get("created_at")
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v))
    except ValueError:
        return None


def main() -> int:
    print(f"Fetch /audit sur {BRIDGE_URL}", file=sys.stderr)
    orders = _fetch_all()

    # Index des closes par ticket pour matching
    opens_by_ticket: dict[int, dict] = {}
    for o in orders:
        if _is_our_open(o):
            try:
                tk = int(o.get("ticket") or 0)
            except (TypeError, ValueError):
                tk = 0
            if tk:
                opens_by_ticket[tk] = o

    # Aggrégations temporelles basées sur le close_time
    by_hour_pnl_usd: defaultdict[int, float] = defaultdict(float)
    by_hour_count: defaultdict[int, int] = defaultdict(int)
    by_weekday_pnl_usd: defaultdict[int, float] = defaultdict(float)
    by_weekday_count: defaultdict[int, int] = defaultdict(int)
    by_session_pnl_usd: defaultdict[str, float] = defaultdict(float)
    by_session_count: defaultdict[str, int] = defaultdict(int)

    matched = 0
    for o in orders:
        if not _is_close(o):
            continue
        try:
            tk = int(o.get("ticket") or 0)
        except (TypeError, ValueError):
            tk = 0
        if tk not in opens_by_ticket:
            continue
        matched += 1
        pnl = 0.0
        p = o.get("pnl")
        if p is not None:
            try:
                pnl = float(p)
            except (TypeError, ValueError):
                pass

        t = _get_time(o)
        if t is None:
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        t_utc = t.astimezone(timezone.utc)

        h = t_utc.hour
        wd = t_utc.weekday()
        session = _session_label(h)

        by_hour_pnl_usd[h] += pnl
        by_hour_count[h] += 1
        by_weekday_pnl_usd[wd] += pnl
        by_weekday_count[wd] += 1
        by_session_pnl_usd[session] += pnl
        by_session_count[session] += 1

    report = {
        "total_audit_entries": len(orders),
        "matched_close_events": matched,
        "by_hour_utc": [
            {
                "hour_utc": h,
                "trades": by_hour_count.get(h, 0),
                "pnl_usd": round(by_hour_pnl_usd.get(h, 0), 2),
                "pnl_eur": round(by_hour_pnl_usd.get(h, 0) / EUR_USD_RATE, 2),
                "pnl_per_trade_usd": round(
                    by_hour_pnl_usd.get(h, 0) / by_hour_count[h], 3,
                ) if by_hour_count.get(h) else 0.0,
            }
            for h in range(24)
        ],
        "by_weekday_utc": [
            {
                "day": DAYS_FR[wd],
                "trades": by_weekday_count.get(wd, 0),
                "pnl_eur": round(by_weekday_pnl_usd.get(wd, 0) / EUR_USD_RATE, 2),
                "pnl_per_trade_usd": round(
                    by_weekday_pnl_usd.get(wd, 0) / by_weekday_count[wd], 3,
                ) if by_weekday_count.get(wd) else 0.0,
            }
            for wd in range(7)
        ],
        "by_session": {
            session: {
                "trades": by_session_count[session],
                "pnl_usd": round(by_session_pnl_usd[session], 2),
                "pnl_eur": round(by_session_pnl_usd[session] / EUR_USD_RATE, 2),
                "pnl_per_trade_usd": round(
                    by_session_pnl_usd[session] / by_session_count[session], 3,
                ) if by_session_count[session] else 0.0,
            }
            for session in sorted(by_session_count)
        },
    }

    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    print(
        f"\n→ Matched : {matched} closes sur {len(orders)} entries",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
