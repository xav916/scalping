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
from datetime import datetime, timezone, timedelta
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
BRIDGE_LIVE_URL = os.environ.get("BRIDGE_LIVE_URL", "").strip()
BRIDGE_LIVE_KEY = os.environ.get("BRIDGE_LIVE_KEY", "").strip()
BRIDGE_LIVE_ENABLED = bool(BRIDGE_LIVE_URL and BRIDGE_LIVE_KEY)
QUOTE_PAIR = os.environ.get("QUOTE_PAIR", "EUR/USD").strip()
QUOTE_STALE_MAX_SEC = int(os.environ.get("QUOTE_STALE_MAX_SEC", "900"))
BRIDGE_IBKR_URL = os.environ.get("BRIDGE_IBKR_URL", "").strip()
BRIDGE_IBKR_KEY = os.environ.get("BRIDGE_IBKR_KEY", "").strip()
BRIDGE_IBKR_ENABLED = bool(BRIDGE_IBKR_URL)

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
def probe_bridge(
    name: str, base_url: str, api_key: str, quote_pair: str | None = None,
    key_header: str = "X-API-Key",
) -> dict:
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
            # ⚠️ IBKR : `ok` peut etre vrai alors que la socket vers IB
            # Gateway est morte. `connected` est le seul champ qui dit si
            # le port 4001 repond — la panne du 12-19/08 est restee
            # invisible sept jours faute de le regarder.
            elif "connected" in h and not h.get("connected"):
                out["health_error"] = "connected=false — Gateway injoignable"
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
            headers={key_header: api_key},
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

    # Horodatage de la derniere cotation. Un bridge peut repondre ok:true
    # pendant des heures avec un terminal MT5 deconnecte du courtier : seul
    # ce champ bouge (ou pas). Cf. panne du 2026-08-19.
    if quote_pair:
        t2 = time.perf_counter()
        try:
            r = requests.get(
                f"{base_url}/tick/{quote_pair}",
                headers={key_header: api_key},
                timeout=REQUEST_TIMEOUT_SEC,
            )
            out["quote_ms"] = round((time.perf_counter() - t2) * 1000, 1)
            out["quote_code"] = r.status_code
            if r.ok:
                t = r.json()
                out["quote_pair"] = quote_pair
                out["quote_ts"] = t.get("time")
                out["quote_bid"] = t.get("bid")
            else:
                out["quote_fetch_error"] = r.text[:200]
        except requests.RequestException as e:
            out["quote_fetch_error"] = f"{type(e).__name__}: {e}"
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
        if probe.get("quote_error"):
            return False
        return bool(probe.get("health", {}).get("ok"))
    if kind == "systemd":
        return bool(probe.get("ok"))
    if kind in {"data", "disk", "tailscale"}:
        return bool(probe.get("ok"))
    return False


