"""Classification de la session de marche en cours.

Fenetres UTC (horaires standards, DST ignoree — cela decale de 1h deux
fois par an, on acceptera l'approximation tant qu'on n'a pas de preuve
qu'elle biaise les stats) :
- Sydney   : 21:00 → 06:00
- Tokyo    : 00:00 → 09:00
- London   : 07:00 → 16:00
- New York : 12:00 → 21:00

Overlaps marquants :
- London/NY : 12:00 → 16:00 UTC (60% du volume daily forex)
- Sydney/Tokyo : 00:00 → 06:00 UTC

Le score `activity_multiplier` est utilise par `sizing.py` :
- overlap London/NY → 1.2x (sweet spot)
- London ou NY seul → 1.0x
- Asian hors overlap → 0.7x (ranges, mouvements lents)
- Weekend → 0.0x (on ne trade pas)
"""
from __future__ import annotations

from datetime import datetime, timezone


def _in_window(hour_utc: int, start: int, end: int) -> bool:
    """Vrai si `hour_utc` est dans [start, end), avec wrap a minuit
    (ex: Sydney 21-6 couvre 21,22,23,0,1,2,3,4,5)."""
    if start <= end:
        return start <= hour_utc < end
    return hour_utc >= start or hour_utc < end


def active_sessions(dt: datetime | None = None) -> list[str]:
    """Liste des sessions actives a l'instant `dt` (par defaut : now UTC)."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    hour = dt.hour
    sessions = []
    if _in_window(hour, 21, 6):
        sessions.append("sydney")
    if _in_window(hour, 0, 9):
        sessions.append("tokyo")
    if _in_window(hour, 7, 16):
        sessions.append("london")
    if _in_window(hour, 12, 21):
        sessions.append("new_york")
    return sessions


def is_weekend(dt: datetime | None = None) -> bool:
    """True si on est en weekend forex (vendredi 21h UTC -> dimanche 21h UTC).
    Simplification acceptable : certains brokers ferment 22h, tant pis."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    wd = dt.weekday()  # 0 = lundi ... 6 = dimanche
    hour = dt.hour
    if wd == 5:  # samedi
        return True
    if wd == 4 and hour >= 21:  # vendredi soir
        return True
    if wd == 6 and hour < 21:   # dimanche avant 21h
        return True
    return False


def label(dt: datetime | None = None) -> str:
    """Label lisible resumant la fenetre actuelle."""
    if is_weekend(dt):
        return "weekend"
    sessions = active_sessions(dt)
    london_ny = "london" in sessions and "new_york" in sessions
    tokyo_only = sessions == ["tokyo"] or sessions == ["sydney", "tokyo"]
    if london_ny:
        return "london_ny_overlap"
    if "new_york" in sessions:
        return "new_york"
    if "london" in sessions:
        return "london"
    if tokyo_only:
        return "asian"
    if "sydney" in sessions:
        return "sydney"
    return "off_hours"


def activity_multiplier(dt: datetime | None = None) -> float:
    """Multiplicateur d'activite a appliquer au risk_money.

    La grille est volontairement modeste (0.7x-1.2x) : on n'a pas encore
    les 500+ trades necessaires pour calibrer un edge session fort, mais
    on introduit deja le biais dans le bon sens.
    """
    lbl = label(dt)
    return {
        "london_ny_overlap": 1.2,
        "new_york": 1.0,
        "london": 1.0,
        "asian": 0.7,
        "sydney": 0.7,
        "off_hours": 0.5,
        "weekend": 0.0,
    }.get(lbl, 1.0)
