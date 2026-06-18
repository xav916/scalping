"""Binance Long/Short Account Ratio (LSR) comme filtre contrarien crypto.

Phase 2 Palier 2 — chantier #3 (2026-06-18) : utilise le ratio de
comptes long/short Binance Futures comme signal de positioning retail.
Miroir du funding rate (chantier #2) mais sous un angle différent :

- Le **funding rate** mesure ce que payent les longs/shorts (qui dérive
  de l'écart perp vs index).
- Le **LSR** mesure combien de **comptes** sont long vs short, sans
  considérer la taille des positions.

Les deux signaux sont **complémentaires** : un funding extrême + LSR
extrême dans le même sens = signal de positioning vraiment surcrowdé.
Un seul des deux extrême = signal modéré.

## Logique

LSR > 2.0 (typiquement = >67% des comptes long) → BUY contrarien soft veto.
LSR < 0.7 (typiquement = >58% des comptes short) → SELL contrarien soft veto.
Sinon : neutre (mult 1.0).

Aligné avec le LSR (rare, contrarien profitable) : pas de boost. Phase R&D
on évalue d'abord la valeur du filtre downside.

## Activation

Feature flag ``BINANCE_LSR_SCORING_ENABLED=true`` dans .env. Désactivé
= no-op.

## Sources

``binance_lsr_service.get_features(pair)`` retourne dict avec ``lsr_ratio``,
``lsr_excess_long``, ``lsr_excess_short``, ``lsr_available``. Refresh
scheduler toutes les 15 min (LSR Binance mis à jour ~5 min côté source).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_SOFT_VETO_MULTIPLIER = 0.85


def is_crypto_pair(pair: str) -> bool:
    """Mapping miroir des cryptos couvertes par Binance LSR."""
    return pair in {
        "BTC/USD", "ETH/USD", "SOL/USD", "ADA/USD", "XRP/USD",
        "LTC/USD", "BCH/USD", "DOT/USD", "DOGE/USD",
    }


def apply_lsr_filter(pair: str, direction: str) -> tuple[float, str | None]:
    """Retourne (multiplier, reason).

    multiplier : 1.0 (neutre) ou 0.85 (soft veto contrarien).
    reason : string explicative si veto soft, sinon None.

    Best-effort : (1.0, None) silencieusement sur toute erreur.
    """
    if not is_crypto_pair(pair):
        return 1.0, None
    try:
        from backend.services import binance_lsr_service as _lsr
        feats = _lsr.get_features(pair)
        if not feats.get("lsr_available"):
            return 1.0, None
        ratio = float(feats.get("lsr_ratio") or 0)
        long_pct = float(feats.get("lsr_long_pct") or 0)
        short_pct = float(feats.get("lsr_short_pct") or 0)
    except Exception as e:
        logger.debug(f"lsr_scoring {pair}: {e}")
        return 1.0, None

    # Réutilise les flags computés côté service (seuils 2.0 / 0.7)
    if direction == "buy" and feats.get("lsr_excess_long"):
        return (_SOFT_VETO_MULTIPLIER,
                f"LSR {ratio:.2f} ({long_pct*100:.0f}% comptes longs) — surcrowdé long, contrarien BUY")
    if direction == "sell" and feats.get("lsr_excess_short"):
        return (_SOFT_VETO_MULTIPLIER,
                f"LSR {ratio:.2f} ({short_pct*100:.0f}% comptes shorts) — surcrowdé short, contrarien SELL")
    return 1.0, None