# ------- extended probes -------
def probe_radar_cycle() -> dict:
    """Confirm the radar is producing cycles recently.

    Pre-2026-05-09: regardait MAX(signal_rejections.created_at) — proxy
    bruyant qui causait des restart inutiles 1-4×/h sur sessions calmes.

    Depuis 2026-05-09: regarde la table dédiée radar_cycle_heartbeat
    (peuplée par radar_heartbeat_service.record_cycle() à chaque cycle
    même quand 0 signal/0 rejection produit). Seuil resserré à 300s
    parce que les cycles tournent toutes les ~3-5 min en prod.

    Fallback : si la table heartbeat n'existe pas ou est vide (radar pas
    encore mis à jour), retombe sur l'ancien proxy signal_rejections.
    """
    out = {"name": "radar_cycle", "kind": "data"}
    last_iso = None
    source = None
    try:
        con = sqlite3.connect(
            f"file:{TRADES_DB_PATH}?mode=ro", uri=True, timeout=2
        )
        try:
            # Source primaire: heartbeat dédié.
            try:
                cur = con.execute(
                    "SELECT MAX(cycle_completed_at) FROM radar_cycle_heartbeat"
                )
                row = cur.fetchone()
                if row and row[0]:
                    last_iso = row[0]
                    source = "heartbeat"
            except sqlite3.OperationalError:
                # Table inexistante (vieux radar pas encore déployé).
                pass

            # Fallback: ancien proxy signal_rejections.
            if not last_iso:
                cur = con.execute(
                    "SELECT MAX(created_at) FROM signal_rejections"
                )
                row = cur.fetchone()
                last_iso = row[0] if row else None
                source = "signal_rejections_fallback"
        finally:
            con.close()
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        out["ok"] = False
        return out

    if not last_iso:
        out["error"] = "no rows in radar_cycle_heartbeat NOR signal_rejections"
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
    out["source"] = source
    out["ok"] = age_sec <= RADAR_CYCLE_MAX_AGE_SEC
    if not out["ok"]:
        out["error"] = (
            f"last cycle event {round(age_sec)}s ago "
            f"(source={source}), max={RADAR_CYCLE_MAX_AGE_SEC}s"
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

    # disk: la recuperation est DELEGUEE a disk-reclaim.timer, qui tourne en
    # root. Ce service-ci tourne en ec2-user avec NoNewPrivileges=yes : il ne
    # peut ni ecrire dans /opt/scalping/data (root) ni vider le journal
    # systemd. Son ancienne action `docker image prune -f` recuperait 0 B
    # pendant que le disque montait a 97 % -- un placebo, qui armait en plus
    # un verrou de 24 h meme quand il echouait.
    # On ne fait donc qu'une chose ici : dire ce que le reclaimer a fait.
    elif kind == "disk":
        summary["action"] = "disk_reclaim_delegue"
        summary["ok"] = True
        summary["detail"] = dernier_reclaim()
        _recovery_log(summary)
        return summary

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


RECLAIM_LOG = Path(os.getenv("RECLAIM_LOG", "/var/log/scalping/disk_reclaim.log"))


def dernier_reclaim() -> str:
    """Derniere ligne du journal de disk_reclaim.py, rendue lisible.

    Rend une phrase explicite quand le reclaimer ne s'est jamais exprime :
    un detail vide se lirait comme « rien a signaler » alors qu'il voudrait
    dire « je ne sais pas ».
    """
    try:
        lignes = [
            l for l in RECLAIM_LOG.read_text(errors="replace").splitlines() if l.strip()
        ]
    except OSError:
        return "recuperation deleguee a disk-reclaim.timer (aucun journal lisible)"
    if not lignes:
        return "recuperation deleguee a disk-reclaim.timer (journal vide)"
    try:
        d = json.loads(lignes[-1])
    except ValueError:
        return "recuperation deleguee a disk-reclaim.timer (derniere ligne illisible)"
    quand = str(d.get("ts", ""))[11:19]
    if d.get("decision") == "sous_le_seuil_rien_a_faire":
        return f"reclaimer {quand}Z : sous le seuil, rien a faire"
    libere = d.get("libere_mo", 0)
    av = (d.get("avant") or {}).get("used_pct")
    ap = (d.get("apres") or {}).get("used_pct")
    return f"reclaimer {quand}Z : {av}% -> {ap}%, {libere} Mo recuperes"


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
    """Format vulgarisé alerte infra (2026-06-13).
    Tout le monde doit comprendre : qu'est-ce qui se passe, pourquoi, quel impact.
    """
    # Vulgarisation du nom de probe
    _NAME_FR = {
        "bridge_local": "Bridge Démo",
        "bridge_demo": "Bridge Démo",
        "bridge_vps": "Bridge Démo",
        "bridge_live": "Bridge Live",
        "bridge_ibkr": "Bridge IBKR",
        "radar_cycle": "Cycle radar",
        "disk": "Espace disque serveur",
        "tailscale": "Réseau privé (Tailscale)",
        "systemd_scalping": "Service Scalping (radar)",
        "scalping": "Service Scalping (radar)",
    }
    name_fr = _NAME_FR.get(name, name)

    emoji = {"DOWN": "🚨", "UP": "✅", "STILL_DOWN": "⚠️"}.get(status, "ℹ️")
    verb_fr = {
        "DOWN": "est tombé",
        "UP": "récupéré",
        "STILL_DOWN": "toujours hors service",
    }.get(status, status)

    # Impact selon le composant
    _IMPACT = {
        "bridge_local": "Sans ce tunnel, le radar ne peut plus envoyer d'ordres au broker Démo.",
        "bridge_demo": "Sans ce tunnel, le radar ne peut plus envoyer d'ordres au broker Démo.",
        "bridge_vps": "Sans ce tunnel, le radar ne peut plus envoyer d'ordres au broker Démo.",
        "bridge_live": "Sans ce tunnel, aucun ordre Live ne part vers IC Markets — argent réel concerné.",
        "bridge_ibkr": "IB Gateway ne répond plus : aucune lecture ni aucun ordre IBKR. Souvent une double authentification à revalider.",
        "radar_cycle": "Le radar n'analyse plus le marché — aucun nouveau signal détecté.",
        "disk": "Si le disque sature, le service peut planter — impact sur le trading auto.",
        "tailscale": "Le réseau interne entre EC2 et le VPS bridge est en souci.",
        "systemd_scalping": "Le service principal du radar est arrêté — aucune analyse en cours.",
        "scalping": "Le service principal du radar est arrêté — aucune analyse en cours.",
    }
    impact_line = _IMPACT.get(name, "")

    parts = [f"{emoji} *{name_fr}* {verb_fr}"]
    parts.append("")

    kind = probe.get("kind")
    if kind == "bridge":
        err = probe.get("health_error") or probe.get("account_error")
        if err:
            parts.append(f"⚙️ Détail technique : `{err[:150]}`")
        acc = probe.get("account") or {}
        if acc and status == "UP":
            parts.append(
                f"💰 Compte : {acc.get('balance')} {acc.get('currency')} · "
                f"{acc.get('positions_count')} position(s) ouverte(s)"
            )
    elif kind == "systemd":
        parts.append(f"⚙️ État systemd : `{probe.get('active')}`")
    elif kind == "data":
        if probe.get("error"):
            parts.append(f"⚙️ Détail : `{probe['error'][:150]}`")
        if probe.get("age_sec") is not None:
            parts.append(f"⏱ Dernier signe de vie : il y a {probe['age_sec']} secondes")
    elif kind == "disk":
        if probe.get("used_pct") is not None:
            parts.append(
                f"💾 Utilisé : {probe['used_pct']}% · libre : {probe.get('free_gb')} GB"
            )
    elif kind == "tailscale":
        if probe.get("error"):
            parts.append(f"⚙️ Détail : `{probe['error'][:150]}`")

    if impact_line and status in ("DOWN", "STILL_DOWN"):
        parts.append("")
        parts.append(f"ℹ️ {impact_line}")
    elif status == "UP" and impact_line:
        parts.append("")
        parts.append(f"ℹ️ Composant à nouveau fonctionnel — activité normale reprend.")

    if recovery:
        rec_emoji = "🔧" if recovery.get("ok") else "🛑"
        rec_status = "réussie" if recovery.get("ok") else "échouée"
        parts.append("")
        parts.append(
            f"{rec_emoji} Récupération auto {rec_status} : `{recovery.get('action')}` "
            f"({recovery.get('detail', '')[:80]})"
        )

    # Footer : heure Paris au lieu d'ISO UTC technique
    paris_time = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%H:%M Paris")
    parts.append("")
    parts.append(f"_{paris_time}_")
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


_quote_state: dict[str, dict] = {}


def _track_quote(probe: dict) -> float | None:
    """Met a jour l'etat d'avancement du tick ; rend son age de gel en s."""
    ts = probe.get("quote_ts")
    if not ts:
        return None
    now = time.time()
    st = _quote_state.setdefault(probe["name"], {"ts": None, "since": now})
    if ts != st["ts"]:
        st["ts"] = ts
        st["since"] = now
    return now - st["since"]


def annotate_quote_staleness(probe: dict, witness: dict) -> None:
    """Signale un bridge qui repond mais ne recoit plus de cotations.

    La panne du 2026-08-19 etait invisible de /health : le bridge Live a
    rendu ok:true pendant 7h30 alors que son terminal MT5 avait perdu le
    lien avec IC Markets. Seul l'horodatage du tick avait cesse d'avancer.

    Les horloges courtier ne sont pas UTC (IC Markets et Pepperstone sont
    en UTC+3 et l'annoncent +00:00), donc un age absolu ne veut rien dire
    ici : on regarde si le tick *avance*. Le bridge demo sert de temoin
    d'ouverture de marche, sinon chaque week-end declencherait une alerte.
    """
    frozen = _track_quote(probe)
    witness_frozen = _track_quote(witness)
    if frozen is None or frozen < QUOTE_STALE_MAX_SEC:
        return
    if witness_frozen is None or witness_frozen >= QUOTE_STALE_MAX_SEC:
        return  # temoin gele aussi -> marche ferme, pas une panne
    probe["quote_frozen_sec"] = int(frozen)
    probe["quote_error"] = (
        f"cotations figees depuis {int(frozen)}s "
        f"(dernier tick {probe.get('quote_ts')}) alors que "
        f"{witness.get('name')} avance — terminal MT5 deconnecte ?"
    )


def do_cycle() -> dict:
    """One polling cycle: probe everything, update state, write log line."""
    global _last_cycle_ts
    results = {}

    probes = []
    if BRIDGE_LOCAL_ENABLED:
        probes.append(probe_bridge("bridge_local", BRIDGE_LOCAL_URL, BRIDGE_LOCAL_KEY))
    demo_probe = probe_bridge(
        "bridge_vps", BRIDGE_VPS_URL, BRIDGE_VPS_KEY, quote_pair=QUOTE_PAIR
    )
    probes.append(demo_probe)
    if BRIDGE_LIVE_ENABLED:
        live_probe = probe_bridge(
            "bridge_live", BRIDGE_LIVE_URL, BRIDGE_LIVE_KEY,
            quote_pair=QUOTE_PAIR,
        )
        annotate_quote_staleness(live_probe, demo_probe)
        probes.append(live_probe)
    if BRIDGE_IBKR_ENABLED:
        probes.append(probe_bridge(
            "bridge_ibkr", BRIDGE_IBKR_URL, BRIDGE_IBKR_KEY,
            key_header="X-Bridge-Key",
        ))
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
                "bridge_live",
                "bridge_ibkr",
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
    """Format vulgarisé (2026-06-13) : tout le monde doit comprendre l'état."""
    _NAME_FR = {
        "bridge_local": "Bridge Démo",
        "bridge_demo": "Bridge Démo",
        "bridge_vps": "Bridge Démo",
        "bridge_live": "Bridge Live",
        "bridge_ibkr": "Bridge IBKR",
        "radar_cycle": "Cycle radar",
        "disk": "Espace disque",
        "tailscale": "Réseau privé",
        "systemd_scalping": "Service Scalping",
        "scalping": "Service Scalping",
    }
    _STATE_FR = {"UP": "OK", "DOWN": "en panne", "UNKNOWN": "inconnu"}
    with _state_lock:
        if not _state:
            return "📡 Surveillance en cours de démarrage, pas encore de données.\n\nℹ️ Réessaie dans une minute."
        lines = ["*📡 État de l'infrastructure*", ""]
        for name in sorted(_state.keys()):
            st = _state[name]
            emoji = {"UP": "✅", "DOWN": "🚨", "UNKNOWN": "❓"}.get(
                st["confirmed"], "❓"
            )
            since = int(time.time() - st.get("last_change_ts", time.time()))
            h, m = since // 3600, (since % 3600) // 60
            since_str = f"{h}h{m:02d}m" if h else f"{m}m"
            name_fr = _NAME_FR.get(name, name)
            state_fr = _STATE_FR.get(st["confirmed"], st["confirmed"])
            if st["confirmed"] == "UP":
                lines.append(f"{emoji} {name_fr} · OK depuis {since_str}")
            elif st["confirmed"] == "DOWN":
                lines.append(f"{emoji} {name_fr} · en panne depuis {since_str}")
            else:
                lines.append(f"{emoji} {name_fr} · {state_fr}")
        lines.append("")
        lines.append("ℹ️ Le radar et ses canaux d'exécution sont opérationnels (sauf indication contraire).")
        lines.append("")
        if _last_cycle_ts:
            try:
                t = datetime.fromisoformat(_last_cycle_ts.replace("Z", "+00:00"))
                paris = (t + timedelta(hours=2)).strftime("%H:%M Paris")
                lines.append(f"_Dernière vérification : {paris}_")
            except Exception:
                lines.append(f"_Dernière vérification : {_last_cycle_ts[:19]}Z_")
        else:
            lines.append("_Pas encore de vérification effectuée_")
        return "\n".join(lines)


# ─── La commande /trade (2026-10-10) ────────────────────────────────────
#
# Demandee par Xavier : << lancer un trade par Telegram >>.
#
# ⛔ CE QU'ELLE NE FAIT PAS : elle ne choisit pas le sens, et elle ne construit
# aucun setup. Elle declenche le CYCLE DE PRODUCTION restreint a l'or
# (`declencheur_manuel`), qui applique toutes les portes habituelles.
#
# 🔑 POURQUOI PAS LE SENS. Mesure du 2026-10-10 : la direction du radar est
# indiscernable du hasard (5 jours, n=59, horizons 1 a 60 min, aucune p-valeur
# sous 0,27, reussite 42-54 %), et celle de Xavier n'est mesurable que sur un
# jour, ou elle ne bat pas un biais acheteur constant. Aucune base pour ouvrir
# un chemin dedie vers l'argent reel.
#
# ⛔ Et l'entree officielle des signaux externes est barree par conception :
#     bridge_destinations.py :  if externe:  # n'atteint JAMAIS l'argent reel
#
# ⚠️ On passe par `docker exec`, comme TOUS les autres jobs de cet hote
# (`/opt/scalping/jobs/*.sh`) : aucun rebuild, et REM-002 reste intact.

_TRADE_OR = {"", "OR", "GOLD", "XAUUSD", "XAU/USD", "XAU"}
_TRADE_SENS = {"BUY", "SELL", "ACHAT", "VENTE", "LONG", "SHORT"}


def parse_commande_trade(texte):
    """Rend `"XAU/USD"`, `None`, ou `"REFUS: <motif>"`.

    ⛔ `None` veut dire << ce n'est pas la commande >> ; `REFUS:` veut dire
    << c'est la commande, mais je ne la fais pas, et voici pourquoi >>. Les
    confondre laisserait Xavier sans reponse.
    """
    t = (texte or "").strip()
    if not t.startswith("/"):
        return None
    mot, _, reste = t.partition(" ")
    mot = mot.split("@", 1)[0].lower()      # /trade@mon_bot -> /trade
    # ⛔ Egalite STRICTE : accepter tout ce qui commence par /trade volerait
    # le nom de commandes futures (/trades, /tradeur).
    if mot != "/trade":
        return None
    arg = reste.strip().upper()
    if arg in _TRADE_SENS:
        return ("REFUS: le sens n'est pas pris en compte. Mesure du 10/10 sur "
                "5 jours (n=59) : la direction est indiscernable du hasard, "
                "aucune p-valeur sous 0,27. `/trade` tout court demande au "
                "radar de regarder l'or maintenant, avec ses propres criteres.")
    if arg not in _TRADE_OR:
        return ("REFUS: " + arg + " n'est pas ouverte au reel. Seul XAU/USD "
                "l'est (MT5_BRIDGE_LIVE_WHITELIST_PAIRS).")
    return "XAU/USD"


def declencher_analyse_or(paire):
    """Declenche le cycle de production sur `paire`, via `docker exec`.

    Rend `(ok, texte)`. Ne leve jamais : appele depuis le fil Telegram.
    """
    code = (
        "import asyncio, json;"
        "from backend.services import declencheur_manuel as D;"
        "print(json.dumps(asyncio.run(D.declencher(%r))))" % paire
    )
    try:
        p = subprocess.run(
            ["docker", "exec", "-w", "/app", "-e", "PYTHONPATH=/app",
             "scalping-radar", "python", "-c", code],
            capture_output=True, text=True, timeout=120,
        )
    except subprocess.TimeoutExpired:
        return False, ("⏱️ Le cycle n'a pas repondu en 120 s. Il tourne "
                       "peut-etre encore : regarde les ordres dans un instant.")
    except Exception as e:  # noqa: BLE001
        return False, "❌ Impossible de joindre le radar : %s" % e
    sortie = (p.stdout or "").strip().splitlines()
    for ligne in reversed(sortie):
        try:
            d = json.loads(ligne)
        except Exception:  # noqa: BLE001
            continue
        if d.get("lance"):
            return True, ("✅ *Analyse de l'or lancee*\n\n"
                          "Le cycle de production a tourne sur `%s` avec toutes "
                          "ses portes. S'il y avait un setup qualifie, l'ordre "
                          "est parti ; sinon rien ne s'est passe, et c'est "
                          "voulu : `/trade` supprime une attente, il ne "
                          "fabrique pas de signal." % d.get("paire"))
        return False, "🚫 *Refuse* — %s" % d.get("motif", "motif inconnu")
    err = (p.stderr or "").strip().splitlines()
    return False, ("❌ Le radar n'a rien rendu de lisible.\n`%s`"
                   % (err[-1][:300] if err else "aucune sortie"))


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
                cible = parse_commande_trade(text)
                if cible is not None:
                    if cible.startswith("REFUS:"):
                        tg_send("🚫 " + cible[len("REFUS:"):].strip())
                    else:
                        tg_send("⏳ J'analyse l'or maintenant...")
                        ok, reponse = declencher_analyse_or(cible)
                        tg_send(reponse)
                    continue
                if text.lower().startswith("/status"):
                    tg_send(tg_build_status_reply())
                elif text.lower().startswith("/start"):
                    tg_send(
                        "👋 *Surveillance infra active*\n\n"
                        "Envoie `/status` à tout moment pour voir l'état des composants "
                        "(bridges, disque, réseau, radar).\n"
                        "Envoie `/trade` pour que le radar regarde l'or tout de suite "
                        "— avec toutes ses portes. Il choisit le sens : la mesure du "
                        "10/10 a montré qu'aucune direction, ni la sienne ni la tienne, "
                        "ne se distingue du hasard.\n\n"
                        "ℹ️ Tu reçois automatiquement une alerte ici dès qu'un composant tombe "
                        "en panne ou se rétablit."
                    )
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
        "🤖 Récupération auto activée : "
        + ", ".join(sorted(RECOVERY_ACTIONS_ENABLED))
        if AUTO_RECOVERY_ENABLED
        else "🤖 Récupération auto désactivée (actions juste loggées)"
    )
    tg_send(
        f"🟢 *Surveillance infra démarrée*\n\n"
        f"📡 Le système qui surveille les bridges, le disque, le réseau et le radar est actif "
        f"sur `{os.uname().nodename}`.\n"
        f"🌐 Dashboard : http://{WEB_BIND_HOST}:{WEB_BIND_PORT}/infra\n"
        f"{auto_label}\n\n"
        f"ℹ️ Tu recevras une alerte ici dès qu'un composant tombe ou se rétablit. "
        f"Envoie `/status` à tout moment pour un état complet."
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
