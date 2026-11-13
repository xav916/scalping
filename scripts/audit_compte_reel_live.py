"""Audit historique des trades envoyés sur le compte RÉEL IC Markets.

## Pourquoi

Le 2026-11-13, on a découvert qu'un pipeline legacy
(scheduler.py:509/882 → mt5_bridge.send_setups → resolve_destinations)
routait des trades XAU/USD vers le bridge port 8788 = compte RÉEL
(login 13137475, serveur ICMarketsEU-MT5-5). Flag ``MT5_BRIDGE_LIVE_ENABLED``
était actif depuis au moins 2026-08-28 (`sltp_guard_activated_at`).

Ce script interroge ``/audit`` sur le bridge LIVE pour reconstituer
l'historique complet des trades envoyés sur le compte réel, en remontant
depuis l'id 0.

## Usage

À lancer **dans le container** (où les env vars MT5_BRIDGE_LIVE_* sont
disponibles) :

    docker exec scalping-radar python -m scripts.audit_compte_reel_live

Ou en standalone (nécessite ``MT5_BRIDGE_LIVE_URL`` + ``MT5_BRIDGE_LIVE_API_KEY``
dans l'env) :

    export MT5_BRIDGE_LIVE_URL=http://100.74.160.72:8788
    export MT5_BRIDGE_LIVE_API_KEY=<clé>
    python scripts/audit_compte_reel_live.py

## Sortie

- Nombre total de deals sur le compte réel
- Fenêtre temporelle (premier → dernier)
- Breakdown par paire, par direction, par close_reason
- P&L cumulé en EUR (approximation via EUR_USD_RATE=1.07)
- Par jour calendaire : volume + P&L réalisé
- Top 10 des pires trades (pour mesurer la queue de perte)
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

import httpx


BRIDGE_URL = os.getenv("MT5_BRIDGE_LIVE_URL", "").rstrip("/")
API_KEY = os.getenv("MT5_BRIDGE_LIVE_API_KEY", "")
EUR_USD_RATE = float(os.getenv("EUR_USD_FIXED", "1.07"))


def _fetch_all_deals() -> list[dict]:
    """Pagine /audit?since_id=X&limit=100 jusqu'à épuisement."""
    if not BRIDGE_URL or not API_KEY:
        print(
            "ERREUR : MT5_BRIDGE_LIVE_URL et MT5_BRIDGE_LIVE_API_KEY requis.",
            file=sys.stderr,
        )
        sys.exit(2)

    headers = {"X-API-Key": API_KEY}
    all_deals: list[dict] = []
    since_id = 0
    page_num = 0
    with httpx.Client(timeout=30.0) as client:
        while True:
            page_num += 1
            url = f"{BRIDGE_URL}/audit?since_id={since_id}&limit=500"
            r = client.get(url, headers=headers)
            if r.status_code != 200:
                print(
                    f"ERREUR HTTP {r.status_code} page {page_num} : {r.text[:200]}",
                    file=sys.stderr,
                )
                break
            data = r.json()
            entries = data.get("entries") or data.get("deals") or data.get(
                "audit") or []
            if not entries:
                break
            print(
                f"  page {page_num}: +{len(entries)} entries "
                f"(since_id={since_id})",
                file=sys.stderr,
            )
            all_deals.extend(entries)
            # Progression du curseur
            max_id = max(
                (int(e.get("id") or e.get("deal_id") or e.get("ticket") or 0)
                 for e in entries),
                default=since_id,
            )
            if max_id <= since_id:
                break
            since_id = max_id
            if len(entries) < 500:
                break
    return all_deals


def _is_from_scalping_system(deal: dict) -> bool:
    comment = (deal.get("comment") or "").lower()
    return "scalping-radar" in comment


def _resolve_pair(deal: dict) -> str:
    return (deal.get("symbol") or deal.get("pair") or "?").upper()


def _resolve_direction(deal: dict) -> str:
    t = (deal.get("type") or deal.get("direction") or "").lower()
    if t in ("buy", "0"):
        return "buy"
    if t in ("sell", "1"):
        return "sell"
    return t or "?"


