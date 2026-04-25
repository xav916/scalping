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
from backend.services.backtest_engine import compute_volatility as _compute_vol_from_candles
from backend.services.forexfactory_service import fetch_economic_events
from backend.services.macro_context_service import refresh_macro_context
from backend.services import backtest_service, coaching, ml_features, ml_predictor
from backend.services.notification_service import (
    broadcast_cockpit,
    broadcast_signals,
    broadcast_update,
)
from backend.services.telegram_service import (
    send_setups as telegram_send_setups,
    send_signals as telegram_send_signals,
)
from backend.services.mt5_bridge import (
    health_check as mt5_bridge_health_check,
    send_setups as mt5_bridge_send_setups,
)
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
            fetch_economic_events(),
        ]
        # Bougies CANDLE_INTERVAL (5min) pour analyse principale
        for pair in WATCHED_PAIRS:
            fetch_tasks.append(fetch_candles(pair, interval=CANDLE_INTERVAL, outputsize=CANDLE_COUNT))
        # Bougies 1h pour confirmation MTF + calcul volatilité ATR
        # (cap a 50 bougies = 50h d'historique, suffisant pour ATR 14 + baseline 35)
        for pair in WATCHED_PAIRS:
            fetch_tasks.append(fetch_candles(pair, interval="1h", outputsize=50))

        results = await asyncio.gather(*fetch_tasks)

        economic_events = results[0]
        n = len(WATCHED_PAIRS)

        # Bougies 5min
        all_candles = {}
        simulated_pairs = {}
        for i, pair in enumerate(WATCHED_PAIRS):
            candles, is_simulated = results[1 + i]
            all_candles[pair] = candles
            simulated_pairs[pair] = is_simulated

        # Bougies 1h (pour MTF + volatilité)
        h1_candles = {}
        for i, pair in enumerate(WATCHED_PAIRS):
            try:
                cs, _sim = results[1 + n + i]
                h1_candles[pair] = cs
            except IndexError:
                h1_candles[pair] = []

        # Volatilité calculée localement depuis les bougies 1h Twelve Data.
        # Remplace l'ancien fetch Mataf.net (JS-rendered, scraping cassé →
        # ratio 0.0 systématique → factor Volatilité plafonné à 3/20).
        # ATR 14 sur 15 dernières bougies vs baseline 35 antérieures.
        volatility_data = [
            _compute_vol_from_candles(h1_candles.get(pair, []), pair)
            for pair in WATCHED_PAIRS
        ]

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
                        try:
                            if ml_predictor.is_available():
                                feats = ml_features.extract_features_for_setup(setup, h1_candles.get(pair, []))
                                if feats:
                                    proba = ml_predictor.predict_win_proba(feats)
                                    logger.info(
                                        f"ml_proba pair={setup.pair} dir={setup.direction.value} "
                                        f"pattern={setup.pattern.pattern.value} "
                                        f"conf_rule={setup.confidence_score:.1f} proba_ml={proba:.3f}"
                                    )
                        except Exception as e:
                            logger.debug(f"ml_proba shadow log failed: {e}")
                        all_trade_setups.append(setup)

        # Archive ML-ready : on persiste TOUS les signaux (y compris ceux
        # qui seront rejetes par le filtre de confiance) pour pouvoir
        # entrainer plus tard un classifieur sur les faux negatifs.
        try:
            events_by_ccy: dict[str, list] = {}
            for ev in economic_events:
                events_by_ccy.setdefault(ev.currency.upper(), []).append(ev)
            backtest_service.record_signals(
                all_trade_setups,
                volatility_by_pair=vol_map,
                trend_by_pair=trend_map,
                events_by_currency=events_by_ccy,
            )
        except Exception as e:
            logger.warning(f"Backtest record_signals a echoue: {e}")

        # Filtrer pour ne garder que les setups haute confiance
        all_trade_setups = filter_high_confidence_setups(all_trade_setups)

        # Enregistrer les setups haute-conf pour le backtest outcome (dedup par pair+entry)
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

        # Phase 4 — shadow log V2_CORE_LONG (lecture seule, ne touche pas V1)
        # Système recherche validé J1 : Sharpe 1.59 / maxDD 20% sur XAU H4.
        # Détecte les setups V2_CORE_LONG sur bougies H4 aggrégées depuis
        # h1_candles, persiste en DB shadow_setups pour observation. Pas
        # d'auto-exec, pas de Telegram, pas de UI alert.
        # Spec : docs/superpowers/specs/2026-04-25-phase4-shadow-log-spec.md
        try:
            from backend.services.shadow_v2_core_long import run_shadow_log
            shadow_counts = await run_shadow_log(h1_candles, cycle_at=now)
            if any(shadow_counts.values()):
                logger.info(f"shadow log V2_CORE_LONG: {shadow_counts}")
        except Exception as e:
            logger.warning(f"shadow log V2_CORE_LONG failed (non-bloquant): {e}")

        # Pousse un snapshot cockpit immediat des qu'un cycle se termine :
        # les clients connectes voient les nouveaux setups sans attendre le
        # prochain tick du job periodique (jusqu'a 5s de latence evitee).
        try:
            await broadcast_cockpit()
        except Exception as e:
            logger.warning(f"broadcast_cockpit apres cycle a echoue: {e}")

    except Exception as e:
        logger.error(f"Erreur cycle d'analyse: {e}", exc_info=True)


