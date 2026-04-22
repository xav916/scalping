"""Intégration avec le bridge MT5 local (tourne sur le PC Windows de l'user).

Le bridge tourne en loopback sur le PC et est joignable depuis l'EC2 via
Tailscale (ex: http://100.122.188.8:8787). Tant que le bridge tourne en
PAPER_MODE, AUCUN ordre réel n'est envoyé à MT5 — cet appel sert juste
à tracer les setups côté utilisateur.

Sécurité
- Filtre strict : confidence_score ≥ MT5_BRIDGE_MIN_CONFIDENCE (barrière numérique
  dédiée à l'auto-exec, décorrélée du verdict TAKE/WAIT/SKIP utilisé par
  Telegram/UI). Le gate TAKE historique filtrait trop — le scoring de base
  atteint rarement 75, ce qui produisait 0 auto-exec en pratique.
- Dedup in-memory (date, pair, direction, entry arrondi)
- Timeout court (5s) pour ne pas bloquer le cycle d'analyse si le bridge
  est down (PC éteint, Tailscale coupé)
- Best-effort : toute erreur est loggée et ignorée, jamais propagée
"""

import asyncio
import logging
from datetime import date

import httpx

from backend.services.market_hours import is_market_open_for
from config.settings import (
    MT5_BRIDGE_ENABLED,
    MT5_BRIDGE_URL,
    MT5_BRIDGE_API_KEY,
    MT5_BRIDGE_MIN_CONFIDENCE,
    MT5_BRIDGE_LOTS,
    MT5_BRIDGE_ALLOWED_ASSET_CLASSES,
    MT5_BRIDGE_MIN_SL_DISTANCE_PCT,
    MT5_BRIDGE_MIN_SL_DISTANCE_PCT_PER_CLASS,
    MT5_BRIDGE_MAX_POSITIONS_PER_PAIR,
    TRADING_CAPITAL,
    RISK_PER_TRADE_PCT,
    asset_class_for,
)

logger = logging.getLogger(__name__)

# Dedup in-memory : même setup dans la journée = pas de re-push.
# Clé : (date_iso, pair, direction, entry_arrondi_5dp).
_sent_setups_today: set[tuple[str, str, str, str]] = set()


def is_configured() -> bool:
    return bool(MT5_BRIDGE_ENABLED and MT5_BRIDGE_URL and MT5_BRIDGE_API_KEY)


def _direction_value(setup) -> str:
    d = setup.direction
    return d.value if hasattr(d, "value") else str(d)


def _dedup_key(setup) -> tuple[str, str, str, str]:
    return (
        date.today().isoformat(),
        setup.pair,
        _direction_value(setup),
        f"{setup.entry_price:.5f}",
    )


def _cleanup_old_keys() -> None:
    """Purge les entrées des jours précédents."""
    today = date.today().isoformat()
    for key in list(_sent_setups_today):
        if key[0] != today:
            _sent_setups_today.discard(key)


def _min_sl_distance_pct_for(pair: str) -> float:
    """Retourne le seuil min SL distance % applicable à cette pair.

    Priorité : dict per-class (avec cas spécial `forex_jpy` pour les pairs
    avec JPY comme quote/base) > fallback legacy MT5_BRIDGE_MIN_SL_DISTANCE_PCT.
    """
    cfg = MT5_BRIDGE_MIN_SL_DISTANCE_PCT_PER_CLASS or {}
    upper = (pair or "").upper()
    # Pairs JPY ont un pip size 10x plus grand → seuil dédié
    if "JPY" in upper:
        if "forex_jpy" in cfg:
            return float(cfg["forex_jpy"])
    asset_class = asset_class_for(pair)
    # Mapping asset_class → clé du dict. 'forex' → 'forex_major' pour
    # différencier des JPY pairs déjà traitées au-dessus.
    key_map = {
        "forex": "forex_major",
        "metal": "metal",
        "equity_index": "equity_index",
        "crypto": "crypto",
        "energy": "energy",
    }
    key = key_map.get(asset_class)
    if key and key in cfg:
        return float(cfg[key])
    return MT5_BRIDGE_MIN_SL_DISTANCE_PCT


def _max_positions_for_pair(pair: str) -> int:
    """Cap de positions simultanées pour cette pair, via asset class."""
    cfg = MT5_BRIDGE_MAX_POSITIONS_PER_PAIR or {}
    asset_class = asset_class_for(pair)
    if asset_class in cfg:
        return int(cfg[asset_class])
    return 2  # défaut générique


def _count_open_trades_for_pair(pair: str) -> int:
    """Compte les trades auto encore OPEN pour cette pair (source : DB
    locale personal_trades). Évite un round-trip bridge."""
    try:
        import sqlite3
        from backend.services.trade_log_service import _DB_PATH
        with sqlite3.connect(_DB_PATH) as c:
            row = c.execute(
                """
                SELECT COUNT(*) FROM personal_trades
                 WHERE is_auto = 1 AND status = 'OPEN' AND pair = ?
                """,
                (pair,),
            ).fetchone()
        return int(row[0]) if row else 0
    except Exception as e:
        logger.debug(f"mt5_bridge: count_open_trades_for_pair({pair}) failed: {e}")
        return 0


