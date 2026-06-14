#!/usr/bin/env python3
"""
EA Health Monitor — routine exécutée 4×/jour (00:23, 06:23, 12:23, 18:23 UTC)
pour détecter anomalies EAs en production.
"""

import json
import sys
import subprocess
from datetime import datetime, timezone
from pathlib import Path

# Configuration
HEALTH_ENDPOINT = "https://app.scalping-radar.online/api/admin/auto-exec/health-token"
NOTIFY_ENDPOINT = "https://app.scalping-radar.online/api/admin/notify-infra-telegram"
ADMIN_TOKEN = "shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg"

HEARTBEAT_STALE_THRESHOLD = 1800  # 30 min
MIN_ORDERS_FOR_EXEC_RATE = 3
EXEC_RATE_THRESHOLD = 0.5


def fetch_health_data():
    """Fetch health token from endpoint."""
    try:
        result = subprocess.run(
            [
                "curl",
                "-sk",
                f"{HEALTH_ENDPOINT}?token={ADMIN_TOKEN}",
                "-w",
                "\n%{http_code}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        lines = result.stdout.strip().split("\n")
        http_code = lines[-1]
        json_body = "\n".join(lines[:-1])

        if http_code != "200":
            return None, f"HTTP {http_code}", json_body

        data = json.loads(json_body)
        return data, "200", None
    except subprocess.TimeoutExpired:
        return None, "TIMEOUT", None
    except json.JSONDecodeError as e:
        return None, "JSON_INVALID", str(e)
    except Exception as e:
        return None, "ERROR", str(e)


# Mapping email → prénom client (préfixé dans les alertes infra 2026-06-14).
# Ajouter ici tout nouveau Premium pour avoir "Compte client X" au lieu de "user_N".
_USER_DISPLAY_NAME = {
    "c.chaussis@icloud.com": "Cédric",
    "couderc.xavier@gmail.com": "Xavier",
    "pascal.p.couderc@gmail.com": "Pascal",
}


def _client_label(user):
    """Retourne un label lisible 'Compte client <Prénom>' pour un user.
    Fallback : 'Compte client #N' si email pas dans le mapping.
    """
    email = (user.get("email") or "").lower()
    uid = user.get("user_id")
    name = _USER_DISPLAY_NAME.get(email)
    if name:
        return f"Compte client {name}"
    return f"Compte client #{uid}"


def detect_anomalies(data):
    """Parse health data and detect anomalies."""
    issues = []

    for user in data.get("users", []):
        client = _client_label(user)

        # 1) Heartbeat OFFLINE ou stale > 30 min
        hb = user.get("heartbeat") or {}
        age = hb.get("age_seconds") or 0
        status = hb.get("status") or "UNKNOWN"
        if status != "LIVE" and age > HEARTBEAT_STALE_THRESHOLD:
            issues.append(
                f"{client} : robot {status.lower()} — dernier signe de vie il y a {age}s"
            )

        # 2) Zombies (sent_stale ou pending_overdue)
        z = user.get("zombies") or {}
        ztotal = z.get("total") or 0
        if ztotal > 0:
            issues.append(
                f"{client} : {ztotal} ordres bloqués en attente "
                f"(envoyés trop vieux : {z.get('sent_stale', 0)}, en attente trop long : {z.get('pending_overdue', 0)})"
            )

        # 3) Low executed_rate sur >=3 ordres résolus
        o = user.get("orders_24h") or {}
        total = o.get("total") or 0
        exec_rate = o.get("executed_rate")
        if total >= MIN_ORDERS_FOR_EXEC_RATE and exec_rate is not None and exec_rate < EXEC_RATE_THRESHOLD:
            by_status = o.get("by_status") or {}
            failed_by_pair = o.get("failed_by_pair") or {}
            if failed_by_pair:
                worst = max(failed_by_pair.items(), key=lambda x: x[1])
                top = f"{worst[0]} ({worst[1]} échecs)"
            else:
                top = "?"
            issues.append(
                f"{client} : taux d'exécution {int(exec_rate*100)}% sur {total} ordres dernières 24h "
                f"(réussis : {by_status.get('EXECUTED', 0)}, échoués : {by_status.get('FAILED', 0)}, "
                f"paire la plus problématique : {top})"
            )

    # 4) Totaux globaux
    T = data.get("totals") or {}
    if (T.get("users_offline") or 0) > 0:
        issues.append(f"Global : {T['users_offline']} client(s) hors ligne")

    return issues


def notify_infra_telegram(issues, data):
    """POST anomalies to infra telegram endpoint. Vulgarized 2026-06-13."""
    if not issues:
        return "OK", None

    T = data.get("totals", {})
    body_lines = ["⚠️ *Anomalie(s) détectée(s) :*"]
    body_lines.extend(["• " + i for i in issues])
    body_lines.append("")
    body_lines.append("ℹ️ Pourquoi ce message ?")
    body_lines.append(
        "Le radar surveille en permanence les robots de trading des users Premium "
        "(Cédric et autres). S'ils n'exécutent plus les ordres ou sont déconnectés, "
        "ils ratent des trades — donc on alerte."
    )
    body_lines.append("")
    body_lines.append("📊 *État global*")
    body_lines.append(
        f"Users configurés : {len(data.get('users', []))}  "
        f"(en ligne : {T.get('users_live', 0)}, hors ligne : {T.get('users_offline', 0)}, "
        f"silencieux : {T.get('users_stale', 0)})"
    )
    body_lines.append(
        f"Ordres tentés 24h : {T.get('orders_24h', '?')}  "
        f"(taux réussite : {T.get('executed_rate_24h', '?')}, "
        f"en attente : {T.get('zombies_total', 0)})"
    )
    body = "\n".join(body_lines)

    title = f"🚨 Robot Premium · {len(issues)} souci(s) détecté(s)"
    payload = json.dumps({"title": title, "body": body})

    try:
        result = subprocess.run(
            [
                "curl",
                "-sk",
                "-X",
                "POST",
                f"{NOTIFY_ENDPOINT}?token={ADMIN_TOKEN}",
                "-H",
                "Content-Type: application/json",
                "-d",
                payload,
                "-w",
                "\n%{http_code}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        lines = result.stdout.strip().split("\n")
        http_code = lines[-1]

        if http_code == "200":
            return "SENT_200", None
        elif http_code == "503":
            return "NOT_CONFIGURED", http_code
        else:
            return f"FAILED_{http_code}", http_code
    except subprocess.TimeoutExpired:
        return "TIMEOUT", None
    except Exception as e:
        return "ERROR", str(e)


def run_health_check():
    """Main health check routine."""
    utc_now = datetime.now(timezone.utc)
    timestamp = utc_now.isoformat()

    print(f"\n{'='*70}")
    print(f"EA Health Monitor — {timestamp}")
    print(f"{'='*70}")

    # Step 1: Fetch health data
    print("\n[1] Fetching health data...")
    data, fetch_status, fetch_detail = fetch_health_data()

    if fetch_status != "200":
        print(f"❌ Health endpoint FAILED: {fetch_status}")
        if fetch_detail:
            print(f"   Detail: {fetch_detail[:200]}")

        # Critical alert: endpoint down
        print("\n[2] POSTing critical alert to Telegram...")
        payload = json.dumps({
            "title": "🚨 Surveillance robots Premium HS",
            "body": (
                "⚠️ Le service qui vérifie l'état des robots des users Premium "
                "(Cédric et autres) ne répond plus.\n\n"
                f"Code retour : {fetch_status}\n"
                f"Détail : {fetch_detail or 'aucun'}\n\n"
                "ℹ️ Pourquoi ce message ?\n"
                "Sans ce service, on ne sait plus si les robots Premium "
                "exécutent les trades. À vérifier rapidement côté backend."
            )
        })

        try:
            result = subprocess.run(
                [
                    "curl",
                    "-sk",
                    "-X",
                    "POST",
                    f"{NOTIFY_ENDPOINT}?token={ADMIN_TOKEN}",
                    "-H",
                    "Content-Type: application/json",
                    "-d",
                    payload,
                    "-w",
                    "\n%{http_code}",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            lines = result.stdout.strip().split("\n")
            http_code = lines[-1]
            alert_status = "SENT" if http_code == "200" else f"FAILED_{http_code}"
        except Exception as e:
            alert_status = f"ERROR: {e}"

        print(f"   Alert status: {alert_status}")
        print(f"\n[FINAL] Health check failed — endpoint unavailable")
        return False

    print(f"✓ Health endpoint OK (HTTP 200)")

    # Step 2: Detect anomalies
    print("\n[2] Detecting anomalies...")
    issues = detect_anomalies(data)
    T = data.get("totals", {})

    print(f"   Users: {len(data.get('users', []))} live={T.get('users_live', 0)} "
          f"offline={T.get('users_offline', 0)} stale={T.get('users_stale', 0)}")
    print(f"   Orders 24h: {T.get('orders_24h', '?')} exec_rate={T.get('executed_rate_24h', '?')} "
          f"zombies={T.get('zombies_total', 0)}")

    if issues:
        print(f"\n   ⚠️  {len(issues)} anomalie(s) detected:")
        for i, issue in enumerate(issues, 1):
            print(f"      {i}. {issue}")
    else:
        print(f"   ✓ No anomalies detected")

    # Step 3: Notify if issues
    if issues:
        print("\n[3] POSTing alert to Telegram...")
        alert_status, detail = notify_infra_telegram(issues, data)
        if "SENT" in alert_status or "FAILED" in alert_status or "NOT_CONFIGURED" in alert_status:
            print(f"   Alert status: {alert_status}")
            if detail:
                print(f"   Detail: {detail}")
        else:
            print(f"   ⚠️  Alert status: {alert_status}")
    else:
        print("\n[3] No alert needed — all systems nominal")
        alert_status = "NOT_NEEDED"

    # Step 4: Final report
    print(f"\n[FINAL] Health check complete")
    print(f"   Anomalies: {len(issues)}")
    print(f"   Alert status: {alert_status}")
    print(f"   Snapshot: users_live={T.get('users_live', 0)} "
          f"orders_24h={T.get('orders_24h', '?')} "
          f"exec_rate_24h={T.get('executed_rate_24h', '?')}")
    print(f"{'='*70}\n")

    return True


if __name__ == "__main__":
    success = run_health_check()
    sys.exit(0 if success else 1)
