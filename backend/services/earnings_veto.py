"""Veto 24h avant/après earnings sur signaux equity individuels.

P2 chantier : évite les gaps overnight brutaux liés aux publications
de résultats trimestriels (EPS surprises, guidance warnings, etc.).

## Logique

Applicable uniquement aux asset_class == "equity" (actions individuelles :
AAPL, TSLA, NVDA, MSFT, MSTR, HOOD, GOOGL, etc.).
Non applicable : equity_index (SPX/NDX/SPY/QQQ), crypto, forex, metal, energy.

Fenêtres veto :
- next_earnings dans les 24h → soft veto ×0.60 (pré-earnings, forte incertitude)
- last_earnings dans les 24h → soft veto ×0.70 (post-earnings, volatilité résiduelle)
- Sinon → no-op (score inchangé)

Les deux fenêtres peuvent se chevaucher si un earnings est prévu pile maintenant.
Dans ce cas, le multiplicateur le plus sévère (×0.60 pre) l'emporte.

## Best-effort

Si earnings_calendar_service fail (yfinance indispo, SQLite absent),
retourne (base_score, {}) sans modifier le score. Jamais d'exception propagée.

## Feature flag

Gated par EARNINGS_VETO_ENABLED (défaut true, config/settings.py).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Asset class cible : uniquement equity individuel (pas les indices)
_EQUITY_CLASS = "equity"

# Fenêtre veto en heures
_WINDOW_HOURS = 24

# Multiplicateurs soft veto
_MULT_PRE_EARNINGS = 0.60   # 24h avant : forte incertitude
_MULT_POST_EARNINGS = 0.70  # 24h après : volatilité résiduelle


def apply_earnings_veto(
    pair: str,
    direction: str,
    base_score: float,
    now: Optional[datetime] = None,
) -> tuple[float, dict]:
    """Applique un soft veto earnings sur le score si dans la fenêtre ±24h.

    Parameters
    ----------
    pair : str
        Paire du setup (ex. "AAPL", "TSLA", "NVDA.NAS").
    direction : str
        "buy" ou "sell" (non utilisé pour la logique veto, inclus pour symétrie).
    base_score : float
        Score de confiance avant ce veto.
    now : datetime | None
        Timestamp de référence (UTC). Si None, utilise datetime.now(UTC).

    Returns
    -------
    tuple[float, dict]
        (new_score, metadata)
        - new_score : score après application du veto (ou base_score si no-op)
        - metadata : dict vide si no-op, sinon contient earnings_at, hours_delta,
          veto_direction, multiplier, asset_class.

    Best-effort : toute exception retourne (base_score, {'earnings_error': ...}).
    """
    from config.settings import asset_class_for

    try:
        # 1. Filtre asset class
        # Normalise le pair pour gérer les suffixes broker (ex. "AAPL.NAS" → "AAPL")
        symbol = pair.split(".")[0].upper()
        asset_class = asset_class_for(symbol)
        if asset_class != _EQUITY_CLASS:
            return base_score, {}

        if now is None:
            now = datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        # 2. Lecture earnings dates (cache SQLite, best-effort)
        from backend.services import earnings_calendar_service as _ecs

        next_earnings: Optional[datetime] = None
        last_earnings: Optional[datetime] = None

        try:
            next_earnings = _ecs.get_next_earnings(symbol)
        except Exception as e:
            logger.debug(f"earnings_veto: get_next_earnings({symbol}) error: {e}")

        try:
            last_earnings = _ecs.get_last_earnings(symbol)
        except Exception as e:
            logger.debug(f"earnings_veto: get_last_earnings({symbol}) error: {e}")

        # 3. Calcul des deltas
        pre_hours: Optional[float] = None
        post_hours: Optional[float] = None

        if next_earnings is not None:
            delta_next = (next_earnings - now).total_seconds() / 3600
            if 0 <= delta_next <= _WINDOW_HOURS:
                pre_hours = delta_next  # earnings dans les 24h à venir

        if last_earnings is not None:
            delta_last = (now - last_earnings).total_seconds() / 3600
            if 0 <= delta_last <= _WINDOW_HOURS:
                post_hours = delta_last  # earnings dans les 24h passées

        # 4. Sélection du veto le plus sévère (pre prime sur post)
        if pre_hours is not None:
            multiplier = _MULT_PRE_EARNINGS
            veto_direction = "before"
            earnings_at = next_earnings.isoformat()
            hours_delta = round(pre_hours, 1)
        elif post_hours is not None:
            multiplier = _MULT_POST_EARNINGS
            veto_direction = "after"
            earnings_at = last_earnings.isoformat()
            hours_delta = round(post_hours, 1)
        else:
            # Pas de veto actif
            return base_score, {}

        # 5. Application
        new_score = round(min(100.0, max(0.0, base_score * multiplier)), 1)

        meta = {
            "asset_class": asset_class,
            "symbol": symbol,
            "earnings_at": earnings_at,
            "hours_delta": hours_delta,
            "veto_direction": veto_direction,
            "multiplier": multiplier,
        }

        logger.info(
            f"earnings_veto pair={pair} symbol={symbol} dir={direction} "
            f"veto={veto_direction} earnings_at={earnings_at} "
            f"hours_delta={hours_delta}h mult={multiplier} "
            f"score={base_score}→{new_score}"
        )

        return new_score, meta

    except Exception as e:
        logger.warning(f"earnings_veto: top-level error for {pair}: {e}")
        return base_score, {"earnings_error": str(e)}
