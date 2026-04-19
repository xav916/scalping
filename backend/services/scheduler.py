"""Scheduler qui récupère périodiquement les données et lance l'analyse."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from backend.models.schemas import MarketOverview
from backend.services.analysis_engine import (
    analyze_trend,
    detect_signals,
    enrich_trade_setup,
    filter_high_confidence_setups,
)
from backend.services.forexfactory_service import fetch_economic_events
from backend.services.macro_context_service import refresh_macro_context
from backend.services.mataf_service import fetch_volatility_data
from backend.services import backtest_service, coaching
from backend.services.notification_service import broadcast_signals, broadcast_update
from backend.services.telegram_service import (
    send_setups as telegram_send_setups,
    send_signals as telegram_send_signals,
)
from backend.services.mt5_bridge import send_setups as mt5_bridge_send_setups
from backend.services.pattern_detector import calculate_trade_setup, detect_patterns
from backend.services.price_service import fetch_candles
from config.settings import (
    CANDLE_COUNT,
    CANDLE_INTERVAL,
    MACRO_REFRESH_INTERVAL_SEC,
    MACRO_SCORING_ENABLED,
    MATAF_POLL_INTERVAL,
    WATCHED_PAIRS,
)

logger = logging.getLogger(__name__)

# État partagé
_latest_overview: MarketOverview | None = None
_latest_candles_by_pair: dict[str, list] = {}
_latest_h1_candles_by_pair: dict[str, list] = {}
_last_cycle_at: datetime | None = None
_scheduler: AsyncIOScheduler | None = None


def get_latest_overview() -> MarketOverview | None:
    return _latest_overview


def get_candles_for_pair(pair: str) -> list:
    """Retourne les dernieres bougies pour une paire donnee."""
    return _latest_candles_by_pair.get(pair, [])


def get_h1_candles_for_pair(pair: str) -> list:
    return _latest_h1_candles_by_pair.get(pair, [])


def get_all_pair_candles() -> dict[str, list]:
    return dict(_latest_candles_by_pair)


def get_last_cycle_at() -> datetime | None:
    return _last_cycle_at


def compute_h1_trend(candles: list) -> str:
    """Tendance simple sur bougies 1h : compare moyenne 5 dernieres vs 20 dernieres."""
    if len(candles) < 20:
        return "neutral"
    recent = sum(c.close for c in candles[-5:]) / 5
    longer = sum(c.close for c in candles[-20:]) / 20
    diff_pct = (recent - longer) / longer * 100
    if diff_pct > 0.15:
        return "bullish"
    if diff_pct < -0.15:
        return "bearish"
    return "neutral"


async def run_analysis_cycle() -> None:
    """Exécute un cycle complet : récupération, analyse, détection de patterns, notification."""
    global _latest_overview, _latest_candles_by_pair, _latest_h1_candles_by_pair, _last_cycle_at

    logger.info("Démarrage du cycle d'analyse...")
    _last_cycle_at = datetime.now(timezone.utc)

    try:
        # Récupérer toutes les données en parallèle
        fetch_tasks = [
            fetch_volatility_data(),
            fetch_economic_events(),
        ]
        # Bougies CANDLE_INTERVAL (5min) pour analyse principale
        for pair in WATCHED_PAIRS:
            fetch_tasks.append(fetch_candles(pair, interval=CANDLE_INTERVAL, outputsize=CANDLE_COUNT))
        # Bougies 1h pour confirmation MTF (cap a 50 bougies = 50h d'historique)
        for pair in WATCHED_PAIRS:
            fetch_tasks.append(fetch_candles(pair, interval="1h", outputsize=50))

        results = await asyncio.gather(*fetch_tasks)

        volatility_data = results[0]
        economic_events = results[1]
        n = len(WATCHED_PAIRS)

        # Bougies 5min
        all_candles = {}
        simulated_pairs = {}
        for i, pair in enumerate(WATCHED_PAIRS):
            candles, is_simulated = results[2 + i]
            all_candles[pair] = candles
            simulated_pairs[pair] = is_simulated

        # Bougies 1h (pour MTF)
        h1_candles = {}
        for i, pair in enumerate(WATCHED_PAIRS):
            try:
                cs, _sim = results[2 + n + i]
                h1_candles[pair] = cs
            except IndexError:
                h1_candles[pair] = []

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
                        # Enrichissement coaching : guidance + verdict (avec MTF)
                        vol = vol_map.get(pair)
                        tr = trend_map.get(pair)
                        h1_trend = compute_h1_trend(h1_candles.get(pair, []))
                        setup.guidance = coaching.generate_guidance(setup, volatility=vol, trend=tr, events=economic_events, h1_trend=h1_trend)
                        verdict = coaching.compute_verdict(setup, volatility=vol, trend=tr, events=economic_events, h1_trend=h1_trend)
                        setup.verdict_action = verdict["action"]
                        setup.verdict_summary = verdict["summary"]
                        setup.verdict_reasons = verdict["reasons"]
                        setup.verdict_warnings = verdict["warnings"]
                        setup.verdict_blockers = verdict["blockers"]
                        all_trade_setups.append(setup)

        # Filtrer pour ne garder que les setups haute confiance
        all_trade_setups = filter_high_confidence_setups(all_trade_setups)

        # Enregistrer les setups pour le backtest (dedup par pair+entry)
        try:
            backtest_service.record_setups(all_trade_setups)
        except Exception as e:
            logger.warning(f"Backtest record_setups a echoue: {e}")

        # Détecter les signaux de scalping (volatilité + tendance)
        signals = detect_signals(
            volatility_data, economic_events, trends,
            trade_setups=all_trade_setups,
        )

        now = datetime.now(timezone.utc)
        _latest_candles_by_pair = all_candles
        _latest_h1_candles_by_pair = h1_candles
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
            # Push Telegram en parallele (non-bloquant, best effort)
            asyncio.create_task(telegram_send_signals(signals))

        # Push Telegram des trade_setups (chemin distinct des signaux) :
        # pousse tous les setups avec verdict TAKE/WAIT + confiance au-dessus
        # du seuil. Dedup par (date, pair, direction, entry) dans le service.
        if all_trade_setups:
            asyncio.create_task(telegram_send_setups(all_trade_setups))
            # Push MT5 bridge : setups TAKE haute conviction → PC local via
            # Tailscale. Le bridge reste en PAPER_MODE par défaut, zéro risque.
            asyncio.create_task(mt5_bridge_send_setups(all_trade_setups))

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


async def backtest_check_cycle() -> None:
    """Cycle periodique : verifie les trades ouverts (hit SL / TP / open)."""
    try:
        await backtest_service.check_open_trades()
    except Exception as e:
        logger.warning(f"Backtest check_open_trades a echoue: {e}")


# Suivi des sessions deja annoncees aujourd'hui pour eviter les doublons
_session_alerts_sent: set[str] = set()


async def session_alert_cycle() -> None:
    """Tourne chaque minute : annonce les ouvertures de session importantes
    via Telegram, 5 min avant l'evenement."""
    from backend.services.telegram_service import send_text

    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    # Reset au changement de jour
    global _session_alerts_sent
    if not any(k.startswith(today) for k in _session_alerts_sent):
        _session_alerts_sent.clear()

    # Sessions surveillees (heure UTC d'ouverture)
    upcoming = [
        (8, "London", "🇬🇧 Ouverture London dans 5 min — paires EUR/GBP a surveiller"),
        (13, "New York", "🇺🇸 Ouverture New York dans 5 min — debut de l'overlap London/NY (heure d'or scalping)"),
        (0, "Tokyo", "🇯🇵 Ouverture Tokyo dans 5 min — paires JPY actives"),
    ]
    for open_hour, session_name, msg in upcoming:
        # Alerte 5 min avant ouverture
        alert_minute = (open_hour * 60 - 5) % (24 * 60)
        if now.hour * 60 + now.minute == alert_minute:
            # Skip si la session ouvre un sam/dim (forex fermé).
            # L'alerte peut fire la veille (Tokyo, open_hour=0 → alert à 23:55),
            # donc on regarde le weekday de l'ouverture réelle, pas de now.
            open_dt = now + timedelta(minutes=5)
            if open_dt.weekday() >= 5:  # 5=sam, 6=dim
                continue
            key = f"{today}-{session_name}"
            if key in _session_alerts_sent:
                continue
            _session_alerts_sent.add(key)
            try:
                await send_text(msg)
                logger.info(f"Pre-session alert envoyee: {session_name}")
            except Exception as e:
                logger.warning(f"Erreur alert session {session_name}: {e}")


