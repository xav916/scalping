"""Client HTTP pour pousser un setup vers le kraken-spot-bridge.

Créé 2026-08-02 comme bridge Spot dédié BTC/ETH sur le marché réel.
Kraken Spot = achat réel de crypto (pas de dérivés), long-only, sans levier.

Ce client est appelé depuis ``mt5_bridge._push_to_destination`` quand la
destination résolue a ``bridge_type="kraken_spot"``.

Restrictions vs kraken_bridge_client (Futures) :
- Long-only : direction != "buy" → reject avec reason kraken_spot_short_rejected
- Paires limitées à BTC/USD et ETH/USD (Spot uniquement BTC/ETH sur ce bridge)
- Env vars préfixées KRAKEN_SPOT_* pour isolation complète
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

RESPECT_VERDICT = os.getenv("KRAKEN_SPOT_RESPECT_VERDICT", "true").strip().lower() in ("true", "1", "yes")
MIN_FINAL_CONFIDENCE = float(os.getenv("KRAKEN_SPOT_MIN_FINAL_CONFIDENCE", "75"))
KRAKEN_SPOT_BRIDGE_TIMEOUT_SEC = float(os.getenv("KRAKEN_SPOT_BRIDGE_TIMEOUT_SEC", "10"))

# Paires supportées par ce bridge (Kraken Spot = BTC + ETH uniquement)
_SPOT_SUPPORTED_PAIRS = frozenset({"BTC/USD", "ETH/USD"})


def _build_kraken_spot_payload(setup, sz: dict, dest) -> dict[str, Any]:
    """Convertit un setup scalping-radar en payload kraken-spot-bridge.

    Payload attendu par le bridge :
    {pair, direction, qty (base currency), sl, tp}

    qty = risk_money / |entry - sl|  — même formule que Kraken Futures.
    Kraken Spot sizes en base asset direct (XBT pour XBTUSD).
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


