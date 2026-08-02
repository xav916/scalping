"""VIX regime veto — soft veto multiplicateur sur signaux equity/equity_index.

Gap 1 MVP (2026-08-02) : premier composant du scoring equity (DTR V0 spec).

## Logique

Le VIX (CBOE Volatility Index) mesure la volatilité implicite à 30j du S&P500.
En régime stress (VIX élevé), les signaux equity long ont un edge réduit :
- Risk-off généralisé comprime les rebonds
- Corrélations inter-actifs montent (diversification réduite)
- Slippage et spread élargis sur les CFD equity

Régimes et multiplicateurs :
- VIX < 20  : calme → 1.0 (neutre)
- 20–30     : modéré → 0.95 (soft veto léger)
- 30–40     : stress → 0.85 (soft veto standard, aligné crypto filtering)
- VIX >= 40 : panique → 0.70 (fort filtre)

Applicable uniquement aux asset_class in {'equity', 'equity_index'}.
Sinon retourne (base_score, {}) sans modification.

## Sources

Utilise vix_service.get_current() — cache SQLite 5 min peuplé par le
scheduler refresh toutes les 5 min. Best-effort : si VIX indisponible,
retourne score inchangé + metadata {'vix_error': ...}.

## Non-scope (DTR V0)

- Corrélations sectorielles (tech vs financier)
- Dividend yield impact
- Earnings calendar per-stock
- Cross-asset regime (10Y yield, DXY)
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from backend.services import vix_service

logger = logging.getLogger(__name__)

# Asset classes sur lesquelles le veto VIX s'applique.
_EQUITY_CLASSES = {"equity", "equity_index"}

# Régimes VIX : (seuil_min, seuil_max, multiplier, label)
_REGIMES = [
    (0.0, 20.0, 1.0, "calm"),
    (20.0, 30.0, 0.95, "moderate"),
    (30.0, 40.0, 0.85, "stress"),
    (40.0, float("inf"), 0.70, "panic"),
]

# Cache mémoire : (vix_value, timestamp_fetched)
# Doublon du cache SQLite de vix_service — couche ultra-rapide intra-cycle.
_MEM_CACHE: tuple[float, float] | None = None
_MEM_CACHE_TTL = 5 * 60  # 5 min (aligné vix_service._CACHE_TTL_SEC)
# Seuil au-delà duquel une valeur VIX en cache (SQLite) est considérée périmée.
_STALE_AGE_SEC = 60 * 60  # 1h — log warning mais utilise quand même


def _get_vix_value(now: datetime | None = None) -> tuple[float | None, dict]:
    """Lit le VIX depuis le cache mémoire, puis SQLite (vix_service).

    Retourne (vix_value, metadata_partielle). vix_value=None si indisponible.
    """
    global _MEM_CACHE

    now_ts = time.monotonic()

    # 1. Cache mémoire
    if _MEM_CACHE is not None:
        val, fetched_ts = _MEM_CACHE
        if (now_ts - fetched_ts) < _MEM_CACHE_TTL:
            return val, {"vix_source": "mem_cache"}

    # 2. SQLite via vix_service
    try:
        snap = vix_service.get_current()
    except Exception as e:
        logger.debug(f"vix_scoring: vix_service call failed: {e}")
        return None, {"vix_error": "fetch_failed"}

    if not snap.get("available"):
        reason = snap.get("reason", "unavailable")
        logger.debug(f"vix_scoring: vix not available — {reason}")
        return None, {"vix_error": reason}

    vix_val = float(snap["value"])
    age_sec = snap.get("age_sec", 0)

    if age_sec > _STALE_AGE_SEC:
        logger.warning(
            f"vix_scoring: VIX cache stale ({age_sec:.0f}s > {_STALE_AGE_SEC}s), "
            f"using anyway value={vix_val:.2f}"
        )

    # Mise à jour cache mémoire
    _MEM_CACHE = (vix_val, now_ts)
    return vix_val, {"vix_source": "sqlite_cache", "vix_age_sec": round(age_sec)}


def _multiplier_for(vix: float) -> tuple[float, str]:
    """Retourne (multiplier, regime_label) pour une valeur VIX donnée."""
    for lo, hi, mult, label in _REGIMES:
        if lo <= vix < hi:
            return mult, label
    # Fallback (ne devrait pas arriver avec le dernier bucket inf)
    return 0.70, "panic"


def apply_vix_veto(
    pair: str,
    direction: str,
    base_score: float,
    now: datetime | None = None,
) -> tuple[float, dict]:
    """Applique un soft veto sur le score si le VIX est en régime stress.

    Règles :
    - VIX < 20  : régime calme → pas de modif (multiplier 1.0)
    - 20 <= VIX < 30 : régime modéré → multiplier 0.95
    - VIX >= 30 : régime stress → multiplier 0.85 (filtre équivalent aux vetos crypto)
    - VIX >= 40 : régime panique → multiplier 0.70 (fort filtre)

    Applique uniquement aux asset_class in {'equity', 'equity_index'}. Sinon
    retourne (base_score, {}).

    Retourne (new_score, metadata_dict) où metadata contient vix_value + multiplier.
    """
    from config.settings import asset_class_for

    asset_class = asset_class_for(pair)
    if asset_class not in _EQUITY_CLASSES:
        return base_score, {}

    vix_val, fetch_meta = _get_vix_value(now)

    if vix_val is None:
        # Best-effort : ne bloque pas le scoring
        return base_score, fetch_meta

    multiplier, regime = _multiplier_for(vix_val)
    new_score = round(min(100.0, max(0.0, base_score * multiplier)), 1)

    meta = {
        **fetch_meta,
        "vix_value": round(vix_val, 2),
        "vix_regime": regime,
        "vix_multiplier": multiplier,
        "asset_class": asset_class,
    }

    if multiplier != 1.0:
        logger.info(
            f"vix_veto pair={pair} dir={direction} vix={vix_val:.2f} "
            f"regime={regime} mult={multiplier} "
            f"score={base_score}→{new_score}"
        )

    return new_score, meta
