"""Blackout auto-exec autour des events economiques HIGH-impact.

Principe : dans la fenetre +/- BLACKOUT_WINDOW_MIN autour d'un event
HIGH-impact sur la devise de la paire tradee, on bloque l'envoi de
nouveaux ordres au bridge.

Pourquoi ?
- Spread qui s'elargit d'un coup (broker protege ses marges)
- Prix qui saute sans remplir l'intermediaire (gap intraday)
- Volatilite post-news qui casse regulierement les SL serres du scalping

On ne coupe PAS l'emission de signaux — le radar continue d'analyser,
les signaux partent sur Telegram / cockpit, mais aucun ordre automatique
n'est envoye au bridge tant que la fenetre est active.

Les events sont pris depuis le dernier overview du scheduler
(economic_events deja filtres sur les ~24h a venir par forexfactory_service).

Exposition :
- `is_blackout_for(pair)` : True/False + raison pour le logging.
- `active_blackouts()` : liste payload pour l'UI cockpit.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# Fenetre +/- autour de l'event (en minutes). Choix 15min : suffit a
# absorber le pic de volatilite + les premiers mouvements post-news.
BLACKOUT_WINDOW_MIN = 15


def _event_currencies(pair: str) -> set[str]:
    """Devises impactees par un event — base + cotation de la paire.
    Pour XAU/USD, USD est impactant (la plupart des events macro affectent
    l'or via le dollar). Pour un index (SPX, NDX), USD est la reference."""
    if "/" in pair:
        base, quote = pair.upper().split("/", 1)
        return {base, quote}
    # Indices sans slash
    up = pair.upper()
    if up in {"SPX", "NDX", "DJI", "RUT", "US30", "US500", "NAS100"}:
        return {"USD"}
    if up in {"DAX", "CAC40", "UK100"}:
        return {"EUR", "GBP"}
    if up in {"N225", "NIKKEI", "JP225"}:
        return {"JPY"}
    if up in {"WTI", "BRENT"}:
        return {"USD"}
    return set()


def _parse_event_time(raw: str | None) -> datetime | None:
    """Les events forexfactory peuvent arriver en ISO ou HH:MM local UTC.
    On accepte les deux, on renvoie None si parsing KO."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None


def is_blackout_for(pair: str, events: list | None = None, now: datetime | None = None) -> dict:
    """Retourne `{active: bool, reason: str|None}`. Scanne les events
    HIGH-impact dans +/- BLACKOUT_WINDOW_MIN autour de `now`."""
    if now is None:
        now = datetime.now(timezone.utc)
    if events is None:
        # Best-effort : lire l'overview en cache.
        try:
            from backend.services.scheduler import get_latest_overview
            overview = get_latest_overview()
            events = overview.economic_events if overview else []
        except Exception:
            events = []

    currencies = _event_currencies(pair)
    if not currencies:
        return {"active": False, "reason": None}

    window = timedelta(minutes=BLACKOUT_WINDOW_MIN)
    for e in events:
        impact = (
            e.impact.value if hasattr(getattr(e, "impact", None), "value")
            else getattr(e, "impact", None)
        )
        if str(impact).lower() != "high":
            continue
        ccy = (getattr(e, "currency", "") or "").upper()
        if ccy not in currencies:
            continue
        when = _parse_event_time(getattr(e, "time", None))
        if when is None:
            continue
        if abs((when - now).total_seconds()) <= window.total_seconds():
            minutes = int((when - now).total_seconds() / 60)
            if minutes >= 0:
                label = f"HIGH {ccy} {getattr(e, 'event_name', '?')} dans {minutes}min"
            else:
                label = f"HIGH {ccy} {getattr(e, 'event_name', '?')} il y a {-minutes}min"
            return {"active": True, "reason": label}
    return {"active": False, "reason": None}


def active_blackouts(events: list | None = None, pairs: list[str] | None = None) -> list[dict]:
    """Liste des blackouts actifs maintenant (pour l'UI cockpit).
    Si `pairs` n'est pas fournie, on utilise WATCHED_PAIRS."""
    from config.settings import WATCHED_PAIRS
    pairs = pairs or list(WATCHED_PAIRS)
    items: list[dict] = []
    for p in pairs:
        status = is_blackout_for(p, events=events)
        if status["active"]:
            items.append({"pair": p, "reason": status["reason"]})
    return items
