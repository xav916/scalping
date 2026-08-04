"""Client HTTP pour pousser un setup vers le binance-bridge.

Pendant Phase 2 R&D (Palier 2 — vraies cryptos via Binance USDⓈ-M perp),
ce client est appelé depuis ``mt5_bridge._push_to_destination`` quand la
destination résolue a ``bridge_type="binance"``. Il :

- Convertit le sizing risk-money en qty base currency
- POST au bridge ``/order`` avec payload {pair, direction, qty, sl, tp, leverage}
- Enregistre le résultat dans mt5_pushes (même table que MT5, destination_id
  ``admin_binance``) pour analyse comparative

Le bridge gère côté MT5 / Binance les détails (margin_type, leverage,
re-poll fill, watcher SL/TP). On envoie un payload simple.

Phase 2 R&D : single-tenant Xavier testnet. Multi-tenant à architecturer
plus tard (cf. memory feedback_multi_tenant_by_default).
"""
from __future__ import annotations

import logging
import os
import time
from datetime import date
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Gating final (2026-06-18) — refuse les pushes Binance shadow quand le
# verdict ou le score final disent SKIP. Avant ce gate, le shadow exécutait
# tous les setups détectés, y compris ceux verdictés SKIP par l'engine
# (donc invisibles côté MT5) → le wallet testnet saignait sur des trades
# que le système flaggait déjà comme à éviter. Toggle pour rollback rapide.
RESPECT_VERDICT = os.getenv("BINANCE_RESPECT_VERDICT", "true").strip().lower() in ("true", "1", "yes")
MIN_FINAL_CONFIDENCE = float(os.getenv("BINANCE_MIN_FINAL_CONFIDENCE", "50"))


# Chantier #9 — Funding-aware sizing.
# Si direction alignée avec funding receiver (long quand funding négatif,
# short quand positif), size ×UP. Si counter, size ×DOWN. Caps [DOWN, UP].
# Seuils + caps configurables via env. Désactivable globalement.
FUNDING_SIZING_ENABLED = os.getenv("BINANCE_FUNDING_SIZING_ENABLED", "true").strip().lower() in ("true", "1", "yes")
FUNDING_SIZING_THRESHOLD = float(os.getenv("BINANCE_FUNDING_SIZING_THRESHOLD", "0.0001"))  # 0.01%
FUNDING_SIZING_ALIGNED_MULT = float(os.getenv("BINANCE_FUNDING_SIZING_ALIGNED_MULT", "1.2"))
FUNDING_SIZING_COUNTER_MULT = float(os.getenv("BINANCE_FUNDING_SIZING_COUNTER_MULT", "0.8"))
FUNDING_SIZING_MAX_MULT = float(os.getenv("BINANCE_FUNDING_SIZING_MAX_MULT", "1.5"))
FUNDING_SIZING_MIN_MULT = float(os.getenv("BINANCE_FUNDING_SIZING_MIN_MULT", "0.7"))


def _funding_sizing_mult(pair: str, direction: str) -> tuple[float, str]:
    """Multiplicateur sizing selon alignement direction vs funding rate.

    Retourne (mult, reason). reason ∈ {"disabled", "no_data", "neutral",
    "aligned_long_negative", "aligned_short_positive",
    "counter_long_positive", "counter_short_negative"}.
    Best-effort : toute erreur → (1.0, "error").
    """
    if not FUNDING_SIZING_ENABLED:
        return 1.0, "disabled"
    try:
        from backend.services import binance_funding_service
        d = binance_funding_service.get_funding_rate(pair)
        if not d.get("available") or not d.get("is_fresh"):
            return 1.0, "no_data"
        rate = float(d["rate"])
        if abs(rate) < FUNDING_SIZING_THRESHOLD:
            return 1.0, "neutral"
        dir_lower = direction.lower()
        if dir_lower == "buy":
            if rate < 0:
                m = min(FUNDING_SIZING_ALIGNED_MULT, FUNDING_SIZING_MAX_MULT)
                return m, "aligned_long_negative"
            m = max(FUNDING_SIZING_COUNTER_MULT, FUNDING_SIZING_MIN_MULT)
            return m, "counter_long_positive"
        if dir_lower == "sell":
            if rate > 0:
                m = min(FUNDING_SIZING_ALIGNED_MULT, FUNDING_SIZING_MAX_MULT)
                return m, "aligned_short_positive"
            m = max(FUNDING_SIZING_COUNTER_MULT, FUNDING_SIZING_MIN_MULT)
            return m, "counter_short_negative"
        return 1.0, "neutral"
    except Exception as e:
        logger.debug(f"funding sizing mult error {pair}: {e}")
        return 1.0, "error"


