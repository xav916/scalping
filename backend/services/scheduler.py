"""Scheduler qui récupère périodiquement les données et lance l'analyse."""

import asyncio
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from backend.models.schemas import MarketOverview
from backend.services.analysis_engine import (
    analyze_trend,
    detect_signals,
    enrich_trade_setup,
    filter_high_confidence_setups,
)
from backend.services.forexfactory_service import fetch_economic_events
from backend.services.mataf_service import fetch_volatility_data
from backend.services.notification_service import broadcast_signals, broadcast_update
from backend.services.pattern_detector import calculate_trade_setup, detect_patterns
from backend.services.price_service import fetch_candles
from config.settings import (
    CANDLE_COUNT,
    CANDLE_INTERVAL,
    MATAF_POLL_INTERVAL,
    WATCHED_PAIRS,
)

logger = logging.getLogger(__name__)

# État partagé
_latest_overview: MarketOverview | None = None
_scheduler: AsyncIOScheduler | None = None


def get_latest_overview() -> MarketOverview | None:
    return _latest_overview


async def run_analysis_cycle() -> None:
    """Exécute un cycle complet : récupération, analyse, détection de patterns, notification."""
    global _latest_overview

    logger.info("Démarrage du cycle d'analyse...")

    try:
        # Récupérer toutes les données en parallèle
        fetch_tasks = [
            fetch_volatility_data(),
            fetch_economic_events(),
        ]
        # Ajouter la récupération des bougies pour chaque paire
        for pair in WATCHED_PAIRS:
            fetch_tasks.append(fetch_candles(pair, interval=CANDLE_INTERVAL, outputsize=CANDLE_COUNT))

        results = await asyncio.gather(*fetch_tasks)

        volatility_data = results[0]
        economic_events = results[1]

        # Regrouper les bougies par paire (fetch_candles retourne (candles, is_simulated))
        all_candles = {}
        simulated_pairs = {}
        for i, pair in enumerate(WATCHED_PAIRS):
            candles, is_simulated = results[2 + i]
            all_candles[pair] = candles
            simulated_pairs[pair] = is_simulated

        # Analyser les tendances pour chaque paire
        trends = [
            analyze_trend(pair, vol, economic_events)
            for pair in WATCHED_PAIRS
            for vol in volatility_data
            if vol.pair == pair
        ]

        # Détecter les patterns de scalping sur chaque paire
        all_patterns = []
        all_trade_setups = []
        all_candles_flat = []

        # Map volatility par paire pour enrichissement
        vol_map = {v.pair: v for v in volatility_data}
        trend_map = {t.pair: t for t in trends}

        for pair in WATCHED_PAIRS:
            candles = all_candles.get(pair, [])
            all_candles_flat.extend(candles)

            if candles:
                patterns = detect_patterns(candles, pair)
                all_patterns.extend(patterns)

                # Calculer les setups de trade pour chaque pattern
                for pattern in patterns:
                    setup = calculate_trade_setup(pair, pattern, candles, is_simulated=simulated_pairs.get(pair, False))
                    if setup:
                        # Enrichir avec score de confiance, explications, money management
                        enrich_trade_setup(
                            setup,
                            volatility=vol_map.get(pair),
                            trend=trend_map.get(pair),
                            events=economic_events,
                        )
                        all_trade_setups.append(setup)

        # Filtrer pour ne garder que les setups haute confiance
        all_trade_setups = filter_high_confidence_setups(all_trade_setups)

        # Détecter les signaux de scalping (volatilité + tendance)
        signals = detect_signals(
            volatility_data, economic_events, trends,
            trade_setups=all_trade_setups,
        )

        now = datetime.now(timezone.utc)
        _latest_overview = MarketOverview(
            volatility_data=volatility_data,
            economic_events=economic_events,
            trends=trends,
            signals=signals,
            candles=all_candles_flat[-100:],  # Garder les 100 dernières bougies
            patterns=all_patterns,
            trade_setups=all_trade_setups,
            last_update=now,
        )

        # Notifier les clients connectés
        if signals:
            logger.info(f"{len(signals)} signal(s) de scalping détecté(s)")
            await broadcast_signals(signals)

        # Envoyer la mise à jour complète
        await broadcast_update({
            "volatility": [v.model_dump(mode="json") for v in volatility_data],
            "events": [e.model_dump(mode="json") for e in economic_events],
            "trends": [t.model_dump(mode="json") for t in trends],
            "patterns": [p.model_dump(mode="json") for p in all_patterns],
            "trade_setups": [s.model_dump(mode="json") for s in all_trade_setups],
            "signals_count": len(signals),
            "setups_count": len(all_trade_setups),
            "last_update": now.isoformat(),
        })

        logger.info(
            f"Cycle terminé: {len(signals)} signal(s), "
            f"{len(all_patterns)} pattern(s), "
            f"{len(all_trade_setups)} setup(s) de trade"
        )

    except Exception as e:
        logger.error(f"Erreur cycle d'analyse: {e}", exc_info=True)


def start_scheduler() -> AsyncIOScheduler:
    """Démarre le scheduler périodique."""
    global _scheduler

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        run_analysis_cycle,
        "interval",
        seconds=MATAF_POLL_INTERVAL,
        id="analysis_cycle",
        name="Cycle d'analyse marché",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info(f"Scheduler démarré. Analyse toutes les {MATAF_POLL_INTERVAL}s")
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown()
        _scheduler = None
