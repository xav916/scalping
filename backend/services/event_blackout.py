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

## ⛔ CE GARDE-FOU N'AVAIT JAMAIS BLOQUE UN SEUL ORDRE (corrige le 2026-09-20)

Constat, dans la copie de lecture : **zero ligne `event_blackout` dans
`signal_rejections`, depuis l'existence du code**. Cause, trouvee en lisant le
producteur et le consommateur cote a cote :

    forexfactory_service : time=dt.strftime("%H:%M")   ->  "14:30"
    event_blackout       : datetime.fromisoformat(raw) ->  LEVE sur "14:30"

Une heure SANS DATE d'un cote, un ISO complet exige de l'autre. Chaque annonce
etait donc ecartee en silence par le `continue`, et `is_blackout_for` ne pouvait
STRUCTURELLEMENT jamais rendre `active: True`.

⚠️ **Et pourquoi personne ne l'a vu : les tests fabriquaient
`time=when.isoformat()`.** Six tests verts sur un garde-fou inerte. Une fixture
plus capable que le producteur reel ne prouve rien — c'est le defaut derriere
le defaut, et il valait plus que le bug lui-meme.

🔑 **La reparation ne patche pas le parseur, elle change de source.**
`economic_calendar_service` stocke deja des `ts_utc` complets (170 events, 23
HIGH au 20/09) et expose exactement la fenetre qu'il faut. Le blackout lit
donc LA BASE, plus l'overview. La date manquante n'etait de toute facon pas
rattrapable cote consommateur : « 14:30 » ne dit pas quel jour.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# ⚠️ Interrupteur d'arret. Ce garde-fou passe aujourd'hui de « jamais declenche »
# a « actif », et il est verifie AVANT les verdict_blockers : il s'applique donc
# a TOUTES les destinations, y compris celles ou la pile de vetos douce est
# desactivee (MT5_BRIDGE_LIVE_RESPECT_VERDICT / _USER_). Si l'or se retrouve
# bloque plus souvent qu'utile, on coupe ici sans redeployer une logique.
ACTIF = os.getenv("EVENT_BLACKOUT_ENABLED", "true").strip().lower() in ("true", "1", "yes")

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


def _depuis_le_calendrier(pair: str, currencies: set[str],
                         now: datetime) -> dict | None:
    """La source PRINCIPALE : `economic_events`, avec de vrais `ts_utc`.

    Rend `{active, reason}` quand une annonce HIGH tombe dans la fenetre, un
    dict inactif quand le calendrier repond mais ne contient rien, et `None`
    quand le calendrier est INJOIGNABLE — trois etats, jamais deux : confondre
    « aucune annonce » et « je n'ai pas pu regarder » est exactement le defaut
    que ce fichier vient de payer.
    """
    try:
        from backend.services.economic_calendar_service import get_upcoming_events
        evs = get_upcoming_events(within_minutes=BLACKOUT_WINDOW_MIN,
                                  min_impact="High", now=now)
    except Exception as e:  # noqa: BLE001
        logger.warning("event_blackout: calendrier injoignable (%s) — "
                       "AUCUNE protection news sur %s ce cycle", e, pair)
        return None
    for e in evs:
        if (e.get("currency") or "").upper() not in currencies:
            continue
        m = int(e.get("minutes_delta") or 0)
        quand = f"dans {m}min" if m >= 0 else f"il y a {-m}min"
        return {"active": True,
                "reason": f"HIGH {e.get('currency')} {e.get('event_name', '?')} {quand}"}
    return {"active": False, "reason": None}


def is_blackout_for(pair: str, events: list | None = None, now: datetime | None = None) -> dict:
    """Retourne `{active: bool, reason: str|None}`. Scanne les events
    HIGH-impact dans +/- BLACKOUT_WINDOW_MIN autour de `now`.

    Sans `events` explicites, lit le calendrier en base (vrais `ts_utc`).
    Avec `events`, scanne la liste fournie — chemin conserve pour les tests et
    les appelants qui passent l'overview, mais il exige un `time` ISO complet.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if not ACTIF:
        return {"active": False, "reason": None}

    currencies = _event_currencies(pair)
    if not currencies:
        return {"active": False, "reason": None}

    if events is None:
        depuis_base = _depuis_le_calendrier(pair, currencies, now)
        if depuis_base is not None:
            return depuis_base
        return {"active": False, "reason": None}

    window = timedelta(minutes=BLACKOUT_WINDOW_MIN)
    illisibles = 0
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
            # ⛔ Le `continue` muet d'origine : c'est LUI qui a rendu ce
            # garde-fou inerte pendant dix semaines. On compte, et on le dit.
            illisibles += 1
            continue
        if abs((when - now).total_seconds()) <= window.total_seconds():
            minutes = int((when - now).total_seconds() / 60)
            if minutes >= 0:
                label = f"HIGH {ccy} {getattr(e, 'event_name', '?')} dans {minutes}min"
            else:
                label = f"HIGH {ccy} {getattr(e, 'event_name', '?')} il y a {-minutes}min"
            return {"active": True, "reason": label}
    if illisibles:
        logger.warning(
            "event_blackout: %d/%d events au `time` ILLISIBLE pour %s — le "
            "producteur emet probablement du \"HH:MM\" sans date. Aucune "
            "protection news tiree de cette liste.", illisibles, len(events), pair)
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