def _build_binance_payload(setup, sz: dict, dest) -> dict[str, Any]:
    """Convertit un setup scalping-radar en payload binance-bridge.

    qty (en base currency) = risk_money / |entry - sl| × funding_mult
    Si distance |entry-sl| est nulle, fallback minQty broker — best-effort,
    le bridge rejettera proprement avec code 400.
    """
    entry = float(setup.entry_price)
    sl = float(setup.stop_loss)
    tp = float(setup.take_profit_1)
    risk_money = float(sz["risk_money"])
    sl_distance = abs(entry - sl)
    if sl_distance <= 0:
        qty = 0.0  # bridge va rejeter avec error
    else:
        qty = risk_money / sl_distance
    direction = setup.direction.value if hasattr(setup.direction, "value") else str(setup.direction)
    funding_mult, funding_reason = _funding_sizing_mult(setup.pair, direction)
    if funding_mult != 1.0:
        qty_before = qty
        qty = qty * funding_mult
        logger.info(
            f"binance sizing[{setup.pair}/{direction}] funding ×{funding_mult:.2f} "
            f"({funding_reason}): qty {qty_before:.6f} → {qty:.6f}"
        )
    return {
        "pair": setup.pair,
        "direction": direction,
        "qty": qty,
        "entry": entry,  # utilisé par bridge si USE_MAKER_ORDERS (LIMIT post-only)
        "sl": sl,
        "tp": tp,
        "leverage": getattr(dest, "leverage", None) or 5,
        "margin_type": "ISOLATED",
        "comment": f"scalping-radar-{date.today().isoformat()}",
        "funding_sizing_mult": funding_mult,
        "funding_sizing_reason": funding_reason,
    }


