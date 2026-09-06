#!/usr/bin/env python3
# BUT: met en pause une paire qui derape (generalisation du WTI)
# PERIODE_MIN: 15
"""
Pair auto-pause watchdog — généralisation du pattern WTI.
Cron : */15 * * * * /usr/bin/python3 /opt/scalping/scripts/pair-auto-pause-watchdog.py >> /var/log/scalping/pair-watchdog.log 2>&1

Triggers (par pair AUTO_EXEC) :
  1. N_CONSEC_SL_THRESHOLD (default 5) SL consécutifs Live sur fenêtre récente
  2. PNL_24H_USD_THRESHOLD (default -2.0 USD) PnL cumulé négatif Live sur 24h
Action si déclenché :
  - UPDATE pair_admission_state SET state='PAUSED'
  - Telegram alert (infra bot)
Skip si déjà PAUSED.
"""
import sqlite3, json, os, sys, urllib.request, urllib.parse
from datetime import datetime, timezone

DB = "/opt/scalping/data/trades.db"

N_CONSEC_SL_THRESHOLD = int(os.getenv("WATCHDOG_N_SL_CONSEC", "5"))
PNL_24H_USD_THRESHOLD = float(os.getenv("WATCHDOG_PNL_24H_USD", "-2.0"))
LOOKBACK_PUSHES = 20  # combien de pushes récents on regarde pour trouver les CLOSED

# Pairs explicitement exemptées (pas critiques pour le watchdog)
EXEMPT_PAIRS = set(filter(None, os.getenv("WATCHDOG_EXEMPT_PAIRS", "").split(",")))


def load_env():
    env = {}
    try:
        with open("/opt/scalping/.env") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    except Exception:
        pass
    return env


def alert_telegram(env, msg):
    tok = env.get("INFRA_TELEGRAM_BOT_TOKEN", "")
    chat = env.get("INFRA_TELEGRAM_CHAT_ID", "")
    if not tok or not chat:
        print("  [telegram] no INFRA_TELEGRAM_* vars, skip notify")
        return
    try:
        data = urllib.parse.urlencode({"chat_id": chat, "text": msg, "parse_mode": "HTML"}).encode()
        urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage", data=data, timeout=10).read()
        print("  [telegram] alert sent")
    except Exception as e:
        print(f"  [telegram] fail: {e}")


def get_live_pushes(con, pair, limit=LOOKBACK_PUSHES):
    """Retourne les tickets des derniers pushes admin_live ok=1 pour la pair."""
    tickets = []
    rows = con.execute(
        "SELECT bridge_response FROM mt5_pushes WHERE destination_id='admin_live' AND pair=? AND ok=1 ORDER BY id DESC LIMIT ?",
        (pair, limit),
    ).fetchall()
    for r in rows:
        try:
            d = json.loads(r["bridge_response"])
            t = d.get("ticket")
            if t:
                tickets.append(int(t))
        except Exception:
            pass
    return tickets


def get_closed_trades(con, tickets):
    """Retourne les trades CLOSED parmi les tickets fournis, dans l'ordre tickets."""
    closed = []
    for ticket in tickets:
        r = con.execute(
            "SELECT mt5_ticket, pnl, close_reason, closed_at FROM personal_trades WHERE mt5_ticket=? AND status='CLOSED'",
            (ticket,),
        ).fetchone()
        if r:
            closed.append(dict(r))
    return closed


def check_pair(con, pair, env):
    """Retourne True si la pair vient d'être paused, False sinon."""
    # Déjà PAUSED ?
    paused = con.execute(
        "SELECT reason FROM pair_admission_state WHERE pair=? AND state='PAUSED' LIMIT 1",
        (pair,),
    ).fetchone()
    if paused:
        print(f"  [{pair}] already PAUSED ({paused['reason']!r}) — skip")
        return False

    tickets = get_live_pushes(con, pair)
    if not tickets:
        print(f"  [{pair}] no live pushes — skip")
        return False

    closed = get_closed_trades(con, tickets)
    if not closed:
        print(f"  [{pair}] no closed trades — skip")
        return False

    # Trigger 1 : N_CONSEC_SL consécutifs
    last_n = closed[:N_CONSEC_SL_THRESHOLD]
    consec_sl_triggered = (
        len(last_n) >= N_CONSEC_SL_THRESHOLD
        and all(t.get("close_reason") == "SL" for t in last_n)
    )

    # Trigger 2 : PnL 24h < seuil
    now = datetime.now(timezone.utc)
    pnl_24h = 0.0
    n_24h = 0
    for t in closed:
        if not t.get("closed_at"):
            continue
        try:
            ts = datetime.fromisoformat(t["closed_at"].replace("Z", "+00:00"))
        except Exception:
            continue
        if (now - ts).total_seconds() <= 24 * 3600:
            pnl_24h += float(t.get("pnl") or 0)
            n_24h += 1
    pnl_24h_triggered = n_24h > 0 and pnl_24h < PNL_24H_USD_THRESHOLD

    if not (consec_sl_triggered or pnl_24h_triggered):
        reasons = [t.get("close_reason") for t in last_n]
        print(f"  [{pair}] OK last_close_reasons={reasons} pnl_24h={pnl_24h:+.2f}({n_24h})")
        return False

    # Trigger → PAUSE
    reason_parts = []
    if consec_sl_triggered:
        ticks = ", ".join(str(t["mt5_ticket"]) for t in last_n)
        reason_parts.append(f"{N_CONSEC_SL_THRESHOLD} SL consec ({ticks})")
    if pnl_24h_triggered:
        reason_parts.append(f"PnL 24h {pnl_24h:+.2f} USD sur {n_24h} trades")
    reason = "auto-watchdog: " + " ; ".join(reason_parts)

    con.execute(
        "UPDATE pair_admission_state SET state='PAUSED', state_since=datetime('now'), reason=? WHERE pair=? AND state='AUTO_EXEC'",
        (reason, pair),
    )
    con.commit()

    msg = (
        f"⛔ <b>{pair} auto-pause</b>\n\n"
        f"{reason}\n\n"
        f"ℹ️ {pair} désormais PAUSED. Reprise manuelle via /v2/admin ou DB UPDATE."
    )
    alert_telegram(env, msg)
    print(f"  [{pair}] PAUSED — {reason}")
    return True


def main():
    env = load_env()
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    # Liste dynamique des pairs AUTO_EXEC
    pairs_auto = [
        r["pair"]
        for r in con.execute(
            "SELECT DISTINCT pair FROM pair_admission_state WHERE state='AUTO_EXEC' ORDER BY pair"
        )
        if r["pair"] not in EXEMPT_PAIRS
    ]

    print(
        f"=== {datetime.now(timezone.utc).isoformat()[:19]} pair-watchdog "
        f"N_SL={N_CONSEC_SL_THRESHOLD} PNL_24H<={PNL_24H_USD_THRESHOLD} "
        f"exempt={sorted(EXEMPT_PAIRS) or '-'} ==="
    )
    print(f"Pairs AUTO_EXEC : {pairs_auto}")

    paused_count = 0
    for pair in pairs_auto:
        if check_pair(con, pair, env):
            paused_count += 1

    print(f"=== done : {paused_count} pair(s) paused ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
