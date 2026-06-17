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
import time
from datetime import date
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def _build_binance_payload(setup, sz: dict, dest) -> dict[str, Any]:
    """Convertit un setup scalping-radar en payload binance-bridge.

    qty (en base currency) = risk_money / |entry - sl|
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
    return {
        "pair": setup.pair,
        "direction": direction,
        "qty": qty,
        "sl": sl,
        "tp": tp,
        "leverage": getattr(dest, "leverage", None) or 5,
        "margin_type": "ISOLATED",
        "comment": f"scalping-radar-{date.today().isoformat()}",
    }


async def push_to_binance(setup, sz: dict, dest) -> None:
    """Pousse un setup vers le binance-bridge. Logge le résultat dans mt5_pushes
    (mêmes tables que pour MT5 pour comparaison MT5 Demo vs Binance testnet).

    Best-effort : timeout / 4xx / 5xx → record_rejection + return. Pas
    d'exception remontée au cycle d'analyse.
    """
    from backend.services import mt5_pushes_service
    from backend.services.rejection_service import record_rejection

    direction = setup.direction.value if hasattr(setup.direction, "value") else str(setup.direction)
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
        )
        mt5_pushes_service.discard_push(
            dest.destination_id, push_date, setup.pair, direction, entry_5dp,
        )
