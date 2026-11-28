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
- ``MEANREV_TRADING_HOURS_UTC="13:00-16:00"`` : overlap Londres/NY
  uniquement — maximum liquidité pour les majors FX (cf. mesure
  2026-11-28 ci-dessous).
- Non défini : comportement actuel (trade H24 selon forex_hours).

## Mesure liquidité 2026-11-28 (28 jours tick_volume, majors FX)

Depuis ``spreads_minute.db``, tick_volume moyen par heure UTC
(marché ouvert) pour les 3 majors meanrev :

    AUD/USD : top 5 = 15h(58), 16h(56), 17h(53), 14h(49), 13h(49) t/min
              bot 5 = 22h(20), 23h(24), 00h(25), 21h(28), 06h(28)
    USD/CHF : top 5 = 15h(92), 16h(85), 14h(79), 17h(77), 13h(75) t/min
              bot 5 = 22h(21), 23h(28), 21h(29), 06h(32), 20h(35)
    GBP/USD : top 5 = 15h(122), 16h(120), 14h(110), 13h(104), 17h(103)
              bot 5 = 22h(27), 23h(32), 21h(43), 00h(47), 06h(51)

L'overlap Londres/NY (13h-16h UTC) sort systématiquement en tête :
sur ces 3 paires, 13-16h concentre le top 4 des tickvolume horaires.
Pour maximiser la profondeur de carnet (spreads serrés, slippage
minimum), restreindre MEANREV_TRADING_HOURS_UTC à "13:00-16:00".

Trade-off : fréquence de signaux divisée par ~4 (fenêtre 13h/24h →
3h/24h). À arbitrer selon le volume de trades souhaité.

Observation 16-23 nov (3 trades meanrev du state) :
- AUD/USD 11:01 UTC → 33 t/min, rang 14/24 (milieu)
- USD/CHF 15:07 UTC → 92 t/min, rang 1/24 (pic)
- GBP/USD 16:03 UTC → 120 t/min, rang 2/24 (quasi-pic)

L'AUD/USD aurait gagné +75% de liquidité en attendant 13-15h UTC.
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
