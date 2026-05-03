"""Agrégateur cockpit : un seul appel pour alimenter la page d'accueil.

Le dashboard est pensé comme une "tour de contrôle" — il doit répondre en
1 coup d'œil à 4 questions : qu'est-ce qui se passe (trades actifs), qu'est-ce
qui arrive (setups/events), comment va le système (bridge/cycle), quel est
le contexte (macro).

Ce service réunit les données déjà exposées sur plusieurs endpoints REST
pour offrir un snapshot cohérent en un seul round-trip. La logique métier
reste dans les services sources — on ne fait qu'orchestrer.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.services import trade_log_service
from backend.services.market_hours import is_market_open_for
from backend.services.mt5_bridge import health_check as mt5_bridge_health_check
from backend.services.notification_service import _connected_clients
from backend.services.scheduler import (
    get_candles_for_pair,
    get_last_cycle_at,
    get_latest_overview,
)
from backend.services.twelvedata_ws import get_latest_ticks
from config.settings import TRADING_CAPITAL, WATCHED_PAIRS

# Paires auto-exec stars (XAU/XAG/WTI/ETH) — affichées avec statut marché
# dans le cockpit. XLI/XLK volontairement exclus : shadow log uniquement.
_STAR_PAIRS_AUTO_EXEC = ("XAU/USD", "XAG/USD", "WTI/USD", "ETH/USD")

logger = logging.getLogger(__name__)


# Fenêtre pour flagger un event comme "imminent" dans le cockpit.
_IMMINENT_WINDOW = timedelta(hours=4)

# Seuil en % de la distance entry→SL en-dessous duquel on alerte "proche SL".
_SL_PROXIMITY_ALERT_PCT = 30.0

# Cache TTL pour le ping bridge MT5. Le cockpit peut etre appele a chaque
# cycle d'analyse ET tous les 5s via WebSocket ; pinger le bridge a cette
# frequence serait inutile (il y a deja un job dedie toutes les 5min). On
# autorise donc une reutilisation du dernier resultat pendant 30s.
_BRIDGE_HEALTH_TTL = timedelta(seconds=30)
_bridge_health_cache: dict | None = None
_bridge_health_cached_at: datetime | None = None


def _current_price(pair: str) -> float | None:
    """Dernier prix connu pour `pair` : tick temps réel > close bougie."""
    ticks = get_latest_ticks()
    if pair in ticks:
        return ticks[pair].price
    candles = get_candles_for_pair(pair)
    if candles:
        return candles[-1].close
    return None


def _units_per_lot(pair: str) -> float:
    """Unités sous-jacentes par lot. Approximation simple :
    - forex : 100 000
    - métaux (XAU/XAG) : 100 onces par lot
    Utilisé uniquement pour le PnL unrealized affiché en UI.
    """
    base = pair.split("/")[0].upper() if "/" in pair else pair.upper()
    if base in {"XAU", "XAG", "XPT", "XPD"}:
        return 100.0
    return 100_000.0


def _compute_unrealized_pnl(trade: dict, current_price: float) -> float:
    entry = trade["entry_price"]
    size = trade["size_lot"]
    units = _units_per_lot(trade["pair"]) * size
    if trade["direction"] == "buy":
        return round((current_price - entry) * units, 2)
    return round((entry - current_price) * units, 2)


def _pip_size(pair: str) -> float:
    """Taille d'un pip pour afficher un delta lisible.
    Approximation cohérente avec le reste du code.
    """
    base = pair.split("/")[0].upper() if "/" in pair else pair.upper()
    quote = pair.split("/")[1].upper() if "/" in pair else ""
    if base in {"XAU", "XAG", "XPT", "XPD"}:
        return 0.01
    if quote == "JPY":
        return 0.01
    return 0.0001


def _risk_money(trade: dict) -> float | None:
    """Max loss approximée en USD si le SL est touché.
    abs(entry - SL) * taille * units_per_lot, même approximation que PnL
    unrealized (ignore les conversions cross-currency)."""
    sl = trade.get("stop_loss")
    if sl is None:
        return None
    entry = trade["entry_price"]
    size = trade["size_lot"]
    units = _units_per_lot(trade["pair"]) * size
    return round(abs(entry - sl) * units, 2)


def _notional(trade: dict) -> float:
    """Exposition notionnelle en USD (entry * units * size). Représente
    l'enveloppe sous-jacente, pas la marge bloquée."""
    entry = trade["entry_price"]
    size = trade["size_lot"]
    units = _units_per_lot(trade["pair"]) * size
    return round(entry * units, 2)


