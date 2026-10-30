"""Client HTTP pour pousser un setup vers le bridge Kraken Futures.

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

# Filtre de paires cote BACKEND, pose le 2026-10-30.
#
# Mesure du 29/10 : `admin_kraken` tient de l'argent reel, est joignable,
# porte 22 buckets AUTO_EXEC -- et AUCUN filtre de paires ne s'applique a
# lui. Ce n'etait pas un oubli de configuration : la liste blanche de
# `mt5_bridge` est gardee par `bridge_type == "mt5"` (mt5_bridge.py:1097-1117),
# donc la porte SAUTE une destination Kraken. Le compte IC Markets
# (`admin_live`) est filtre a une seule paire depuis toujours ; celui-ci ne
# l'etait pas du tout.
#
# ⛔ OPT-IN STRICT : vide par defaut, donc RIEN ne passe. C'est l'inverse de
# la semantique MT5, ou une liste vide signifie « pas de filtrage »
# (`if LIVE_WHITELIST_PAIRS and ...`). La meme absence veut donc dire
# « protection maximale » ici et « aucune protection » la-bas. Si vous
# touchez l'une, ne recopiez pas le test de l'autre.
_KRAKEN_WHITELIST_PAIRS = frozenset(
    p.strip().upper()
    for p in os.getenv("KRAKEN_BRIDGE_WHITELIST_PAIRS", "").split(",")
    if p.strip()
)


def _build_kraken_payload(setup, sz: dict, dest) -> dict[str, Any]:
    """Convertit un setup scalping-radar en payload kraken-bridge.

    Payload attendu par le bridge Kraken :
    {pair, direction, qty (base currency), sl, tp, entry, sl_dist, tp_dist}

    qty = risk_money / |entry - sl|  — même formule que Binance.
    Kraken PF_* sizes en base asset direct (comme Binance USDT-M).

    ⚠️ `sl_dist` / `tp_dist` (2026-08-19) : les prix absolus sont calculés sur
    le prix du SIGNAL. Entre le signal et l'exécution le marché bouge, et poser
    les stops au prix du signal déforme le rapport risque/gain réel — mesuré
    0,7-1,3 au lieu de 1,8 sur ETH/USD le 2026-05-18. Le correctif existe côté
    MT5 depuis cette date (`_build_order_payload`) mais manquait ici, alors que
    le bridge Kraken calculait déjà `avg_price` sans s'en servir.

    Les prix absolus sont **conservés** : ils restent le repli du bridge quand
    aucun remplissage n'est remonté.
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
        "entry": entry,
        # Distances positives, en unités de prix. Le bridge repose les stops
        # depuis le prix de remplissage quand il en connaît un.
        "sl_dist": sl_distance,
        "tp_dist": abs(tp - entry),
    }


async def alerter_si_non_protegee(body: dict, pair: str, direction: str,
                                  destination_id: str) -> None:
    """Alerte immediate si le bridge dit que la position n'a PAS de stop.

    Sur Kraken, une entree est **trois ordres independants** : marche, stop,
    objectif. Le stop peut echouer a la pose sans que l'entree echoue, et
    `/order` rendait alors `ok: True` comme si tout allait bien. Le champ
    `sl_error` existait deja dans la reponse — personne ne le lisait.

    C'est l'incident du 2026-08-05 (position XAU/USD sans stop, decouverte 7 h
    plus tard a -51 EUR), cote Kraken cette fois. Le bridge MT5 a ce garde-fou
    depuis le 06/08 ; il n'avait jamais ete propage ici.

    ⚠️ **`protected is False`, jamais `not protected`.** Un bridge pas encore
    deploye n'a pas le champ, et « pas de champ » ne veut pas dire « pas de
    stop » : alerter la-dessus apprendrait a ignorer l'alerte.

    ⛔ Best-effort : le flux d'ordre ne doit jamais dependre de Telegram.
    """
    if body.get("protected") is not False:
        return
    try:
        from backend.services import telegram_service as _tg
        await _tg.send_infra_text(
            "🚨 <b>Position Kraken ouverte SANS stop</b>\n"
            f"Destination : <code>{destination_id}</code>\n"
            f"Pair : <code>{pair}</code> {str(direction).upper()}\n"
            f"Symbole : <code>{body.get('symbol') or '?'}</code>\n"
            f"Ordre : <code>{body.get('market_order_id') or '?'}</code>\n"
            f"SL error : <code>{body.get('sl_error') or '?'}</code>\n"
            "\n👉 Le stop est un ordre INDEPENDANT sur Kraken : verifier "
            "<code>/openorders</code> et le reposer a la main si besoin.",
            parse_mode="HTML",
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"alerte position kraken non protegee echouee : {e}")


