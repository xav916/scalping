"""Veille positions IBKR : poll le bridge périodiquement, détecte 5 événements
et push des alertes Telegram (``send_info_text`` / ``send_infra_text``).

Pensé comme un **observateur passif** — ne passe aucun ordre, n'arrête rien,
ne modifie rien côté broker. Son seul effet de bord est l'envoi de notifs et
l'écriture d'un snapshot in-memory lu par ``cockpit_service.build_cockpit``.

## Les 5 événements surveillés (baseline configurable via env)

| Événement | Seuil env | Canal Telegram |
|---|---|---|
| Drawdown journalier | ``COCKPIT_IBKR_DAILY_DD_ALERT_PCT`` (5.0) | ``send_info_text`` warn |
| Nouvelle position détectée | — (toute apparition) | ``send_info_text`` info |
| Position fermée | — (toute disparition) | ``send_info_text`` info |
| Nombre positions ouvertes | ``COCKPIT_IBKR_MAX_OPEN_POSITIONS`` (10) | ``send_info_text`` warn |
| Bridge silencieux | ``COCKPIT_IBKR_BRIDGE_SILENCE_ALERT_SEC`` (300) | ``send_infra_text`` critical |

Chaque alerte est **dédupliquée par jour** : si le drawdown reste au-dessus du
seuil 30 minutes, une seule notif part. Le dédup se reset à minuit UTC.

## État in-memory

Volontairement pas de persistance SQLite ni JSON : au restart du radar, on
repart d'un snapshot vide — le premier poll après restart devient la baseline
de la journée. Acceptable : les alertes sont proactives, pas rétrospectives.

## Env vars

- ``COCKPIT_IBKR_WATCH_ENABLED`` (défaut ``false``) — kill switch global
- ``IBKR_BRIDGE_URL`` (défaut ``http://100.74.160.72:8792``) — URL du bridge
- ``IBKR_BRIDGE_API_KEY`` — auth header ``X-Bridge-Key`` (partagée avec le bridge)
- ``COCKPIT_IBKR_POLL_SEC`` (défaut 60) — intervalle de polling
- ``COCKPIT_IBKR_DAILY_DD_ALERT_PCT`` (défaut 5.0)
- ``COCKPIT_IBKR_MAX_OPEN_POSITIONS`` (défaut 10)
- ``COCKPIT_IBKR_BRIDGE_SILENCE_ALERT_SEC`` (défaut 300)
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ─── Config env (lue à l'import, relue par `_config_enabled` à chaque poll) ──
ENABLED_DEFAULT = "false"
BRIDGE_URL = os.getenv("IBKR_BRIDGE_URL", "http://100.74.160.72:8792").rstrip("/")
BRIDGE_KEY = os.getenv("IBKR_BRIDGE_API_KEY", "")
POLL_INTERVAL_SEC = int(os.getenv("COCKPIT_IBKR_POLL_SEC", "60"))
DAILY_DD_ALERT_PCT = float(os.getenv("COCKPIT_IBKR_DAILY_DD_ALERT_PCT", "5.0"))
MAX_OPEN_POSITIONS = int(os.getenv("COCKPIT_IBKR_MAX_OPEN_POSITIONS", "10"))
BRIDGE_SILENCE_ALERT_SEC = int(os.getenv("COCKPIT_IBKR_BRIDGE_SILENCE_ALERT_SEC", "300"))


def _config_enabled() -> bool:
    """Relu à chaque poll pour permettre l'activation/désactivation à chaud."""
    return os.getenv("COCKPIT_IBKR_WATCH_ENABLED", ENABLED_DEFAULT).strip().lower() in ("true", "1", "yes")


# ─── État in-memory ─────────────────────────────────────────────────────
_lock = asyncio.Lock()
_snapshot: dict[str, Any] | None = None
_last_ok_at: datetime | None = None
_opening_net_liq_today: float | None = None
_opening_date: date | None = None
_known_positions_keys: set[str] = set()
_alerts_sent_today: set[str] = set()


def get_snapshot() -> dict[str, Any] | None:
    """Pour ``cockpit_service.build_cockpit`` : lit l'état sans forcer un poll.

    Retourne ``None`` si la veille est désactivée ou si aucun poll n'a encore
    réussi (démarrage du service, bridge inaccessible depuis le boot).
    """
    if not _config_enabled():
        return None
    return _snapshot


