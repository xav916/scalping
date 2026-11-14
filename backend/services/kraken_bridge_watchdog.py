"""Monitoring Kraken Futures bridge — alerte Telegram instantanée si DOWN.

## Pourquoi

Le bridge Kraken Futures (`admin_kraken`, argent RÉEL) peut tomber en silence :
- Reboot de l'hôte où il tourne (Docker Compose, VM, bare metal)
- Perte réseau interne (bridge Tailscale, routing Docker)
- Clé API Kraken révoquée / IP whitelist modifiée
- Dépendance externe (API Kraken en maintenance)

Sans monitoring, on ne s'en aperçoit qu'au prochain cycle de poussée qui
échoue, ou — pire — au moment où un stop devrait être posé et ne l'est pas.
Même pattern que ``ibkr_gateway_watchdog`` : poll /health toutes les 5 min,
alerte Telegram infra ⚙️ sur transition UP→DOWN et DOWN→UP.

## State machine

    UP → UP          : silence, cooldown réinitialisé
    UP → DOWN        : ALERTE Telegram immédiate "Kraken bridge DOWN"
    DOWN → DOWN      : ré-alerte toutes les 30 min (anti-spam) tant que down
    DOWN → UP        : ALERTE Telegram "Kraken bridge BACK UP"

## Env vars

- ``KRAKEN_BRIDGE_WATCHDOG_ENABLED`` (défaut ``true``) — switch global
- ``KRAKEN_BRIDGE_URL`` — déjà présent (ex ``http://172.17.0.1:8790``)
- ``KRAKEN_BRIDGE_API_KEY`` — déjà présent (optionnel pour /health)
- ``KRAKEN_BRIDGE_WATCHDOG_COOLDOWN_SEC`` (défaut 1800 = 30 min)

## Fail-safe

Toute exception interne → log WARNING + return silencieux. Un bug du
watchdog ne doit pas tuer le scalping.service.
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)


STATE_PATH = os.getenv(
    "KRAKEN_BRIDGE_WATCHDOG_STATE",
    "/app/data/kraken_bridge_watchdog.json",
)
COOLDOWN_SEC_DEFAULT = 1800  # 30 min


def _enabled() -> bool:
    return os.getenv(
        "KRAKEN_BRIDGE_WATCHDOG_ENABLED", "true"
    ).strip().lower() in ("true", "1", "yes", "on")


def _cooldown_sec() -> int:
    try:
        return int(os.getenv("KRAKEN_BRIDGE_WATCHDOG_COOLDOWN_SEC",
                             str(COOLDOWN_SEC_DEFAULT)))
    except (TypeError, ValueError):
        return COOLDOWN_SEC_DEFAULT


def _load_state() -> dict:
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"was_connected": True, "last_alert_at": None}
    except Exception as e:  # noqa: BLE001
        logger.warning("kraken_bridge_watchdog: load_state failed — %s", e)
        return {"was_connected": True, "last_alert_at": None}


def _save_state(state: dict) -> None:
    try:
        p = pathlib.Path(STATE_PATH)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(p) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, STATE_PATH)
    except Exception as e:  # noqa: BLE001
        logger.warning("kraken_bridge_watchdog: save_state failed — %s", e)


async def _fetch_health() -> dict:
    url = os.getenv("KRAKEN_BRIDGE_URL", "").strip().rstrip("/")
    key = os.getenv("KRAKEN_BRIDGE_API_KEY", "").strip()
    if not url:
        return {"ok": False, "error": "no_KRAKEN_BRIDGE_URL"}
    try:
        headers = {"X-API-Key": key} if key else {}
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(f"{url}/health", headers=headers)
            if r.status_code != 200:
                return {"ok": False, "error": f"http_{r.status_code}"}
            try:
                return r.json()
            except Exception:  # noqa: BLE001
                # ⛔ Certains bridges rendent un 200 texte « ok ». On
                # considère ça comme UP, pas comme DOWN.
                return {"ok": True, "connected": True}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"exception: {str(e)[:120]}"}


def _is_connected(health: dict) -> bool:
    """Un /health est UP si ``ok`` ET (``connected`` est vrai ou absent).

    ⛔ Le bridge Kraken peut rendre {"ok": true} sans champ ``connected`` :
    pour ``ibkr_gateway_watchdog`` on exige connected=True car la Gateway peut
    répondre /health alors que la connexion IBKR est perdue. Ici, un 200
    propre suffit à dire que le bridge tourne et répond — on ne veut pas
    alerter DOWN sur un bridge en vie juste parce qu'il manque un champ.
    """
    if not health.get("ok"):
        return False
    conn = health.get("connected")
    if conn is None:
        return True  # 200 sans champ connected = up
    return bool(conn)


def _cooldown_elapsed(last_iso: str | None, cooldown_sec: int) -> bool:
    if not last_iso:
        return True
    try:
        last = datetime.fromisoformat(last_iso)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - last).total_seconds()
        return elapsed >= cooldown_sec
    except ValueError:
        return True


async def _send_down_alert(health: dict) -> None:
    """Alerte DOWN sur canal infra."""
    err = health.get("error") or "unknown"
    text = (
        "🚨🚨 <b>Bridge Kraken DOWN</b>\n"
        f"bridge {os.getenv('KRAKEN_BRIDGE_URL', '?')}\n"
        f"motif : <code>{err}</code>\n"
        f"heure UTC : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}\n"
        f"\n"
        f"⚠️ <b>Argent RÉEL</b> : les positions ouvertes ne sont plus\n"
        f"protégées par <code>kraken_sltp_guard</code> tant que le bridge\n"
        f"est muet. Vérifier manuellement sur le site Kraken.\n"
        f"\n"
        f"🔧 Action :\n"
        f"1. Vérifier le process du bridge Kraken (hôte Docker)\n"
        f"2. Logs : <code>docker logs kraken-bridge --tail 100</code>\n"
        f"3. API Kraken joignable ? <code>curl https://futures.kraken.com</code>\n"
        f"4. Si OK : <code>docker restart kraken-bridge</code>"
    )
    try:
        from backend.services import telegram_service
        await telegram_service.send_infra_text(text, parse_mode="HTML")
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "kraken_bridge_watchdog: send_down_alert failed — %s", e)


async def _send_recovery_alert(health: dict) -> None:
    """Alerte UP (retour en ligne) sur canal infra."""
    text = (
        "✅ <b>Bridge Kraken BACK UP</b>\n"
        f"bridge {os.getenv('KRAKEN_BRIDGE_URL', '?')}\n"
        f"heure UTC : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}"
    )
    extras = {k: health.get(k) for k in ("account", "accounts", "mode")
              if health.get(k) is not None}
    if extras:
        for k, v in extras.items():
            text += f"\n{k} : <code>{v}</code>"
    try:
        from backend.services import telegram_service
        await telegram_service.send_infra_text(text, parse_mode="HTML")
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "kraken_bridge_watchdog: send_recovery_alert failed — %s", e)


async def check_and_alert() -> dict:
    """Job appelé par le scheduler toutes les 5 min.

    Returns ``{"ran": bool, "connected": bool, "alerted": bool, ...}``
    """
    if not _enabled():
        return {"ran": False, "reason": "watchdog_disabled"}

    health = await _fetch_health()
    is_connected = _is_connected(health)

    state = _load_state()
    was_connected = state.get("was_connected", True)
    last_alert_at = state.get("last_alert_at")
    cooldown = _cooldown_sec()
    alerted = False

    if is_connected:
        if not was_connected:
            await _send_recovery_alert(health)
            alerted = True
            logger.warning("kraken_bridge_watchdog: recovery alert sent")
        state["was_connected"] = True
        state["last_alert_at"] = None
    else:
        if was_connected or _cooldown_elapsed(last_alert_at, cooldown):
            await _send_down_alert(health)
            alerted = True
            state["last_alert_at"] = datetime.now(
                timezone.utc).isoformat(timespec="seconds")
            logger.warning(
                "kraken_bridge_watchdog: DOWN alert sent (first=%s, was_connected=%s)",
                not was_connected, was_connected,
            )
        state["was_connected"] = False

    _save_state(state)
    return {
        "ran": True,
        "connected": is_connected,
        "alerted": alerted,
        "state": {"was_connected": state["was_connected"]},
    }