async def push_to_kraken(setup, sz: dict, dest) -> None:
    """Pousse un setup vers le kraken-bridge. Logge dans ``mt5_pushes``.

    Best-effort : timeout / 4xx / 5xx → record_rejection + return. Pas
    d'exception remontée au cycle d'analyse.

    ⚠️ La clé de push est **réservée avant** l'appel HTTP. Jusqu'au
    2026-08-04 elle ne l'était pas, et l'enregistrement se faisait après le
    fill via une fonction inexistante : un ordre réel partait chez Kraken
    sans laisser la moindre trace, et se rejouait au cycle suivant. Voir
    ``bridge_push_ledger``.
    """
    from backend.services import sizing as _sizing
    from backend.services.bridge_push_ledger import PushLedger
    from backend.services.rejection_service import record_rejection

    direction = setup.direction.value if hasattr(setup.direction, "value") else str(setup.direction)
    score = float(getattr(setup, "confidence_score", 0) or 0)
    verdict = getattr(setup, "verdict_action", None)

    # ⛔ Filtre de paires -- EN PREMIER, et avant tout appel reseau.
    # La propriete qui compte n'est pas le refus mais son MOMENT : un ordre
    # refuse ici n'a pas ete envoye et ne laisse aucune reservation de push.
    # Place avant la porte de verdict pour que le motif rapporte soit le bon
    # quand les deux s'appliquent -- sinon on corrigerait la mauvaise chose.
    if setup.pair not in _KRAKEN_WHITELIST_PAIRS:
        record_rejection(
            pair=setup.pair, direction=direction, confidence=score,
            reason_code="kraken_pair_not_whitelisted",
            details={"pair": setup.pair,
                     "autorisees": sorted(_KRAKEN_WHITELIST_PAIRS)},
            destination_id=dest.destination_id,
        )
        logger.info(
            f"kraken[{dest.destination_id}] REFUSE {setup.pair} : hors liste "
            f"blanche backend (autorisees : "
            f"{sorted(_KRAKEN_WHITELIST_PAIRS) or 'aucune'})"
        )
        return

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
            details={"reason": _sizing.raison_du_refus(sz, setup), "payload": payload},
            destination_id=dest.destination_id,
        )
        return

    bridge_url = dest.bridge_url.rstrip("/")
    bridge_key = dest.bridge_api_key
    url = f"{bridge_url}/order"

    # Réservation AVANT l'envoi : c'est elle qui empêche un doublon si la
    # suite tourne mal, et qui garantit une trace même sans confirmation.
    ledger = PushLedger.for_setup(dest, setup, direction)
    if not ledger.reserve():
        record_rejection(
            pair=setup.pair, direction=direction, confidence=score,
            reason_code="kraken_already_pushed",
            details={"entry_5dp": ledger.entry_5dp},
            destination_id=dest.destination_id,
        )
        return

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
            ledger.confirm(body)
            logger.warning(
                f"kraken bridge[{dest.destination_id}] → {setup.pair} {direction} "
                f"OK order_id={body.get('market_order_id')} avg_price={body.get('avg_price')}"
            )
            # Notification « Trade OUVERT » — même formateur que MT5 et
            # Binance. Ce hook manquait : les trades Kraken n'apparaissaient
            # que via le poller shell, dans un format degrade et sur le mauvais
            # canal. Best-effort, ne casse jamais le flux d'ordre.
            try:
                from backend.services import telegram_service as _tg
                await _tg.send_trade_opened(
                    setup,
                    ticket=body.get("market_order_id") or "n/a",
                    fill_price=float(body.get("avg_price") or setup.entry_price),
                    volume=float(body.get("volume") or payload.get("qty") or 0),
                    mode=str(body.get("mode") or "live"),
                    destination_id=dest.destination_id,
                )
            except Exception as _e:
                logger.warning(f"send_trade_opened kraken hook error: {_e}")
            # ⛔ L'entree a reussi, mais son stop a pu echouer : trois ordres
            # independants. Sans ce controle, une position nue passait pour
            # saine — `sl_error` etait rendu et personne ne le lisait.
            await alerter_si_non_protegee(
                body, pair=setup.pair, direction=direction,
                destination_id=dest.destination_id)
        elif r.status_code == 429 and body.get("blocked"):
            # Kill-switch bridge (daily drawdown, whitelist, max positions).
            # Rien n'est parti au marché : la contrainte peut se lever seule,
            # donc on relâche pour laisser un cycle suivant retenter.
            reason = body.get("reason", "unknown")
            ledger.release()
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
            # Rejet explicite de l'exchange (`invalidSize`, symbole inconnu…).
            # Il se reproduirait à l'identique : on garde la réservation pour
            # ne pas marteler Kraken toutes les cinq minutes.
            ledger.flag_unknown({"status": r.status_code, "body": str(body)[:400]})
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
        # La requête est partie ; l'ordre a pu être rempli sans que la réponse
        # revienne. Sur un compte réel, un doublon coûte plus cher qu'un trade
        # manqué : on conserve la réservation.
        ledger.flag_unknown({"error": "timeout", "timeout_sec": KRAKEN_BRIDGE_TIMEOUT_SEC})
        record_rejection(
            pair=setup.pair, direction=direction, confidence=score,
            reason_code="kraken_bridge_timeout",
            details={"timeout_sec": KRAKEN_BRIDGE_TIMEOUT_SEC},
            destination_id=dest.destination_id,
        )
        logger.warning(f"kraken bridge[{dest.destination_id}] timeout — skip {setup.pair}")
    except httpx.ConnectError as e:
        # Le bridge est injoignable : rien n'a atteint Kraken, on peut retenter.
        ledger.release()
        record_rejection(
            pair=setup.pair, direction=direction, confidence=score,
            reason_code="kraken_bridge_unreachable",
            details={"error": str(e)[:200], "url": url},
            destination_id=dest.destination_id,
        )
        logger.warning(f"kraken bridge[{dest.destination_id}] injoignable: {url}")
    except Exception as e:
        # Cas du 2026-08-04 : l'exception survenait APRÈS le fill. On ne peut
        # pas savoir, donc on garde la réservation.
        ledger.flag_unknown({"error": str(e)[:300]})
        record_rejection(
            pair=setup.pair, direction=direction, confidence=score,
            reason_code="kraken_bridge_exception",
            details={"error": str(e)[:200]},
            destination_id=dest.destination_id,
        )
        logger.exception(f"kraken bridge[{dest.destination_id}] exception for {setup.pair}")