def _resolve_profit_usd(deal: dict) -> float:
    for k in ("profit_usd", "profit", "pnl", "pnl_usd"):
        v = deal.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return 0.0


def _resolve_time(deal: dict) -> datetime | None:
    for k in ("time", "close_time", "exit_time", "time_utc", "timestamp"):
        v = deal.get(k)
        if not v:
            continue
        try:
            return datetime.fromisoformat(str(v))
        except ValueError:
            try:
                return datetime.fromtimestamp(float(v), tz=timezone.utc)
            except (TypeError, ValueError):
                pass
    return None


def _resolve_close_reason(deal: dict) -> str:
    return str(
        deal.get("close_reason") or deal.get("reason") or "?"
    ).lower()


def _summarize(deals: list[dict]) -> dict:
    scalping_deals = [d for d in deals if _is_from_scalping_system(d)]
    other_deals = [d for d in deals if not _is_from_scalping_system(d)]

    by_pair = Counter(_resolve_pair(d) for d in scalping_deals)
    by_direction = Counter(_resolve_direction(d) for d in scalping_deals)
    by_reason = Counter(_resolve_close_reason(d) for d in scalping_deals)

    by_day_pnl: dict[str, float] = defaultdict(float)
    by_day_count: dict[str, int] = defaultdict(int)
    times = []
    total_pnl_usd = 0.0
    all_pnl = []
    for d in scalping_deals:
        p = _resolve_profit_usd(d)
        total_pnl_usd += p
        all_pnl.append((p, d))
        t = _resolve_time(d)
        if t:
            times.append(t)
            day = t.date().isoformat()
            by_day_pnl[day] += p
            by_day_count[day] += 1

    all_pnl.sort(key=lambda x: x[0])
    pires = all_pnl[:10]

    first = min(times) if times else None
    last = max(times) if times else None

    return {
        "total_deals_bridge": len(deals),
        "total_deals_scalping_system": len(scalping_deals),
        "total_deals_other": len(other_deals),
        "first_deal_utc": first.isoformat() if first else None,
        "last_deal_utc": last.isoformat() if last else None,
        "by_pair": dict(by_pair.most_common()),
        "by_direction": dict(by_direction.most_common()),
        "by_close_reason": dict(by_reason.most_common()),
        "pnl_usd_total": round(total_pnl_usd, 2),
        "pnl_eur_total": round(total_pnl_usd / EUR_USD_RATE, 2),
        "by_day_pnl_eur": {
            d: round(v / EUR_USD_RATE, 2)
            for d, v in sorted(by_day_pnl.items())
        },
        "by_day_count": {d: v for d, v in sorted(by_day_count.items())},
        "pires_trades": [
            {
                "ticket": p[1].get("ticket") or p[1].get("id"),
                "pair": _resolve_pair(p[1]),
                "direction": _resolve_direction(p[1]),
                "time": (_resolve_time(p[1]) or "").isoformat()
                        if _resolve_time(p[1]) else None,
                "pnl_usd": round(p[0], 2),
            }
            for p in pires
        ],
    }


def main() -> int:
    print(f"Fetch tous les deals depuis {BRIDGE_URL}/audit", file=sys.stderr)
    deals = _fetch_all_deals()
    print(f"\nTotal brut : {len(deals)} deals", file=sys.stderr)

    summary = _summarize(deals)
    print(json.dumps(summary, indent=2, ensure_ascii=False))

    pnl = summary["pnl_eur_total"]
    nb = summary["total_deals_scalping_system"]
    print(
        f"\n→ {nb} trades signés 'scalping-radar-*' sur le compte RÉEL, "
        f"PnL cumulé {pnl:+.2f} EUR",
        file=sys.stderr,
    )
    if summary["first_deal_utc"]:
        print(
            f"→ Fenêtre : {summary['first_deal_utc']} "
            f"→ {summary['last_deal_utc']}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
