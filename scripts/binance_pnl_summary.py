"""Binance Futures USDⓈ-M PnL summary — décompose le delta wallet par catégorie.

Usage (EC2 host, via le venv du binance-bridge qui a httpx + les API keys) :

    sudo BINANCE_API_KEY=... BINANCE_API_SECRET=... BINANCE_ENV=testnet \\
        /opt/binance-bridge/venv/bin/python /opt/binance-bridge/binance_pnl_summary.py \\
        --since 2026-06-17T22:00:00Z

Ou avec les env vars déjà chargées par le service binance-bridge-rd :

    sudo systemd-run --pty --setenv-source=binance-bridge-rd.service \\
        /opt/binance-bridge/venv/bin/python /opt/binance-bridge/binance_pnl_summary.py

Output : tableau récap par incomeType (REALIZED_PNL, COMMISSION, FUNDING_FEE, etc.)
+ total net. Permet de répondre à "combien j'ai perdu / gagné depuis date X".
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

try:
    import httpx
except ImportError:
    print("ERROR: httpx package missing. Install with: pip install httpx", file=sys.stderr)
    sys.exit(1)

BINANCE_ENV = os.getenv("BINANCE_ENV", "testnet").lower()
_BASE_URLS = {
    "testnet": "https://testnet.binancefuture.com",
    "live": "https://fapi.binance.com",
}
BASE_URL = _BASE_URLS.get(BINANCE_ENV)
if BASE_URL is None:
    print(f"ERROR: invalid BINANCE_ENV={BINANCE_ENV}", file=sys.stderr)
    sys.exit(1)

API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")
if not API_KEY or not API_SECRET:
    print("ERROR: BINANCE_API_KEY and BINANCE_API_SECRET required", file=sys.stderr)
    sys.exit(1)


def _sign(params: dict[str, Any]) -> dict[str, Any]:
    params = dict(params)
    params["timestamp"] = int(time.time() * 1000)
    query = urlencode(params, doseq=True)
    sig = hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    params["signature"] = sig
    return params


def _signed_get(path: str, params: dict[str, Any] | None = None) -> Any:
    url = f"{BASE_URL}{path}"
    headers = {"X-MBX-APIKEY": API_KEY}
    with httpx.Client(timeout=15.0) as c:
        r = c.get(url, params=_sign(params or {}), headers=headers)
        r.raise_for_status()
        return r.json()


def fetch_income(since_ms: int, until_ms: int | None = None) -> list[dict[str, Any]]:
    """Fetch /fapi/v1/income en paginant si > 1000 entries (limit Binance)."""
    all_rows: list[dict[str, Any]] = []
    cursor = since_ms
    end_ms = until_ms or int(time.time() * 1000)
    while True:
        params = {"startTime": cursor, "endTime": end_ms, "limit": 1000}
        batch = _signed_get("/fapi/v1/income", params)
        if not batch:
            break
        all_rows.extend(batch)
        if len(batch) < 1000:
            break
        # Page suivante : décaler de 1 ms après la dernière entrée
        last_ts = max(int(r["time"]) for r in batch)
        if last_ts <= cursor:
            break  # safety pour éviter boucle infinie
        cursor = last_ts + 1
    return all_rows


def fetch_wallet() -> dict[str, Any]:
    """Snapshot du wallet actuel (totalWalletBalance + détails par asset)."""
    a = _signed_get("/fapi/v2/account")
    return {
        "totalWalletBalance": float(a.get("totalWalletBalance", 0)),
        "totalUnrealizedProfit": float(a.get("totalUnrealizedProfit", 0)),
        "availableBalance": float(a.get("availableBalance", 0)),
        "assets": [
            {
                "asset": x["asset"],
                "walletBalance": float(x.get("walletBalance", 0)),
                "unrealizedProfit": float(x.get("unrealizedProfit", 0)),
                "marginBalance": float(x.get("marginBalance", 0)),
            }
            for x in a.get("assets", [])
            if float(x.get("walletBalance", 0)) != 0
            or float(x.get("unrealizedProfit", 0)) != 0
        ],
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggrège les income rows par incomeType + symbol."""
    by_type: dict[str, float] = {}
    by_symbol: dict[str, dict[str, float]] = {}
    for r in rows:
        amt = float(r.get("income", 0))
        itype = r.get("incomeType", "?")
        sym = r.get("symbol", "")
        by_type[itype] = by_type.get(itype, 0) + amt
        if sym:
            bucket = by_symbol.setdefault(sym, {})
            bucket[itype] = bucket.get(itype, 0) + amt
    return {
        "rows_count": len(rows),
        "by_type": by_type,
        "by_symbol": by_symbol,
        "total_net": sum(by_type.values()),
    }