async def daily_email_summary_cycle() -> None:
    """Envoi du resume email quotidien (sans user specifique = tous)."""
    try:
        from backend.services.email_summary import send_daily_summary, is_configured
        if not is_configured():
            return
        # Envoi pour chaque user configure (cf AUTH_USERS)
        from config.settings import AUTH_USERS
        users = list(AUTH_USERS.keys()) or [None]
        for u in users:
            send_daily_summary(user=u)
    except Exception as e:
        logger.warning(f"Daily email summary echec: {e}")


async def health_check_cycle() -> None:
    """Verifie que le radar tourne. Si aucun cycle d'analyse depuis >10 min,
    envoie une alerte Telegram (one-shot, evite le spam)."""
    from backend.services.telegram_service import send_text

    global _health_alerted
    last = get_last_cycle_at()
    if last is None:
        return
    delta = (datetime.now(timezone.utc) - last).total_seconds()
    if delta > 600:
        if not _health_alerted:
            _health_alerted = True
            try:
                await send_text(f"⚠️ *Scalping Radar*: aucun cycle d'analyse depuis {int(delta/60)} min. Le radar est peut-etre en panne.")
            except Exception as e:
                logger.warning(f"Health alert echec: {e}")
    else:
        _health_alerted = False


_health_alerted = False


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
    # Check backtest toutes les 60s (independant du cycle d'analyse)
    _scheduler.add_job(
        backtest_check_cycle,
        "interval",
        seconds=60,
        id="backtest_check",
        name="Check trades backtest",
        replace_existing=True,
    )
    # Alertes pre-session (toutes les minutes, ne fait quelque chose qu'a l'heure d'alerte)
    _scheduler.add_job(
        session_alert_cycle,
        "interval",
        seconds=60,
        id="session_alert",
        name="Alertes pre-session",
        replace_existing=True,
    )
    # Health check toutes les 2 min
    _scheduler.add_job(
        health_check_cycle,
        "interval",
        seconds=120,
        id="health_check",
        name="Health check radar",
        replace_existing=True,
    )
    # Email summary tous les jours a 22h UTC (~ 23h-00h heure FR selon DST)
    from apscheduler.triggers.cron import CronTrigger
    _scheduler.add_job(
        daily_email_summary_cycle,
        CronTrigger(hour=22, minute=0),
        id="email_summary",
        name="Email summary quotidien",
        replace_existing=True,
    )
    # Sync bridge MT5 → personal_trades : pull incrémental depuis /audit
    # pour que les ordres auto apparaissent dans le dashboard.
    from backend.services.mt5_sync import sync_from_bridge
    from config.settings import MT5_SYNC_INTERVAL_SEC
    _scheduler.add_job(
        sync_from_bridge,
        "interval",
        seconds=MT5_SYNC_INTERVAL_SEC,
        id="mt5_sync",
        name="Sync bridge MT5 → personal_trades",
        replace_existing=True,
    )
    if MACRO_SCORING_ENABLED:
        _scheduler.add_job(
            refresh_macro_context,
            "interval",
            seconds=MACRO_REFRESH_INTERVAL_SEC,
            id="macro_context_refresh",
            name="Refresh macro context snapshot",
            replace_existing=True,
        )
        logger.info(f"macro: refresh job scheduled every {MACRO_REFRESH_INTERVAL_SEC}s")

    _scheduler.start()
    logger.info(
        f"Scheduler démarré. Analyse {MATAF_POLL_INTERVAL}s, backtest 60s, "
        f"session_alert 60s, health 120s, mt5_sync {MT5_SYNC_INTERVAL_SEC}s"
    )
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown()
        _scheduler = None
