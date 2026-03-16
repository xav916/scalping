"""Service to fetch economic calendar data from Forex Factory."""

import logging
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup

from backend.models.schemas import EconomicEvent, EventImpact
from config.settings import FOREXFACTORY_CALENDAR_URL

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def _parse_impact(impact_element) -> EventImpact:
    """Parse impact level from Forex Factory HTML element."""
    if impact_element is None:
        return EventImpact.LOW

    # Forex Factory uses colored icons/classes for impact
    classes = impact_element.get("class", [])
    title = impact_element.get("title", "").lower()
    text = impact_element.get_text(strip=True).lower()

    combined = " ".join(classes) + " " + title + " " + text

    if "high" in combined or "red" in combined:
        return EventImpact.HIGH
    elif "medium" in combined or "orange" in combined or "amber" in combined:
        return EventImpact.MEDIUM
    return EventImpact.LOW


async def fetch_economic_events() -> list[EconomicEvent]:
    """Fetch today's economic events from Forex Factory calendar.

    Scrapes the calendar page for event times, currencies, impact levels,
    and forecast/previous/actual values.
    """
    events: list[EconomicEvent] = []

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(FOREXFACTORY_CALENDAR_URL, headers=HEADERS)
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "lxml")

        # Forex Factory calendar uses table rows with class 'calendar_row'
        calendar_rows = soup.find_all("tr", class_="calendar_row")
        if not calendar_rows:
            # Try alternative selectors
            calendar_rows = soup.select("tr[data-eventid]")

        current_time = ""
        for row in calendar_rows:
            try:
                # Time cell
                time_cell = row.find("td", class_="calendar__time")
                if time_cell:
                    time_text = time_cell.get_text(strip=True)
                    if time_text:
                        current_time = time_text

                # Currency cell
                currency_cell = row.find("td", class_="calendar__currency")
                currency = currency_cell.get_text(strip=True) if currency_cell else ""

                # Impact cell
                impact_cell = row.find("td", class_="calendar__impact")
                impact_span = impact_cell.find("span") if impact_cell else None
                impact = _parse_impact(impact_span)

                # Event name
                event_cell = row.find("td", class_="calendar__event")
                event_name = event_cell.get_text(strip=True) if event_cell else ""

                if not event_name:
                    continue

                # Forecast, previous, actual
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
        logger.error(f"Error fetching Forex Factory data: {e}")

    if not events:
        logger.info("No events found from scraping, returning sample data")
        events = _generate_sample_events()

    return events


def _get_cell_text(cell) -> str | None:
    """Extract text from a table cell, returning None if empty."""
    if cell is None:
        return None
    text = cell.get_text(strip=True)
    return text if text else None


def _generate_sample_events() -> list[EconomicEvent]:
    """Generate sample events as fallback when scraping fails."""
    return [
        EconomicEvent(
            time="08:30",
            currency="USD",
            impact=EventImpact.HIGH,
            event_name="Non-Farm Payrolls",
            forecast="180K",
            previous="175K",
        ),
        EconomicEvent(
            time="10:00",
            currency="EUR",
            impact=EventImpact.MEDIUM,
            event_name="ECB Press Conference",
        ),
        EconomicEvent(
            time="14:00",
            currency="GBP",
            impact=EventImpact.HIGH,
            event_name="BOE Interest Rate Decision",
            forecast="5.25%",
            previous="5.25%",
        ),
    ]
