"""Filtre d'heures de trading par pipeline — UTC uniquement.

## Pourquoi

L'audit temporel 2026-11-14 a révélé que les pertes sur le compte réel
étaient concentrées sur les heures d'Asie illiquide (00h-01h, 05h-07h
UTC) avec -3 à -5 USD/trade, tandis que 02h-04h UTC (Tokyo matin)
était gagnant à +2.4 USD/trade.

Ce module permet d'interdire les scans de cycle hors des plages
définies, par pipeline, via env var ``<PREFIX>_TRADING_HOURS_UTC``.

## Format

``"HH:MM-HH:MM,HH:MM-HH:MM"`` — liste de plages horaires UTC séparées
par virgule. Les ranges qui franchissent minuit (``22:00-02:00``) sont
supportés.

Vide ou absent = aucune restriction (= comportement actuel).

## Exemples

- ``M5_TRADING_HOURS_UTC="02:00-05:00,08:00-21:00"`` : trade sur Tokyo
  matin + Londres/NY, skip Asie illiquide et nuit profonde.
- ``SCALP_TRADING_HOURS_UTC="08:00-16:00"`` : seulement session Londres
  (overlap NY inclus).
- Non défini : comportement actuel (trade H24 selon forex_hours).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, time, timezone

logger = logging.getLogger(__name__)


def _parse_hm(s: str) -> time:
    """Parse ``HH:MM`` → time object."""
    parts = s.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"format attendu HH:MM, reçu {s!r}")
    h = int(parts[0])
    m = int(parts[1])
    if not (0 <= h < 24) or not (0 <= m < 60):
        raise ValueError(f"heure invalide {s!r}")
    return time(hour=h, minute=m)


def parse_ranges(spec: str) -> list[tuple[time, time]]:
    """Parse ``"02:00-05:00,08:00-21:00"`` → ``[(02:00, 05:00), (08:00, 21:00)]``.

    Spec vide ou invalide → liste vide (= aucune restriction).
    """
    if not spec:
        return []
    ranges = []
    for rng in spec.split(","):
        rng = rng.strip()
        if not rng:
            continue
        try:
            start_s, end_s = rng.split("-")
            start = _parse_hm(start_s)
            end = _parse_hm(end_s)
            ranges.append((start, end))
        except (ValueError, IndexError) as e:
            logger.warning(
                "trading_hours: range invalide %r ignorée — %s", rng, e,
            )
            continue
    return ranges


def _now_in_any_range(
    now_t: time, ranges: list[tuple[time, time]],
) -> bool:
    """True si ``now_t`` tombe dans au moins une plage."""
    if not ranges:
        return True
    for start, end in ranges:
        if start <= end:
            # Même journée (ex: 02:00-05:00)
            if start <= now_t < end:
                return True
        else:
            # Franchit minuit (ex: 22:00-02:00)
            if now_t >= start or now_t < end:
                return True
    return False


def is_within_trading_hours(prefix: str) -> bool:
    """Autorise-t-on un cycle de trading maintenant pour ce pipeline ?

    Lit l'env var ``<PREFIX>_TRADING_HOURS_UTC``. Vide ou absente
    → True (comportement actuel). Sinon vérifie que ``now.time()``
    UTC tombe dans au moins une plage.

    Fail-open : exception interne → True (ne pas bloquer le trading
    sur un bug du garde-fou).
    """
    try:
        spec = os.getenv(f"{prefix}_TRADING_HOURS_UTC", "").strip()
        if not spec:
            return True
        ranges = parse_ranges(spec)
        if not ranges:
            return True
        now_t = datetime.now(timezone.utc).time()
        return _now_in_any_range(now_t, ranges)
    except Exception as e:  # noqa: BLE001
        logger.error(
            "trader_trading_hours: exception fail-open — %s", e,
        )
        return True
