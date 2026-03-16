"""Service to fetch volatility data from Mataf.net."""

import logging
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup

from backend.models.schemas import VolatilityData, VolatilityLevel
from config.settings import (
    MATAF_VOLATILITY_URL,
    VOLATILITY_THRESHOLD_HIGH,
    VOLATILITY_THRESHOLD_MEDIUM,
    WATCHED_PAIRS,
)

logger = logging.getLogger(__name__)

# Headers to mimic a browser request
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def _classify_volatility(ratio: float) -> VolatilityLevel:
    if ratio >= VOLATILITY_THRESHOLD_HIGH:
        return VolatilityLevel.HIGH
    elif ratio >= VOLATILITY_THRESHOLD_MEDIUM:
        return VolatilityLevel.MEDIUM
    return VolatilityLevel.LOW


async def fetch_volatility_data() -> list[VolatilityData]:
    """Fetch volatility data from Mataf.net for watched currency pairs.

    Scrapes the volatility table and computes current vs average ratios.
    Returns a list of VolatilityData for each watched pair.
    """
    results: list[VolatilityData] = []
    now = datetime.now(timezone.utc)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(MATAF_VOLATILITY_URL, headers=HEADERS)
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "lxml")

        # Look for volatility table rows
        table = soup.find("table")
        if not table:
            logger.warning("No volatility table found on Mataf page")
            return _generate_fallback_data(now)

        rows = table.find_all("tr")
        for row in rows[1:]:  # skip header
            cells = row.find_all("td")
            if len(cells) < 3:
                continue

            pair_text = cells[0].get_text(strip=True).upper()
            # Normalize pair format (EURUSD -> EUR/USD)
            if len(pair_text) == 6 and "/" not in pair_text:
                pair_text = f"{pair_text[:3]}/{pair_text[3:]}"

            if pair_text not in WATCHED_PAIRS:
                continue

            try:
                current_vol = _parse_float(cells[1].get_text(strip=True))
                avg_vol = _parse_float(cells[2].get_text(strip=True))
                if avg_vol == 0:
                    continue

                ratio = current_vol / avg_vol
                results.append(VolatilityData(
                    pair=pair_text,
                    current_volatility=current_vol,
                    average_volatility=avg_vol,
                    volatility_ratio=round(ratio, 3),
                    level=_classify_volatility(ratio),
                    updated_at=now,
                ))
            except (ValueError, IndexError):
                continue

    except Exception as e:
        logger.error(f"Error fetching Mataf data: {e}")
        return _generate_fallback_data(now)

    # Fill in any missing pairs with fallback
    found_pairs = {v.pair for v in results}
    for pair in WATCHED_PAIRS:
        if pair not in found_pairs:
            results.append(_make_fallback_entry(pair, now))

    return results


def _parse_float(text: str) -> float:
    """Parse a float from text, removing non-numeric chars except dot."""
    cleaned = "".join(c for c in text if c.isdigit() or c == ".")
    return float(cleaned) if cleaned else 0.0


def _make_fallback_entry(pair: str, now: datetime) -> VolatilityData:
    """Create a neutral fallback entry when scraping fails."""
    return VolatilityData(
        pair=pair,
        current_volatility=0.0,
        average_volatility=0.0,
        volatility_ratio=1.0,
        level=VolatilityLevel.LOW,
        updated_at=now,
    )


def _generate_fallback_data(now: datetime) -> list[VolatilityData]:
    """Generate fallback data for all watched pairs."""
    return [_make_fallback_entry(pair, now) for pair in WATCHED_PAIRS]
