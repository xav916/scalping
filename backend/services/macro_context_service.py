"""Fetches macro indicators from Twelve Data and caches the latest snapshot.

- `refresh_macro_context()` is called periodically by the scheduler.
- `get_macro_snapshot()` is called synchronously from enrich_trade_setup().
- `is_fresh(dt)` returns True if `dt` is within MACRO_CACHE_MAX_AGE_SEC.
- If all fetches fail, the previous cached snapshot is kept.
"""
from __future__ import annotations

import asyncio
import logging
import statistics
from datetime import datetime, timezone
from typing import Optional

import httpx

from config.settings import (
    MACRO_CACHE_MAX_AGE_SEC,
    MACRO_SCORING_ENABLED,
    MACRO_SYMBOL_DE10Y,
    MACRO_SYMBOL_DXY,
    MACRO_SYMBOL_GOLD,
    MACRO_SYMBOL_NIKKEI,
    MACRO_SYMBOL_OIL,
    MACRO_SYMBOL_SPX,
    MACRO_SYMBOL_US10Y,
    MACRO_SYMBOL_VIX,
    TWELVEDATA_API_KEY,
)
from backend.models.macro_schemas import (
    MacroContext,
    MacroDirection,
    RiskRegime,
    VixLevel,
    direction_from_zscore,
    vix_level_from_value,
)

logger = logging.getLogger(__name__)

_TWELVEDATA_BASE = "https://api.twelvedata.com"
_cache_snapshot: Optional[MacroContext] = None


async def _fetch_candles_for_symbol(symbol: str, outputsize: int = 21) -> list[dict]:
    """Fetch daily closes for a single symbol. Returns [] on any failure."""
    if not TWELVEDATA_API_KEY:
        return []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                f"{_TWELVEDATA_BASE}/time_series",
                params={
                    "symbol": symbol,
                    "interval": "1day",
                    "outputsize": outputsize,
                    "apikey": TWELVEDATA_API_KEY,
                },
            )
        if r.status_code != 200:
            logger.warning(f"macro: {symbol} HTTP {r.status_code}")
            return []
        data = r.json()
        values = data.get("values", [])
        return values
    except Exception as e:
        logger.warning(f"macro: {symbol} fetch error: {e}")
        return []


def _compute_zscore(current: float, closes: list[float]) -> float:
    if not closes:
        return 0.0
    mean = statistics.fmean(closes)
    if len(closes) < 2:
        return 0.0
    try:
        stddev = statistics.pstdev(closes)
    except statistics.StatisticsError:
        return 0.0
    if stddev == 0:
        return 0.0
    return (current - mean) / stddev


def _extract_last_and_series(candles: list[dict]) -> tuple[Optional[float], list[float]]:
    """From Twelve Data response (newest first), extract current spot + series of 20 prior closes."""
    if not candles:
        return None, []
    try:
        floats = [float(c["close"]) for c in candles]
    except (ValueError, KeyError):
        return None, []
    current = floats[0]
    prior = floats[1:21]
    return current, prior


def _derive_risk_regime(vix_level: VixLevel, spx_dir: MacroDirection) -> RiskRegime:
    if vix_level in (VixLevel.ELEVATED, VixLevel.HIGH) and spx_dir in (
        MacroDirection.DOWN,
        MacroDirection.STRONG_DOWN,
    ):
        return RiskRegime.RISK_OFF
    if vix_level == VixLevel.LOW and spx_dir in (MacroDirection.UP, MacroDirection.STRONG_UP):
        return RiskRegime.RISK_ON
    return RiskRegime.NEUTRAL


def _spread_trend(us_z: float, de_z: float) -> str:
    diff = us_z - de_z
    if diff > 0.5:
        return "widening"
    if diff < -0.5:
        return "narrowing"
    return "flat"


async def refresh_macro_context() -> bool:
    """Fetch all 8 symbols and rebuild the cached snapshot.

    Returns True if a fresh snapshot was built, False otherwise.
    On any total failure, the previous cached snapshot is preserved.
    """
    global _cache_snapshot

    if not MACRO_SCORING_ENABLED:
        return False

    symbols = {
        "dxy": MACRO_SYMBOL_DXY,
        "spx": MACRO_SYMBOL_SPX,
        "vix": MACRO_SYMBOL_VIX,
        "us10y": MACRO_SYMBOL_US10Y,
        "de10y": MACRO_SYMBOL_DE10Y,
        "oil": MACRO_SYMBOL_OIL,
        "nikkei": MACRO_SYMBOL_NIKKEI,
        "gold": MACRO_SYMBOL_GOLD,
    }

    tasks = {k: _fetch_candles_for_symbol(sym) for k, sym in symbols.items()}
    results = await asyncio.gather(*tasks.values(), return_exceptions=False)
    raw = dict(zip(tasks.keys(), results))

    spot: dict[str, float] = {}
    zscore: dict[str, float] = {}
    for k, candles in raw.items():
        current, prior = _extract_last_and_series(candles)
        if current is None:
            continue
        spot[k] = current
        zscore[k] = _compute_zscore(current, prior)

    if not spot:
        logger.warning("macro: refresh failed — no symbols returned data, keeping previous cache")
        return False

    def _dir(key: str) -> MacroDirection:
        return direction_from_zscore(zscore.get(key, 0.0))

    vix_value = spot.get("vix", 17.0)
    vix_level = vix_level_from_value(vix_value)
    spx_dir = _dir("spx")

    snapshot = MacroContext(
        fetched_at=datetime.now(timezone.utc),
        dxy_direction=_dir("dxy"),
        spx_direction=spx_dir,
        vix_level=vix_level,
        vix_value=vix_value,
        us10y_trend=_dir("us10y"),
        de10y_trend=_dir("de10y"),
        us_de_spread_trend=_spread_trend(zscore.get("us10y", 0.0), zscore.get("de10y", 0.0)),
        oil_direction=_dir("oil"),
        nikkei_direction=_dir("nikkei"),
        gold_direction=_dir("gold"),
        risk_regime=_derive_risk_regime(vix_level, spx_dir),
        raw_values=spot,
        dxy_intraday_sigma=0.0,
    )

    _cache_snapshot = snapshot
    logger.info(
        f"macro: refreshed — dxy={snapshot.dxy_direction.value} "
        f"spx={snapshot.spx_direction.value} vix={vix_value:.1f}({vix_level.value}) "
        f"risk={snapshot.risk_regime.value}"
    )
    return True


def get_macro_snapshot() -> Optional[MacroContext]:
    return _cache_snapshot


def is_fresh(fetched_at: datetime) -> bool:
    age = (datetime.now(timezone.utc) - fetched_at).total_seconds()
    return age <= MACRO_CACHE_MAX_AGE_SEC
