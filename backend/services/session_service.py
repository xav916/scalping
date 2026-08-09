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


def activity_multiplier(dt: datetime | None = None, pair: str | None = None) -> float:
    """Multiplicateur d'activite a appliquer au risk_money.

    La grille est volontairement modeste (0.7x-1.2x) : on n'a pas encore
    les 500+ trades necessaires pour calibrer un edge session fort, mais
    on introduit deja le biais dans le bon sens.

    Cas crypto (2026-08-09) : la grille ne s'applique pas du tout. Sydney,
    Tokyo, London et NY sont des fenetres de volume du FOREX ; un perpetuel
    crypto cote 24/7 et n'a pas de seance. On retourne 1.0 a toute heure —
    donc ni penalite de weekend, ni bonus d'overlap : sans calibration, la
    neutralite est la seule valeur defendable, et elle doit valoir dans les
    deux sens.

    Ce que cela remplace : depuis 2026-06-14 le crypto en weekend recevait
    0.7 ("equiv. Asian"). Ce 0.7 n'etait pas une mesure, c'etait un pis-aller
    pour eviter qu'un multiplicateur de 0.0 ne tue risk_money et ne bloque
    l'auto-exec (cf. memo feedback_crypto_weekend_market_closed_bug). Il a
    coute 30% de taille sur les trois premiers trades reels de la route
    Kraken — qui ne trade QUE du crypto, sur des setups journaliers tombant
    a n'importe quelle heure.

    ⚠️ La reconnaissance passe par `asset_class_for`, qui repose sur une
    liste de prefixes codee en dur PLUS `ASSET_CLASS_OVERRIDES` du .env. Un
    instrument crypto non declare retombe en "forex" et recupere donc 0.0 le
    weekend, soit `risk_money = 0`. Le repli reste volontairement strict :
    elargir ici masquerait l'oubli de declaration au lieu de le reveler.

    Sans `pair`, comportement historique inchange (les appelants qui n'en
    fournissent pas gardent la grille telle quelle).
    """
    lbl = label(dt)
    if pair:
        try:
            from backend.services.market_hours import asset_class_for
            if asset_class_for(pair) == "crypto":
                return 1.0
        except Exception:
            pass
    grid = {
        "london_ny_overlap": 1.2,
        "new_york": 1.0,
        "london": 1.0,
        "asian": 0.7,
        "sydney": 0.7,
        "off_hours": 0.5,
        "weekend": 0.0,
    }
    return grid.get(lbl, 1.0)
