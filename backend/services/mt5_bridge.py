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
from datetime import date, datetime, timezone

import httpx

from backend.services.market_hours import is_market_open_for
from backend.services.shadow_v2_core_long import SHADOW_PAIRS as _STAR_PAIRS
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
    MT5_BRIDGE_BLOCKED_DIRECTIONS,
    MT5_BRIDGE_AVOID_HOURS_UTC,
    TRADING_CAPITAL,
    RISK_PER_TRADE_PCT,
    asset_class_for,
)

logger = logging.getLogger(__name__)

# Dedup in-memory : même setup dans la journée = pas de re-push.
# Clé : (date_iso, pair, direction, entry_arrondi_5dp).
_sent_setups_today: set[tuple[str, str, str, str]] = set()

# Filtre auto-exec : on n'envoie au bridge MT5 que les setups dont la paire
# fait partie du portefeuille stars Phase 4 (XAU/XAG/WTI/ETH/XLI/XLK).
# Cohérent avec le filtre Telegram. XLI/XLK ne sont pas dans WATCHED_PAIRS
# côté V1 et n'apparaîtront jamais ici en pratique.
_STAR_PAIRS_SET: frozenset[str] = frozenset(_STAR_PAIRS)


def is_configured() -> bool:
    return bool(MT5_BRIDGE_ENABLED and MT5_BRIDGE_URL and MT5_BRIDGE_API_KEY)


def _direction_value(setup) -> str:
    d = setup.direction
    return d.value if hasattr(d, "value") else str(d)


