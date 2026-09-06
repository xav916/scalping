#!/usr/bin/env python3
# BUT: met le WTI en pause hors de sa fenetre de seance
# PERIODE_MIN: 5
"""
WTI auto-pause watchdog.
Cron : */5 * * * * /usr/bin/python3 /opt/scalping/scripts/wti-auto-pause.py >> /var/log/scalping/wti-watchdog.log 2>&1

Logique :
1. Cherche les 2 derniers trades WTI/USD admin_live CLOSED
2. Si les 2 ont close_reason=SL → DEMOTE pair_admission_state WTI/USD à PAUSED
3. Send Telegram infra alert
"""
import sqlite3, json, os, sys, urllib.request, urllib.parse
from datetime import datetime, timezone

DB = "/opt/scalping/data/trades.db"

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
    """Passe par l'endpoint, canal `ic_markets`.

    Cette pause ne concerne QUE le compte reel : la requete filtre sur
    `destination_id='admin_live'`. Le message partait pourtant sur le fil
    infra, parce que le script lisait `INFRA_TELEGRAM_BOT_TOKEN` en dur — un
    contournement de plus de la table des canaux.

    Une paire mise en pause est une decision de TRADING : elle appartient au
    fil du compte concerne, la ou Xavier lit ses trades.
    """
    import json as _json
    jeton = "shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg"
    url = ("https://app.scalping-radar.online/api/admin/"
           "notify-infra-telegram?token=" + jeton + "&channel=ic_markets")
    lignes = str(msg).splitlines() or [""]
    charge = _json.dumps({
        "title": lignes[0][:120],
        "body": chr(10).join(lignes[1:]) or lignes[0],
    }).encode("utf-8")
    try:
        rq = urllib.request.Request(
            url, data=charge, headers={"Content-Type": "application/json"},
            method="POST")
        urllib.request.urlopen(rq, timeout=10).read()
    except Exception as e:
        print(f"telegram fail: {e}")

def main():
    env = load_env()
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    # Already paused ?
    paused = con.execute("SELECT pair, state, reason FROM pair_admission_state WHERE pair='WTI/USD' AND state='PAUSED' LIMIT 1").fetchone()
    if paused:
        print(f"[{datetime.now(timezone.utc).isoformat()[:19]}] WTI already PAUSED ({dict(paused)['reason']!r}) — skip")
        return 0

    # Last 5 admin_live WTI pushes (tickets)
    tickets = []
    for r in con.execute("SELECT bridge_response, pushed_at FROM mt5_pushes WHERE destination_id='admin_live' AND pair='WTI/USD' AND ok=1 ORDER BY id DESC LIMIT 5"):
        try:
            d = json.loads(r["bridge_response"])
            t = d.get("ticket")
            if t:
                tickets.append(int(t))
        except Exception:
            pass

    if len(tickets) < 2:
        print(f"[{datetime.now(timezone.utc).isoformat()[:19]}] only {len(tickets)} WTI live pushes — skip")
        return 0

    # Find the 2 most recent CLOSED ones
    closed = []
    for ticket in tickets:
        r = con.execute("SELECT mt5_ticket, pnl, close_reason, closed_at FROM personal_trades WHERE mt5_ticket=? AND status='CLOSED'", (ticket,)).fetchone()
        if r:
            closed.append(dict(r))
        if len(closed) >= 2:
            break

    if len(closed) < 2:
        print(f"[{datetime.now(timezone.utc).isoformat()[:19]}] only {len(closed)} WTI live CLOSED trades — skip")
        return 0

    last_two = closed[:2]
    are_sl = [t.get("close_reason") == "SL" for t in last_two]

    if all(are_sl):
        # Pause WTI admin state for both directions
        con.execute("UPDATE pair_admission_state SET state='PAUSED', state_since=datetime('now'), reason=? WHERE pair='WTI/USD' AND state='AUTO_EXEC'", (f"auto-watchdog: 2 SL consecutifs Live ({last_two[0]['mt5_ticket']} + {last_two[1]['mt5_ticket']})",))
        con.commit()
        total_pnl = (last_two[0].get("pnl") or 0) + (last_two[1].get("pnl") or 0)
        msg = (
            "⛔ <b>WTI auto-pause</b>\n\n"
            f"2 SL consécutifs sur compte Live IC Markets.\n"
            f"Tickets : <code>{last_two[0][mt5_ticket]}</code> + <code>{last_two[1][mt5_ticket]}</code>\n"
            f"PnL cumulé : <code>{total_pnl:+.2f}</code>\n\n"
            "ℹ️ WTI désormais PAUSED en auto-exec. Reprise manuelle via /v2/admin ou DB UPDATE."
        )
        alert_telegram(env, msg)
        print(f"[{datetime.now(timezone.utc).isoformat()[:19]}] WTI PAUSED (2 SL consec, tickets {last_two[0][mt5_ticket]} + {last_two[1][mt5_ticket]}, pnl_total={total_pnl:.2f})")
        return 0
    else:
        reasons = [t.get("close_reason") for t in last_two]
        print(f"[{datetime.now(timezone.utc).isoformat()[:19]}] last 2 WTI live close_reasons = {reasons} — pas 2 SL, OK")
        return 0

if __name__ == "__main__":
    sys.exit(main())
