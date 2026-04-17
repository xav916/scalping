"""Source de prix temps réel via MetaTrader 5.

Nécessite :
- MT5 desktop installé et lancé sur la machine (Windows natif ou Wine)
- Le package Python `MetaTrader5` (`pip install MetaTrader5`)
- Un compte MT5 actif (OANDA TMS démo fonctionne)

La lib MetaTrader5 est synchrone : tous les appels sont wrappés dans
`asyncio.to_thread` pour préserver l'architecture async du radar.
"""

import asyncio
import logging
from datetime import datetime, timezone

from backend.models.schemas import Candle
from config.settings import (
    MT5_LOGIN,
    MT5_PASSWORD,
    MT5_SERVER,
    MT5_SYMBOL_MAP,
    MT5_TERMINAL_PATH,
)

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5  # type: ignore
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None  # type: ignore
    MT5_AVAILABLE = False
    logger.info("Package MetaTrader5 non installé (pip install MetaTrader5)")


# Intervalle Scalping Radar -> timeframe MT5
_TIMEFRAME_MAP = {
    "1min": "TIMEFRAME_M1",
    "5min": "TIMEFRAME_M5",
    "15min": "TIMEFRAME_M15",
    "30min": "TIMEFRAME_M30",
    "1h": "TIMEFRAME_H1",
    "4h": "TIMEFRAME_H4",
    "1day": "TIMEFRAME_D1",
}

_initialized = False
_init_lock = asyncio.Lock()


def _resolve_symbol(pair: str) -> str:
    """Traduit une paire Scalping Radar vers un symbole MT5.

    Utilise MT5_SYMBOL_MAP si défini, sinon applique une règle par défaut :
    "XAU/USD" -> "XAUUSD" (pour la plupart des brokers).
    Pour OANDA TMS, définir MT5_SYMBOL_MAP=XAU/USD:GOLD.pro,EUR/USD:EURUSD.pro,...
    """
    if pair in MT5_SYMBOL_MAP:
        return MT5_SYMBOL_MAP[pair]
    return pair.replace("/", "")


def _mt5_timeframe(interval: str):
    name = _TIMEFRAME_MAP.get(interval, "TIMEFRAME_M5")
    return getattr(mt5, name)


def _initialize_sync() -> bool:
    if not MT5_AVAILABLE:
        return False

    kwargs = {}
    if MT5_TERMINAL_PATH:
        kwargs["path"] = MT5_TERMINAL_PATH
    if MT5_LOGIN:
        kwargs["login"] = int(MT5_LOGIN)
    if MT5_PASSWORD:
        kwargs["password"] = MT5_PASSWORD
    if MT5_SERVER:
        kwargs["server"] = MT5_SERVER

    if not mt5.initialize(**kwargs):
        err = mt5.last_error()
        logger.error(f"MT5 initialize() échoué: {err}")
        return False

    account = mt5.account_info()
    if account is None:
        logger.error(f"MT5 account_info() échoué: {mt5.last_error()}")
        return False

    logger.info(
        f"MT5 connecté: compte {account.login} ({account.server}), "
        f"solde {account.balance} {account.currency}"
    )
    return True


async def ensure_initialized() -> bool:
    """Initialise la connexion MT5 si pas encore fait. Idempotent."""
    global _initialized
    if _initialized:
        return True
    async with _init_lock:
        if _initialized:
            return True
        _initialized = await asyncio.to_thread(_initialize_sync)
        return _initialized


def _fetch_candles_sync(symbol: str, interval: str, outputsize: int):
    timeframe = _mt5_timeframe(interval)
    # copy_rates_from_pos(symbol, timeframe, start_pos, count)
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, outputsize)
    if rates is None:
        logger.warning(f"MT5 copy_rates_from_pos({symbol}) a renvoyé None: {mt5.last_error()}")
        return []
    return list(rates)


async def fetch_candles(
    pair: str,
    interval: str = "5min",
    outputsize: int = 50,
) -> tuple[list[Candle], bool]:
    """Récupère les bougies OHLC depuis MT5.

    Returns:
        (candles triées du plus ancien au plus récent, is_simulated=False)
        ou ([], True) si MT5 est indisponible.
    """
    if not await ensure_initialized():
        return [], True

    symbol = _resolve_symbol(pair)

    # S'assurer que le symbole est visible dans Market Watch
    sym_info = await asyncio.to_thread(mt5.symbol_info, symbol)
    if sym_info is None:
        logger.warning(f"MT5: symbole {symbol} inconnu (pair={pair})")
        return [], True
    if not sym_info.visible:
        await asyncio.to_thread(mt5.symbol_select, symbol, True)

    rates = await asyncio.to_thread(_fetch_candles_sync, symbol, interval, outputsize)
    if not rates:
        return [], True

    candles = [
        Candle(
            timestamp=datetime.fromtimestamp(r["time"], tz=timezone.utc),
            open=float(r["open"]),
            high=float(r["high"]),
            low=float(r["low"]),
            close=float(r["close"]),
            volume=float(r["tick_volume"]),
        )
        for r in rates
    ]
    # copy_rates_from_pos renvoie déjà du plus ancien au plus récent
    logger.info(f"MT5: {len(candles)} bougies pour {pair} ({symbol}, {interval})")
    return candles, False


async def fetch_current_price(pair: str) -> float | None:
    """Prix actuel (mid) d'une paire via le dernier tick."""
    if not await ensure_initialized():
        return None

    symbol = _resolve_symbol(pair)
    tick = await asyncio.to_thread(mt5.symbol_info_tick, symbol)
    if tick is None:
        return None
    # Mid-price bid/ask
    if tick.bid and tick.ask:
        return (tick.bid + tick.ask) / 2.0
    return float(tick.last) if tick.last else None


async def shutdown() -> None:
    global _initialized
    if MT5_AVAILABLE and _initialized:
        await asyncio.to_thread(mt5.shutdown)
        _initialized = False
        logger.info("MT5 déconnecté")
