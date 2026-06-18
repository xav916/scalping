"""Binance Futures klines WebSocket — streaming live des bougies OHLC.

Chantier #7 (2026-06-18) — remplace le REST polling de
``binance_klines_service.fetch_klines`` par une connexion WebSocket
persistante. Latence cible : ~0 ms (push) vs 100-500 ms (REST polling).

Architecture :
- Stream Binance combiné : wss://fstream.binance.com/stream?streams=<sym>@kline_<itv>/...
- Cache en mémoire dict[(symbol, interval), list[Candle]] (200 dernières)
- Pré-amorçage REST au démarrage pour avoir les 50 dernières bougies
  immédiatement (sinon faut attendre 50 × 5min = 4h pour avoir un signal).
- Tâche asyncio daemon avec auto-reconnect + backoff exponentiel
- Fallback transparent : si cache vide ou WS down, le caller (fetch_klines)
  retombera sur REST.

Toggle via env :
- BINANCE_KLINES_WS_ENABLED=true|false (default false — opt-in pour rollback)
- BINANCE_KLINES_WS_INTERVALS=5m,15m  (intervals streamés, default 5m)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from backend.models.schemas import Candle

logger = logging.getLogger(__name__)

WS_ENABLED = os.getenv("BINANCE_KLINES_WS_ENABLED", "false").strip().lower() in ("true", "1", "yes")
_INTERVALS_RAW = os.getenv("BINANCE_KLINES_WS_INTERVALS", "5m").strip()
WS_INTERVALS: list[str] = [s.strip() for s in _INTERVALS_RAW.split(",") if s.strip()]
WS_URL = "wss://fstream.binance.com/stream"
_CACHE_MAX = 250
_RECONNECT_BACKOFF_INITIAL = 1.0
_RECONNECT_BACKOFF_MAX = 60.0

# Mapping pair scalping-radar → symbole Binance.
_PAIR_TO_SYMBOL: dict[str, str] = {
    "BTC/USD": "BTCUSDT",
    "ETH/USD": "ETHUSDT",
    "SOL/USD": "SOLUSDT",
    "ADA/USD": "ADAUSDT",
    "XRP/USD": "XRPUSDT",
    "LTC/USD": "LTCUSDT",
    "BCH/USD": "BCHUSDT",
    "DOT/USD": "DOTUSDT",
    "DOGE/USD": "DOGEUSDT",
}
_SYMBOL_TO_PAIR: dict[str, str] = {v: k for k, v in _PAIR_TO_SYMBOL.items()}

# Cache des bougies. Indexé par (symbol_lower, interval).
_cache: dict[tuple[str, str], list[Candle]] = {}
_cache_lock: asyncio.Lock | None = None
_task: asyncio.Task | None = None
_started = False


def _ensure_lock() -> asyncio.Lock:
    global _cache_lock
    if _cache_lock is None:
        _cache_lock = asyncio.Lock()
    return _cache_lock


def is_ws_supported(pair: str, interval: str) -> bool:
    """True si le WS gère cette pair × interval (et que WS est activé)."""
    if not WS_ENABLED:
        return False
    if pair not in _PAIR_TO_SYMBOL:
        return False
    return interval in WS_INTERVALS


def get_cached_candles(pair: str, interval: str, limit: int) -> list[Candle]:
    """Lecture sync du cache. Retourne [] si vide.

    Pas de lock — les writes sont atomiques (réassignation de liste).
    Lecture potentiellement stale d'1 message au pire.
    """
    sym = _PAIR_TO_SYMBOL.get(pair)
    if not sym:
        return []
    candles = _cache.get((sym, interval))
    if not candles:
        return []
    return candles[-limit:]


async def _prime_cache_via_rest() -> None:
    """Pré-amorçage : fetch les 50 dernières bougies via REST pour chaque
    (pair × interval) au démarrage. Sinon il faudrait attendre N × interval
    avant d'avoir un signal exploitable.
    """
    from backend.services import binance_klines_service as ks
    for pair in _PAIR_TO_SYMBOL:
        for interval in WS_INTERVALS:
            try:
                candles = await ks.fetch_klines(pair, interval, limit=50, _bypass_ws=True)
                if candles:
                    sym = _PAIR_TO_SYMBOL[pair]
                    _cache[(sym, interval)] = list(candles)
            except Exception as e:
                logger.debug(f"prime cache {pair}/{interval}: {e}")


def _build_stream_url() -> str:
    """Construit l'URL combinée pour tous les streams (sym@kline_itv)."""
    streams = []
    for sym in _PAIR_TO_SYMBOL.values():
        for itv in WS_INTERVALS:
            streams.append(f"{sym.lower()}@kline_{itv}")
    return f"{WS_URL}?streams={'/'.join(streams)}"


def _apply_kline_message(msg: dict[str, Any]) -> None:
    """Applique un message kline au cache. Format Binance :
    {"stream": "btcusdt@kline_5m", "data": {"e": "kline", "s": "BTCUSDT",
     "k": {"t": open_ms, "o": "...", "h": "...", "l": "...", "c": "...",
           "v": "...", "x": true|false (closed)}}}
    """
    data = msg.get("data") or {}
    k = data.get("k") or {}
    sym = data.get("s")
    if not sym or not k:
        return
    # Récupère interval depuis le stream name
    stream = msg.get("stream", "")
    interval = stream.split("@kline_")[-1] if "@kline_" in stream else None
    if not interval:
        return
    try:
        candle = Candle(
            timestamp=datetime.fromtimestamp(k["t"] / 1000, tz=timezone.utc),
            open=float(k["o"]),
            high=float(k["h"]),
            low=float(k["l"]),
            close=float(k["c"]),
            volume=float(k["v"]),
        )
    except (KeyError, ValueError, TypeError) as e:
        logger.debug(f"ws kline parse {sym} {interval}: {e}")
        return
    key = (sym, interval)
    existing = _cache.get(key, [])
    # Une kline arrive en streaming partiel (x=false) puis finale (x=true).
    # On remplace toujours la dernière si timestamp identique.
    if existing and existing[-1].timestamp == candle.timestamp:
        existing[-1] = candle
    else:
        existing.append(candle)
        if len(existing) > _CACHE_MAX:
            existing = existing[-_CACHE_MAX:]
    _cache[key] = existing


async def _ws_loop() -> None:
    """Boucle de connexion WebSocket avec auto-reconnect."""
    import websockets

    url = _build_stream_url()
    backoff = _RECONNECT_BACKOFF_INITIAL
    while True:
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                logger.info(f"binance klines WS connected ({len(_PAIR_TO_SYMBOL)} symbols × {len(WS_INTERVALS)} intervals)")
                backoff = _RECONNECT_BACKOFF_INITIAL
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        _apply_kline_message(msg)
                    except json.JSONDecodeError as e:
                        logger.debug(f"ws decode: {e}")
        except Exception as e:
            logger.warning(f"binance klines WS disconnected: {e} (retry in {backoff:.1f}s)")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _RECONNECT_BACKOFF_MAX)


async def ensure_started() -> None:
    """Démarre le WS loop si pas déjà fait. Idempotent.

    Best-effort : si websockets package absent, log + désactive.
    """
    global _started, _task
    if not WS_ENABLED:
        return
    if _started:
        return
    _started = True  # set early pour éviter double init concurrent
    try:
        import websockets  # noqa: F401
    except ImportError:
        logger.warning("binance klines WS: websockets package missing — disabled")
        return
    _ensure_lock()
    await _prime_cache_via_rest()
    _task = asyncio.create_task(_ws_loop(), name="binance-klines-ws")
    logger.info("binance klines WS started")
