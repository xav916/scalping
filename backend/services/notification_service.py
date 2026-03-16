"""Notification service using WebSocket for real-time browser alerts."""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from backend.models.schemas import ScalpingSignal

logger = logging.getLogger(__name__)

# Connected WebSocket clients (FastAPI WebSocket instances)
_connected_clients: set[Any] = set()

# Signal history (kept in memory)
_signal_history: list[dict] = []
MAX_HISTORY = 100


def register_client(ws: Any) -> None:
    _connected_clients.add(ws)
    logger.info(f"Client connected. Total: {len(_connected_clients)}")


def unregister_client(ws: Any) -> None:
    _connected_clients.discard(ws)
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
            _connected_clients.discard(client)


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
        _connected_clients.discard(client)


def get_signal_history() -> list[dict]:
    """Return recent signal history."""
    return list(reversed(_signal_history))
