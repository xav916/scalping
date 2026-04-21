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

from config.settings import (
    MT5_BRIDGE_ENABLED,
    MT5_BRIDGE_URL,
    MT5_BRIDGE_API_KEY,
    MT5_BRIDGE_MIN_CONFIDENCE,
    MT5_BRIDGE_LOTS,
    MT5_BRIDGE_ALLOWED_ASSET_CLASSES,
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


def _should_push(setup) -> bool:
    if not is_configured():
        return False
    # Kill switch global : coupe l'auto-exec si perte journaliere atteinte
    # ou si un flag manuel est actif. Ne bloque PAS l'emission de signaux
    # (UI, Telegram), seulement l'envoi au bridge.
    try:
        from backend.services import kill_switch
        if kill_switch.is_active():
            return False
    except Exception as e:
        logger.debug(f"mt5_bridge: kill_switch check failed: {e}")
    # Event blackout : ne pas executer dans la fenetre +/-15min autour
    # d'un event HIGH-impact sur une devise de la paire. Le signal reste
    # visible cote UI / Telegram — seul l'auto-exec est coupe.
    try:
        from backend.services import event_blackout
        bo = event_blackout.is_blackout_for(setup.pair)
        if bo["active"]:
            logger.info(
                f"mt5_bridge: blackout event pour {setup.pair} — {bo['reason']}"
            )
            return False
    except Exception as e:
        logger.debug(f"mt5_bridge: event_blackout check failed: {e}")
    # Jamais d'auto-exec sur candles simulées : le fallback price_service utilise
    # un prix hardcodé (2650 pour la plupart des pairs), ce qui produit un
    # entry/SL/TP fantôme que MT5 refuse via rc=10016 INVALID_STOPS. Le flag
    # is_simulated remonte depuis fetch_candles jusqu'au TradeSetup.
    if getattr(setup, "is_simulated", False):
        return False
    # Respecter uniquement les blockers durs (marché fermé, macro veto) —
    # pas le verdict_action lui-même, qui tag aussi SKIP sur "score < 75"
    # (le scoring de base atteint rarement 75 donc le gate TAKE produisait
    # 0 auto-exec en pratique).
    if getattr(setup, "verdict_blockers", None):
        return False
    score = getattr(setup, "confidence_score", None) or 0
    if score < MT5_BRIDGE_MIN_CONFIDENCE:
        return False
    return True


async def send_setup(setup) -> None:
    """Push un trade_setup vers le bridge MT5 local si toutes les conditions
    sont remplies (verdict TAKE, seuil, dedup)."""
    if not _should_push(setup):
        return
    # Guard : le broker courant (MetaQuotes-Demo par défaut) ne supporte
    # qu'une partie des asset classes. Court-circuite les setups crypto /
    # indices / énergie tant qu'on n'a pas migré vers un broker multi-asset
    # (Pepperstone, IC Markets, ...). Évite SYMBOL_SELECT errors et la
    # pollution de l'audit DB.
    asset_class = asset_class_for(setup.pair)
    if asset_class not in MT5_BRIDGE_ALLOWED_ASSET_CLASSES:
        logger.debug(
            f"mt5_bridge: skipping {setup.pair} ({asset_class}) — "
            f"broker supports only {MT5_BRIDGE_ALLOWED_ASSET_CLASSES}"
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
                    f"session={sz['session']}:{sz['session_mult']}x) "
                    f"mode={data.get('mode', '?')}"
                )
            else:
                logger.warning(
                    f"MT5 bridge a répondu {r.status_code} pour {setup.pair}: "
                    f"{r.text[:200]}"
                )
                # Si l'ordre a été rejeté par le bridge, on retire de la dedup
                # pour qu'un cycle suivant puisse retenter.
                _sent_setups_today.discard(key)
    except httpx.TimeoutException:
        logger.info(f"MT5 bridge timeout (PC éteint ?) — skip {setup.pair}")
        _sent_setups_today.discard(key)  # retente au cycle suivant
    except Exception as e:
        logger.warning(f"MT5 bridge exception pour {setup.pair}: {e}")
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
