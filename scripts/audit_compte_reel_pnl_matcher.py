"""Audit v2 : matche ouvertures ↔ fermetures par ticket pour reconstruire le PnL.

Le script v1 (audit_compte_reel_live.py) reporte 0.00 EUR car le champ ``pnl``
est null sur les événements d'ouverture dans /audit. Les fermetures
(direction = close-buy, close-sell) portent le ``pnl``, mais ne sont pas
signées par le client_comment ``scalping-radar-*`` (elles ont souvent
kill-switch, tp, sl, ou aucun comment).

Ce script v2 :

1. Fetch TOUS les deals /audit (ouvertures + fermetures)
2. Indexe les ouvertures scalping-radar par ``ticket`` MT5
3. Parcourt les fermetures et matche par ticket avec une ouverture scalping
4. Agrège le PnL réalisé par jour, par paire, et total

## Hypothèses sur le shape des fermetures

À vérifier au premier run (le script print un sample de close events) :
- direction : "close-buy" | "close-sell"
- ticket : SAME que l'ouverture (ticket MT5 de l'order) OU un autre
- pnl : ``float`` (peut être négatif pour une perte)
- close_reason : "tp" | "sl" | "manual" | "time_stop" | ...

## Usage

    docker exec scalping-radar python -m scripts.audit_compte_reel_pnl_matcher \\
        > /tmp/audit_pnl.json 2> /tmp/audit_pnl.stderr
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
        print(
            "ERREUR : MT5_BRIDGE_LIVE_URL et MT5_BRIDGE_LIVE_API_KEY requis.",
            file=sys.stderr,
        )
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
                print(f"HTTP {r.status_code} page {page}: {r.text[:200]}",
                      file=sys.stderr)
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


def _get_pair(o: dict) -> str:
    return (o.get("pair") or o.get("symbol") or "?").upper()


def _get_dir(o: dict) -> str:
    return (o.get("direction") or o.get("type") or "").lower()


def _get_time(o: dict) -> datetime | None:
    for k in ("created_at", "time", "close_time", "timestamp"):
        v = o.get(k)
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


def _get_pnl(o: dict) -> float | None:
    for k in ("pnl", "profit_usd", "profit"):
        v = o.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return None


def _is_our_open(o: dict) -> bool:
    comment = (o.get("client_comment") or o.get("comment") or "").lower()
    direction = _get_dir(o)
    return (
        "scalping-radar" in comment
        and direction in ("buy", "sell")
    )


def _is_close(o: dict) -> bool:
    direction = _get_dir(o)
    if direction in ("close-buy", "close-sell"):
        return True
    if _get_pnl(o) is not None:
        return True
    return False


def main() -> int:
    print(f"Fetch /audit sur {BRIDGE_URL}", file=sys.stderr)
    orders = _fetch_all()
    print(f"\nTotal : {len(orders)} entries", file=sys.stderr)

    opens_by_ticket: dict[int, dict] = {}
    opens_scalping = 0
    closes_all = 0
    for o in orders:
        if _is_our_open(o):
            opens_scalping += 1
            try:
                tk = int(o.get("ticket") or 0)
            except (TypeError, ValueError):
                tk = 0
            if tk:
                opens_by_ticket[tk] = o
        if _is_close(o):
            closes_all += 1

    print(
        f"\nOuvertures scalping-radar : {opens_scalping} "
        f"(dont {len(opens_by_ticket)} avec ticket identifiable)",
        file=sys.stderr,
    )
    print(f"Fermetures (tous comments) : {closes_all}", file=sys.stderr)

    # Sample de 3 fermetures pour vérifier le shape
    sample_closes = [o for o in orders if _is_close(o)][:3]
    if sample_closes:
        print("\n=== Sample fermeture[0] ===", file=sys.stderr)
        print(json.dumps(sample_closes[0], indent=2, ensure_ascii=False)[:1500],
              file=sys.stderr)

    # Matching : pour chaque fermeture, trouver l'ouverture par ticket
    matched: list[tuple[dict, dict]] = []  # (open, close)
    unmatched_closes = 0
    for o in orders:
        if not _is_close(o):
            continue
        try:
            tk = int(o.get("ticket") or 0)
        except (TypeError, ValueError):
            tk = 0
        if tk and tk in opens_by_ticket:
            matched.append((opens_by_ticket[tk], o))
        else:
            unmatched_closes += 1

    print(
        f"\nMatched (open↔close) : {len(matched)} / "
        f"{len(opens_by_ticket)} opens / {closes_all} closes",
        file=sys.stderr,
    )
    print(f"Unmatched closes : {unmatched_closes}", file=sys.stderr)

    # Aggrégations sur matched
    total_pnl_usd = 0.0
    by_day_pnl_eur: dict[str, float] = defaultdict(float)
    by_day_count: dict[str, int] = defaultdict(int)
    by_pair_pnl_usd: dict[str, float] = defaultdict(float)
    by_pair_count: dict[str, int] = defaultdict(int)
    by_reason = Counter()
    pnl_list: list[tuple[float, dict, dict]] = []

    opens_without_close = len(opens_by_ticket) - len(matched)

    for op, cl in matched:
        pnl = _get_pnl(cl) or 0.0
        total_pnl_usd += pnl
        t = _get_time(cl) or _get_time(op)
        day = t.date().isoformat() if t else "?"
        by_day_pnl_eur[day] += pnl / EUR_USD_RATE
        by_day_count[day] += 1
        pair = _get_pair(op)
        by_pair_pnl_usd[pair] += pnl
        by_pair_count[pair] += 1
        reason = str(cl.get("close_reason") or cl.get("close_reason_code")
                     or "?").lower()
        by_reason[reason] += 1
        pnl_list.append((pnl, op, cl))

    pnl_list.sort(key=lambda x: x[0])
    worst = pnl_list[:10]
    best = pnl_list[-10:][::-1]

    def _pos_snapshot(op, cl):
        return {
            "ticket": op.get("ticket"),
            "pair": _get_pair(op),
            "direction": _get_dir(op),
            "entry": op.get("entry"),
            "exit": cl.get("exit_price") or cl.get("close_price")
                    or cl.get("price"),
            "pnl_usd": round(_get_pnl(cl) or 0.0, 2),
            "open_time": (_get_time(op) or "").isoformat()
                         if _get_time(op) else None,
            "close_time": (_get_time(cl) or "").isoformat()
                          if _get_time(cl) else None,
            "reason": str(cl.get("close_reason")
                          or cl.get("close_reason_code") or ""),
        }

    report = {
        "bridge_url": BRIDGE_URL,
        "total_audit_entries": len(orders),
        "opens_scalping_system": opens_scalping,
        "opens_with_ticket": len(opens_by_ticket),
        "closes_all": closes_all,
        "matched_pairs": len(matched),
        "unmatched_closes": unmatched_closes,
        "opens_without_close": opens_without_close,
        "pnl_usd_total_matched": round(total_pnl_usd, 2),
        "pnl_eur_total_matched": round(total_pnl_usd / EUR_USD_RATE, 2),
        "by_day_pnl_eur": {
            d: round(v, 2) for d, v in sorted(by_day_pnl_eur.items())
        },
        "by_day_count": {d: v for d, v in sorted(by_day_count.items())},
        "by_pair": {
            pair: {
                "trades": by_pair_count[pair],
                "pnl_usd": round(by_pair_pnl_usd[pair], 2),
                "pnl_eur": round(by_pair_pnl_usd[pair] / EUR_USD_RATE, 2),
            }
            for pair in sorted(
                by_pair_count, key=lambda p: by_pair_pnl_usd[p],
            )
        },
        "by_close_reason": dict(by_reason.most_common()),
        "pires_trades": [_pos_snapshot(op, cl) for pnl, op, cl in worst],
        "meilleurs_trades": [_pos_snapshot(op, cl) for pnl, op, cl in best],
    }

    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))

    pnl_eur = report["pnl_eur_total_matched"]
    print(
        f"\n→ PnL cumulé (fermetures matchées) : {pnl_eur:+.2f} EUR "
        f"sur {len(matched)} trades fermés",
        file=sys.stderr,
    )
    print(
        f"→ {opens_without_close} ouvertures sans fermeture identifiée "
        f"(closes manuels / désync audit / positions encore ouvertes).",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
