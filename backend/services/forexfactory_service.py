"""Service to fetch economic calendar data from Forex Factory.

Uses the free JSON feed at nfs.faireconomy.media for current week data.
Falls back to HTML scraping if the feed is unavailable.
"""

import logging
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


async def fetch_economic_events() -> list[EconomicEvent]:
    """Fetch this week's economic events.

    Strategy:
    1. Try the free JSON feed (easiest, most reliable)
    2. Fall back to HTML scraping
    3. Si tout échoue : retourne [] plutôt que des events fictifs qui
       pollueraient les warnings de verdict ('News high-impact à surveiller'
       alors qu'il n'y a rien de réel).
    """
    events = await _fetch_from_json_feed()
    if events:
        return events

    logger.info("JSON feed unavailable, falling back to HTML scraping")
    events = await _fetch_from_html()
    if events:
        return events

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