def _enrich_open_trade(trade: dict) -> dict:
    """Ajoute PnL unrealized, distances SL/TP, durée, risk/notional, asset_class."""
    from config.settings import asset_class_for
    price = _current_price(trade["pair"])
    pip = _pip_size(trade["pair"])

    pnl_unrealized: float | None = None
    pnl_pips: float | None = None
    distance_to_sl_pct: float | None = None
    distance_to_tp_pct: float | None = None
    near_sl: bool = False

    if price is not None:
        pnl_unrealized = _compute_unrealized_pnl(trade, price)
        entry = trade["entry_price"]
        delta = price - entry if trade["direction"] == "buy" else entry - price
        pnl_pips = round(delta / pip, 1) if pip else None

        sl = trade.get("stop_loss")
        tp = trade.get("take_profit")
        sl_total = abs(entry - sl) if sl else None
        tp_total = abs(tp - entry) if tp else None

        # Distance restante au SL (% de la distance entry→SL encore disponible).
        if sl_total and sl_total > 0:
            if trade["direction"] == "buy":
                remaining = max(price - sl, 0.0)
            else:
                remaining = max(sl - price, 0.0)
            distance_to_sl_pct = round((remaining / sl_total) * 100, 1)
            near_sl = distance_to_sl_pct <= _SL_PROXIMITY_ALERT_PCT

        if tp_total and tp_total > 0:
            if trade["direction"] == "buy":
                remaining = max(tp - price, 0.0)
            else:
                remaining = max(price - tp, 0.0)
            distance_to_tp_pct = round((remaining / tp_total) * 100, 1)

    duration_min = None
    created_at = trade.get("created_at")
    if created_at:
        try:
            dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            duration_min = int((datetime.now(timezone.utc) - dt).total_seconds() // 60)
        except Exception:
            duration_min = None

    return {
        "id": trade.get("id"),
        "pair": trade["pair"],
        "asset_class": asset_class_for(trade["pair"]),
        "direction": trade["direction"],
        "entry_price": trade["entry_price"],
        "current_price": price,
        "stop_loss": trade.get("stop_loss"),
        "take_profit": trade.get("take_profit"),
        "size_lot": trade["size_lot"],
        "risk_money": _risk_money(trade),
        "notional": _notional(trade),
        "pnl_unrealized": pnl_unrealized,
        "pnl_pips": pnl_pips,
        "distance_to_sl_pct": distance_to_sl_pct,
        "distance_to_tp_pct": distance_to_tp_pct,
        "near_sl": near_sl,
        "duration_min": duration_min,
        "is_auto": bool(trade.get("is_auto")),
        "mt5_ticket": trade.get("mt5_ticket"),
    }


def _summarize_setup(setup: Any) -> dict:
    """Version compacte d'un TradeSetup pour le cockpit."""
    return {
        "pair": setup.pair,
        "direction": (
            setup.direction.value if hasattr(setup.direction, "value") else setup.direction
        ),
        "entry_price": setup.entry_price,
        "stop_loss": setup.stop_loss,
        "take_profit_1": setup.take_profit_1,
        "confidence_score": setup.confidence_score,
        "verdict_action": setup.verdict_action,
        "asset_class": setup.asset_class,
        "pattern": setup.pattern.pattern.value if setup.pattern else None,
        "message": setup.message,
        "timestamp": setup.timestamp.isoformat() if setup.timestamp else None,
    }


def _imminent_events(events: list) -> list[dict]:
    """Ne garde que les events dont l'heure tombe dans la fenêtre imminente."""
    now = datetime.now(timezone.utc)
    horizon = now + _IMMINENT_WINDOW
    items: list[dict] = []
    for e in events:
        # `time` peut être un ISO string ou un format HH:MM. On essaye ISO en priorité.
        when_dt: datetime | None = None
        raw = getattr(e, "time", None)
        if isinstance(raw, str):
            try:
                when_dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except Exception:
                when_dt = None
        if when_dt is None:
            # On garde l'event sans filtrage temporel si on ne peut pas le parser :
            # mieux vaut afficher trop que rien du tout.
            items.append({
                "time": raw,
                "currency": getattr(e, "currency", None),
                "impact": getattr(e.impact, "value", None) if hasattr(e, "impact") else None,
                "event_name": getattr(e, "event_name", None),
            })
            continue
        if now <= when_dt <= horizon:
            items.append({
                "time": when_dt.isoformat(),
                "currency": getattr(e, "currency", None),
                "impact": getattr(e.impact, "value", None) if hasattr(e, "impact") else None,
                "event_name": getattr(e, "event_name", None),
            })
    return items


def _macro_snapshot() -> dict | None:
    """Résumé macro pour le bandeau haut : None si indisponible."""
    from backend.services.macro_context_service import get_macro_snapshot, is_fresh

    snap = get_macro_snapshot()
    if snap is None:
        return None
    return {
        "fresh": is_fresh(snap.fetched_at),
        "risk_regime": snap.risk_regime.value,
        "dxy": snap.dxy_direction.value,
        "spx": snap.spx_direction.value,
        "vix_level": snap.vix_level.value,
        "vix_value": snap.vix_value,
        "fetched_at": snap.fetched_at.isoformat(),
    }


async def _cached_bridge_health() -> dict:
    """Ping bridge MT5 au plus une fois toutes les _BRIDGE_HEALTH_TTL secondes.
    Le job dedie `bridge_health_cycle` du scheduler garde le bridge sous
    surveillance toutes les 5min ; ici on ne fait que l'afficher."""
    global _bridge_health_cache, _bridge_health_cached_at
    now = datetime.now(timezone.utc)
    if (
        _bridge_health_cache is not None
        and _bridge_health_cached_at is not None
        and now - _bridge_health_cached_at < _BRIDGE_HEALTH_TTL
    ):
        return _bridge_health_cache
    result = await mt5_bridge_health_check()
    _bridge_health_cache = result
    _bridge_health_cached_at = now
    return result


async def _system_health() -> dict:
    last = get_last_cycle_at()
    seconds_since = None
    healthy_cycle = False
    if last:
        seconds_since = (datetime.now(timezone.utc) - last).total_seconds()
        healthy_cycle = seconds_since < 600  # < 10 min

    bridge = await _cached_bridge_health()
    bridge_ok = bool(bridge.get("reachable"))

    return {
        "healthy": healthy_cycle and (bridge_ok or not bridge.get("configured")),
        "last_cycle_at": last.isoformat() if last else None,
        "seconds_since_last_cycle": (
            round(seconds_since, 1) if seconds_since is not None else None
        ),
        "bridge": {
            "configured": bool(bridge.get("configured")),
            "reachable": bridge_ok,
            "mode": bridge.get("mode"),
        },
        "ws_clients": len(_connected_clients),
        "watched_pairs": len(WATCHED_PAIRS),
        "markets_open": {
            pair: is_market_open_for(pair) for pair in _STAR_PAIRS_AUTO_EXEC
        },
    }


def _build_alerts(active_trades: list[dict], next_events: list[dict]) -> list[dict]:
    alerts: list[dict] = []
    for t in active_trades:
        if t.get("near_sl"):
            alerts.append({
                "level": "warning",
                "code": "near_sl",
                "msg": f"{t['pair']} proche du stop loss ({t['distance_to_sl_pct']}% restant)",
            })
    for e in next_events:
        if (e.get("impact") or "").upper() == "HIGH":
            alerts.append({
                "level": "info",
                "code": "high_impact_event",
                "msg": f"Event HIGH imminent : {e.get('event_name')} ({e.get('currency')})",
            })
    return alerts


async def build_cockpit(user: str, user_id: int | None = None) -> dict:
    """Snapshot cockpit consolidé pour la homepage.

    Un seul appel depuis le frontend → 1 payload complet → rendu rapide
    et cohérent (toutes les zones partagent le même instant de lecture).

    `user_id` (Chantier 3 SaaS) : si fourni, scope la lecture par user_id
    pour isolation multi-tenant ; sinon fallback sur `user` TEXT (legacy).
    """
    # Trades actifs enrichis (PnL temps réel, distance SL/TP, durée).
    open_trades = trade_log_service.list_trades(status="OPEN", user=user, user_id=user_id)
    active_trades = [_enrich_open_trade(t) for t in open_trades]
    total_unrealized = sum((t["pnl_unrealized"] or 0) for t in active_trades)
    total_exposure = sum(t.get("size_lot") or 0 for t in active_trades)

    # Setups et events du dernier cycle d'analyse.
    overview = get_latest_overview()
    if overview is not None:
        setups = [_summarize_setup(s) for s in overview.trade_setups]
        takeable = [s for s in setups if s["verdict_action"] == "TAKE"]
        next_events = _imminent_events(overview.economic_events)
    else:
        setups = []
        takeable = []
        next_events = []

    # Stats du jour (réutilise la logique existante).
    daily = trade_log_service.get_daily_status(user=user, user_id=user_id)

    # Santé et contexte.
    health = await _system_health()
    macro = _macro_snapshot()

    # Etat du kill switch (info critique pour le cockpit : l'utilisateur
    # doit voir en un coup d'oeil si l'auto-exec est gele).
    from backend.services import kill_switch as _ks
    try:
        ks_status = _ks.status()
    except Exception:
        ks_status = {"active": False, "reason": None}

    # Blackouts actifs autour des events HIGH-impact. Visible dans l'UI
    # pour que l'utilisateur sache pourquoi un setup n'est pas execute.
    from backend.services import event_blackout as _ebo
    try:
        blackouts = _ebo.active_blackouts(
            events=overview.economic_events if overview else None
        )
    except Exception:
        blackouts = []

    # Session de marche en cours (contexte utile pour le sizing et l'UI).
    from backend.services import session_service as _session
    try:
        session_info = {
            "label": _session.label(),
            "activity_multiplier": _session.activity_multiplier(),
            "is_weekend": _session.is_weekend(),
        }
    except Exception:
        session_info = {}

    # COT extremes : positionnement des gros a >= 2 ecarts-types. Utile
    # comme signal contrarien en toile de fond.
    from backend.services import cot_service as _cot
    try:
        cot_extremes = _cot.find_extremes()
    except Exception:
        cot_extremes = []

    # CNN Fear & Greed : sentiment agrege equity US. Utile comme toile
    # de fond risk-on / risk-off complementaire au VIX et au regime macro.
    from backend.services import fear_greed_service as _fg
    try:
        fear_greed = _fg.get_current()
    except Exception:
        fear_greed = None

    alerts = _build_alerts(active_trades, next_events)
    if ks_status.get("active"):
        alerts.insert(0, {
            "level": "critical",
            "code": "kill_switch",
            "msg": f"Kill switch ACTIF : {ks_status.get('reason') or 'raison inconnue'}",
        })
    for bo in blackouts:
        alerts.append({
            "level": "warning",
            "code": "event_blackout",
            "msg": f"Blackout {bo['pair']} : {bo['reason']}",
        })
    for cot_item in cot_extremes:
        pair = cot_item.get("pair")
        for signal in cot_item.get("signals", []):
            alerts.append({
                "level": "info",
                "code": "cot_extreme",
                "msg": f"COT {pair} : {signal['interpretation']} (z={signal['z']})",
            })
    if fear_greed and fear_greed.get("classification") in ("extreme_fear", "extreme_greed"):
        alerts.append({
            "level": "info",
            "code": "fear_greed_extreme",
            "msg": (
                f"Fear & Greed : {fear_greed['classification']} "
                f"({fear_greed['value']}/100) — signal contrarien potentiel"
            ),
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "active_trades": {
            "count": len(active_trades),
            "total_exposure_lots": round(total_exposure, 2),
            "unrealized_pnl": round(total_unrealized, 2),
            "items": active_trades,
        },
        "pending_setups": {
            "count": len(takeable),
            "total_count": len(setups),
            "items": takeable[:10],
        },
        "today_stats": {
            "date": daily["date"],
            "pnl": daily["pnl_today"],
            "pnl_pct": daily["pnl_pct"],
            "n_trades": daily["n_trades_today"],
            "n_open": daily["n_open"],
            "n_closed": daily["n_closed_today"],
            "silent_mode": daily["silent_mode"],
            "loss_alert": daily["loss_alert"],
            "capital": TRADING_CAPITAL,
        },
        "system_health": health,
        "macro": macro,
        "kill_switch": ks_status,
        "session": session_info,
        "blackouts": blackouts,
        "cot_extremes": cot_extremes,
        "fear_greed": fear_greed,
        "next_events": next_events[:5],
        "alerts": alerts,
    }
