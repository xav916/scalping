"""Client WebSocket Twelve Data pour des prix temps reel (<1s).

Architecture :
- Se connecte a wss://ws.twelvedata.com/v1/quotes/price
- S'abonne aux paires configurees (capees au plan, ex: 8 symboles pour Grow)
- Maintient un cache en memoire des derniers ticks
- Rebroadcast chaque tick vers le frontend via notification_service
- Reconnexion automatique avec backoff exponentiel
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

import websockets

from backend.models.schemas import Tick
from backend.services.notification_service import broadcast_tick
from config.settings import (
    TWELVEDATA_API_KEY,
    TWELVEDATA_WS_ENABLED,
    TWELVEDATA_WS_MAX_SYMBOLS,
    WATCHED_PAIRS,
)

logger = logging.getLogger(__name__)

WS_URL = "wss://ws.twelvedata.com/v1/quotes/price"

_latest_ticks: dict[str, Tick] = {}
_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None


def get_latest_ticks() -> dict[str, Tick]:
    """Snapshot immuable des derniers ticks par paire."""
    return dict(_latest_ticks)


def get_subscribed_symbols() -> list[str]:
    """Liste des paires reellement abonnees (apres cap au plan)."""
    return WATCHED_PAIRS[:TWELVEDATA_WS_MAX_SYMBOLS]


async def _run_connection(stop_event: asyncio.Event) -> None:
    """Boucle de connexion unique (reconnect gere par l'appelant)."""
    symbols = get_subscribed_symbols()
    if not symbols:
        logger.warning("Aucune paire a streamer, WebSocket Twelve Data ne demarre pas")
        return

    url = f"{WS_URL}?apikey={TWELVEDATA_API_KEY}"

    async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
        subscribe_msg = {
            "action": "subscribe",
            "params": {"symbols": ",".join(symbols)},
        }
        await ws.send(json.dumps(subscribe_msg))
        logger.info(f"WebSocket Twelve Data: abonne a {len(symbols)} symboles ({','.join(symbols)})")

        # Heartbeat task pour envoyer des pings applicatifs
        heartbeat_task = asyncio.create_task(_heartbeat(ws, stop_event))
        try:
            while not stop_event.is_set():
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=60)
                except asyncio.TimeoutError:
                    logger.warning("WebSocket Twelve Data: pas de message depuis 60s")
                    continue
                await _handle_message(raw)
        finally:
            heartbeat_task.cancel()


async def _heartbeat(ws, stop_event: asyncio.Event) -> None:
    """Envoie un heartbeat applicatif toutes les 10s (recommande par Twelve Data)."""
    while not stop_event.is_set():
        try:
            await asyncio.sleep(10)
            await ws.send(json.dumps({"action": "heartbeat"}))
        except (asyncio.CancelledError, websockets.ConnectionClosed):
            return
        except Exception as e:
            logger.debug(f"Heartbeat error: {e}")
            return


async def _handle_message(raw: str) -> None:
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        logger.debug(f"Message WS non-JSON ignore: {raw[:100]}")
        return

    event = msg.get("event")
    if event == "subscribe-status":
        status = msg.get("status")
        if status == "ok":
            logger.info(f"Abonnement confirme: {msg.get('success', [])}")
        else:
            logger.warning(f"Probleme abonnement: {msg}")
        return
    if event == "heartbeat":
        return
    if event != "price":
        logger.debug(f"Event WS ignore: {event}")
        return

    symbol = msg.get("symbol")
    price = msg.get("price")
    if not symbol or price is None:
        return

    tick = Tick(
        pair=symbol,
        price=float(price),
        bid=float(msg["bid"]) if msg.get("bid") else None,
        ask=float(msg["ask"]) if msg.get("ask") else None,
        timestamp=datetime.fromtimestamp(msg["timestamp"], tz=timezone.utc)
        if msg.get("timestamp")
        else datetime.now(timezone.utc),
    )
    _latest_ticks[symbol] = tick

    # Broadcast vers le frontend (non-bloquant, les erreurs sont loggees en interne)
    await broadcast_tick(tick)


async def _supervisor() -> None:
    """Boucle de supervision : reconnecte avec backoff exponentiel."""
    assert _stop_event is not None
    backoff = 1
    while not _stop_event.is_set():
        try:
            await _run_connection(_stop_event)
            backoff = 1  # Reset sur deconnexion propre
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"WebSocket Twelve Data erreur: {e}. Reconnexion dans {backoff}s")
            try:
                await asyncio.wait_for(_stop_event.wait(), timeout=backoff)
                return  # stop demande
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, 60)


def start() -> bool:
    """Demarre la tache WebSocket. Retourne True si demarree."""
    global _task, _stop_event

    if not TWELVEDATA_WS_ENABLED:
        logger.info("TWELVEDATA_WS_ENABLED=false, WebSocket non demarre")
        return False
    if not TWELVEDATA_API_KEY:
        logger.warning("TWELVEDATA_API_KEY vide, WebSocket non demarre")
        return False
    if _task and not _task.done():
        return True

    _stop_event = asyncio.Event()
    _task = asyncio.create_task(_supervisor(), name="twelvedata-ws")
    logger.info("WebSocket Twelve Data demarre (tache en arriere-plan)")
    return True


async def stop() -> None:
    """Arrete la tache WebSocket proprement."""
    global _task, _stop_event
    if _stop_event:
        _stop_event.set()
    if _task:
        _task.cancel()
        try:
            await _task
        except (asyncio.CancelledError, Exception):
            pass
    _task = None
    _stop_event = None
    logger.info("WebSocket Twelve Data arrete")
