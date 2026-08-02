"""Validation tick pre-push : fraîcheur + spread + cohérence prix radar vs bridge.

Appelé depuis ``mt5_bridge._check_rejection()`` avant d'envoyer un ordre vers
un bridge. Récupère le tick courant via ``GET {bridge_url}/tick/{pair}`` et
vérifie 3 conditions :

1. Fraîcheur (time < TICK_MAX_AGE_SEC secondes)
2. Spread absolu vs seuil par asset_class
3. Cohérence prix : |setup.entry - mid| / mid < 0.5 %

Best-effort : si l'appel /tick échoue (bridge down, timeout, endpoint absent),
retourne ``None`` pour ne jamais bloquer un ordre par précaution. Seules les
anomalies avérées (tick trop vieux, spread trop large, divergence prix) sont
des rejections dures.

Seuils configurables via env vars :
- BRIDGE_TICK_MAX_AGE_SEC (défaut 30)
- BRIDGE_MAX_SPREAD_PCT_FOREX / _METAL / _CRYPTO / _EQUITY / _EQUITY_INDEX / _ENERGY
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ─── Configuration seuils ────────────────────────────────────────────────────

TICK_MAX_AGE_SEC: int = int(os.getenv("BRIDGE_TICK_MAX_AGE_SEC", "30"))

# Spread max (%) par asset_class. Valeurs calibrées sur volatilité normale
# hors news (forex tight, énergie spread wide, crypto variable).
_DEFAULT_MAX_SPREAD_PCT: dict[str, float] = {
    "forex":         float(os.getenv("BRIDGE_MAX_SPREAD_PCT_FOREX",         "0.05")),
    "metal":         float(os.getenv("BRIDGE_MAX_SPREAD_PCT_METAL",         "0.10")),
    "crypto":        float(os.getenv("BRIDGE_MAX_SPREAD_PCT_CRYPTO",        "0.20")),
    "equity":        float(os.getenv("BRIDGE_MAX_SPREAD_PCT_EQUITY",        "0.15")),
    "equity_index":  float(os.getenv("BRIDGE_MAX_SPREAD_PCT_EQUITY_INDEX",  "0.10")),
    "energy":        float(os.getenv("BRIDGE_MAX_SPREAD_PCT_ENERGY",        "0.30")),
}

# Seuil divergence prix radar vs mid bridge (%)
_PRICE_DIVERGENCE_MAX_PCT: float = float(os.getenv("BRIDGE_PRICE_DIVERGENCE_MAX_PCT", "0.5"))

# Timeout appel /tick (court : ne doit pas bloquer le cycle d'analyse)
_TICK_HTTP_TIMEOUT_SEC: float = float(os.getenv("BRIDGE_TICK_HTTP_TIMEOUT_SEC", "3.0"))


def _auth_header(dest) -> dict[str, str]:
    """Sélectionne le header d'authentification selon bridge_type.

    - mt5 → ``X-API-Key`` (convention bridge MT5 Windows)
    - binance / kraken / kraken_spot → ``X-Bridge-Key`` (bridges Python FastAPI)
    """
    bridge_type: str = getattr(dest, "bridge_type", "mt5") or "mt5"
    api_key: str = getattr(dest, "bridge_api_key", "") or ""
    if not api_key:
        return {}
    if bridge_type == "mt5":
        return {"X-API-Key": api_key}
    return {"X-Bridge-Key": api_key}


def _max_spread_pct_for(pair: str) -> float:
    """Retourne le seuil spread max (%) pour la pair donnée."""
    try:
        from config.settings import asset_class_for
        asset_class = asset_class_for(pair)
    except Exception:
        asset_class = "forex"
    return _DEFAULT_MAX_SPREAD_PCT.get(asset_class, _DEFAULT_MAX_SPREAD_PCT["forex"])


def _parse_tick(data: dict[str, Any]) -> tuple[float, float, float | None]:
    """Extrait (bid, ask, tick_time_sec_utc | None) depuis la réponse /tick.

    Format MT5 :  ``{bid, ask, time}`` (``time`` = timestamp POSIX secondes ou ISO)
    Format Kraken : ``{bid, ask}`` sans ``time``

    Retourne ``(bid, ask, None)`` si ``time`` absent ou non parseable.
    """
    bid = float(data["bid"])
    ask = float(data["ask"])
    raw_time = data.get("time")
    tick_ts: float | None = None
    if raw_time is not None:
        if isinstance(raw_time, (int, float)):
            tick_ts = float(raw_time)
        elif isinstance(raw_time, str):
            try:
                tick_ts = datetime.fromisoformat(raw_time.replace("Z", "+00:00")).timestamp()
            except Exception:
                try:
                    tick_ts = float(raw_time)
                except Exception:
                    tick_ts = None
    return bid, ask, tick_ts


def validate_tick_pre_push(dest: Any, setup: Any, now: datetime | None = None) -> str | None:
    """Valide le tick courant avant d'envoyer un ordre au bridge.

    Appelle ``GET {dest.bridge_url}/tick/{setup.pair}`` de façon synchrone
    (httpx sync, timeout 3s) et vérifie :

    1. ``stale_tick``        : tick_time > TICK_MAX_AGE_SEC secondes vs ``now``
    2. ``spread_too_wide``   : (ask-bid)/mid*100 > seuil asset_class
    3. ``price_divergence``  : |setup.entry_price - mid| / mid > 0.5 %

    Retourne ``None`` si tout est OK ou si l'appel /tick échoue (best-effort).
    En cas d'échec réseau / timeout / endpoint absent, logue en DEBUG et
    retourne ``None`` pour ne pas bloquer le pipeline.

    Parameters
    ----------
    dest : BridgeConfig
        Destination bridge (bridge_url, bridge_api_key, bridge_type).
    setup : Any
        Trade setup avec au minimum ``pair`` et ``entry_price``.
    now : datetime | None
        Moment de référence (UTC). Si None, utilise ``datetime.now(timezone.utc)``.
        Injecté par les tests pour contrôler le temps.
    """
    bridge_url: str = (getattr(dest, "bridge_url", "") or "").rstrip("/")
    pair: str = getattr(setup, "pair", "") or ""
    if not bridge_url or not pair:
        return None

    url = f"{bridge_url}/tick/{pair}"
    headers = _auth_header(dest)

    try:
        with httpx.Client(timeout=_TICK_HTTP_TIMEOUT_SEC) as client:
            r = client.get(url, headers=headers)
        if r.status_code != 200:
            logger.debug(
                f"bridge_tick_validator: {url} → HTTP {r.status_code}, skip validation"
            )
            return None
        data = r.json()
    except httpx.TimeoutException:
        logger.debug(f"bridge_tick_validator: timeout on {url}, skip validation")
        return None
    except Exception as exc:
        logger.debug(f"bridge_tick_validator: error calling {url}: {exc!s}, skip validation")
        return None

    try:
        bid, ask, tick_ts = _parse_tick(data)
    except (KeyError, ValueError, TypeError) as exc:
        logger.debug(f"bridge_tick_validator: cannot parse tick from {url}: {exc!s}")
        return None

    if bid <= 0 or ask <= 0 or ask < bid:
        logger.debug(f"bridge_tick_validator: invalid bid/ask from {url}: bid={bid} ask={ask}")
        return None

    # 1. Fraîcheur du tick (uniquement si timestamp disponible)
    if tick_ts is not None:
        ref_now = (now or datetime.now(timezone.utc)).timestamp()
        age_sec = ref_now - tick_ts
        if age_sec > TICK_MAX_AGE_SEC:
            logger.info(
                f"bridge_tick_validator [{pair}]: stale_tick age={age_sec:.0f}s "
                f"(max={TICK_MAX_AGE_SEC}s)"
            )
            return "stale_tick"

    # 2. Spread absolu vs seuil asset_class
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return None
    spread_pct = (ask - bid) / mid * 100.0
    max_spread = _max_spread_pct_for(pair)
    if spread_pct > max_spread:
        logger.info(
            f"bridge_tick_validator [{pair}]: spread_too_wide "
            f"spread={spread_pct:.4f}% max={max_spread}%"
        )
        return "spread_too_wide"

    # 3. Cohérence prix radar vs mid bridge
    entry = float(getattr(setup, "entry_price", 0) or 0)
    if entry > 0:
        divergence_pct = abs(entry - mid) / mid * 100.0
        if divergence_pct > _PRICE_DIVERGENCE_MAX_PCT:
            logger.info(
                f"bridge_tick_validator [{pair}]: price_divergence "
                f"entry={entry} mid={mid:.5f} divergence={divergence_pct:.3f}% "
                f"(max={_PRICE_DIVERGENCE_MAX_PCT}%)"
            )
            return "price_divergence"

    return None