def _dedup_key(setup, dest_id: str = "admin_legacy") -> tuple[str, str, str, str, str]:
    """Clé de dedup étendue avec ``dest_id`` pour le multi-tenant routing.

    L'ordre est ``(date, pair, direction, entry, dest_id)`` — pair en
    position [1] est figé pour ne pas casser les tests legacy qui font
    ``k[0]==today and k[1]==pair``. ``dest_id`` en queue permet à plusieurs
    destinations de pousser le même setup sans collision.
    """
    return (
        date.today().isoformat(),
        setup.pair,
        _direction_value(setup),
        f"{setup.entry_price:.5f}",
        dest_id,
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


def _check_rejection(setup, dest=None) -> str | None:
    """Retourne None si le setup peut être pushé, sinon un reason_code parmi
    ceux définis dans `rejection_service.REASON_LABELS_FR`. Seuls les cas qui
    représentent un "ordre perdu" sont loggés — pas les early-returns purement
    techniques (bridge non configuré, dedup, etc.).

    Si ``dest`` (``BridgeConfig``) est fourni, utilise ``dest.min_confidence``
    en remplacement du ``MT5_BRIDGE_MIN_CONFIDENCE`` global et skip le check
    ``is_configured()`` (la résolution garantit déjà la config). Sans ``dest``,
    comportement legacy mono-tenant inchangé.
    """
    if dest is None and not is_configured():
        return "_not_configured"  # privé, non enregistré
    if setup.pair not in _STAR_PAIRS_SET:
        return "_not_a_star"  # privé : filtre auto-exec stars-only, attendu pour 12 paires sur 16
    try:
        from backend.services import kill_switch
        # Passe le pair pour que les pauses per-pair (rafale chirurgicale)
        # soient prises en compte en plus des triggers globaux.
        if kill_switch.is_active(pair=setup.pair):
            # Sub-typing pour traçabilité dans les logs/rejections
            if kill_switch.is_pair_rafale_paused(setup.pair)[0]:
                return "kill_switch_pair_paused"
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
    min_conf = dest.min_confidence if dest is not None else MT5_BRIDGE_MIN_CONFIDENCE
    if score < min_conf:
        return "below_confidence"
    # Filtre direction par pair (diagnostic 2026-04-24 : les BUY ont 18%
    # winrate vs 42% pour les SELL sur notre dataset post-fix pipeline).
    # Env `MT5_BRIDGE_BLOCKED_DIRECTIONS=PAIR:dir,*:dir,...`.
    direction = _direction_value(setup).lower()
    pair_upper = setup.pair.upper()
    if (pair_upper, direction) in MT5_BRIDGE_BLOCKED_DIRECTIONS:
        return "direction_blocked_for_pair"
    if ("*", direction) in MT5_BRIDGE_BLOCKED_DIRECTIONS:
        return "direction_blocked_global"
    # Filtre session : skip les heures UTC qui saignent (diag : session
    # NY pm 17-21 UTC = 23% winrate, -186€ sur 17 trades).
    if MT5_BRIDGE_AVOID_HOURS_UTC:
        current_hour_utc = datetime.now(timezone.utc).hour
        if current_hour_utc in MT5_BRIDGE_AVOID_HOURS_UTC:
            return "hour_in_avoid_list"
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


async def _push_to_destination(setup, dest) -> None:
    """Push un setup vers UNE destination (``BridgeConfig``).

    Tous les filtres / dedup / HTTP sont paramétrés par ``dest``. Cette
    fonction est l'évolution V2 du corps historique de ``send_setup`` —
    cf. `docs/superpowers/specs/2026-04-28-multi-tenant-bridge-routing.md`.
    """
    from backend.services.rejection_service import record_rejection

    rejection = _check_rejection(setup, dest)
    if rejection is not None:
        # Les reason codes privés (commencent par "_") ne sont pas loggés
        if not rejection.startswith("_"):
            record_rejection(
                pair=setup.pair,
                direction=_direction_value(setup),
                confidence=getattr(setup, "confidence_score", None),
                reason_code=rejection,
                user_id=dest.user_id,
            )
        return
    # Guard asset class : broker de cette destination ne supporte pas
    # toutes les classes. Per-destination en V2 (avant : global env).
    asset_class = asset_class_for(setup.pair)
    if asset_class not in dest.allowed_asset_classes:
        logger.debug(
            f"mt5_bridge[{dest.destination_id}]: skipping {setup.pair} "
            f"({asset_class}) — broker supports only {sorted(dest.allowed_asset_classes)}"
        )
        record_rejection(
            pair=setup.pair,
            direction=_direction_value(setup),
            confidence=getattr(setup, "confidence_score", None),
            reason_code="asset_class_blocked",
            details={"asset_class": asset_class, "allowed": sorted(dest.allowed_asset_classes)},
            user_id=dest.user_id,
        )
        return
    _cleanup_old_keys()
    key = _dedup_key(setup, dest.destination_id)
    if key in _sent_setups_today:
        return
    # Dedup atomique en DB (UNIQUE constraint INSERT OR IGNORE) — source de
    # vérité partagée multi-process. Le set in-memory reste en parallèle pour
    # rétro-compat des tests existants. Best-effort : si la DB est
    # inaccessible, le service retourne True (fallback safe).
    from backend.services import mt5_pushes_service

    push_date = key[0]
    direction = _direction_value(setup)
    entry_5dp = f"{setup.entry_price:.5f}"
    if not mt5_pushes_service.try_register_push(
        dest.destination_id, push_date, setup.pair, direction, entry_5dp
    ):
        return
    _sent_setups_today.add(key)
    # Sizing dynamique : base = RISK_PER_TRADE_PCT du capital, module par
    # la confiance du signal (0.5x a 1.5x) et par le PnL recent (0.5x si
    # en drawdown sur 7j, sinon 1.0x). Voir sizing.compute_risk_money.
    # Note V1 : sizing reste global (pas per-user). À adresser en V2.
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

    # ─── Routing dispatch (Phase MQL.C) ──────────────────────────────
    # admin_legacy (user_id=None) : push HTTP synchrone vers le bridge admin.
    # user destinations (user_id=int) : enqueue dans mt5_pending_orders.
    # L'EA MQL5 du user récupère via GET /api/ea/pending toutes les ~30s.
    if dest.user_id is not None:
        from backend.services import mt5_pending_orders_service

        try:
            order_id = mt5_pending_orders_service.enqueue(
                user_id=dest.user_id,
                api_key=dest.bridge_api_key,
                payload=payload,
            )
            mt5_pushes_service.update_push_result(
                dest.destination_id, push_date, setup.pair, direction, entry_5dp,
                ok=True,
                response={"enqueued_order_id": order_id, "via": "ea_queue"},
            )
            logger.info(
                f"MT5 ea_queue[{dest.destination_id}] enqueued "
                f"order_id={order_id} {setup.pair} {direction} risk=${risk_money}"
            )
        except Exception as e:
            logger.warning(
                f"MT5 ea_queue[{dest.destination_id}] enqueue failed for "
                f"{setup.pair}: {e}"
            )
            record_rejection(
                pair=setup.pair,
                direction=direction,
                confidence=getattr(setup, "confidence_score", None),
                reason_code="bridge_error",
                details={"exception": str(e)[:200]},
                user_id=dest.user_id,
            )
            _sent_setups_today.discard(key)
            mt5_pushes_service.discard_push(
                dest.destination_id, push_date, setup.pair, direction, entry_5dp
            )
        return

    # admin_legacy : path HTTP synchrone, comportement V1 inchangé.
    url = dest.bridge_url + "/order"
    headers = {
        "X-API-Key": dest.bridge_api_key,
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(url, json=payload, headers=headers)
            if r.status_code == 200:
                data = r.json()
                mt5_pushes_service.update_push_result(
                    dest.destination_id, push_date, setup.pair, direction, entry_5dp,
                    ok=True, response=data,
                )
                logger.info(
                    f"MT5 bridge[{dest.destination_id}] → {setup.pair} {direction} "
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
                    f"MT5 bridge[{dest.destination_id}] a répondu {r.status_code} "
                    f"pour {setup.pair}: {r.text[:200]}"
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
                    user_id=dest.user_id,
                )
                # Si l'ordre a été rejeté par le bridge, on retire de la dedup
                # (mémoire + DB) pour qu'un cycle suivant puisse retenter.
                _sent_setups_today.discard(key)
                mt5_pushes_service.discard_push(
                    dest.destination_id, push_date, setup.pair, direction, entry_5dp
                )
    except httpx.TimeoutException:
        logger.info(
            f"MT5 bridge[{dest.destination_id}] timeout — skip {setup.pair}"
        )
        record_rejection(
            pair=setup.pair,
            direction=direction,
            confidence=getattr(setup, "confidence_score", None),
            reason_code="bridge_timeout",
            user_id=dest.user_id,
        )
        _sent_setups_today.discard(key)  # retente au cycle suivant
        mt5_pushes_service.discard_push(
            dest.destination_id, push_date, setup.pair, direction, entry_5dp
        )
    except Exception as e:
        logger.warning(
            f"MT5 bridge[{dest.destination_id}] exception pour {setup.pair}: {e}"
        )
        record_rejection(
            pair=setup.pair,
            direction=direction,
            confidence=getattr(setup, "confidence_score", None),
            reason_code="bridge_error",
            details={"exception": str(e)[:200]},
            user_id=dest.user_id,
        )
        _sent_setups_today.discard(key)
        mt5_pushes_service.discard_push(
            dest.destination_id, push_date, setup.pair, direction, entry_5dp
        )


async def send_setup(setup) -> None:
    """Push un trade_setup vers chaque destination active.

    V1 : 1 destination max (``admin_legacy`` depuis l'env). Phase C
    élargira pour inclure les users Premium auto-exec via
    ``bridge_destinations.resolve_destinations()``.
    """
    from backend.services.bridge_destinations import resolve_destinations

    destinations = resolve_destinations(setup)
    if not destinations:
        return
    await asyncio.gather(
        *(_push_to_destination(setup, dest) for dest in destinations),
        return_exceptions=True,
    )


async def send_setups(setups: list) -> None:
    """Push plusieurs setups en parallèle. No-op si bridge pas configuré."""
    if not is_configured() or not setups:
        return
    # Pré-filtre 1 : stars du portefeuille Phase 4 uniquement.
    setups = [s for s in setups if s.pair in _STAR_PAIRS_SET]
    if not setups:
        return
    # Pré-filtre 2 : asset class supportée par le broker courant.
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
