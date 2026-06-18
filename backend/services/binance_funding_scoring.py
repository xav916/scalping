"""Funding rate Binance USDⓈ-M comme filtre contrarien du scoring crypto.

Phase 2 Palier 2 — chantier #2 (2026-06-18) : utilise le funding rate Binance
comme signal de positioning (longs vs shorts surreprésentés) pour moduler le
score IA sur les setups crypto.

## Logique

Le funding rate est payé toutes les 8h par les longs aux shorts (si positif)
ou inverse (si négatif). Magnitude :
- Funding ~ 0     : marché équilibré
- Funding > 0.05% (par 8h, annualisé ~54%) : longs surcrowdés → bearish signal
- Funding < -0.05% : shorts surcrowdés → bullish signal

Comme filtre contrarien :
- Setup BUY crypto + funding extrême positif (longs déjà surchargés) → veto soft
  (multiplier 0.85, suffisant pour disqualifier les setups borderline)
- Setup SELL crypto + funding extrême négatif (shorts déjà surchargés) → veto soft
- Sinon : multiplier 1.0 (neutre)

Aligné avec le funding (rare cas où le funding paye dans ton sens) : pas de boost
pour Phase 2 R&D — uniquement filtre downside. À revoir si le signal est utile.

## Activation

Feature flag ``BINANCE_FUNDING_SCORING_ENABLED=true`` dans .env. Désactivé =
no-op, le scoring est identique au comportement pré-chantier #2.

## Sources

``binance_funding_service.get_funding_rate(pair)`` retourne dict
``{rate, last_update, is_fresh}``. Mise à jour scheduler toutes les 30 min
(funding lui-même est settlement 8h).
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# Seuils funding rate "extrême" par défaut (par 8h, en valeur absolue).
# Surcharge possible via env BINANCE_FUNDING_EXTREME_THRESHOLD.
_DEFAULT_EXTREME_THRESHOLD = 0.0005  # 0.05% par 8h, annualisé ~54%
_EXTREME_THRESHOLD = float(os.getenv("BINANCE_FUNDING_EXTREME_THRESHOLD", _DEFAULT_EXTREME_THRESHOLD))

# Multiplier de soft veto quand misaligné (direction surcrowdée).
# 0.85 = score 60 → 51 (sous le seuil 50 typique = setup rejeté).
_SOFT_VETO_MULTIPLIER = 0.85


def is_crypto_pair(pair: str) -> bool:
    """Mapping miroir de binance_klines_service. Hard-coded pour éviter dépendance."""
    return pair in {
        "BTC/USD", "ETH/USD", "SOL/USD", "ADA/USD", "XRP/USD",
        "LTC/USD", "BCH/USD", "DOT/USD", "DOGE/USD",
    }


def apply_funding_filter(pair: str, direction: str) -> tuple[float, str | None]:
    """Retourne (multiplier, reason).

    multiplier : 1.0 (neutre) ou 0.85 (soft veto contrarien). À multiplier au
    confidence_score post-macro.
    reason : string explicative si le veto soft s'applique, sinon None.

    Best-effort : retourne (1.0, None) silencieusement sur toute erreur (data
    absente, parsing, etc.) — comportement neutre safe par défaut.
    """
    if not is_crypto_pair(pair):
        return 1.0, None
    try:
        from backend.services import binance_funding_service as _bf
        info = _bf.get_funding_rate(pair)
        rate = info.get("rate")
        if rate is None or not info.get("is_fresh"):
            return 1.0, None
        rate = float(rate)
    except Exception as e:
        logger.debug(f"funding_scoring {pair}: {e}")
        return 1.0, None

    # Direction surcrowdée vs setup direction
    if direction == "buy" and rate > _EXTREME_THRESHOLD:
        return (_SOFT_VETO_MULTIPLIER,
                f"funding extrême positif {rate*100:.3f}% — longs surcrowdés, contrarien BUY")
    if direction == "sell" and rate < -_EXTREME_THRESHOLD:
        return (_SOFT_VETO_MULTIPLIER,
                f"funding extrême négatif {rate*100:.3f}% — shorts surcrowdés, contrarien SELL")
    return 1.0, None