def _check_rejection(setup) -> str | None:
    """Retourne None si le setup peut être pushé, sinon un reason_code parmi
    ceux définis dans `rejection_service.REASON_LABELS_FR`. Seuls les cas qui
    représentent un "ordre perdu" sont loggés — pas les early-returns purement
    techniques (bridge non configuré, dedup, etc.).
    """
    if not is_configured():
        return "_not_configured"  # privé, non enregistré
    try:
        from backend.services import kill_switch
        if kill_switch.is_active():
            return "kill_switch"
    except Exception as e:
        logger.debug(f"mt5_bridge: kill_switch check failed: {e}")
    try:
        from backend.services import event_blackout
        bo = event_blackout.is_blackout_for(setup.pair)
        if bo["active"]:
            logger.info(
                f"mt5_bridge: blackout event pour {setup.pair} — {bo['reason']}"
            )
            return "event_blackout"
    except Exception as e:
        logger.debug(f"mt5_bridge: event_blackout check failed: {e}")
    if getattr(setup, "is_simulated", False):
        return "simulated_data"
    if getattr(setup, "verdict_blockers", None):
        return "verdict_blocker"
    if not is_market_open_for(setup.pair):
        return "market_closed"
    entry = getattr(setup, "entry_price", 0) or 0
    sl = getattr(setup, "stop_loss", 0) or 0
    if entry > 0 and sl > 0:
        sl_pct = abs(entry - sl) / entry * 100
        min_pct = _min_sl_distance_pct_for(setup.pair)
        if sl_pct < min_pct:
            return "sl_too_close"
    score = getattr(setup, "confidence_score", None) or 0
    if score < MT5_BRIDGE_MIN_CONFIDENCE:
        return "below_confidence"
    # Cap par pair : forcer la diversification. Le backtest a montré qu'on
    # peut avoir jusqu'à 5-7 trades XAU simultanés sur un même régime, ce
    # qui transforme 1 pari macro en 5-7 pertes corrélées si le régime
    # tourne. Limite configurable par asset class.
    open_count = _count_open_trades_for_pair(setup.pair)
    max_allowed = _max_positions_for_pair(setup.pair)
    if open_count >= max_allowed:
        return "max_positions_per_pair"
    return None


def _should_push(setup) -> bool:
    """Backward-compat : True si OK, False si rejeté."""
    return _check_rejection(setup) is None


