#!/usr/bin/env python3
"""
Scalping infra monitor.

What it does:
  * Poll /health + /account on both bridges (local PC + VPS) every POLL_INTERVAL_SEC.
  * Poll `systemctl is-active` for critical local services.
  * Track UP/DOWN state per check with N-cycle debounce.
  * Send Telegram alerts on confirmed DOWN, periodic reminders while down,
    and recovery notices.
  * Expose an HTML dashboard on the Tailscale IP for mobile consumption.
  * Respond to `/status` commands sent to the Telegram bot (long polling).
  * Append a JSON line per cycle to LOG_PATH for offline analysis.

Deps: requests (stdlib otherwise).
"""
from __future__ import annotations

import html
import json
import logging
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import requests

# ------- config -------
POLL_INTERVAL_SEC = int(os.getenv("POLL_INTERVAL_SEC", "60"))
REQUEST_TIMEOUT_SEC = float(os.getenv("REQUEST_TIMEOUT_SEC", "5"))
DOWN_CONFIRM_CYCLES = int(os.getenv("DOWN_CONFIRM_CYCLES", "2"))
REMINDER_EVERY_SEC = int(os.getenv("REMINDER_EVERY_SEC", "900"))  # 15 min

BRIDGE_LOCAL_URL = os.environ.get("BRIDGE_LOCAL_URL", "").strip()
BRIDGE_LOCAL_KEY = os.environ.get("BRIDGE_LOCAL_KEY", "").strip()
BRIDGE_LOCAL_ENABLED = bool(BRIDGE_LOCAL_URL and BRIDGE_LOCAL_KEY)
BRIDGE_VPS_URL = os.environ["BRIDGE_VPS_URL"]
BRIDGE_VPS_KEY = os.environ["BRIDGE_VPS_KEY"]

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_ENABLED = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)

# Sondes dont on coupe les alertes Telegram (probe continue, dashboard + log
# JSONL gardent la trace). Utile quand un bridge passe hot-spare : on veut
# savoir s'il est UP/DOWN dans le dashboard mais pas se faire spammer.
TG_SILENCED_PROBES = set(
    n.strip() for n in os.getenv("MONITOR_TG_SILENCED", "").split(",") if n.strip()
)

WEB_BIND_HOST = os.getenv("WEB_BIND_HOST", "100.103.107.75")
WEB_BIND_PORT = int(os.getenv("WEB_BIND_PORT", "8090"))

LOG_PATH = Path(os.getenv("LOG_PATH", "/var/log/scalping/bridge_monitor.log"))
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

SYSTEMD_SERVICES = [
    s.strip()
    for s in os.getenv(
        "SYSTEMD_SERVICES",
        "scalping.service,scalping-bridge-monitor.service,nginx.service",
    ).split(",")
    if s.strip()
]

# ------- extended sondes config -------
TRADES_DB_PATH = os.getenv("TRADES_DB_PATH", "/opt/scalping/data/trades.db")
RADAR_CYCLE_MAX_AGE_SEC = int(os.getenv("RADAR_CYCLE_MAX_AGE_SEC", "300"))  # 5 min
DISK_WARN_PCT = float(os.getenv("DISK_WARN_PCT", "85"))
TAILSCALE_TRACKED_HOSTS = [
    h.strip()
    for h in os.getenv("TAILSCALE_TRACKED_HOSTS", "ec2amaz-f7osd1r").split(",")
    if h.strip()
]

# ------- auto-recovery config -------
# Set AUTO_RECOVERY_ENABLED=true to actually take corrective actions.
# When false, the framework still computes the would-be action and logs it.
AUTO_RECOVERY_ENABLED = os.getenv("AUTO_RECOVERY_ENABLED", "false").lower() == "true"
RECOVERY_ACTIONS_ENABLED = set(
    a.strip()
    for a in os.getenv(
        "RECOVERY_ACTIONS_ENABLED",
        "restart_systemd,docker_prune",  # safe defaults; lightsail reboot opt-in
    ).split(",")
    if a.strip()
)
LIGHTSAIL_INSTANCE_NAME = os.getenv("LIGHTSAIL_INSTANCE_NAME", "scalping-bridge-vps")
LIGHTSAIL_REGION = os.getenv("LIGHTSAIL_REGION", "eu-north-1")
LIGHTSAIL_REBOOT_GRACE_SEC = int(os.getenv("LIGHTSAIL_REBOOT_GRACE_SEC", "300"))  # only reboot after 5 min of confirmed DOWN

