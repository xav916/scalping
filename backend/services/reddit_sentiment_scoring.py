"""Reddit sentiment scoring — filtre contrarien crypto BTC/ETH.

P3 MVP (2026-08-03) : applique un soft veto ×0.90 sur les setups crypto
BTC/USD et ETH/USD quand le sentiment Reddit est fortement opposé à la
direction du trade (signal d'épuisement retail).

## Logique

- Si BUY crypto + sentiment Reddit < -0.3 (bearish fort) → ×0.90
  Raison : retail bearish = surcrowdé short → contrarien BUY OK… mais
  quand le consensus Reddit est très négatif et qu'on trade dans le sens
  d'un sentiment neuf (BUY lors de panique Reddit) = edge ambigu.
  Le filtre cible le cas inverse : retail bullish fort + on SELL = pas de
  friction. Retail bearish fort + on BUY = le BUY va contre la panique
  retail, SAUF que ce cas est souvent le bon trade contrarien → soft veto
  léger ×0.90 seulement (vs ×0.85 funding/LSR) pour ne pas trop filtrer.

  DÉTAIL : le veto s'applique quand la direction du setup EST DANS LE SENS
  du sentiment extrême (crowd-following). Ex :
  - BUY + sentiment > +0.3 (tout le monde est bullish → surcrowdé) → ×0.90
  - SELL + sentiment < -0.3 (tout le monde est bearish → surcrowdé) → ×0.90

## Seuils

REDDIT_SENTIMENT_THRESHOLD (défaut 0.3) : seuil de "sentiment fort".
  > 0.3 = bullish fort (beaucoup plus de posts bullish que bearish)
  < -0.3 = bearish fort
  Entre -0.3 et +0.3 = neutre → pas de veto

REDDIT_SENTIMENT_MULTIPLIER (défaut 0.90) : légèrement moins sévère que
  les filtres Binance (0.85) car le signal Reddit est plus bruité et moins
  structurel que le funding rate. Conçu pour disqualifier seulement les
  setups borderline (60 → 54, sous le seuil min_conf 55-60).

## Activation

Feature-flagged via REDDIT_SENTIMENT_ENABLED=true dans .env (défaut false).
Désactivé = no-op total, le scoring est identique au comportement pré-P3.

## Sources

reddit_sentiment_service.get_sentiment(symbol) retourne dict avec
{score, bullish_count, bearish_count, sample_size, fetched_at, is_fresh}.
Cache 1h (refresh scheduler horaire). Best-effort : si indisponible → (score, {}).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# Paires supportées : BTC/USD et ETH/USD uniquement (subreddits dédiés)
_SUPPORTED_PAIRS = {"BTC/USD", "ETH/USD"}

# Seuil magnitude sentiment pour déclencher le veto (valeur absolue)
_DEFAULT_THRESHOLD = 0.30
_THRESHOLD = float(os.getenv("REDDIT_SENTIMENT_THRESHOLD", _DEFAULT_THRESHOLD))

# Multiplier soft veto — légèrement moins sévère que funding/LSR (0.85)
# car signal Reddit plus bruité (keyword matching vs données on-chain)
_DEFAULT_MULTIPLIER = 0.90
_SOFT_VETO_MULTIPLIER = float(os.getenv("REDDIT_SENTIMENT_MULTIPLIER", _DEFAULT_MULTIPLIER))


def _is_crypto_pair(pair: str) -> bool:
    """Retourne True si la paire est dans le scope Reddit sentiment."""
    return pair in _SUPPORTED_PAIRS


def apply_reddit_sentiment(
    pair: str,
    direction: str,
    base_score: float,
    now: datetime | None = None,
) -> tuple[float, dict[str, Any]]:
    """Applique un soft veto si le sentiment Reddit est extrême et crowd-following.

    Règle : si la direction du setup SUIT le sentiment extrême (crowd-following),
    le marché retail est surcrowdé dans ce sens → veto ×0.90.

    - BUY + sentiment > +{threshold} (bullish fort, retail tout dans le même sens) → ×0.90
    - SELL + sentiment < -{threshold} (bearish fort, retail surcrowdé short) → ×0.90

    Cas contrarien (setup CONTRE le sentiment) : pas de veto, laisse passer.
    Ex : BUY en période de panique Reddit (sentiment < -0.3) = bon timing potentiel.

    Retourne (new_score, metadata_dict).
    metadata vide {} si pas de modification.
    """
    if not _is_crypto_pair(pair):
        return base_score, {}

    try:
        from backend.services import reddit_sentiment_service as _rs
        sentiment = _rs.get_sentiment(pair)
    except Exception as e:
        logger.debug(f"reddit_sentiment_scoring {pair}: service error: {e}")
        return base_score, {}

    if sentiment is None:
        logger.debug(f"reddit_sentiment_scoring {pair}: no data available")
        return base_score, {"reddit_error": "no_data"}

    score = float(sentiment.get("score", 0.0))
    is_crowd_following = (
        (direction == "buy" and score > _THRESHOLD)
        or (direction == "sell" and score < -_THRESHOLD)
    )

    if not is_crowd_following:
        # Neutre ou contrarien : pas de veto
        return base_score, {
            "reddit_score": score,
            "reddit_sample_size": sentiment.get("sample_size", 0),
            "reddit_is_fresh": sentiment.get("is_fresh", False),
            "reddit_multiplier": 1.0,
        }

    # Crowd-following détecté → soft veto
    new_score = round(min(100.0, max(0.0, base_score * _SOFT_VETO_MULTIPLIER)), 1)

    direction_label = "bullish" if score > 0 else "bearish"
    reason = (
        f"Reddit sentiment {direction_label} fort ({score:+.2f}) "
        f"— crowd-following {direction.upper()}, "
        f"contrarien filter ({sentiment.get('bullish_count', 0)} bull "
        f"/ {sentiment.get('bearish_count', 0)} bear "
        f"sur {sentiment.get('sample_size', 0)} posts)"
    )

    logger.info(
        f"reddit_sentiment_applied pair={pair} dir={direction} "
        f"reddit_score={score:.3f} mult={_SOFT_VETO_MULTIPLIER} "
        f"prev={base_score} final={new_score}"
    )

    meta: dict[str, Any] = {
        "reddit_score": score,
        "reddit_bullish_count": sentiment.get("bullish_count", 0),
        "reddit_bearish_count": sentiment.get("bearish_count", 0),
        "reddit_sample_size": sentiment.get("sample_size", 0),
        "reddit_is_fresh": sentiment.get("is_fresh", False),
        "reddit_multiplier": _SOFT_VETO_MULTIPLIER,
        "reddit_reason": reason,
    }
    return new_score, meta
