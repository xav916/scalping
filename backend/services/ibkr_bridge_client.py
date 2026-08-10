"""Client HTTP pour pousser un setup vers le bridge IBKR (actions US).

Ouvert le 2026-08-10 à la demande de Xavier. Le bridge lui-même
(``ibkr-bridge/bridge.py``, port 8792) existait depuis le 2026-08-04 en
lecture seule, avec sa mécanique de bracket déjà validée en réel sur AAPL.

⚠️ **Ce que la mesure dit de cette route, et qui ne change pas.** Sur les
actions US individuelles, les patterns du système font **−0,182 R par trade
contre une entrée au hasard** (IC [−0,235 ; −0,123], p < 0,001, seule cellule
significative sur 17). L'ouverture du dispatch est une décision produit ; les
garde-fous ci-dessous sont ce qui reste pour que cette décision reste bornée.

Trois différences avec les clients crypto, toutes structurelles :

1. **La quantité est un nombre entier d'actions.** Une fraction n'existe pas
   sur un compte cash standard : ``qty`` est planché à l'entier inférieur, et
   **zéro action est un refus**, pas un ordre nul. C'est le cas nominal quand
   le capital est insuffisant — une action AAPL vaut 306 USD pour un compte à
   115.
2. **Le marché ferme.** Les actions US cotent 13:30-20:30 UTC : contrairement
   au crypto, ``is_market_open_for_destination`` doit mordre, et la grille de
   séance s'applique.
3. **Le Gateway a son propre interrupteur.** ``IBKR_ALLOW_ORDERS`` vit côté
   bridge ; tant qu'il est faux la session IB est ouverte en ``readonly=True``
   et le Gateway refuse lui-même toute écriture. Un `403` n'est donc pas une
   panne : c'est le garde-fou qui fonctionne.
"""
from __future__ import annotations

import logging
import math
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

RESPECT_VERDICT = os.getenv("IBKR_RESPECT_VERDICT", "true").strip().lower() in ("true", "1", "yes")
MIN_FINAL_CONFIDENCE = float(os.getenv("IBKR_MIN_FINAL_CONFIDENCE", "60"))
IBKR_BRIDGE_TIMEOUT_SEC = float(os.getenv("IBKR_BRIDGE_TIMEOUT_SEC", "30"))


def actions_pour(risk_money: float, entry: float, stop_loss: float) -> int:
    """Nombre **entier** d'actions, ou ``0`` si le capital ne suffit pas.

    ``0`` est un résultat légitime et fréquent : il signifie « le risque
    autorisé ne paie pas une seule action ». Le planchage vers le bas est
    délibéré — arrondir au supérieur ferait dépasser le risque voulu, ce qui
    est précisément ce que le lot minimum impose déjà côté MT5.
    """
    distance = abs(float(entry) - float(stop_loss))
    if distance <= 0 or risk_money <= 0:
        return 0
    return max(0, math.floor(float(risk_money) / distance))


def _build_payload(setup, sz: dict, dest) -> dict[str, Any]:
    entry = float(setup.entry_price)
    sl = float(setup.stop_loss)
    tp = float(setup.take_profit_1)
    direction = setup.direction.value if hasattr(setup.direction, "value") else str(setup.direction)
    return {
        "pair": setup.pair,
        "direction": direction,
        "qty": actions_pour(float(sz["risk_money"]), entry, sl),
        "sl": sl,
        "tp": tp,
        # Le bridge simule par defaut ; l'envoi reel est un acte explicite,
        # doublement garde par `IBKR_ALLOW_ORDERS` cote Gateway.
        "dry_run": False,
    }