# ------- logging -------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
log = logging.getLogger("monitor")


# ------- state -------
_stop_evt = threading.Event()
_state_lock = threading.Lock()
_state: dict[str, dict] = {}
_last_cycle_ts: str = ""

# Recovery cooldown / rate-limit state.
# action_id -> {"attempts": [ts, ...], "last_ts": float}
_recovery_lock = threading.Lock()
_recovery_state: dict[str, dict] = {}
# Recent recovery attempts (rolling buffer for dashboard display)
_recovery_history: list[dict] = []
_RECOVERY_HISTORY_MAX = 20


def _signal_handler(signum, _frame):
    log.info("signal %s received, shutting down", signum)
    _stop_evt.set()


signal.signal(signal.SIGTERM, _signal_handler)
signal.signal(signal.SIGINT, _signal_handler)


# ------- probes -------
def probe_bridge(name: str, base_url: str, api_key: str) -> dict:
    out = {"name": name, "kind": "bridge", "url": base_url}
    t0 = time.perf_counter()
    try:
        r = requests.get(f"{base_url}/health", timeout=REQUEST_TIMEOUT_SEC)
        out["health_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        out["health_code"] = r.status_code
        if r.ok:
            h = r.json()
            out["health"] = h
            if not h.get("ok"):
                out["health_error"] = f"health.ok=false (payload={h})"
        else:
            out["health_error"] = r.text[:200]
            return out
    except requests.RequestException as e:
        out["health_error"] = f"{type(e).__name__}: {e}"
        return out

    t1 = time.perf_counter()
    try:
        r = requests.get(
            f"{base_url}/account",
            headers={"X-API-Key": api_key},
            timeout=REQUEST_TIMEOUT_SEC,
        )
        out["account_ms"] = round((time.perf_counter() - t1) * 1000, 1)
        out["account_code"] = r.status_code
        if r.ok:
            a = r.json()
            out["account"] = {
                k: a.get(k)
                for k in (
                    "login",
                    "currency",
                    "balance",
                    "equity",
                    "margin",
                    "margin_free",
                    "profit",
                    "positions_count",
                )
            }
        else:
            out["account_error"] = r.text[:200]
    except requests.RequestException as e:
        out["account_error"] = f"{type(e).__name__}: {e}"
    return out


def probe_systemd(name: str) -> dict:
    out = {"name": name, "kind": "systemd"}
    try:
        r = subprocess.run(
            ["systemctl", "is-active", name],
            capture_output=True,
            text=True,
            timeout=5,
        )
        state = r.stdout.strip() or r.stderr.strip()
        out["active"] = state
        out["ok"] = state == "active"
    except subprocess.TimeoutExpired:
        out["active"] = "timeout"
        out["ok"] = False
    except Exception as e:
        out["active"] = f"error: {type(e).__name__}"
        out["ok"] = False
    return out


def is_up(probe: dict) -> bool:
    kind = probe.get("kind")
    if kind == "bridge":
        if probe.get("health_error") or probe.get("account_error"):
            return False
        return bool(probe.get("health", {}).get("ok"))
    if kind == "systemd":
        return bool(probe.get("ok"))
    if kind in {"data", "disk", "tailscale"}:
        return bool(probe.get("ok"))
    return False


# ------- extended probes -------
def probe_radar_cycle() -> dict:
    """Confirm the radar is producing rows in signal_rejections recently.

    The radar emits a row to signal_rejections each time a candidate is dropped
    below the confidence/SL threshold — which happens dozens of times per cycle
    in practice. If the most recent row is older than RADAR_CYCLE_MAX_AGE_SEC,
    the radar is considered frozen even if scalping.service shows active.
    """
    out = {"name": "radar_cycle", "kind": "data"}
    try:
        con = sqlite3.connect(
            f"file:{TRADES_DB_PATH}?mode=ro", uri=True, timeout=2
        )
        try:
            cur = con.execute("SELECT MAX(created_at) FROM signal_rejections")
            row = cur.fetchone()
            last_iso = row[0] if row else None
        finally:
            con.close()
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        out["ok"] = False
        return out

    if not last_iso:
        out["error"] = "no rows in signal_rejections"
        out["ok"] = False
        return out

    try:
        last_dt = datetime.fromisoformat(last_iso)
    except ValueError:
        out["error"] = f"unparsable iso: {last_iso}"
        out["ok"] = False
        return out

    now_dt = datetime.now(timezone.utc)
    age_sec = (now_dt - last_dt).total_seconds()
    out["last_event_iso"] = last_iso
    out["age_sec"] = round(age_sec)
    out["ok"] = age_sec <= RADAR_CYCLE_MAX_AGE_SEC
    if not out["ok"]:
        out["error"] = (
            f"last cycle event {round(age_sec)}s ago, "
            f"max={RADAR_CYCLE_MAX_AGE_SEC}s"
        )
    return out


def probe_disk() -> dict:
    out = {"name": "disk_root", "kind": "disk"}
    try:
        usage = shutil.disk_usage("/")
        used_pct = (usage.used / usage.total) * 100
        out["used_pct"] = round(used_pct, 1)
        out["free_gb"] = round(usage.free / (1024 ** 3), 2)
        out["total_gb"] = round(usage.total / (1024 ** 3), 2)
        out["ok"] = used_pct < DISK_WARN_PCT
        if not out["ok"]:
            out["error"] = (
                f"disk {used_pct:.1f}% used (threshold {DISK_WARN_PCT}%)"
            )
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        out["ok"] = False
    return out


def probe_tailscale() -> dict:
    out = {"name": "tailscale", "kind": "tailscale"}
    try:
        r = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode != 0:
            out["error"] = f"tailscale exit={r.returncode}: {r.stderr[:120]}"
            out["ok"] = False
            return out
        data = json.loads(r.stdout)
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        out["ok"] = False
        return out

    peers = data.get("Peer") or {}
    nodes = []
    any_critical_offline = False
    for _, peer in peers.items():
        host = peer.get("HostName") or ""
        for tracked in TAILSCALE_TRACKED_HOSTS:
            if tracked in host:
                online = bool(peer.get("Online", False))
                nodes.append({"host": host, "online": online, "tracked": tracked})
                if not online:
                    any_critical_offline = True
                break
    out["nodes"] = nodes
    out["ok"] = not any_critical_offline
    if not out["ok"]:
        offline = [n["host"] for n in nodes if not n["online"]]
        out["error"] = f"tailscale tracked nodes offline: {offline}"
    return out


# ------- auto-recovery -------
def _recovery_can_attempt(
    action: str,
    cooldown_sec: int,
    max_in_window: int = 3,
    window_sec: int = 3600,
) -> tuple[bool, str]:
    """Return (allowed, reason_if_blocked)."""
    now = time.time()
    with _recovery_lock:
        st = _recovery_state.setdefault(action, {"attempts": [], "last_ts": 0.0})
        st["attempts"] = [t for t in st["attempts"] if now - t < window_sec]
        if now - st["last_ts"] < cooldown_sec:
            return False, f"cooldown {int(cooldown_sec - (now - st['last_ts']))}s"
        if len(st["attempts"]) >= max_in_window:
            return False, (
                f"rate-limit {len(st['attempts'])}/{max_in_window} in last "
                f"{window_sec}s"
            )
    return True, ""


def _recovery_record(action: str) -> None:
    now = time.time()
    with _recovery_lock:
        st = _recovery_state.setdefault(action, {"attempts": [], "last_ts": 0.0})
        st["attempts"].append(now)
        st["last_ts"] = now


def _recovery_log(entry: dict) -> None:
    """Append to dashboard rolling history."""
    with _recovery_lock:
        _recovery_history.append(entry)
        if len(_recovery_history) > _RECOVERY_HISTORY_MAX:
            del _recovery_history[: -_RECOVERY_HISTORY_MAX]


def attempt_recovery(name: str, probe: dict, st: dict) -> dict | None:
    """Best-effort corrective action. Returns recovery summary or None."""
    kind = probe.get("kind")
    summary: dict = {"name": name, "ts": datetime.now(timezone.utc).isoformat()}

    chosen_action = None  # action_id used for cooldown bookkeeping
    cmd: list[str] | None = None
    cooldown_sec = 300
    max_in_window = 3
    window_sec = 3600

    # systemd: restart the service
    if kind == "systemd":
        chosen_action = f"restart_{name}"
        if "restart_systemd" not in RECOVERY_ACTIONS_ENABLED:
            summary["action"] = chosen_action
            summary["ok"] = False
            summary["detail"] = "action 'restart_systemd' disabled"
            _recovery_log(summary)
            return summary
        cmd = ["systemctl", "restart", name]
        cooldown_sec = 300
        max_in_window = 3
        window_sec = 3600

    # data freshness loss usually means the radar (scalping.service) is wedged
    # even if systemctl shows active — try restart of scalping.service.
    elif kind == "data" and name == "radar_cycle":
        chosen_action = "restart_scalping_via_radar_cycle"
        if "restart_systemd" not in RECOVERY_ACTIONS_ENABLED:
            summary["action"] = chosen_action
            summary["ok"] = False
            summary["detail"] = "action 'restart_systemd' disabled"
            _recovery_log(summary)
            return summary
        cmd = ["systemctl", "restart", "scalping.service"]
        cooldown_sec = 600  # don't thrash the radar
        max_in_window = 2
        window_sec = 3600

    # disk: prune docker images
    elif kind == "disk":
        chosen_action = "docker_prune"
        if "docker_prune" not in RECOVERY_ACTIONS_ENABLED:
            summary["action"] = chosen_action
            summary["ok"] = False
            summary["detail"] = "action 'docker_prune' disabled"
            _recovery_log(summary)
            return summary
        cmd = ["docker", "image", "prune", "-f"]
        cooldown_sec = 86400
        max_in_window = 2
        window_sec = 86400

    # bridge VPS DOWN: reboot via Lightsail (requires IAM)
    elif kind == "bridge" and name == "bridge_vps":
        chosen_action = "reboot_lightsail_vps"
        if "lightsail_reboot" not in RECOVERY_ACTIONS_ENABLED:
            summary["action"] = chosen_action
            summary["ok"] = False
            summary["detail"] = (
                "action 'lightsail_reboot' disabled — requires IAM role on EC2 + "
                "explicit opt-in via RECOVERY_ACTIONS_ENABLED env var"
            )
            _recovery_log(summary)
            return summary
        # Only reboot after grace period of confirmed DOWN
        down_for = time.time() - st.get("last_change_ts", time.time())
        if down_for < LIGHTSAIL_REBOOT_GRACE_SEC:
            summary["action"] = chosen_action
            summary["ok"] = False
            summary["detail"] = (
                f"grace period: VPS down for {int(down_for)}s, "
                f"reboot after {LIGHTSAIL_REBOOT_GRACE_SEC}s"
            )
            _recovery_log(summary)
            return summary
        cmd = [
            "aws",
            "lightsail",
            "reboot-instance",
            "--instance-name",
            LIGHTSAIL_INSTANCE_NAME,
            "--region",
            LIGHTSAIL_REGION,
        ]
        cooldown_sec = 1800
        max_in_window = 2
        window_sec = 86400

    if not chosen_action or not cmd:
        return None  # no recovery defined for this probe kind

    # Cooldown / rate limit
    can, why = _recovery_can_attempt(
        chosen_action, cooldown_sec, max_in_window, window_sec
    )
    if not can:
        summary["action"] = chosen_action
        summary["ok"] = False
        summary["detail"] = f"skipped: {why}"
        _recovery_log(summary)
        return summary

    # Master switch
    if not AUTO_RECOVERY_ENABLED:
        summary["action"] = chosen_action
        summary["ok"] = False
        summary["detail"] = "AUTO_RECOVERY_ENABLED=false (would-be action)"
        summary["would_run"] = " ".join(cmd)
        _recovery_log(summary)
        return summary

    # Execute
    log.info("recovery: running %s", " ".join(cmd))
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        ok = r.returncode == 0
        detail = (r.stdout or "").strip()[:200] or (r.stderr or "").strip()[:200]
        summary["action"] = chosen_action
        summary["ok"] = ok
        summary["detail"] = detail or ("ran" if ok else "non-zero exit")
        summary["cmd"] = " ".join(cmd)
        _recovery_record(chosen_action)
        _recovery_log(summary)
        return summary
    except Exception as e:
        summary["action"] = chosen_action
        summary["ok"] = False
        summary["detail"] = f"{type(e).__name__}: {e}"
        summary["cmd"] = " ".join(cmd)
        _recovery_log(summary)
        return summary


# ------- Telegram helpers -------
def tg_send(msg: str) -> None:
    if not TELEGRAM_ENABLED:
        log.debug("telegram disabled, skip: %s", msg)
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": msg,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        if not r.ok:
            log.warning("telegram send http=%s body=%s", r.status_code, r.text[:200])
    except requests.RequestException as e:
        log.warning("telegram send failed: %s", e)


def tg_format_alert(
    name: str, status: str, probe: dict, recovery: dict | None = None
) -> str:
    emoji = {"DOWN": "🚨", "UP": "✅", "STILL_DOWN": "⚠️"}.get(status, "ℹ️")
    verb = {
        "DOWN": "DOWN",
        "UP": "RECOVERED",
        "STILL_DOWN": "still DOWN",
    }.get(status, status)
    parts = [f"{emoji} *{name}* {verb}"]
    kind = probe.get("kind")
    if kind == "bridge":
        err = probe.get("health_error") or probe.get("account_error")
        if err:
            parts.append(f"detail: `{err[:150]}`")
        acc = probe.get("account") or {}
        if acc and status == "UP":
            parts.append(
                f"balance {acc.get('balance')} {acc.get('currency')}, "
                f"{acc.get('positions_count')} pos"
            )
    elif kind == "systemd":
        parts.append(f"systemctl: `{probe.get('active')}`")
    elif kind == "data":
        if probe.get("error"):
            parts.append(f"detail: `{probe['error'][:150]}`")
        if probe.get("age_sec") is not None:
            parts.append(f"age: {probe['age_sec']}s")
    elif kind == "disk":
        if probe.get("used_pct") is not None:
            parts.append(
                f"used: {probe['used_pct']}% · free: {probe.get('free_gb')} GB"
            )
    elif kind == "tailscale":
        if probe.get("error"):
            parts.append(f"detail: `{probe['error'][:150]}`")

    if recovery:
        rec_emoji = "🔧" if recovery.get("ok") else "🛑"
        parts.append(
            f"{rec_emoji} recovery `{recovery.get('action')}`: "
            f"{recovery.get('detail', '')[:120]}"
        )
    parts.append(f"_{datetime.now(timezone.utc).isoformat(timespec='seconds')}_")
    return "\n".join(parts)


# ------- core polling loop -------
def evaluate_and_alert(probe: dict) -> dict:
    """Update _state for this probe, emit alerts on transitions."""
    name = probe["name"]
    up = is_up(probe)
    now = time.time()

    with _state_lock:
        st = _state.setdefault(
            name,
            {
                "confirmed": "UNKNOWN",
                "last_probe_up": None,
                "consec_down": 0,
                "last_change_ts": now,
                "last_reminder_ts": 0.0,
                "last_probe": None,
                "last_recovery": None,
            },
        )
        st["last_probe"] = probe
        st["last_probe_up"] = up
        prev_confirmed = st["confirmed"]

        silenced = name in TG_SILENCED_PROBES
        recovery: dict | None = None

        if up:
            st["consec_down"] = 0
            if prev_confirmed != "UP":
                st["confirmed"] = "UP"
                st["last_change_ts"] = now
                if prev_confirmed == "DOWN" and not silenced:
                    tg_send(tg_format_alert(name, "UP", probe))
        else:
            st["consec_down"] += 1
            if st["consec_down"] >= DOWN_CONFIRM_CYCLES and prev_confirmed != "DOWN":
                st["confirmed"] = "DOWN"
                st["last_change_ts"] = now
                st["last_reminder_ts"] = now
                # Try corrective action on first confirmed DOWN
                recovery = attempt_recovery(name, probe, st)
                if recovery:
                    st["last_recovery"] = recovery
                if not silenced:
                    tg_send(tg_format_alert(name, "DOWN", probe, recovery))
            elif prev_confirmed == "DOWN" and (
                now - st["last_reminder_ts"]
            ) >= REMINDER_EVERY_SEC:
                st["last_reminder_ts"] = now
                # On STILL_DOWN reminder, try recovery again (cooldown allowing)
                recovery = attempt_recovery(name, probe, st)
                if recovery:
                    st["last_recovery"] = recovery
                if not silenced:
                    tg_send(tg_format_alert(name, "STILL_DOWN", probe, recovery))
        return dict(st)


def do_cycle() -> dict:
    """One polling cycle: probe everything, update state, write log line."""
    global _last_cycle_ts
    results = {}

    probes = []
    if BRIDGE_LOCAL_ENABLED:
        probes.append(probe_bridge("bridge_local", BRIDGE_LOCAL_URL, BRIDGE_LOCAL_KEY))
    probes.append(probe_bridge("bridge_vps", BRIDGE_VPS_URL, BRIDGE_VPS_KEY))
    for svc in SYSTEMD_SERVICES:
        probes.append(probe_systemd(svc))
    # Extended sondes
    probes.append(probe_radar_cycle())
    probes.append(probe_disk())
    probes.append(probe_tailscale())

    for p in probes:
        evaluate_and_alert(p)
        results[p["name"]] = p

    ts = datetime.now(timezone.utc).isoformat()
    _last_cycle_ts = ts
    with LOG_PATH.open("a", buffering=1) as fh:
        rec = {"ts": ts, "probes": results, "confirmed": {
            name: st["confirmed"]
            for name, st in _state.items()
        }}
        fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
    return results


def poller_thread():
    log.info("poller starting — interval=%ss", POLL_INTERVAL_SEC)
    while not _stop_evt.is_set():
        cycle_start = time.time()
        try:
            do_cycle()
        except Exception as e:
            log.exception("cycle error: %s", e)
        elapsed = time.time() - cycle_start
        sleep_for = max(1.0, POLL_INTERVAL_SEC - elapsed)
        _stop_evt.wait(sleep_for)
    log.info("poller stopped")


# ------- dashboard -------
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="fr"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="10">
<title>Scalping Infra — {TS}</title>
<style>
  body {{ background:#0d1117; color:#e6edf3; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; margin:0; padding:16px; }}
  h1 {{ font-size:18px; font-weight:600; margin:0 0 12px; color:#7ee787; }}
  .subtitle {{ font-size:12px; color:#8b949e; margin:0 0 18px; }}
  table {{ width:100%; border-collapse:collapse; font-size:14px; }}
  th {{ text-align:left; padding:8px 10px; border-bottom:1px solid #30363d; color:#8b949e; font-weight:500; font-size:11px; text-transform:uppercase; letter-spacing:0.5px; }}
  td {{ padding:12px 10px; border-bottom:1px solid #21262d; vertical-align:middle; }}
  .badge {{ display:inline-block; padding:3px 10px; border-radius:999px; font-weight:600; font-size:12px; letter-spacing:0.3px; }}
  .up {{ background:#1a4f2a; color:#7ee787; }}
  .down {{ background:#5c1a1a; color:#ff7b72; }}
  .unknown {{ background:#3b3b3b; color:#8b949e; }}
  .name {{ font-weight:500; }}
  .meta {{ color:#8b949e; font-size:12px; margin-top:2px; }}
  .detail {{ color:#8b949e; font-size:12px; font-family: ui-monospace,SFMono-Regular,Menlo,monospace; }}
  footer {{ margin-top:24px; color:#8b949e; font-size:11px; text-align:center; }}
</style>
</head><body>
<h1>⚡ Scalping Infra</h1>
<p class="subtitle">Mis à jour {TS_FR} (auto-refresh 10s)</p>
<table>
<thead><tr><th>Check</th><th>État</th><th>Détail</th></tr></thead>
<tbody>
{ROWS}
</tbody></table>
<footer>Scalping monitor — accessible uniquement via Tailscale</footer>
</body></html>
"""


def _fr_now(iso: str) -> str:
    if not iso:
        return "?"
    try:
        dt = datetime.fromisoformat(iso)
    except Exception:
        return iso
    # to Paris-ish (UTC+2 CEST in April, don't import pytz; simple approx)
    from datetime import timedelta
    paris = dt + timedelta(hours=2)
    return paris.strftime("%H:%M:%S Paris")


def render_row(name: str, st: dict) -> str:
    confirmed = st.get("confirmed", "UNKNOWN")
    probe = st.get("last_probe") or {}
    cls = confirmed.lower()
    since_sec = int(time.time() - st.get("last_change_ts", time.time()))
    h, m, s = since_sec // 3600, (since_sec % 3600) // 60, since_sec % 60
    since_str = f"{h}h{m:02d}m" if h else (f"{m}m{s:02d}s" if m else f"{s}s")

    detail_parts = []
    kind = probe.get("kind")
    if kind == "bridge":
        acc = probe.get("account") or {}
        if acc:
            detail_parts.append(
                f"{acc.get('login')} · bal {acc.get('balance')}{acc.get('currency','')} · {acc.get('positions_count')}p"
            )
        hms = probe.get("health_ms")
        ams = probe.get("account_ms")
        if hms is not None and ams is not None:
            detail_parts.append(f"h={hms}ms a={ams}ms")
        err = probe.get("health_error") or probe.get("account_error")
        if err:
            detail_parts.append(f"err: {html.escape(err[:80])}")
    elif kind == "systemd":
        detail_parts.append(f"systemctl: {probe.get('active', '?')}")
    elif kind == "data":
        age = probe.get("age_sec")
        if age is not None:
            detail_parts.append(f"last event {age}s ago")
        if probe.get("error"):
            detail_parts.append(f"err: {html.escape(probe['error'][:80])}")
    elif kind == "disk":
        used = probe.get("used_pct")
        free = probe.get("free_gb")
        if used is not None:
            detail_parts.append(f"{used}% used · {free} GB free")
        if probe.get("error"):
            detail_parts.append(f"err: {html.escape(probe['error'][:80])}")
    elif kind == "tailscale":
        nodes = probe.get("nodes") or []
        if nodes:
            chunks = [
                f"{n['host']}={'on' if n['online'] else 'off'}" for n in nodes
            ]
            detail_parts.append(" ".join(chunks))
        if probe.get("error"):
            detail_parts.append(f"err: {html.escape(probe['error'][:80])}")

    rec = st.get("last_recovery")
    if rec:
        rec_class = "up" if rec.get("ok") else "down"
        action_label = html.escape(str(rec.get("action", "")))
        rec_detail = html.escape(str(rec.get("detail", ""))[:80])
        detail_parts.append(
            f'<span class="badge {rec_class}" style="font-size:10px">'
            f"{action_label}</span> {rec_detail}"
        )

    detail = " · ".join(detail_parts) if detail_parts else "—"
    return f"""<tr>
  <td><div class="name">{html.escape(name)}</div><div class="meta">since {since_str}</div></td>
  <td><span class="badge {cls}">{confirmed}</span></td>
  <td class="detail">{detail}</td>
</tr>"""


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "scalping-monitor/1.0"

    def log_message(self, format, *args):
        log.debug("http %s %s", self.address_string(), format % args)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/infra", "/infra/"):
            self._serve_html()
        elif path == "/status.json":
            self._serve_json()
        elif path == "/health":
            self._serve_plain("ok")
        else:
            self.send_error(404, "Not found")

    def _serve_plain(self, body: str):
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_json(self):
        with _state_lock:
            snap = {
                name: {
                    "confirmed": st["confirmed"],
                    "last_change_ts": st["last_change_ts"],
                    "last_probe": st["last_probe"],
                    "last_recovery": st.get("last_recovery"),
                }
                for name, st in _state.items()
            }
        with _recovery_lock:
            recoveries = list(_recovery_history)
        payload = json.dumps(
            {
                "ts": _last_cycle_ts,
                "services": snap,
                "recoveries": recoveries,
                "auto_recovery_enabled": AUTO_RECOVERY_ENABLED,
                "actions_enabled": sorted(RECOVERY_ACTIONS_ENABLED),
            },
            separators=(",", ":"),
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _serve_html(self):
        with _state_lock:
            order = [
                "bridge_vps",
                "bridge_local",
                "radar_cycle",
                "scalping.service",
                "scalping-bridge-monitor.service",
                "nginx.service",
                "tailscale",
                "disk_root",
            ]
            seen = set()
            rows = []
            for name in order:
                if name in _state:
                    rows.append(render_row(name, _state[name]))
                    seen.add(name)
            for name, st in _state.items():
                if name not in seen:
                    rows.append(render_row(name, st))

        body = DASHBOARD_HTML.format(
            TS=_last_cycle_ts or "—",
            TS_FR=_fr_now(_last_cycle_ts),
            ROWS="\n".join(rows) or "<tr><td colspan='3'>Aucun check encore exécuté</td></tr>",
        )
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def dashboard_thread():
    try:
        srv = ThreadingHTTPServer((WEB_BIND_HOST, WEB_BIND_PORT), DashboardHandler)
    except OSError as e:
        log.error("cannot bind dashboard on %s:%s — %s", WEB_BIND_HOST, WEB_BIND_PORT, e)
        return
    log.info("dashboard on http://%s:%s/infra", WEB_BIND_HOST, WEB_BIND_PORT)
    srv.timeout = 1
    while not _stop_evt.is_set():
        srv.handle_request()
    srv.server_close()
    log.info("dashboard stopped")


# ------- Telegram command listener (/status) -------
def tg_build_status_reply() -> str:
    with _state_lock:
        if not _state:
            return "📡 monitor warming up, pas encore de données"
        lines = ["*Scalping Infra Status*", ""]
        for name in sorted(_state.keys()):
            st = _state[name]
            emoji = {"UP": "✅", "DOWN": "🚨", "UNKNOWN": "❓"}.get(
                st["confirmed"], "❓"
            )
            since = int(time.time() - st.get("last_change_ts", time.time()))
            h, m = since // 3600, (since % 3600) // 60
            since_str = f"{h}h{m:02d}m" if h else f"{m}m"
            lines.append(f"{emoji} `{name}` · {st['confirmed']} · {since_str}")
        lines.append("")
        lines.append(f"_updated {_last_cycle_ts[:19] if _last_cycle_ts else '?'}Z_")
        return "\n".join(lines)


def telegram_listener_thread():
    if not TELEGRAM_ENABLED:
        log.info("telegram disabled, /status listener not started")
        return
    offset = None
    log.info("telegram listener starting")
    while not _stop_evt.is_set():
        try:
            params = {"timeout": 25}
            if offset is not None:
                params["offset"] = offset
            r = requests.get(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates",
                params=params,
                timeout=30,
            )
            if not r.ok:
                log.warning("getUpdates http=%s", r.status_code)
                _stop_evt.wait(5)
                continue
            data = r.json()
            for upd in data.get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message") or upd.get("channel_post") or {}
                text = (msg.get("text") or "").strip()
                chat_id = str((msg.get("chat") or {}).get("id", ""))
                if chat_id != TELEGRAM_CHAT_ID:
                    continue
                if text.lower().startswith("/status"):
                    tg_send(tg_build_status_reply())
                elif text.lower().startswith("/start"):
                    tg_send("Bot infra actif. Envoie `/status` pour un snapshot.")
        except requests.RequestException as e:
            log.warning("telegram poll error: %s", e)
            _stop_evt.wait(5)
        except Exception as e:
            log.exception("telegram listener error: %s", e)
            _stop_evt.wait(5)
    log.info("telegram listener stopped")


# ------- main -------
def main() -> int:
    log.info(
        "starting: local=%s vps=%s telegram=%s dashboard=%s:%s",
        BRIDGE_LOCAL_URL or "(disabled)",
        BRIDGE_VPS_URL,
        "on" if TELEGRAM_ENABLED else "off",
        WEB_BIND_HOST,
        WEB_BIND_PORT,
    )
    auto_label = (
        "auto-recovery ON: "
        + ", ".join(sorted(RECOVERY_ACTIONS_ENABLED))
        if AUTO_RECOVERY_ENABLED
        else "auto-recovery OFF (would-be actions logged)"
    )
    tg_send(
        f"🟢 *scalping infra monitor started* on `{os.uname().nodename}`\n"
        f"dashboard: http://{WEB_BIND_HOST}:{WEB_BIND_PORT}/infra\n"
        f"{auto_label}"
    )

    threads = []
    t_poll = threading.Thread(target=poller_thread, name="poller", daemon=True)
    t_poll.start()
    threads.append(t_poll)

    t_web = threading.Thread(target=dashboard_thread, name="dashboard", daemon=True)
    t_web.start()
    threads.append(t_web)

    t_tg = threading.Thread(target=telegram_listener_thread, name="telegram", daemon=True)
    t_tg.start()
    threads.append(t_tg)

    _stop_evt.wait()
    log.info("shutdown in progress")
    for t in threads:
        t.join(timeout=5)
    log.info("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
