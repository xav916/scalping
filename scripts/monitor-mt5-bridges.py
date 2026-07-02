#!/usr/bin/env python3
"""
MT5 Bridges Health Monitor — runs hourly (xx:37 UTC)
Checks legacy (8787) and live (8788) bridges, alerts Telegram on anomalies
"""

import json
import sys
from datetime import datetime, timezone
from typing import Any
import subprocess
from pathlib import Path

# Configuration
ENDPOINT = "https://app.scalping-radar.online/api/admin/mt5-bridges-health"
NOTIFY_ENDPOINT = "https://app.scalping-radar.online/api/admin/notify-infra-telegram"
TOKEN = "shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg"

def log(msg: str):
    """Log with UTC timestamp"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{now}] {msg}", file=sys.stderr)

def fetch_health() -> dict[str, Any] | None:
    """Fetch bridge health endpoint"""
    log("Fetching MT5 bridges health...")
    try:
        result = subprocess.run(
            [
                "curl",
                "-sk",
                "--max-time", "10",
                f"{ENDPOINT}?token={TOKEN}",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            log(f"ERROR: curl failed — {result.stderr}")
            return None

        data = json.loads(result.stdout)
        log(f"✓ Health endpoint responded (HTTP 200)")
        return data
    except Exception as e:
        log(f"ERROR: {e}")
        return None

def detect_issues(health: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse bridge health and detect anomalies"""
    issues = []
    for key in ("legacy", "live"):
        b = health.get(key) or {}
        label = {
            "legacy": "Pepperstone Demo (legacy/8787)",
            "live": "IC Markets Live (live/8788)",
        }[key]

        if not b.get("configured"):
            continue

        if not b.get("reachable"):
            err = b.get("error") or b.get("status") or "unknown"
            issues.append({
                "key": key,
                "label": label,
                "url": b.get("url"),
                "detail": f"UNREACHABLE ({err})",
            })
            continue

        if not b.get("ok"):
            issues.append({
                "key": key,
                "label": label,
                "url": b.get("url"),
                "detail": f"reachable but ok=false (login={b.get('login')}, server={b.get('server')})",
            })

    return issues

def send_alert(issue: dict[str, Any]) -> bool:
    """Send Telegram alert for an issue"""
    title = f"🚨 Bridge {issue['label']} DOWN"
    body = (
        f"{issue['detail']}\n"
        f"URL : {issue['url']}\n"
        f"Action : RDP au VPS cedric-mt5-bridge, relancer mt5-bridge-{issue['key']} "
        f"via .\\venv\\Scripts\\python.exe .\\bridge.py"
    )
    payload = {
        "title": title,
        "body": body,
        "dedup_key": f"bridge_{issue['key']}_down",
        "cooldown_seconds": 10800,
    }

    try:
        result = subprocess.run(
            [
                "curl",
                "-sk",
                "-X", "POST",
                f"{NOTIFY_ENDPOINT}?token={TOKEN}",
                "-H", "Content-Type: application/json",
                "-d", json.dumps(payload),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0:
            try:
                resp = json.loads(result.stdout)
                if resp.get("sent"):
                    log(f"✓ Alert sent for {issue['key']}")
                    return True
            except json.JSONDecodeError:
                pass

        log(f"⚠ Alert send for {issue['key']} — response: {result.stdout}")
        return False
    except Exception as e:
        log(f"ERROR sending alert: {e}")
        return False

def main():
    log("=== MT5 BRIDGES HEALTH MONITOR ===")

    # Fetch health
    health = fetch_health()
    if not health:
        log("ERROR: Could not fetch health endpoint")
        sys.exit(1)

    # Detect issues
    issues = detect_issues(health)

    if issues:
        log(f"⚠ Detected {len(issues)} anomaly/ies — sending alerts...")
        for issue in issues:
            send_alert(issue)
    else:
        log("✓ All bridges OK — no alerts needed")

    # Report
    print("\n=== BRIDGE STATUS ===")
    for key in ("legacy", "live"):
        b = health.get(key) or {}
        label = {"legacy": "8787 legacy", "live": "8788 live"}[key]
        status = "🔴 DOWN" if not b.get("reachable") else "🟢 UP"
        ok = "✓" if b.get("ok") else "✗"
        login = b.get("login", "—")
        server = b.get("server", "—")
        print(f"  {label}: {status} {ok} | login={login} | server={server}")

    log("Monitor cycle complete")
    return 0

if __name__ == "__main__":
    sys.exit(main())