async def push_to_ibkr(setup, sz: dict, dest) -> None:
    """Pousse un setup vers le bridge IBKR. Logge dans ``mt5_pushes``.

    Même contrat que ``kraken_bridge_client.push_to_kraken`` : best-effort,
    aucune exception ne remonte au cycle d'analyse, et **la clé de push est
    réservée avant l'appel HTTP** — c'est elle qui garantit une trace même
    sans confirmation, et qui empêche le rejeu.
    """
    from backend.services import sizing as _sizing
    from backend.services.bridge_push_ledger import PushLedger
    from backend.services.rejection_service import record_rejection

    direction = setup.direction.value if hasattr(setup.direction, "value") else str(setup.direction)
    score = float(getattr(setup, "confidence_score", 0) or 0)
    verdict = getattr(setup, "verdict_action", None)

    if RESPECT_VERDICT and verdict == "SKIP":
        record_rejection(
            pair=setup.pair, direction=direction, confidence=score,
            reason_code="ibkr_verdict_skip",
            details={"verdict": verdict, "score": score},
            destination_id=dest.destination_id,
        )
        return
    if score < MIN_FINAL_CONFIDENCE:
        record_rejection(
            pair=setup.pair, direction=direction, confidence=score,
            reason_code="ibkr_below_final_confidence",
            details={"score": score, "threshold": MIN_FINAL_CONFIDENCE},
            destination_id=dest.destination_id,
        )
        return

    payload = _build_payload(setup, sz, dest)
    if payload["qty"] <= 0:
        # Cas NOMINAL, pas une anomalie : le risque autorise ne paie pas une
        # action. Le motif le dit en clair plutot que de laisser croire a un
        # stop colle a l'entree.
        record_rejection(
            pair=setup.pair, direction=direction, confidence=score,
            reason_code="ibkr_capital_insuffisant",
            details={
                "raison": _sizing.raison_du_refus(sz, setup),
                "risque_autorise": sz.get("risk_money"),
                "prix_action": getattr(setup, "entry_price", None),
                "capital": sz.get("capital"),
                "payload": payload,
            },
            destination_id=dest.destination_id,
        )
        return

    url = dest.bridge_url.rstrip("/") + "/order"
    ledger = PushLedger.for_setup(dest, setup, direction)
    if not ledger.reserve():
        record_rejection(
            pair=setup.pair, direction=direction, confidence=score,
            reason_code="ibkr_already_pushed",
            details={"entry_5dp": ledger.entry_5dp},
            destination_id=dest.destination_id,
        )
        return

    try:
        async with httpx.AsyncClient(timeout=IBKR_BRIDGE_TIMEOUT_SEC) as c:
            r = await c.post(
                url, json=payload,
                headers={"X-Bridge-Key": dest.bridge_api_key} if dest.bridge_api_key else {},
            )
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text[:200]}

        if r.status_code == 200 and body.get("ok"):
            ledger.confirm(body)
            logger.warning(
                f"ibkr bridge[{dest.destination_id}] → {setup.pair} {direction} "
                f"{payload['qty']} action(s) OK order_id={body.get('order_id')} "
                f"fill={body.get('avg_fill_price')} commission={body.get('commission')}"
            )
            try:
                from backend.services import telegram_service as _tg
                _tg.send_trade_opened(
                    pair=setup.pair, direction=direction,
                    entry=float(body.get("avg_fill_price") or setup.entry_price),
                    sl=payload["sl"], tp=payload["tp"],
                    volume=float(body.get("filled") or payload["qty"]),
                    destination_id=dest.destination_id,
                )
            except Exception as _e:
                logger.warning(f"send_trade_opened ibkr hook error: {_e}")
            return

        # ⚠️ 403 = `IBKR_ALLOW_ORDERS` faux cote bridge. Ce n'est pas une
        # panne : la session IB est en lecture seule et le Gateway refuse
        # lui-meme. Le distinguer evite de chercher une cause ailleurs.
        code = ("ibkr_ecriture_desactivee" if r.status_code == 403
                else "ibkr_bridge_error")
        ledger.flag_unknown(body) if r.status_code >= 500 else ledger.release()
        record_rejection(
            pair=setup.pair, direction=direction, confidence=score,
            reason_code=code,
            details={"status": r.status_code, "reponse": str(body)[:300],
                     "payload": payload},
            destination_id=dest.destination_id,
        )
        logger.warning(
            f"ibkr bridge[{dest.destination_id}] {code} {r.status_code} "
            f"pour {setup.pair}: {str(body)[:200]}"
        )
    except httpx.TimeoutException:
        # L'ordre a PEUT-ETRE atteint le marche : garder la reservation.
        ledger.flag_unknown({"timeout": True})
        logger.warning(f"ibkr bridge[{dest.destination_id}] timeout — {setup.pair}")
    except Exception:
        ledger.release()
        logger.exception(f"ibkr bridge[{dest.destination_id}] exception pour {setup.pair}")