async def poll() -> dict[str, Any]:
    """Un cycle complet : fetch bridge, diff avec snapshot précédent, alertes.

    Appelé par le scheduler apscheduler toutes les ``POLL_INTERVAL_SEC``.
    Jamais ré-entrant (``max_instances=1`` côté scheduler).

    Retourne le snapshot post-poll (ou le précédent si le bridge est KO), à
    des fins de test et de monitoring.
    """
    global _snapshot, _last_ok_at, _opening_net_liq_today, _opening_date, _known_positions_keys

    if not _config_enabled():
        return {"enabled": False}

    headers = {"X-Bridge-Key": BRIDGE_KEY} if BRIDGE_KEY else {}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r_acc = await client.get(f"{BRIDGE_URL}/account", headers=headers)
            r_pos = await client.get(f"{BRIDGE_URL}/positions", headers=headers)
    except Exception as e:
        logger.warning("positions_watcher: bridge unreachable — %s", e)
        await _check_bridge_silence_alert()
        return _snapshot or {"enabled": True, "ok": False, "error": str(e)}

    if r_acc.status_code != 200 or r_pos.status_code != 200:
        logger.warning(
            "positions_watcher: bridge non-200 — acc=%d pos=%d",
            r_acc.status_code, r_pos.status_code,
        )
        await _check_bridge_silence_alert()
        return _snapshot or {"enabled": True, "ok": False}

    acc = r_acc.json()
    pos = r_pos.json()
    if not acc.get("ok") or not pos.get("ok"):
        logger.warning("positions_watcher: bridge logical error — acc=%s", acc.get("error"))
        return _snapshot or {"enabled": True, "ok": False}

    async with _lock:
        _last_ok_at = datetime.now(timezone.utc)
        net_liq = float(acc.get("NetLiquidation") or 0)
        currency = acc.get("currency") or "USD"
        positions = pos.get("positions") or []

        # Reset opening au changement de jour UTC
        today = date.today()
        if _opening_date != today:
            _opening_date = today
            _opening_net_liq_today = net_liq
            _alerts_sent_today.clear()
            _known_positions_keys = {_pos_key(p) for p in positions}
            logger.info(
                "positions_watcher: nouveau jour %s — baseline net_liq=%.2f %s, %d position(s) connues",
                today, net_liq, currency, len(_known_positions_keys),
            )

        daily_pnl_pct = (
            ((net_liq - _opening_net_liq_today) / _opening_net_liq_today) * 100
            if _opening_net_liq_today else 0.0
        )

        current_keys = {_pos_key(p) for p in positions}
        new_keys = current_keys - _known_positions_keys
        closed_keys = _known_positions_keys - current_keys
        _known_positions_keys = current_keys

        # ─── Émission alertes (dédupliquées par jour) ───────────────────
        await _alert_daily_dd(daily_pnl_pct, net_liq, currency)
        await _alert_new_positions(new_keys, positions)
        await _alert_closed_positions(closed_keys)
        await _alert_too_many_positions(len(positions))

        _snapshot = {
            "enabled": True,
            "ok": True,
            "fetched_at": _last_ok_at.isoformat(),
            "bridge_url": BRIDGE_URL,
            "currency": currency,
            "net_liquidation": net_liq,
            "buying_power": float(acc.get("BuyingPower") or 0),
            "cash": float(acc.get("TotalCashValue") or 0),
            "gross_position_value": float(acc.get("GrossPositionValue") or 0),
            "opening_net_liquidation_today": _opening_net_liq_today,
            "daily_pnl_pct": round(daily_pnl_pct, 2),
            "open_positions_count": len(positions),
            "positions": positions,
        }

    return _snapshot


# ─── Helpers ────────────────────────────────────────────────────────────


def _pos_key(p: dict) -> str:
    return f"{p.get('symbol')}|{p.get('sec_type')}|{p.get('currency')}"


def _dedup_key(kind: str, extra: str = "") -> str:
    return f"{date.today().isoformat()}|{kind}|{extra}"


async def _alert_daily_dd(pnl_pct: float, net_liq: float, currency: str) -> None:
    if pnl_pct >= -DAILY_DD_ALERT_PCT:
        return
    key = _dedup_key("daily_dd")
    if key in _alerts_sent_today:
        return
    _alerts_sent_today.add(key)
    await _send_info(
        f"⚠️ IBKR daily drawdown {pnl_pct:.1f}% (seuil -{DAILY_DD_ALERT_PCT}%)\n"
        f"NetLiq: {net_liq:.2f} {currency} / Opening: {_opening_net_liq_today:.2f} {currency}"
    )


async def _alert_new_positions(keys: set[str], positions: list[dict]) -> None:
    for k in keys:
        dkey = _dedup_key("new_position", k)
        if dkey in _alerts_sent_today:
            continue
        _alerts_sent_today.add(dkey)
        p = next((p for p in positions if _pos_key(p) == k), None)
        if p:
            await _send_info(
                f"ℹ️ IBKR nouvelle position détectée\n"
                f"{p['symbol']} {p['sec_type']} {p['position']:+g} @ {p['avg_cost']:.2f} {p['currency']}"
            )


async def _alert_closed_positions(keys: set[str]) -> None:
    for k in keys:
        dkey = _dedup_key("closed_position", k)
        if dkey in _alerts_sent_today:
            continue
        _alerts_sent_today.add(dkey)
        await _send_info(f"ℹ️ IBKR position fermée : {k.split('|')[0]}")


async def _alert_too_many_positions(count: int) -> None:
    if count <= MAX_OPEN_POSITIONS:
        return
    key = _dedup_key("too_many_positions", str(count))
    if key in _alerts_sent_today:
        return
    _alerts_sent_today.add(key)
    await _send_info(
        f"⚠️ IBKR {count} positions ouvertes (seuil {MAX_OPEN_POSITIONS})"
    )


async def _check_bridge_silence_alert() -> None:
    """Alerte critical si le bridge reste silencieux au-delà du seuil."""
    if _last_ok_at is None:
        return
    silence_sec = (datetime.now(timezone.utc) - _last_ok_at).total_seconds()
    if silence_sec < BRIDGE_SILENCE_ALERT_SEC:
        return
    minutes = int(silence_sec // 60)
    key = _dedup_key("bridge_silence", str(minutes))
    if key in _alerts_sent_today:
        return
    _alerts_sent_today.add(key)
    await _send_infra(
        f"🚨 IBKR bridge silence depuis {minutes} min "
        f"(seuil {BRIDGE_SILENCE_ALERT_SEC // 60} min) — "
        f"veille positions sans données fraîches"
    )


async def _send_info(text: str) -> None:
    """Wrapper qui isole les skills du module de notif (facile à mocker en test)."""
    try:
        from backend.services import telegram_service
        await telegram_service.send_info_text(text, parse_mode="HTML")
    except Exception as e:
        logger.warning("positions_watcher: send_info_text failed — %s", e)


async def _send_infra(text: str) -> None:
    try:
        from backend.services import telegram_service
        await telegram_service.send_infra_text(text, parse_mode="HTML")
    except Exception as e:
        logger.warning("positions_watcher: send_infra_text failed — %s", e)