async def send_setup(setup) -> None:
    """Push un trade_setup vers le bridge MT5 local si toutes les conditions
    sont remplies (verdict TAKE, seuil, dedup)."""
    from backend.services.rejection_service import record_rejection

    rejection = _check_rejection(setup)
    if rejection is not None:
        # Les reason codes privés (commencent par "_") ne sont pas loggés
        if not rejection.startswith("_"):
            record_rejection(
                pair=setup.pair,
                direction=_direction_value(setup),
                confidence=getattr(setup, "confidence_score", None),
                reason_code=rejection,
            )
        return
    # Guard asset class : broker actuel ne supporte pas toutes les classes
    asset_class = asset_class_for(setup.pair)
    if asset_class not in MT5_BRIDGE_ALLOWED_ASSET_CLASSES:
        logger.debug(
            f"mt5_bridge: skipping {setup.pair} ({asset_class}) — "
            f"broker supports only {MT5_BRIDGE_ALLOWED_ASSET_CLASSES}"
        )
        record_rejection(
            pair=setup.pair,
            direction=_direction_value(setup),
            confidence=getattr(setup, "confidence_score", None),
            reason_code="asset_class_blocked",
            details={"asset_class": asset_class, "allowed": list(MT5_BRIDGE_ALLOWED_ASSET_CLASSES)},
        )
        return
    _cleanup_old_keys()
    key = _dedup_key(setup)
    if key in _sent_setups_today:
        return
    _sent_setups_today.add(key)

    direction = _direction_value(setup)
    # Sizing dynamique : base = RISK_PER_TRADE_PCT du capital, module par
    # la confiance du signal (0.5x a 1.5x) et par le PnL recent (0.5x si
    # en drawdown sur 7j, sinon 1.0x). Voir sizing.compute_risk_money.
    from backend.services import sizing
    sz = sizing.compute_risk_money(setup)
    risk_money = sz["risk_money"]
    payload = {
        "pair": setup.pair,
        "direction": direction,
        "entry": setup.entry_price,
        "sl": setup.stop_loss,
        "tp": setup.take_profit_1,
        # risk_money : le bridge calcule les lots en utilisant les specs
        # RÉELLES du symbole chez le broker (trade_tick_value, volume_step,
        # etc.). Évite les formules forex appliquées aux métaux qui
        # sous-sizent sur XAU/XAG.
        "risk_money": risk_money,
        "comment": f"scalping-radar-{date.today().isoformat()}",
        # Infos complémentaires pour les logs du bridge
        "tp2": getattr(setup, "take_profit_2", None),
        "risk_pct": RISK_PER_TRADE_PCT,
        "confidence": getattr(setup, "confidence_score", None),
        "sizing_detail": sz,
    }

    url = MT5_BRIDGE_URL.rstrip("/") + "/order"
    headers = {
        "X-API-Key": MT5_BRIDGE_API_KEY,
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(url, json=payload, headers=headers)
            if r.status_code == 200:
                data = r.json()
                logger.info(
                    f"MT5 bridge → {setup.pair} {direction} "
                    f"risk=${risk_money} "
                    f"(conf={sz['conf_mult']}x pnl={sz['pnl_mult']}x "
                    f"session={sz['session']}:{sz['session_mult']}x "
                    f"macro={sz['macro_mult']}x"
                    + (f" {sz['macro_reasons']}" if sz.get('macro_reasons') else "")
                    + ") "
                    f"mode={data.get('mode', '?')}"
                )
            else:
                logger.warning(
                    f"MT5 bridge a répondu {r.status_code} pour {setup.pair}: "
                    f"{r.text[:200]}"
                )
                # Catégorise la rejection bridge pour la viz dédiée
                body_text = r.text or ""
                if r.status_code == 429 or "Max open positions" in body_text:
                    reason = "bridge_max_positions"
                elif "10016" in body_text or "INVALID_STOPS" in body_text:
                    reason = "bridge_invalid_stops"
                else:
                    reason = "bridge_error"
                record_rejection(
                    pair=setup.pair,
                    direction=direction,
                    confidence=getattr(setup, "confidence_score", None),
                    reason_code=reason,
                    details={"status": r.status_code, "body": body_text[:200]},
                )
                # Si l'ordre a été rejeté par le bridge, on retire de la dedup
                # pour qu'un cycle suivant puisse retenter.
                _sent_setups_today.discard(key)
    except httpx.TimeoutException:
        logger.info(f"MT5 bridge timeout (PC éteint ?) — skip {setup.pair}")
        record_rejection(
            pair=setup.pair,
            direction=direction,
            confidence=getattr(setup, "confidence_score", None),
            reason_code="bridge_timeout",
        )
        _sent_setups_today.discard(key)  # retente au cycle suivant
    except Exception as e:
        logger.warning(f"MT5 bridge exception pour {setup.pair}: {e}")
        record_rejection(
            pair=setup.pair,
            direction=direction,
            confidence=getattr(setup, "confidence_score", None),
            reason_code="bridge_error",
            details={"exception": str(e)[:200]},
        )
        _sent_setups_today.discard(key)


async def send_setups(setups: list) -> None:
    """Push plusieurs setups en parallèle. No-op si bridge pas configuré."""
    if not is_configured() or not setups:
        return
    # Pré-filtre sur l'asset class supportée par le broker courant.
    setups = [
        s for s in setups
        if asset_class_for(s.pair) in MT5_BRIDGE_ALLOWED_ASSET_CLASSES
    ]
    if not setups:
        return
    await asyncio.gather(*(send_setup(s) for s in setups), return_exceptions=True)


async def get_account() -> dict:
    """Récupère l'état du compte broker via bridge /account.

    Retourne un dict enrichi avec `margin_level_pct` (équity / margin × 100).
    Si bridge pas configuré ou injoignable, retourne
    `{configured: bool, reachable: False, error: str}`.
    """
    if not is_configured():
        return {"configured": False, "reachable": False}
    url = MT5_BRIDGE_URL.rstrip("/") + "/account"
    headers = {"X-API-Key": MT5_BRIDGE_API_KEY}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(url, headers=headers)
            if r.status_code != 200:
                return {
                    "configured": True,
                    "reachable": False,
                    "status": r.status_code,
                }
            data = r.json()
            margin = float(data.get("margin") or 0)
            equity = float(data.get("equity") or 0)
            # Margin level = equity / margin × 100. Indéfini si margin=0
            # (aucune position ouverte) → convention broker: "Infinity",
            # on renvoie None pour que l'UI affiche "—".
            margin_level_pct = (equity / margin * 100) if margin > 0 else None
            return {
                "configured": True,
                "reachable": True,
                **data,
                "margin_level_pct": margin_level_pct,
            }
    except httpx.TimeoutException:
        return {"configured": True, "reachable": False, "error": "timeout"}
    except Exception as e:
        return {"configured": True, "reachable": False, "error": str(e)[:120]}


async def health_check() -> dict:
    """Retourne l'état du bridge depuis le point de vue du backend.
    Utile pour un endpoint de debug ou un indicateur UI côté site."""
    if not is_configured():
        return {"configured": False}
    url = MT5_BRIDGE_URL.rstrip("/") + "/health"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(url)
            if r.status_code == 200:
                return {"configured": True, "reachable": True, **r.json()}
            return {"configured": True, "reachable": False, "status": r.status_code}
    except Exception as e:
        return {"configured": True, "reachable": False, "error": str(e)[:100]}
