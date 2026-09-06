"""Daily recap PnL des 3 brokers — envoie le bilan 24h sur Telegram infra.

Source de vérité par broker :
- Pepperstone Demo (admin_legacy) : personal_trades closed sur 24h, jointure mt5_pushes
- IC Markets Live (admin_live) : idem mais filtre destination_id=admin_live
- Binance Testnet (admin_binance) : /fapi/v1/income via le bridge testnet

Cron suggéré : 22:00 UTC (= minuit Paris CEST) tous les jours.

Usage manuel :
    /opt/binance-bridge/venv/bin/python /opt/scalping/scripts/daily_recap.py [--since ISO]

Variables d'env requises (exporter avant l'appel ou via cron) :
- BINANCE_API_KEY / BINANCE_API_SECRET / BINANCE_ENV
- INFRA_TELEGRAM_TOKEN (le shadow public token de l'endpoint infra-telegram)
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

try:
    import httpx
except ImportError:
    print("ERROR: httpx package missing", file=sys.stderr)
    sys.exit(1)

BINANCE_ENV = os.getenv("BINANCE_ENV", "testnet").lower()
_BASE_URLS = {
    "testnet": "https://testnet.binancefuture.com",
    "live": "https://fapi.binance.com",
}
BASE_URL = _BASE_URLS.get(BINANCE_ENV)
API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")
INFRA_TELEGRAM_TOKEN = os.getenv("INFRA_TELEGRAM_TOKEN", "shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg")
SCALPING_URL = os.getenv("SCALPING_URL", "http://127.0.0.1:8000")


def _sign(params: dict[str, Any]) -> dict[str, Any]:
    params = dict(params)
    params["timestamp"] = int(time.time() * 1000)
    query = urlencode(params, doseq=True)
    sig = hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    params["signature"] = sig
    return params


def _signed_get(path: str, params: dict[str, Any] | None = None) -> Any:
    headers = {"X-MBX-APIKEY": API_KEY}
    with httpx.Client(timeout=15.0) as c:
        r = c.get(f"{BASE_URL}{path}", params=_sign(params or {}), headers=headers)
        r.raise_for_status()
        return r.json()


def fetch_binance(since_ms: int) -> dict[str, Any]:
    """Wallet snapshot + income décomposé sur 24h.

    ⚠️ BINANCE_DISABLED (2026-08-04) : la destination admin_binance est
    coupée depuis le 2026-08-02. Sans ce drapeau le recap affichait
    « Binance API keys missing », ce qui laissait croire à un incident de
    configuration alors que c'est une décision assumée.
    """
    if os.getenv("BINANCE_DISABLED"):
        return {"error": "destination désactivée (doublon Kraken, arrêtée le 02/08)"}
    if not API_KEY or not API_SECRET:
        return {"error": "Binance API keys missing"}
    try:
        wallet = _signed_get("/fapi/v2/account")
    except Exception as e:
        return {"error": f"wallet fetch: {e}"}
    try:
        rows: list[dict[str, Any]] = []
        cursor = since_ms
        end_ms = int(time.time() * 1000)
        while True:
            batch = _signed_get(
                "/fapi/v1/income",
                {"startTime": cursor, "endTime": end_ms, "limit": 1000},
            )
            if not batch:
                break
            rows.extend(batch)
            if len(batch) < 1000:
                break
            last_ts = max(int(r["time"]) for r in batch)
            if last_ts <= cursor:
                break
            cursor = last_ts + 1
    except Exception as e:
        return {"error": f"income fetch: {e}"}

    by_type: dict[str, float] = {}
    by_symbol: dict[str, float] = {}
    for r in rows:
        amt = float(r.get("income", 0))
        t = r.get("incomeType", "?")
        sym = r.get("symbol", "")
        by_type[t] = by_type.get(t, 0) + amt
        if sym:
            by_symbol[sym] = by_symbol.get(sym, 0) + amt
    top = sorted(by_symbol.items(), key=lambda kv: kv[1])[:3]  # 3 plus mauvais
    best = max(by_symbol.items(), key=lambda kv: kv[1], default=("-", 0))
    return {
        "wallet_balance": float(wallet.get("totalWalletBalance", 0)),
        "unrealized": float(wallet.get("totalUnrealizedProfit", 0)),
        "realized": by_type.get("REALIZED_PNL", 0),
        "commission": by_type.get("COMMISSION", 0),
        "funding": by_type.get("FUNDING_FEE", 0),
        "total_net": sum(by_type.values()),
        "top_losses": top,
        "best_winner": best,
        "rows_count": len(rows),
    }


def fetch_mt5(since_iso: str) -> dict[str, Any]:
    """Via docker exec scalping-radar : PnL par destination sur 24h."""
    py = f'''
import sqlite3, json
from backend.services.trade_log_service import _DB_PATH
con = sqlite3.connect(str(_DB_PATH))
con.row_factory = sqlite3.Row
out = {{}}
for dest in ("admin_legacy", "admin_live"):
    rows = con.execute("""
        SELECT pt.pair, pt.pnl
        FROM personal_trades pt
        WHERE pt.status='CLOSED'
          AND pt.is_auto=1
          AND pt.closed_at >= ?
          AND pt.mt5_ticket IN (
              SELECT CAST(json_extract(bridge_response, '$.ticket') AS INTEGER)
              FROM mt5_pushes WHERE destination_id=?
          )
    """, ("{since_iso}", dest)).fetchall()
    pnls = [float(r["pnl"] or 0) for r in rows]
    by_pair = {{}}
    for r in rows:
        by_pair.setdefault(r["pair"], 0)
        by_pair[r["pair"]] += float(r["pnl"] or 0)
    out[dest] = {{
        "trades": len(rows),
        "pnl_total": sum(pnls),
        "by_pair": sorted(by_pair.items(), key=lambda kv: kv[1]),
    }}
print(json.dumps(out))
'''
    try:
        r = subprocess.run(
            ["sudo", "docker", "exec", "scalping-radar", "python3", "-c", py],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            return {"error": f"docker exec failed: {r.stderr[:200]}"}
        return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception as e:
        return {"error": str(e)}


def fetch_activite(since_iso: str) -> dict:
    """Transitions d'admission + signaux refuses de peu, sur 24h.

    Remplace deux notifications temps reel supprimees le 2026-08-04. C'est en
    relisant sa journee qu'on ajuste un seuil, pas a 3h du matin.
    """
    py = (
        "import sqlite3, json" + chr(10) +
        "from backend.services.trade_log_service import _DB_PATH" + chr(10) +
        "con = sqlite3.connect('file:' + str(_DB_PATH) + '?mode=ro', uri=True)" + chr(10) +
        "s = " + repr(since_iso) + chr(10) +
        "out = {}" + chr(10) +
        "out['transitions'] = dict(con.execute('SELECT state, COUNT(*) FROM "
        "pair_admission_state WHERE state_since >= ? GROUP BY state', (s,)).fetchall())" + chr(10) +
        "out['refus'] = con.execute('SELECT COUNT(*) FROM signal_rejections WHERE "
        "reason_code = ' + chr(34) + 'below_confidence' + chr(34) + ' AND created_at >= ?', (s,)).fetchone()[0]" + chr(10) +
        "h = con.execute('SELECT pair, COUNT(*) c FROM signal_rejections WHERE reason_code = ' "
        "+ chr(34) + 'below_confidence' + chr(34) + ' AND created_at >= ? GROUP BY pair "
        "ORDER BY c DESC LIMIT 1', (s,)).fetchone()" + chr(10) +
        "out['refus_top'] = list(h) if h else None" + chr(10) +
        "print(json.dumps(out))" + chr(10)
    )
    try:
        r = subprocess.run(
            ["docker", "exec", "scalping-radar", "python3", "-c", py],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            return {"error": "docker exec failed: " + r.stderr[:200]}
        return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception as e:
        return {"error": str(e)}


def render(date_str: str, mt5_data: dict, binance: dict, activite: dict | None = None) -> str:
    lines = []

    legacy = mt5_data.get("admin_legacy", {})
    if "error" in mt5_data:
        lines += ["⚠️ Erreur récup MT5 : " + mt5_data["error"]]
    else:
        lines += ["🟦 Pepperstone Demo (admin_legacy)"]
        if legacy.get("trades", 0):
            lines += [
                f"• {legacy['trades']} trades fermés",
                f"• PnL : {legacy['pnl_total']:+.2f} USD",
            ]
            top_win = legacy["by_pair"][-1] if legacy["by_pair"] else None
            top_loss = legacy["by_pair"][0] if legacy["by_pair"] else None
            if top_win and top_win[1] > 0:
                lines.append(f"• Top : {top_win[0]} {top_win[1]:+.2f}")
            if top_loss and top_loss[1] < 0:
                lines.append(f"• Pire : {top_loss[0]} {top_loss[1]:+.2f}")
        else:
            lines += ["• 0 trade fermé sur 24h"]
        lines.append("")

        live = mt5_data.get("admin_live", {})
        lines += ["🟩 IC Markets Live (admin_live, argent réel)"]
        if live.get("trades", 0):
            lines += [
                f"• {live['trades']} trades fermés",
                f"• PnL : {live['pnl_total']:+.2f} EUR",
            ]
        else:
            lines += ["• 0 trade fermé sur 24h"]
            lines += ["• ⚠️ Inactivité — bridge ou compte à vérifier"]
        lines.append("")

    lines += ["🟪 Binance Testnet (admin_binance)"]
    if "error" in binance:
        lines += ["• ⚠️ " + binance["error"]]
    else:
        lines += [
            f"• Wallet : {binance['wallet_balance']:.0f} USDT ({binance['unrealized']:+.0f} unrealized)",
            f"• PnL net 24h : {binance['total_net']:+.2f} USDT",
            f"  ├ Realized : {binance['realized']:+.2f}",
            f"  ├ Commission : {binance['commission']:+.2f}",
            f"  └ Funding : {binance['funding']:+.2f}",
        ]
        if binance["top_losses"]:
            losses_str = ", ".join(f"{s} {v:+.0f}" for s, v in binance["top_losses"])
            lines.append(f"• Top loss : {losses_str}")
        best = binance.get("best_winner")
        if best and best[1] > 0:
            lines.append(f"• Meilleur : {best[0]} {best[1]:+.0f}")
    # Activite du radar : ce qui etait pousse en temps reel sans declencher
    # de decision. Ici, ca sert a ajuster un seuil.
    if activite and "error" not in activite:
        tr = activite.get("transitions") or {}
        total = sum(tr.values())
        refus = activite.get("refus") or 0
        if total or refus:
            lines += ["", "⚙️ Activité du radar"]
        if total:
            detail = []
            for etat, libelle in (("AUTO_EXEC", "activées"), ("TELEGRAM", "en notif"),
                                  ("PAUSED", "en pause"), ("DEMOTED", "rétrogradées"),
                                  ("OBSERVED", "en observation")):
                if tr.get(etat):
                    detail.append(str(tr[etat]) + " " + libelle)
            lines.append("• " + str(total) + " changements de mode" +
                         (" (" + ", ".join(detail) + ")" if detail else ""))
        if refus:
            ligne = "• " + str(refus) + " signaux refusés faute de confiance"
            top = activite.get("refus_top")
            if top:
                ligne += " (surtout " + str(top[0]) + ", " + str(top[1]) + ")"
            lines.append(ligne)
    return "\n".join(lines)


def post_telegram(title: str, body: str, target: str = "infra") -> dict:
    """Envoie le recap sur le bot cible.

    - target=infra (default) : via endpoint backend /api/admin/notify-infra-telegram
    - target=sales : appel direct api.telegram.org avec SALES_TELEGRAM_BOT_TOKEN/CHAT_ID
      (env vars du container scalping-radar, à exporter dans le wrapper cron).
    """
    # CORRIGE LE 06/09. Deux chemins, tous deux fautifs :
    #
    #   target=sales : appel DIRECT a api.telegram.org avec
    #     SALES_TELEGRAM_BOT_TOKEN — le bot nomme « IC MARKETS trades ». Un
    #     recap TRANSVERSE atterrissait donc chaque nuit dans le fil du compte
    #     reel, hors de la table des canaux. Et l'enveloppe cron passait
    #     `sales` PAR DEFAUT.
    #
    #   target=infra : endpoint SANS `channel` — donc le defaut SILENCIEUX.
    #     La bonne destination, par un mecanisme documente comme un piege.
    #
    # Un recap qui parle de TOUS les comptes n'appartient au fil d'aucun. Il
    # part sur `infra`, EXPLICITEMENT, comme les trois autres digests.
    url = (f"{SCALPING_URL}/api/admin/notify-infra-telegram"
           f"?token={INFRA_TELEGRAM_TOKEN}&channel=infra")
    with httpx.Client(timeout=15.0) as c:
        r = c.post(url, json={"title": title, "body": body})
        return {"status": r.status_code, "response": r.json() if r.status_code < 500 else r.text[:200]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="ISO datetime UTC ou epoch_sec. Default: 24h ago.")
    ap.add_argument("--dry-run", action="store_true", help="N'envoie pas le Telegram, affiche le message")
    ap.add_argument("--target", choices=("infra",), default="infra",
                    help="Bot Telegram cible. sales requiert SALES_TELEGRAM_BOT_TOKEN/CHAT_ID dans l'env.")
    args = ap.parse_args()

    if args.since:
        try:
            if args.since.isdigit():
                since_ms = int(args.since) * 1000
            else:
                since_dt = datetime.fromisoformat(args.since.replace("Z", "+00:00"))
                since_ms = int(since_dt.timestamp() * 1000)
        except Exception as e:
            print(f"ERROR --since: {e}", file=sys.stderr)
            return 1
    else:
        since_ms = int((time.time() - 86400) * 1000)

    since_dt = datetime.fromtimestamp(since_ms / 1000, tz=timezone.utc)
    since_iso = since_dt.isoformat()
    paris_now = datetime.now(timezone.utc) + timedelta(hours=2)
    date_str = paris_now.strftime("%Y-%m-%d")

    mt5_data = fetch_mt5(since_iso)

    activite = fetch_activite(since_iso)
    binance = fetch_binance(since_ms)
    body = render(date_str, mt5_data, binance, activite)
    title = f"Daily recap 24h {date_str}"

    if args.dry_run:
        print(f"=== {title} ===")
        print(body)
        return 0

    result = post_telegram(title, body, target=args.target)
    print(f"telegram[{args.target}] POST status={result['status']} response={result['response']}")
    return 0 if result["status"] == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
