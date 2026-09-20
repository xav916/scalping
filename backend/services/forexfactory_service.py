"""Service to fetch economic calendar data from Forex Factory.

Uses the free JSON feed at nfs.faireconomy.media for current week data.
Falls back to HTML scraping if the feed is unavailable.
"""

import logging
import os
import time as _time
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup

from backend.models.schemas import EconomicEvent, EventImpact
from config.settings import FOREXFACTORY_CALENDAR_URL

logger = logging.getLogger(__name__)

# Free JSON feed for current week's Forex Factory calendar
FF_JSON_FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def _normalize_impact(impact_str: str) -> EventImpact:
    """Normalize impact string from JSON feed or HTML."""
    impact_lower = impact_str.lower().strip()
    if impact_lower in ("high", "red"):
        return EventImpact.HIGH
    elif impact_lower in ("medium", "orange", "amber"):
        return EventImpact.MEDIUM
    return EventImpact.LOW


# ⛔ CACHE — ajouté le 2026-09-20 après mesure, pas par principe. Cette
# fonction est appelée par le cycle d'analyse du scheduler, donc TOUTES LES
# TROIS MINUTES : les logs de production montraient « Fetched 75 events from
# JSON feed » à 19:08, 19:11, 19:14, 19:17… soit ~480 requêtes par jour vers
# nfs.faireconomy.media. Or ce calendrier est HEBDOMADAIRE — le scheduler a
# d'ailleurs un job dédié qui ne le rafraîchit que dimanche et jeudi.
#
# 🔑 Le risque n'était pas le coût, c'était le BANNISSEMENT : un feed gratuit
# martelé 480 fois par jour finit par répondre 403, et alors le calendrier
# tombe — avec lui le blackout des annonces et les warnings de verdict.
_TTL_SEC = int(os.getenv("FF_CACHE_TTL_SEC", "1800"))
# Au-delà de cette ancienneté on préfère une liste vide à un calendrier périmé :
# une semaine de retard ferait blackouter sur des annonces déjà passées.
_PERIME_SEC = int(os.getenv("FF_CACHE_MAX_AGE_SEC", "21600"))
_cache: tuple[float, list[EconomicEvent]] | None = None


def _depuis_le_calendrier(heures: int = 36) -> list[EconomicEvent]:
    """Les events des ~36 h a venir, lus dans `economic_events`.

    ⚠️ `time` reste au format "HH:MM" : c'est ce que l'UI affiche, et le
    changer casserait le front. Ce n'est plus un probleme depuis que
    `event_blackout` lit la base directement — mais la raison est ecrite ici
    pour que personne ne "repare" ce format en croyant bien faire.
    """
    try:
        from backend.services.economic_calendar_service import get_upcoming_events
        brut = get_upcoming_events(within_minutes=heures * 60, min_impact="Low")
    except Exception as e:  # noqa: BLE001
        logger.warning("forexfactory: economic_events illisible (%s)", e)
        return []
    out: list[EconomicEvent] = []
    for e in brut:
        try:
            quand = datetime.fromisoformat(e["ts_utc"])
        except (ValueError, TypeError, KeyError):
            continue
        out.append(EconomicEvent(
            time=quand.strftime("%H:%M"),
            currency=(e.get("currency") or "").upper(),
            impact=_normalize_impact(e.get("impact") or "Low"),
            event_name=e.get("event_name") or "?",
            forecast=e.get("forecast") or None,
            previous=e.get("previous") or None,
            actual=e.get("actual") or None,
        ))
    return out


def _cache_lisible(maxi: int) -> list[EconomicEvent] | None:
    if _cache is None:
        return None
    age = _time.monotonic() - _cache[0]
    return _cache[1] if age <= maxi else None


async def fetch_economic_events() -> list[EconomicEvent]:
    """Fetch this week's economic events.

    Strategy:
    1. Cache en mémoire (TTL `FF_CACHE_TTL_SEC`, 30 min par défaut)
    2. Try the free JSON feed (easiest, most reliable)
    3. Fall back to HTML scraping
    4. Si tout échoue : le dernier calendrier connu s'il a moins de
       `FF_CACHE_MAX_AGE_SEC` (6 h), sinon [] plutôt que des events fictifs
       qui pollueraient les warnings de verdict ('News high-impact à
       surveiller' alors qu'il n'y a rien de réel).

    ⚠️ Le repli sur le cache périmé est un choix, pas un oubli : un calendrier
    vieux de deux heures reste VRAI, alors qu'une liste vide fait croire qu'il
    n'y a aucune annonce — et c'est cette forme de silence qui a laissé le
    blackout des news inerte pendant dix semaines.
    """
    global _cache
    frais = _cache_lisible(_TTL_SEC)
    if frais is not None:
        logger.debug("forexfactory: cache (%d events, TTL %ds)", len(frais), _TTL_SEC)
        return frais

    # ⛔ LA BASE D'ABORD, LE RESEAU ENSUITE — ordre inverse jusqu'au 2026-09-20,
    # et voici ce que les logs de production montraient au redemarrage :
    #
    #   20:04:49  economic_calendar_service: refreshed 73 events        <- OK
    #   20:04:51  forexfactory_service: JSON feed failed: 429           <- jete
    #   20:04:51  HTML scraping failed: 403 Forbidden
    #
    # DEUX services appelaient la MEME url a deux secondes d'intervalle. Le
    # premier passait, le second se faisait limiter — et comme le repli HTML
    # repond 403, l'overview repartait avec ZERO event. Le bannissement n'etait
    # donc pas un risque a venir : il etait deja la.
    #
    # 🔑 Une seule source de verite : `economic_calendar_service` va au feed
    # (dimanche et jeudi, job dedie) et stocke des `ts_utc` complets. Ici on
    # LIT sa base. Le reseau ne sert plus que si cette base est vide.
    depuis_base = _depuis_le_calendrier()
    if depuis_base:
        _cache = (_time.monotonic(), depuis_base)
        logger.info("forexfactory: %d events lus dans economic_events "
                    "(aucun appel reseau)", len(depuis_base))
        return depuis_base

    events = await _fetch_from_json_feed()
    if events:
        _cache = (_time.monotonic(), events)
        return events

    logger.info("JSON feed unavailable, falling back to HTML scraping")
    events = await _fetch_from_html()
    if events:
        _cache = (_time.monotonic(), events)
        return events

    vieux = _cache_lisible(_PERIME_SEC)
    if vieux is not None:
        logger.warning(
            "forexfactory: feed ET scraping indisponibles — on sert le dernier "
            "calendrier connu (%d events). Un calendrier vieux reste vrai ; une "
            "liste vide ferait croire qu'aucune annonce n'approche.", len(vieux))
        return vieux

    logger.warning("ForexFactory indisponible (JSON + HTML), pas de calendrier ce cycle")
    return []