async def push_to_kraken_spot(setup, sz: dict, dest) -> None:
    """Pousse un setup vers le kraken-spot-bridge. Logge dans ``mt5_pushes``.

    Best-effort : timeout / 4xx / 5xx → record_rejection + return. Pas
    d'exception remontée au cycle d'analyse.

    ⚠️ La clé de push est **réservée avant** l'appel HTTP : voir
    ``bridge_push_ledger`` pour l'incident qu'elle prévient.
    """
    from backend.services import sizing as _sizing
    from backend.services.bridge_push_ledger import PushLedger
    from backend.services.rejection_service import record_rejection

    direction = setup.direction.value if hasattr(setup.direction, "value") else str(setup.direction)
    score = float(getattr(setup, "confidence_score", 0) or 0)
    verdict = getattr(setup, "verdict_action", None)

    # Long-only gate — Spot bridge ne supporte pas les shorts
    if direction != "buy":
        record_rejection(
            pair=setup.pair, direction=direction, confidence=score,
            reason_code="kraken_spot_short_rejected",
            details={"direction": direction, "reason": "spot bridge is long-only"},
            destination_id=dest.destination_id,
        )
        logger.debug(
            f"kraken_spot[{dest.destination_id}] skip {setup.pair} {direction}: long-only"
        )
        return

    # Pair gate — Spot ne supporte que BTC/USD et ETH/USD
    if setup.pair not in _SPOT_SUPPORTED_PAIRS:
        record_rejection(
            pair=setup.pair, direction=direction, confidence=score,
            reason_code="kraken_spot_pair_not_whitelisted",
            details={"pair": setup.pair, "supported": sorted(_SPOT_SUPPORTED_PAIRS)},
            destination_id=dest.destination_id,
        )
        logger.debug(
            f"kraken_spot[{dest.destination_id}] skip {setup.pair}: pair not supported by Spot bridge"
        )
        return

    # Final-score gate
    if RESPECT_VERDICT and verdict == "SKIP":
        record_rejection(
            pair=setup.pair, direction=direction, confidence=score,
            reason_code="kraken_spot_verdict_skip",
            details={"verdict": verdict, "score": score},
            destination_id=dest.destination_id,
        )
        return
    if score < MIN_FINAL_CONFIDENCE:
        record_rejection(
            pair=setup.pair, direction=direction, confidence=score,
            reason_code="kraken_spot_below_final_confidence",
            details={"score": score, "threshold": MIN_FINAL_CONFIDENCE},
            destination_id=dest.destination_id,
        )
        return

    payload = _build_kraken_spot_payload(setup, sz, dest)
    if payload["qty"] <= 0:
        record_rejection(
            pair=setup.pair, direction=direction, confidence=score,
            reason_code="kraken_spot_bad_sizing",
            details={"reason": _sizing.raison_du_refus(sz, setup), "payload": payload},
            destination_id=dest.destination_id,
        )
        return

    bridge_url = dest.bridge_url.rstrip("/")
    bridge_key = dest.bridge_api_key
    url = f"{bridge_url}/order"

    # Réservation AVANT l'envoi — cf. bridge_push_ledger et l'incident du
    # 2026-08-04 (fill réel sans aucune trace, rejoué au cycle suivant).
    ledger = PushLedger.for_setup(dest, setup, direction)
    if not ledger.reserve():
        record_rejection(
            pair=setup.pair, direction=direction, confidence=score,
            reason_code="kraken_spot_already_pushed",
            details={"entry_5dp": ledger.entry_5dp},
            destination_id=dest.destination_id,
        )
        return

    try:
        async with httpx.AsyncClient(timeout=KRAKEN_SPOT_BRIDGE_TIMEOUT_SEC) as c:
            r = await c.post(
                url, json=payload,
                headers={"X-Bridge-Key": bridge_key} if bridge_key else {},
            )
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text[:200]}

        if r.status_code == 200 and body.get("ok"):
            ledger.confirm(body)
            logger.warning(
                f"kraken_spot bridge[{dest.destination_id}] → {setup.pair} {direction} "
                f"OK txid={body.get('txid')} descr={body.get('descr')!r}"
            )
            # Même formateur que MT5, Binance et Kraken Futures.
            try:
                from backend.services import telegram_service as _tg
                txid = body.get("txid")
                if isinstance(txid, list):
                    txid = txid[0] if txid else None
                await _tg.send_trade_opened(
                    setup,
                    ticket=txid or "n/a",
                    fill_price=float(body.get("avg_price") or setup.entry_price),
                    volume=float(body.get("volume") or payload.get("qty") or 0),
                    mode=str(body.get("mode") or "live"),
                    destination_id=dest.destination_id,
                )
            except Exception as _e:
                logger.warning(f"send_trade_opened kraken_spot hook error: {_e}")
        elif r.status_code == 429 and body.get("blocked"):
            # Contrainte temporaire du bridge : rien n'a atteint le marché.
            reason = body.get("reason", "unknown")
            ledger.release()
            record_rejection(
                pair=setup.pair, direction=direction, confidence=score,
                reason_code="kraken_spot_bridge_blocked",
                details={"status": 429, "reason": reason, "payload": payload},
                destination_id=dest.destination_id,
            )
            logger.warning(
                f"kraken_spot bridge[{dest.destination_id}] BLOCKED {setup.pair}: {reason}"
            )
        else:
            ledger.flag_unknown({"status": r.status_code, "body": str(body)[:400]})
            record_rejection(
                pair=setup.pair, direction=direction, confidence=score,
                reason_code="kraken_spot_bridge_error",
                details={"status": r.status_code, "body": str(body)[:250]},
                destination_id=dest.destination_id,
            )
            logger.warning(
                f"kraken_spot bridge[{dest.destination_id}] error {r.status_code}: {str(body)[:200]}"
            )
    except httpx.TimeoutException:
        # L'ordre a pu être rempli sans que la réponse revienne : on garde la
        # réservation plutôt que de risquer un doublon sur un compte réel.
        ledger.flag_unknown({"error": "timeout", "timeout_sec": KRAKEN_SPOT_BRIDGE_TIMEOUT_SEC})
        record_rejection(
            pair=setup.pair, direction=direction, confidence=score,
            reason_code="kraken_spot_bridge_timeout",
            details={"timeout_sec": KRAKEN_SPOT_BRIDGE_TIMEOUT_SEC},
            destination_id=dest.destination_id,
        )
        logger.warning(f"kraken_spot bridge[{dest.destination_id}] timeout — skip {setup.pair}")
    except httpx.ConnectError as e:
        ledger.release()
        record_rejection(
            pair=setup.pair, direction=direction, confidence=score,
            reason_code="kraken_spot_bridge_unreachable",
            details={"error": str(e)[:200], "url": url},
            destination_id=dest.destination_id,
        )
        logger.warning(f"kraken_spot bridge[{dest.destination_id}] injoignable: {url}")
    except Exception as e:
        ledger.flag_unknown({"error": str(e)[:300]})
        record_rejection(
            pair=setup.pair, direction=direction, confidence=score,
            reason_code="kraken_spot_bridge_exception",
            details={"error": str(e)[:200]},
            destination_id=dest.destination_id,
        )
        logger.exception(f"kraken_spot bridge[{dest.destination_id}] exception for {setup.pair}")
