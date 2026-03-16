"""Scheduler that periodically fetches data and runs analysis."""

import asyncio
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from backend.models.schemas import MarketOverview
from backend.services.analysis_engine import analyze_trend, detect_signals
from backend.services.forexfactory_service import fetch_economic_events
from backend.services.mataf_service import fetch_volatility_data
from backend.services.notification_service import broadcast_signals, broadcast_update
from config.settings import MATAF_POLL_INTERVAL, FOREXFACTORY_POLL_INTERVAL, WATCHED_PAIRS

logger = logging.getLogger(__name__)

# Shared state for the latest market overview
_latest_overview: MarketOverview | None = None
_scheduler: AsyncIOScheduler | None = None


def get_latest_overview() -> MarketOverview | None:
    return _latest_overview


async def run_analysis_cycle() -> None:
    """Execute a full analysis cycle: fetch data, analyze, notify."""
    global _latest_overview

    logger.info("Starting analysis cycle...")

    try:
        # Fetch data concurrently
        volatility_data, economic_events = await asyncio.gather(
            fetch_volatility_data(),
            fetch_economic_events(),
        )

        # Analyze trends for each pair
        trends = [
            analyze_trend(pair, vol, economic_events)
            for pair in WATCHED_PAIRS
            for vol in volatility_data
            if vol.pair == pair
        ]

        # Detect scalping signals
        signals = detect_signals(volatility_data, economic_events, trends)

        # Build overview
        now = datetime.now(timezone.utc)
        _latest_overview = MarketOverview(
            volatility_data=volatility_data,
            economic_events=economic_events,
            trends=trends,
            signals=signals,
            last_update=now,
        )

        # Broadcast to connected clients
        if signals:
            logger.info(f"Detected {len(signals)} scalping signal(s)")
            await broadcast_signals(signals)

        # Broadcast full market update
        await broadcast_update({
            "volatility": [v.model_dump(mode="json") for v in volatility_data],
            "events": [e.model_dump(mode="json") for e in economic_events],
            "trends": [t.model_dump(mode="json") for t in trends],
            "signals_count": len(signals),
            "last_update": now.isoformat(),
        })

        logger.info(f"Analysis cycle complete. {len(signals)} signal(s) found.")

    except Exception as e:
        logger.error(f"Analysis cycle failed: {e}", exc_info=True)


def start_scheduler() -> AsyncIOScheduler:
    """Start the background scheduler for periodic analysis."""
    global _scheduler

    _scheduler = AsyncIOScheduler()

    # Run analysis at the shorter interval (Mataf)
    _scheduler.add_job(
        run_analysis_cycle,
        "interval",
        seconds=MATAF_POLL_INTERVAL,
        id="analysis_cycle",
        name="Market Analysis Cycle",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info(f"Scheduler started. Analysis every {MATAF_POLL_INTERVAL}s")
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown()
        _scheduler = None