async def _fetch_from_json_feed() -> list[EconomicEvent]:
    """Fetch from the free JSON feed at nfs.faireconomy.media."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(FF_JSON_FEED_URL, headers=HEADERS)
            response.raise_for_status()

        data = response.json()
        events: list[EconomicEvent] = []

        for item in data:
            try:
                # Parse date string to extract time
                date_str = item.get("date", "")
                time_str = ""
                if date_str:
                    try:
                        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                        time_str = dt.strftime("%H:%M")
                    except (ValueError, TypeError):
                        time_str = ""

                title = item.get("title", "")
                if not title:
                    continue

                events.append(EconomicEvent(
                    time=time_str,
                    currency=item.get("country", "").upper(),
                    impact=_normalize_impact(item.get("impact", "Low")),
                    event_name=title,
                    forecast=item.get("forecast") or None,
                    previous=item.get("previous") or None,
                    actual=None,  # JSON feed doesn't include actuals
                ))
            except Exception as e:
                logger.debug(f"Error parsing JSON event: {e}")
                continue

        logger.info(f"Fetched {len(events)} events from JSON feed")
        return events

    except Exception as e:
        logger.warning(f"JSON feed failed: {e}")
        return []


async def _fetch_from_html() -> list[EconomicEvent]:
    """Fall back to scraping the Forex Factory HTML calendar."""
    events: list[EconomicEvent] = []

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(FOREXFACTORY_CALENDAR_URL, headers=HEADERS)
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "lxml")

        # Forex Factory calendar uses table rows with class 'calendar_row'
        calendar_rows = soup.find_all("tr", class_="calendar_row")
        if not calendar_rows:
            calendar_rows = soup.select("tr[data-eventid]")

        current_time = ""
        for row in calendar_rows:
            try:
                time_cell = row.find("td", class_="calendar__time")
                if time_cell:
                    time_text = time_cell.get_text(strip=True)
                    if time_text:
                        current_time = time_text

                currency_cell = row.find("td", class_="calendar__currency")
                currency = currency_cell.get_text(strip=True) if currency_cell else ""

                impact_cell = row.find("td", class_="calendar__impact")
                impact_span = impact_cell.find("span") if impact_cell else None
                impact = _parse_html_impact(impact_span)

                event_cell = row.find("td", class_="calendar__event")
                event_name = event_cell.get_text(strip=True) if event_cell else ""
                if not event_name:
                    continue

                forecast_cell = row.find("td", class_="calendar__forecast")
                previous_cell = row.find("td", class_="calendar__previous")
                actual_cell = row.find("td", class_="calendar__actual")

                events.append(EconomicEvent(
                    time=current_time,
                    currency=currency.upper(),
                    impact=impact,
                    event_name=event_name,
                    forecast=_get_cell_text(forecast_cell),
                    previous=_get_cell_text(previous_cell),
                    actual=_get_cell_text(actual_cell),
                ))
            except Exception as e:
                logger.debug(f"Error parsing calendar row: {e}")
                continue

    except Exception as e:
        logger.error(f"HTML scraping failed: {e}")

    return events


def _parse_html_impact(impact_element) -> EventImpact:
    """Parse impact level from Forex Factory HTML element."""
    if impact_element is None:
        return EventImpact.LOW

    classes = impact_element.get("class", [])
    title = impact_element.get("title", "").lower()
    text = impact_element.get_text(strip=True).lower()
    combined = " ".join(classes) + " " + title + " " + text

    if "high" in combined or "red" in combined:
        return EventImpact.HIGH
    elif "medium" in combined or "orange" in combined or "ora" in combined:
        return EventImpact.MEDIUM
    return EventImpact.LOW


def _get_cell_text(cell) -> str | None:
    if cell is None:
        return None
    text = cell.get_text(strip=True)
    return text if text else None


