"""Position correlation guard pour les pushes Binance crypto.

Chantier #13 (2026-06-18) — refuse les pushes qui sur-concentreraient
l'exposition risk-on (ou risk-off) sur le cluster crypto. Les cryptos
USDⓈ-M majeures sont quasiment toutes corrélées au BTC sur les régimes
risk-on/risk-off. Empiler 8 longs simultanés revient à pyramider sur
un seul macro-call déguisé.

Règle :
- Avant chaque push crypto, fetch /positions du binance-bridge.
- Compte les positions ouvertes même direction (BUY/SELL) dans le
  cluster.
- Si count + 1 > MAX_CONCURRENT_SAME_DIRECTION, rejette le push.

Toggle via BINANCE_CORRELATION_GUARD_ENABLED. Cache fetch /positions
(TTL court) pour éviter de hammer le bridge.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

ENABLED = os.getenv("BINANCE_CORRELATION_GUARD_ENABLED", "true").strip().lower() in ("true", "1", "yes")
MAX_CONCURRENT_SAME_DIRECTION = int(os.getenv("BINANCE_CORRELATION_MAX_CONCURRENT", "4"))
FETCH_CACHE_SEC = float(os.getenv("BINANCE_CORRELATION_FETCH_TTL_SEC", "20.0"))

# Cluster crypto majeur (corrélé risk-on/risk-off). Identique au mapping
# binance_klines_service et binance_bridge mais redéfini ici pour ne pas
# créer de dépendance circulaire.
_CRYPTO_SYMBOLS = {
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT", "XRPUSDT",
    "LTCUSDT", "BCHUSDT", "DOTUSDT", "DOGEUSDT",
}

_cache_positions: list[dict[str, Any]] = []
_cache_at: float = 0.0
_lock = threading.Lock()


def _fetch_positions(dest) -> list[dict[str, Any]] | None:
    """GET /positions du bridge Binance. Retourne la liste ou None si fail."""
    if not getattr(dest, "bridge_url", None):
        return None
    url = dest.bridge_url + "/positions"
    headers: dict[str, str] = {}
    if getattr(dest, "bridge_api_key", None):
        headers["X-Bridge-Key"] = dest.bridge_api_key
    try:
        with httpx.Client(timeout=5.0) as c:
            r = c.get(url, headers=headers)
            if r.status_code != 200:
                logger.debug(f"corr_guard /positions → {r.status_code}: {r.text[:120]}")
                return None
            return r.json().get("positions", [])
    except Exception as e:
        logger.debug(f"corr_guard /positions fetch error: {e}")
        return None


def _refresh_positions(dest) -> None:
    """Lazy refresh du cache /positions."""
    global _cache_positions, _cache_at
    now = time.time()
    if (now - _cache_at) > FETCH_CACHE_SEC or not _cache_positions:
        positions = _fetch_positions(dest)
        if positions is not None:
            _cache_positions = positions
            _cache_at = now


def _count_crypto_positions_in_direction(direction: str) -> int:
    """Compte les positions ouvertes (positionAmt != 0) sur le cluster crypto
    dans la direction donnée (BUY = amt > 0, SELL = amt < 0)."""
    count = 0
    for p in _cache_positions:
        sym = p.get("symbol")
        if sym not in _CRYPTO_SYMBOLS:
            continue
        amt = float(p.get("positionAmt", 0) or 0)
        if direction == "buy" and amt > 0:
            count += 1
        elif direction == "sell" and amt < 0:
            count += 1
    return count


def check_correlation(dest, pair: str, direction: str) -> tuple[bool, str | None]:
    """À appeler avant chaque push admin_binance pour une crypto.

    Returns (allowed, reason_if_blocked).
    Non-crypto pairs et toggle off → (True, None) silencieusement.
    Cache /positions miss / network error → (True, None) best-effort.
    """
    if not ENABLED:
        return True, None
    # Court-circuit silencieux pour les non-cryptos (forex, métaux, etc.)
    # — la garde est conçue spécifiquement pour le cluster crypto corrélé.
    if pair not in {
        "BTC/USD", "ETH/USD", "SOL/USD", "ADA/USD", "XRP/USD",
        "LTC/USD", "BCH/USD", "DOT/USD", "DOGE/USD",
    }:
        return True, None
    with _lock:
        _refresh_positions(dest)
        if not _cache_positions:
            return True, None
        same_dir_count = _count_crypto_positions_in_direction(direction.lower())
        if same_dir_count + 1 > MAX_CONCURRENT_SAME_DIRECTION:
            reason = (
                f"correlation guard: {same_dir_count} positions crypto {direction.upper()} "
                f"déjà ouvertes (max {MAX_CONCURRENT_SAME_DIRECTION})"
            )
            return False, reason
        return True, None


def get_status() -> dict[str, Any]:
    """Snapshot lisible pour debug / cockpit."""
    with _lock:
        return {
            "enabled": ENABLED,
            "max_concurrent_same_direction": MAX_CONCURRENT_SAME_DIRECTION,
            "cached_positions_count": len(_cache_positions),
            "cache_age_sec": (time.time() - _cache_at) if _cache_at else None,
            "crypto_buy_count": _count_crypto_positions_in_direction("buy"),
            "crypto_sell_count": _count_crypto_positions_in_direction("sell"),
        }