async def push_to_binance(setup, sz: dict, dest) -> None:
    """Pousse un setup vers le binance-bridge. Logge le résultat dans mt5_pushes
    (mêmes tables que pour MT5 pour comparaison MT5 Demo vs Binance testnet).

    Best-effort : timeout / 4xx / 5xx → record_rejection + return. Pas
    d'exception remontée au cycle d'analyse.
    """
    from backend.services import (
        binance_correlation_guard,
        binance_drawdown_breaker,
        mt5_pushes_service,
    )
    from backend.services.rejection_service import record_rejection

    direction = setup.direction.value if hasattr(setup.direction, "value") else str(setup.direction)

    # Final-score gate — n'envoie pas vers Binance ce que l'engine flaggue SKIP
    # ou ce qui n'atteint pas le seuil de confidence finale (post-microstructure).
    verdict = getattr(setup, "verdict_action", None)
    score = float(getattr(setup, "confidence_score", 0) or 0)
    if RESPECT_VERDICT and verdict == "SKIP":
        logger.info(
            f"binance bridge[{dest.destination_id}] skip {setup.pair} {direction}: "
            f"verdict=SKIP (score={score})"
        )
        record_rejection(
            pair=setup.pair, direction=direction,
            confidence=score,
            reason_code="binance_verdict_skip",
            details={"verdict": verdict, "score": score},
            destination_id=dest.destination_id,
        )
        return
    if score < MIN_FINAL_CONFIDENCE:
        logger.info(
            f"binance bridge[{dest.destination_id}] skip {setup.pair} {direction}: "
            f"final score {score} < {MIN_FINAL_CONFIDENCE}"
        )
        record_rejection(
            pair=setup.pair, direction=direction,
            confidence=score,
            reason_code="binance_below_final_confidence",
            details={"score": score, "threshold": MIN_FINAL_CONFIDENCE},
            destination_id=dest.destination_id,
        )
        return

    # Chantier #15 — circuit breaker drawdown wallet. Si tripped, on rejette
    # le push et le kill_switch global a déjà été activé côté breaker.
    allowed, breaker_reason = binance_drawdown_breaker.check_and_maybe_trip(dest)
    if not allowed:
        logger.warning(
            f"binance bridge[{dest.destination_id}] DD breaker tripped — skip {setup.pair}: {breaker_reason}"
        )
        record_rejection(
            pair=setup.pair, direction=direction,
            confidence=getattr(setup, "confidence_score", None),
            reason_code="binance_dd_breaker",
            details={"reason": breaker_reason},
            destination_id=dest.destination_id,
        )
        return

    # Chantier #13 — position correlation guard. Refuse les nouveaux
    # pushes crypto qui sur-concentreraient l'exposition risk-on/risk-off.
    corr_ok, corr_reason = binance_correlation_guard.check_correlation(
        dest, setup.pair, direction,
    )
    if not corr_ok:
        logger.info(
            f"binance bridge[{dest.destination_id}] correlation guard — skip {setup.pair} {direction}: {corr_reason}"
        )
        record_rejection(
            pair=setup.pair, direction=direction,
            confidence=getattr(setup, "confidence_score", None),
            reason_code="binance_correlation_guard",
            details={"reason": corr_reason},
            destination_id=dest.destination_id,
        )
        return

    payload = _build_binance_payload(setup, sz, dest)
    push_date = date.today().isoformat()
    entry_5dp = f"{setup.entry_price:.5f}"
    url = dest.bridge_url + "/order"
    headers = {"Content-Type": "application/json"}
    if dest.bridge_api_key:
        headers["X-Bridge-Key"] = dest.bridge_api_key

    # Dedup atomique côté DB (réutilise la même table que MT5)
    if not mt5_pushes_service.try_register_push(
        dest.destination_id, push_date, setup.pair, direction, entry_5dp
    ):
        return

    push_start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.post(url, json=payload, headers=headers)
            latency_ms = int((time.perf_counter() - push_start) * 1000)
            if r.status_code == 200:
                data = r.json()
                mt5_pushes_service.update_push_result(
                    dest.destination_id, push_date, setup.pair, direction, entry_5dp,
                    ok=True, response=data,
                )
                logger.info(
                    f"binance bridge[{dest.destination_id}] → {setup.pair} {direction} "
                    f"qty={payload['qty']:.6f} lev={payload['leverage']}x "
                    f"latency_ms={latency_ms} avg_price={data.get('avg_price')}"
                )
                # Notif user "Trade OUVERT" (parité avec MT5). Best-effort.
                # market_order_id Binance peut être None si le bridge a juste
                # registered en watcher sans orderId — fallback hash entry_5dp.
                try:
                    from backend.services import telegram_service as _tg
                    ticket_val = data.get("market_order_id") or data.get("client_order_id") or 0
                    try:
                        ticket_int = int(ticket_val)
                    except (TypeError, ValueError):
                        ticket_int = abs(hash(str(ticket_val))) % (10**9)
                    await _tg.send_trade_opened(
                        setup,
                        ticket=ticket_int,
                        fill_price=float(data.get("avg_price") or setup.entry_price),
                        volume=float(data.get("qty") or payload.get("qty") or 0),
                        mode="testnet",
                        destination_id=dest.destination_id,
                    )
                except Exception as _e:
                    logger.warning(f"send_trade_opened binance hook error: {_e}")
            else:
                logger.warning(
                    f"binance bridge[{dest.destination_id}] répondu {r.status_code} "
                    f"pour {setup.pair} (latency_ms={latency_ms}): {r.text[:200]}"
                )
                record_rejection(
                    pair=setup.pair, direction=direction,
                    confidence=getattr(setup, "confidence_score", None),
                    reason_code="binance_bridge_error",
                    details={"status": r.status_code, "body": r.text[:200]},
                    destination_id=dest.destination_id,
                )
                mt5_pushes_service.discard_push(
                    dest.destination_id, push_date, setup.pair, direction, entry_5dp,
                )
    except httpx.TimeoutException:
        logger.info(f"binance bridge[{dest.destination_id}] timeout — skip {setup.pair}")
        record_rejection(
            pair=setup.pair, direction=direction,
            confidence=getattr(setup, "confidence_score", None),
            reason_code="binance_bridge_timeout",
            destination_id=dest.destination_id,
        )
        mt5_pushes_service.discard_push(
            dest.destination_id, push_date, setup.pair, direction, entry_5dp,
        )
    except Exception as e:
        logger.warning(f"binance bridge[{dest.destination_id}] exception {setup.pair}: {e}")
        record_rejection(
            pair=setup.pair, direction=direction,
            confidence=getattr(setup, "confidence_score", None),
            reason_code="binance_bridge_exception",
            details={"exception": str(e)[:200]},
            destination_id=dest.destination_id,
        )
        mt5_pushes_service.discard_push(
            dest.destination_id, push_date, setup.pair, direction, entry_5dp,
        )