def render_human(since: datetime, summary: dict[str, Any], wallet: dict[str, Any]) -> str:
    lines = [
        f"Binance Futures USDⓈ-M PnL summary (env={BINANCE_ENV})",
        f"Depuis : {since.isoformat()} UTC",
        f"Snapshot pris : {datetime.now(timezone.utc).isoformat()} UTC",
        "",
        "── Wallet actuel ──",
        f"  totalWalletBalance   : {wallet['totalWalletBalance']:>14.2f} USDT",
        f"  unrealizedProfit     : {wallet['totalUnrealizedProfit']:>+14.2f} USDT",
        f"  availableBalance     : {wallet['availableBalance']:>14.2f} USDT",
    ]
    if wallet["assets"]:
        lines.append("  par asset :")
        for a in wallet["assets"]:
            lines.append(
                f"    {a['asset']:>6} wallet={a['walletBalance']:>12.2f}  "
                f"unrealized={a['unrealizedProfit']:>+10.2f}  "
                f"margin={a['marginBalance']:>12.2f}"
            )
    lines += [
        "",
        f"── Income décomposé ({summary['rows_count']} rows) ──",
    ]
    if not summary["by_type"]:
        lines.append("  (aucune ligne income sur la période)")
    else:
        for itype, total in sorted(summary["by_type"].items(), key=lambda kv: -abs(kv[1])):
            lines.append(f"  {itype:<22} {total:>+14.4f} USDT")
        lines.append(f"  {'TOTAL NET':<22} {summary['total_net']:>+14.4f} USDT")
    if summary["by_symbol"]:
        lines.append("")
        lines.append("── Top 10 symbols par |PnL| ──")
        ranked = sorted(
            summary["by_symbol"].items(),
            key=lambda kv: -abs(sum(kv[1].values())),
        )[:10]
        for sym, parts in ranked:
            total = sum(parts.values())
            parts_str = " ".join(f"{k}={v:+.2f}" for k, v in parts.items())
            lines.append(f"  {sym:<12} total={total:>+10.2f}  ({parts_str})")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Binance USDⓈ-M PnL summary")
    ap.add_argument(
        "--since",
        default="2026-06-17T22:00:00Z",
        help="ISO datetime UTC ou epoch_ms ou epoch_sec",
    )
    ap.add_argument("--json", action="store_true", help="Output JSON au lieu de l'humain")
    args = ap.parse_args()

    try:
        if args.since.isdigit():
            v = int(args.since)
            since_ms = v if v > 10**12 else v * 1000
        else:
            since_dt = datetime.fromisoformat(args.since.replace("Z", "+00:00"))
            since_ms = int(since_dt.timestamp() * 1000)
    except Exception as e:
        print(f"ERROR: failed to parse --since {args.since!r}: {e}", file=sys.stderr)
        return 1

    rows = fetch_income(since_ms)
    summary = summarize(rows)
    wallet = fetch_wallet()
    since_dt = datetime.fromtimestamp(since_ms / 1000, tz=timezone.utc)

    if args.json:
        print(json.dumps({
            "env": BINANCE_ENV,
            "since": since_dt.isoformat(),
            "wallet": wallet,
            "summary": summary,
        }, indent=2, default=str))
    else:
        print(render_human(since_dt, summary, wallet))
    return 0


if __name__ == "__main__":
    sys.exit(main())
