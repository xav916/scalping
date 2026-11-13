"""Trailing stop partagé par les 10 pipelines traders.

## Principe

Un trailing stop déplace le SL dans le sens du profit pour verrouiller
une partie des gains dès que la position atteint un seuil d'activation.
Le SL ne peut JAMAIS reculer (ratchet one-way).

## Paramètres par pipeline

Chaque pipeline lit ses propres env vars préfixées :

- ``<PREFIX>_TRAILING_ENABLED`` (bool, défaut false)
- ``<PREFIX>_TRAILING_ACTIVATION_R`` (float, défaut 1.0) :
  profit en unités de R nécessaire avant activation
- ``<PREFIX>_TRAILING_DISTANCE_R`` (float, défaut 0.5) :
  distance du trailing en unités de R (R = |entry - sl_initial|)

## Exemple BUY (SCALP_TRAILING_* activés)

- Entry 3900.00, SL 3892.00 → R = 8.00 (sl_initial = 3892.00)
- ACTIVATION_R=1.0, DISTANCE_R=0.5
- Prix monte à 3908.00 : profit = 8.00 = 1R → activation
  → new_sl = max(3908.00 - 0.5×8.00, 3892.00) = max(3904.00, 3892.00) = 3904.00
- Prix monte à 3915.00 : new_sl = max(3911.00, 3904.00) = 3911.00
- Prix redescend à 3911.00 : hit new_sl, exit avec +11 (vs +0 au SL initial)

## Pré-requis

Le call-site doit stocker ``sl_initial`` dans la position lors de l'ouverture.
Sans ce champ, le trailing est inactif (fail-silent).
"""
from __future__ import annotations

import os


def _env_bool(key: str, default: str = "false") -> bool:
    return os.getenv(key, default).strip().lower() in ("true", "1", "yes", "on")


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


def is_enabled(prefix: str) -> bool:
    return _env_bool(f"{prefix}_TRAILING_ENABLED", "false")


def params(prefix: str) -> tuple[float, float]:
    """Retourne ``(activation_r, distance_r)`` pour le prefix."""
    return (
        _env_float(f"{prefix}_TRAILING_ACTIVATION_R", 1.0),
        _env_float(f"{prefix}_TRAILING_DISTANCE_R", 0.5),
    )


def update_trailing_sl(
    position: dict,
    current_price: float,
    prefix: str,
) -> float | None:
    """Calcule le nouveau SL si le trailing doit être ratché.

    Args:
        position: dict position avec au moins ``entry``, ``sl``, ``direction``,
            et ``sl_initial`` (SL d'entrée, utilisé pour calculer R).
        current_price: prix spot courant.
        prefix: préfixe env var du pipeline (SCALP, M5, DAILY, etc.)

    Returns:
        Nouveau SL arrondi SI le trailing doit se resserrer.
        ``None`` si pas d'ajustement (désactivé, profit insuffisant, SL
        déjà plus serré, données manquantes).

    ⛔ Ne modifie pas ``position`` en place — le call-site applique.
    """
    if not is_enabled(prefix):
        return None

    try:
        entry = float(position["entry"])
        sl = float(position["sl"])
        sl_initial = float(position.get("sl_initial", sl))
    except (KeyError, TypeError, ValueError):
        return None
    direction = position.get("direction")
    if direction not in ("buy", "sell"):
        return None

    activation_r, distance_r = params(prefix)
    one_r = abs(entry - sl_initial)
    if one_r <= 0:
        return None

    if direction == "buy":
        profit = current_price - entry
        if profit < activation_r * one_r:
            return None
        proposed = current_price - distance_r * one_r
        # Ratchet uniquement vers le haut (resserrage)
        if proposed > sl:
            return round(proposed, 5)
    else:  # sell
        profit = entry - current_price
        if profit < activation_r * one_r:
            return None
        proposed = current_price + distance_r * one_r
        # Ratchet uniquement vers le bas (resserrage)
        if proposed < sl:
            return round(proposed, 5)

    return None
