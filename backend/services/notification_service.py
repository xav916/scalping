"""Notification service using WebSocket for real-time browser alerts."""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from backend.models.schemas import ScalpingSignal, Tick

logger = logging.getLogger(__name__)

# Connected WebSocket clients : dict {client -> user}. Le user est stocke
# pour pouvoir pousser des payloads personnalises (ex: cockpit par user).
_connected_clients: dict[Any, str] = {}

# Signal history (kept in memory)
_signal_history: list[dict] = []
MAX_HISTORY = 100


def register_client(ws: Any, user: str = "anonymous") -> None:
    _connected_clients[ws] = user
    logger.info(f"Client connected (user={user}). Total: {len(_connected_clients)}")


def unregister_client(ws: Any) -> None:
    _connected_clients.pop(ws, None)
    logger.info(f"Client disconnected. Total: {len(_connected_clients)}")


async def broadcast_signals(signals: list[ScalpingSignal]) -> None:
    """Broadcast new signals to all connected WebSocket clients."""
    if not signals:
        return

    for signal in signals:
        signal_data = {
            "pair": signal.pair,
            "strength": signal.signal_strength.value,
            "message": signal.message,
            "volatility_ratio": signal.volatility.volatility_ratio,
            "volatility_level": signal.volatility.level.value,
            "trend_direction": signal.trend.direction.value,
            "trend_strength": signal.trend.strength,
            "nearby_events": [
                {"name": e.event_name, "impact": e.impact.value, "time": e.time}
                for e in signal.nearby_events
            ],
            "timestamp": signal.timestamp.isoformat(),
        }

        # Inclure le trade setup s'il existe
        if signal.trade_setup:
            setup = signal.trade_setup
            signal_data["trade_setup"] = {
                "pair": setup.pair,
                "direction": setup.direction.value,
                "entry_price": setup.entry_price,
                "stop_loss": setup.stop_loss,
                "take_profit_1": setup.take_profit_1,
                "take_profit_2": setup.take_profit_2,
                "risk_pips": setup.risk_pips,
                "risk_reward_1": setup.risk_reward_1,
                "risk_reward_2": setup.risk_reward_2,
                "pattern": {
                    "pattern": setup.pattern.pattern.value,
                    "confidence": setup.pattern.confidence,
                    "description": setup.pattern.description,
                },
                "message": setup.message,
            }

        payload = {"type": "signal", "data": signal_data}

        # Store in history
        _signal_history.append(payload["data"])
        if len(_signal_history) > MAX_HISTORY:
            _signal_history.pop(0)

        message = json.dumps(payload)

        # Broadcast to all connected clients
        disconnected = set()
        for client in _connected_clients:
            try:
                await client.send_text(message)
            except Exception:
                disconnected.add(client)

        for client in disconnected:
            _connected_clients.pop(client, None)


async def broadcast_update(data: dict) -> None:
    """Broadcast a general market update to all clients."""
    message = json.dumps({"type": "update", "data": data})
    disconnected = set()
    for client in _connected_clients:
        try:
            await client.send_text(message)
        except Exception:
            disconnected.add(client)
    for client in disconnected:
        _connected_clients.pop(client, None)


async def broadcast_tick(tick: Tick) -> None:
    """Broadcast un tick temps reel a tous les clients connectes."""
    if not _connected_clients:
        return
    payload = {
        "type": "tick",
        "data": {
            "pair": tick.pair,
            "price": tick.price,
            "bid": tick.bid,
            "ask": tick.ask,
            "timestamp": tick.timestamp.isoformat(),
        },
    }
    message = json.dumps(payload)
    disconnected = set()
    for client in _connected_clients:
        try:
            await client.send_text(message)
        except Exception:
            disconnected.add(client)
    for client in disconnected:
        _connected_clients.pop(client, None)


def get_signal_history() -> list[dict]:
    """Return recent signal history."""
    return list(reversed(_signal_history))


async def broadcast_cockpit() -> None:
    """Pousse le snapshot cockpit a chaque client connecte.

    Le payload est construit par user (trades/PnL sont personnels), donc
    on groupe les clients par user, on construit le snapshot une seule
    fois par user, puis on diffuse a tous les clients de ce user.

    No-op si aucun client n'est connecte.
    """
    if not _connected_clients:
        return

    from backend.services.cockpit_service import build_cockpit

    # Groupe client -> user en user -> [clients]
    by_user: dict[str, list[Any]] = {}
    for client, user in _connected_clients.items():
        by_user.setdefault(user, []).append(client)

    for user, clients in by_user.items():
        try:
            snapshot = await build_cockpit(user=user)
        except Exception as e:
            logger.warning(f"cockpit build failed for user={user}: {e}")
            continue

        message = json.dumps({"type": "cockpit", "data": snapshot})
        disconnected = set()
        for client in clients:
            try:
                await client.send_text(message)
            except Exception:
                disconnected.add(client)
        for client in disconnected:
            _connected_clients.pop(client, None)
