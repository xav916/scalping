"""Client HTTP pour pousser un setup vers le kraken-futures-bridge.

Créé 2026-08-02 comme alternative à binance_bridge_client après blocker AMF
Futures France sur Binance mainnet. Kraken Futures est régulé Ireland/EU
et accessible aux résidents FR.

Ce client est appelé depuis ``mt5_bridge._push_to_destination`` quand la
destination résolue a ``bridge_type="kraken"``.

Version MVP : reprend le pattern binance_bridge_client mais SANS les
optimisations avancées (funding sizing, correlation guard, drawdown breaker).
Ces optims pourront être ajoutées quand la baseline Kraken sera établie.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

RESPECT_VERDICT = os.getenv("KRAKEN_RESPECT_VERDICT", "true").strip().lower() in ("true", "1", "yes")
MIN_FINAL_CONFIDENCE = float(os.getenv("KRAKEN_MIN_FINAL_CONFIDENCE", "60"))
KRAKEN_BRIDGE_TIMEOUT_SEC = float(os.getenv("KRAKEN_BRIDGE_TIMEOUT_SEC", "10"))


def _build_kraken_payload(setup, sz: dict, dest) -> dict[str, Any]:
    """Convertit un setup scalping-radar en payload kraken-bridge.

    Payload attendu par le bridge Kraken :
    {pair, direction, qty (base currency), sl, tp}

    qty = risk_money / |entry - sl|  — même formule que Binance.
    Kraken PF_* sizes en base asset direct (comme Binance USDT-M).
    """
    entry = float(setup.entry_price)
    sl = float(setup.stop_loss)
    tp = float(setup.take_profit_1)
    risk_money = float(sz["risk_money"])
    sl_distance = abs(entry - sl)
    if sl_distance <= 0:
        qty = 0.0  # le bridge rejettera
    else:
        qty = risk_money / sl_distance
    direction = setup.direction.value if hasattr(setup.direction, "value") else str(setup.direction)
    return {
        "pair": setup.pair,
        "direction": direction,
        "qty": qty,
        "sl": sl,
        "tp": tp,
    }


async def push_to_kraken(setup, sz: dict, dest) -> None:
    """Pousse un setup vers le kraken-bridge. Logge dans mt5_pushes.

    Best-effort : timeout / 4xx / 5xx → record_rejection + return. Pas
    d'exception remontée au cycle d'analyse.
    """
    from datetime import date

    from backend.services import mt5_pushes_service
    from backend.services.rejection_service import record_rejection

    direction = setup.direction.value if hasattr(setup.direction, "value") else str(setup.direction)
    score = float(getattr(setup, "confidence_score", 0) or 0)
    verdict = getattr(setup, "verdict_action", None)
    push_date = date.today().isoformat()
    entry_5dp = f"{setup.entry_price:.5f}"

    # Final-score gate
    if RESPECT_VERDICT and verdict == "SKIP":
        record_rejection(
            pair=setup.pair, direction=direction, confidence=score,
            reason_code="kraken_verdict_skip",
            details={"verdict": verdict, "score": score},
            destination_id=dest.destination_id,
        )
        return
    if score < MIN_FINAL_CONFIDENCE:
        record_rejection(
            pair=setup.pair, direction=direction, confidence=score,
            reason_code="kraken_below_final_confidence",
            details={"score": score, "threshold": MIN_FINAL_CONFIDENCE},
            destination_id=dest.destination_id,
        )
        return

    payload = _build_kraken_payload(setup, sz, dest)
    if payload["qty"] <= 0:
        record_rejection(
            pair=setup.pair, direction=direction, confidence=score,
            reason_code="kraken_bad_sizing",
            details={"reason": "qty<=0, likely sl==entry", "payload": payload},
            destination_id=dest.destination_id,
        )
        return

    bridge_url = dest.bridge_url.rstrip("/")
    bridge_key = dest.bridge_api_key
    url = f"{bridge_url}/order"

    try:
        async with httpx.AsyncClient(timeout=KRAKEN_BRIDGE_TIMEOUT_SEC) as c:
            r = await c.post(
                url, json=payload,
                headers={"X-Bridge-Key": bridge_key} if bridge_key else {},
            )
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text[:200]}

        if r.status_code == 200 and body.get("ok"):
            mt5_pushes_service.record_push(
                dest.destination_id, push_date, setup.pair, direction, entry_5dp,
                ok=True, bridge_response=body,
            )
            logger.warning(
                f"kraken bridge[{dest.destination_id}] → {setup.pair} {direction} "
                f"OK order_id={body.get('market_order_id')} avg_price={body.get('avg_price')}"
            )
        elif r.status_code == 429 and body.get("blocked"):
            # Kill-switch bridge (daily drawdown, whitelist, max positions)
            reason = body.get("reason", "unknown")
            record_rejection(
                pair=setup.pair, direction=direction, confidence=score,
                reason_code="kraken_bridge_blocked",
                details={"status": 429, "reason": reason, "payload": payload},
                destination_id=dest.destination_id,
            )
            logger.warning(
                f"kraken bridge[{dest.destination_id}] BLOCKED {setup.pair}: {reason}"
            )
        else:
            record_rejection(
                pair=setup.pair, direction=direction, confidence=score,
                reason_code="kraken_bridge_error",
                details={"status": r.status_code, "body": str(body)[:250]},
                destination_id=dest.destination_id,
            )
            logger.warning(
                f"kraken bridge[{dest.destination_id}] error {r.status_code}: {str(body)[:200]}"
            )
    except httpx.TimeoutException:
        record_rejection(
            pair=setup.pair, direction=direction, confidence=score,
            reason_code="kraken_bridge_timeout",
            details={"timeout_sec": KRAKEN_BRIDGE_TIMEOUT_SEC},
            destination_id=dest.destination_id,
        )
        logger.warning(f"kraken bridge[{dest.destination_id}] timeout — skip {setup.pair}")
    except Exception as e:
        record_rejection(
            pair=setup.pair, direction=direction, confidence=score,
            reason_code="kraken_bridge_exception",
            details={"error": str(e)[:200]},
            destination_id=dest.destination_id,
        )
        logger.exception(f"kraken bridge[{dest.destination_id}] exception for {setup.pair}")
