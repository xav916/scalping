"""Vocabulaire d'horizon d'analyse.

Trois écritures du même horizon cohabitent déjà dans le code, pour des
raisons historiques légitimes :

- ``SHADOW_CONFIG`` utilise ``"4h"`` / ``"1d"``
- ``VolatilityData.timeframe`` utilise ``"1H"``
- l'appel Twelve Data de ``run_shadow_log`` utilise ``"1day"``

Ce module est le point où elles se rejoignent. Il est volontairement pur :
ni base, ni réseau, ni horloge — ce qui le rend testable sans fixture et
utilisable depuis le dispatch, où chaque milliseconde compte.

⚠️ ``normalize`` rend ``None`` sur une étiquette inconnue, jamais une valeur
par défaut. Rendre ``"5min"`` ferait passer un setup non étiqueté pour du
scalping et le router vers de l'argent réel.
"""
from __future__ import annotations

# Horizons connus, du plus court au plus long.
HORIZONS: tuple[str, ...] = ("5min", "15min", "1h", "4h", "1d")

# Horizons à partir desquels une position se **détient** : elle paie un
# portage (funding, swap) et traverse des événements (earnings, week-end)
# qu'une position de scalping ne rencontrait jamais.
LONG_HORIZONS: frozenset[str] = frozenset({"4h", "1d"})

_MINUTES: dict[str, int] = {
    "5min": 5,
    "15min": 15,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}

# Écritures alternatives rencontrées dans le code existant, en minuscules.
_ALIASES: dict[str, str] = {
    "5m": "5min",
    "15m": "15min",
    "60min": "1h",
    "1hour": "1h",
    "4hour": "4h",
    "1day": "1d",
    "daily": "1d",
}


def normalize(label: str | None) -> str | None:
    """Ramène une étiquette d'horizon à sa forme canonique, ou ``None``."""
    if not label:
        return None
    cle = str(label).strip().lower()
    if not cle:
        return None
    cle = _ALIASES.get(cle, cle)
    return cle if cle in _MINUTES else None


def bar_minutes(horizon: str | None) -> int | None:
    """Durée d'une bougie de cet horizon, en minutes. ``None`` si inconnu."""
    canonique = normalize(horizon)
    return _MINUTES.get(canonique) if canonique else None


def is_long(horizon: str | None) -> bool:
    """``True`` si une position à cet horizon se détient plutôt qu'elle ne se scalpe.

    Fail-safe : un horizon inconnu rend ``False`` — il n'active pas les
    règles de portage. Il sera bloqué en amont par la porte d'horizon.
    """
    canonique = normalize(horizon)
    return canonique in LONG_HORIZONS if canonique else False
