"""Garde-fou sur les fills du bridge MT5 — défense entry=0.0.

## Pourquoi

L'audit du 2026-11-13 a identifié 217 trades (4,75% du volume) avec
``entry=0.0`` côté bridge, dont un seul XAU/USD #1353960866 responsable
de -265 USD. Root cause probable : le bridge Windows a reçu un
``/order`` et l'a ouvert, mais la réponse à notre /order a été
corrompue (fill_source=null sur 209/217 cas), donc on a enregistré
``entry=requested_entry`` dans notre state alors que le bridge a stocké
``entry=0`` et calcule un PnL absurde quand la position se ferme.

## Ce que fait ce module

``is_fill_price_sane(resp, requested_entry)`` → ``(ok, reason)``.

Retourne ``False`` si :
- le champ ``avg_fill_price`` est absent de la réponse
- sa valeur est <= 0 ou invalide
- l'écart avec ``requested_entry`` dépasse 5% (prévention bridge bug)

Le call-site doit, en cas de refus :
1. Fermer immédiatement la position via ``/close {ticket}`` au broker
2. NE PAS ajouter la position dans ``open_positions`` (sinon on
   essaierait d'auto-gérer une position qu'on ne tracke pas correctement)
3. Envoyer une alerte Telegram pour visibilité humaine

Fail-open : toute erreur d'interprétation → ``True`` (on laisse passer)
pour ne pas bloquer le trading sur un bug du garde-fou lui-même.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


#: Écart maximum acceptable entre le fill et le prix demandé (5%).
#: Au-delà, on soupçonne un bug bridge (symbole différent, entry=0, etc.)
MAX_FILL_DEVIATION_PCT = 5.0


def is_fill_price_sane(
    resp: dict,
    requested_entry: float,
    max_deviation_pct: float = MAX_FILL_DEVIATION_PCT,
) -> tuple[bool, str]:
    """Vérifie que le fill price du bridge est raisonnable.

    Args:
        resp: réponse JSON du bridge sur POST /order.
        requested_entry: prix demandé par le pipeline.
        max_deviation_pct: écart max toléré entre fill et requested.

    Returns:
        ``(True, "ok")`` si fill plausible.
        ``(False, reason)`` sinon. Le call-site doit refuser la position.
    """
    try:
        fill = resp.get("avg_fill_price")
        if fill is None:
            return False, "avg_fill_price absent de la réponse bridge"

        try:
            fill_f = float(fill)
        except (TypeError, ValueError):
            return False, f"avg_fill_price non numérique: {fill!r}"

        if fill_f <= 0:
            return False, f"avg_fill_price <= 0: {fill_f}"

        if requested_entry and requested_entry > 0:
            deviation_pct = abs(fill_f - requested_entry) / requested_entry * 100.0
            if deviation_pct > max_deviation_pct:
                return False, (
                    f"écart fill {fill_f:.5f} vs requested "
                    f"{requested_entry:.5f} = {deviation_pct:.2f}% "
                    f"(max {max_deviation_pct:.1f}%)"
                )

        return True, "ok"
    except Exception as e:  # noqa: BLE001
        # Fail-open : un bug du garde-fou ne doit pas bloquer le trading
        logger.error("trader_fill_guard: exception interne, fail-open — %s", e)
        return True, f"garde-fou erreur ({e}), fail-open"
