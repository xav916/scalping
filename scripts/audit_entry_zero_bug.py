"""Investigue le bug ``entry=0.0`` du bridge live.

## Contexte

Lors de l'audit du 2026-11-13 (scripts/audit_compte_reel_pnl_matcher.py),
le pire trade individuel sur le compte réel était :

    #1353960866 XAU/USD sell entry=0.0 exit=4405.67 pnl=-265.11 USD
    2026-08-11

Entry à 0.0 → le bridge a enregistré la position avec un prix d'entrée
manquant. Perte individuelle plus élevée que les 10 pires jours cumulés
de mai. C'est un trou de qualité de données qui mérite investigation.

## Ce que ce script fait

1. Fetch TOUS les deals /audit du bridge LIVE (port 8788)
2. Isole les ouvertures scalping-radar avec entry = 0.0 OU null
3. Pour chaque cas, sort :
   - ticket, pair, direction, lots, created_at
   - fill_price, fill_source
   - client_comment, message, retcode
4. Agrégations : combien par paire, combien par mois, PnL cumulé
5. Matche les fermetures correspondantes (via ticket) pour quantifier
   l'impact en argent sur ces trades corrompus

## Usage

    docker exec scalping-radar python -m scripts.audit_entry_zero_bug \\
        > /tmp/audit_entry0.json 2> /tmp/audit_entry0.stderr
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
    comment = (o.get("client_comment") or "").lower()
    direction = (o.get("direction") or "").lower()
    return "scalping-radar" in comment and direction in ("buy", "sell")


def _is_close(o: dict) -> bool:
    direction = (o.get("direction") or "").lower()
    if direction in ("close-buy", "close-sell"):
        return True
    if o.get("pnl") is not None:
        return True
    return False


def _entry_is_bugged(o: dict) -> bool:
    e = o.get("entry")
    if e is None:
        return True
    try:
        return float(e) == 0.0
    except (TypeError, ValueError):
        return True


def _get_pnl(o: dict) -> float:
    v = o.get("pnl")
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _get_month(o: dict) -> str:
    v = o.get("created_at") or ""
    if not v:
        return "?"
    try:
        dt = datetime.fromisoformat(str(v))
        return dt.strftime("%Y-%m")
    except ValueError:
        return "?"


def main() -> int:
    print(f"Fetch /audit sur {BRIDGE_URL}", file=sys.stderr)
    orders = _fetch_all()
    print(f"\nTotal brut : {len(orders)} entries", file=sys.stderr)

    # Isoler les ouvertures scalping avec entry bugged
    bugged_opens = [
        o for o in orders
        if _is_our_open(o) and _entry_is_bugged(o)
    ]
    scalping_opens_total = sum(1 for o in orders if _is_our_open(o))

    print(
        f"\nOuvertures scalping-radar avec entry=0/null : "
        f"{len(bugged_opens)} / {scalping_opens_total}",
        file=sys.stderr,
    )

    if not bugged_opens:
        print(json.dumps({
            "bugged_count": 0,
            "total_scalping_opens": scalping_opens_total,
            "message": "Pas d'ouvertures corrompues détectées.",
        }, indent=2))
        return 0

    # Index des fermetures par ticket
    closes_by_ticket: dict[int, dict] = {}
    for o in orders:
        if _is_close(o):
            try:
                tk = int(o.get("ticket") or 0)
            except (TypeError, ValueError):
                tk = 0
            if tk:
                closes_by_ticket[tk] = o

    # Matcher les buggés avec leur fermeture
    matched_bugged = []
    total_pnl_usd = 0.0
    by_month: Counter = Counter()
    by_pair: Counter = Counter()
    by_pair_pnl: defaultdict[str, float] = defaultdict(float)
    by_fill_source: Counter = Counter()

    details = []
    for op in bugged_opens:
        try:
            tk = int(op.get("ticket") or 0)
        except (TypeError, ValueError):
            tk = 0
        cl = closes_by_ticket.get(tk)
        pnl = _get_pnl(cl) if cl else 0.0
        total_pnl_usd += pnl
        by_month[_get_month(op)] += 1
        pair = (op.get("pair") or "?").upper()
        by_pair[pair] += 1
        by_pair_pnl[pair] += pnl
        by_fill_source[op.get("fill_source") or "null"] += 1
        if cl:
            matched_bugged.append((op, cl))

        details.append({
            "id": op.get("id"),
            "ticket": tk,
            "pair": pair,
            "direction": op.get("direction"),
            "lots": op.get("lots"),
            "created_at": op.get("created_at"),
            "entry_raw": op.get("entry"),
            "entry_requested": op.get("entry_requested"),
            "fill_price": op.get("fill_price"),
            "fill_source": op.get("fill_source"),
            "client_comment": op.get("client_comment"),
            "message": op.get("message"),
            "retcode": op.get("retcode"),
            "sl": op.get("sl"),
            "tp": op.get("tp"),
            "matched_close_pnl_usd": round(pnl, 2) if cl else None,
            "matched_close_exit": (cl.get("exit_price") or cl.get("price"))
                                  if cl else None,
        })

    report = {
        "bugged_count": len(bugged_opens),
        "bugged_matched_with_close": len(matched_bugged),
        "total_scalping_opens": scalping_opens_total,
        "pct_scalping_bugged": round(
            len(bugged_opens) * 100.0 / max(scalping_opens_total, 1), 2,
        ),
        "pnl_usd_total_from_bugged": round(total_pnl_usd, 2),
        "pnl_eur_total_from_bugged": round(total_pnl_usd / EUR_USD_RATE, 2),
        "by_month": dict(by_month.most_common()),
        "by_pair": dict(by_pair.most_common()),
        "by_pair_pnl_usd": {
            p: round(v, 2) for p, v in sorted(
                by_pair_pnl.items(), key=lambda x: x[1],
            )
        },
        "by_fill_source": dict(by_fill_source.most_common()),
        "details": details,
    }

    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))

    print(
        f"\n→ {len(bugged_opens)} trades avec entry=0/null, "
        f"PnL cumulé {report['pnl_eur_total_from_bugged']:+.2f} EUR",
        file=sys.stderr,
    )
    print(
        f"→ Distribution par source de fill : {dict(by_fill_source)}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