async def cockpit_broadcast_cycle() -> None:
    """Push periodique du snapshot cockpit (toutes les N secondes).

    Utile pour refresh les PnL unrealized des trades ouverts, meme entre
    deux cycles d'analyse (qui tournent toutes les 180-300s).
    No-op si aucun client connecte."""
    try:
        await broadcast_cockpit()
    except Exception as e:
        logger.warning(f"cockpit_broadcast_cycle a echoue: {e}")


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
    via Telegram, 5 min avant l'evenement.

    Sessions couvertes :
    - Sydney : ouverture hebdo dim 22h UTC (début de semaine forex)
    - Tokyo / London / New York : chaque jour de semaine
    - SPX/NDX (cash) : 13:30 UTC = 15:30 Paris en été, chaque jour de semaine
    """
    from backend.services.telegram_service import send_text

    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    # Reset au changement de jour
    global _session_alerts_sent
    if not any(k.startswith(today) for k in _session_alerts_sent):
        _session_alerts_sent.clear()

    # (heure_UTC, minute_UTC, nom, message, règle_weekend)
    # règle_weekend :
    #   "weekdays"     → envoie si l'ouverture tombe lun-ven
    #   "sunday_only"  → envoie uniquement si l'ouverture tombe un dimanche
    #                    (cas de Sydney qui ouvre la semaine forex)
    upcoming = [
        (22, 0, "Sydney", "🇦🇺 Ouverture Sydney dans 5 min — début de semaine forex", "sunday_only"),
        (0, 0, "Tokyo", "🇯🇵 Ouverture Tokyo dans 5 min — paires JPY actives", "weekdays"),
        (8, 0, "London", "🇬🇧 Ouverture London dans 5 min — paires EUR/GBP à surveiller", "weekdays"),
        (13, 0, "New York", "🇺🇸 Ouverture New York dans 5 min — début de l'overlap London/NY (heure d'or scalping)", "weekdays"),
        (13, 30, "SPX/NDX", "📈 Ouverture cash SPX/NDX dans 5 min — US stocks open", "weekdays"),
    ]
    for open_hour, open_minute, session_name, msg, weekend_rule in upcoming:
        alert_total = (open_hour * 60 + open_minute - 5) % (24 * 60)
        if now.hour * 60 + now.minute != alert_total:
            continue

        # L'alerte peut fire la veille (Tokyo à 23:55 la veille du lundi,
        # Sydney à 21:55 le dimanche), donc on regarde le weekday de
        # l'ouverture réelle, pas de now.
        open_dt = now + timedelta(minutes=5)
        wd = open_dt.weekday()  # 0=lundi ... 5=samedi, 6=dimanche

        if weekend_rule == "sunday_only":
            if wd != 6:
                continue
        elif weekend_rule == "weekdays":
            if wd >= 5:
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


# Surveillance du bridge MT5 côté PC : ping /health toutes les 5 min. On attend
# 2 échecs consécutifs avant d'alerter pour éviter le spam sur un timeout
# réseau transitoire (reconnexion Tailscale, reboot MT5, etc.).
_bridge_fail_count = 0
_bridge_alerted = False


async def bridge_health_cycle() -> None:
    """Ping périodique du bridge MT5 PC. Alerte Telegram après 2 échecs
    consécutifs, reset quand le bridge revient."""
    from backend.services.telegram_service import send_text

    global _bridge_fail_count, _bridge_alerted
    status = await mt5_bridge_health_check()
    if not status.get("configured"):
        return  # bridge non configuré : pas de surveillance

    if status.get("reachable"):
        if _bridge_alerted:
            try:
                await send_text("✅ *Scalping Radar*: bridge MT5 de nouveau joignable. Auto-exec réactivé.")
            except Exception as e:
                logger.warning(f"Bridge recovery alert echec: {e}")
        _bridge_fail_count = 0
        _bridge_alerted = False
        return

    _bridge_fail_count += 1
    logger.warning(f"Bridge MT5 injoignable (#{_bridge_fail_count}): {status.get('error') or status.get('status')}")
    if _bridge_fail_count >= 2 and not _bridge_alerted:
        _bridge_alerted = True
        try:
            reason = status.get("error") or f"HTTP {status.get('status')}"
            await send_text(
                f"🔌 *Scalping Radar*: bridge MT5 injoignable depuis 2 cycles "
                f"(~10 min). Auto-exec bloqué. Vérifier PC / MT5 Desktop / Tailscale.\n"
                f"Détail : `{reason}`"
            )
        except Exception as e:
            logger.warning(f"Bridge down alert echec: {e}")


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
    # Surveillance bridge MT5 toutes les 5 min (alerte après 2 échecs = 10 min)
    _scheduler.add_job(
        bridge_health_cycle,
        "interval",
        seconds=300,
        id="bridge_health",
        name="Surveillance bridge MT5",
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
    # Push cockpit toutes les 5s : rafraichit les PnL unrealized des trades
    # ouverts cote frontend. No-op si aucun client WS connecte.
    _scheduler.add_job(
        cockpit_broadcast_cycle,
        "interval",
        seconds=5,
        id="cockpit_broadcast",
        name="Push cockpit via WebSocket",
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

    # Alertes rafales de rejections : toutes les 5 min, surveille les
    # rejections de la derniere heure. Envoie Telegram si > 10 d'affilee
    # sur un meme reason_code (cooldown 60 min par code).
    from backend.services import rejection_alerts as _rej_alerts
    _scheduler.add_job(
        _rej_alerts.check_and_alert,
        "interval",
        minutes=5,
        id="rejection_alerts_check",
        name="Check rafales rejections + Telegram",
        replace_existing=True,
    )

    # Sync COT reports hebdo. La CFTC publie le vendredi 15h30 ET
    # (~20h30 UTC). On tourne samedi 01h UTC pour avoir les donnees
    # fraiches. Pas critique si ca loupe une semaine : la prochaine
    # execution recupere tout ce qui manque.
    from backend.services import cot_service as _cot
    _scheduler.add_job(
        _cot.sync_latest,
        CronTrigger(day_of_week="sat", hour=1, minute=0),
        id="cot_sync",
        name="Sync CFTC COT reports (hebdo)",
        replace_existing=True,
    )
    # CNN Fear & Greed Index : 1 fetch par jour a 22h UTC (apres la
    # fermeture des marches US). Best-effort : si CNN est indispo, on
    # retente le lendemain.
    from backend.services import fear_greed_service as _fg
    _scheduler.add_job(
        _fg.fetch_latest,
        CronTrigger(hour=22, minute=30),
        id="fear_greed_sync",
        name="Sync CNN Fear & Greed Index (quotidien)",
        replace_existing=True,
    )

    # SaaS : rappels trial J-3 / J-1 envoyés chaque jour à 9h UTC. Best-effort :
    # si SMTP désactivé, la fn devient no-op. Idempotent via trial_reminders_sent.
    from backend.services import user_email_service as _ues
    _scheduler.add_job(
        _ues.run_trial_reminders,
        CronTrigger(hour=9, minute=0),
        id="trial_reminders",
        name="Rappels trial J-3 / J-1 (SaaS)",
        replace_existing=True,
    )

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
