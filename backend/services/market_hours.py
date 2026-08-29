"""Horaires d'ouverture des marchés par asset class.

Le radar envoyait des setups à l'auto-exec même quand le marché du symbole
était fermé (ex: XAU/USD dimanche soir pendant le daily break 21-22h UTC),
ce qui polluait l'audit du bridge avec des rc=10018 MARKET_CLOSED.

Cette fonction filtre en amont côté radar. Horaires Pepperstone typiques ;
les cas limites (fins de semaine, daily break) sont modélisés. Un asset
class inconnu → True (ne bloque pas).
"""

from datetime import datetime, timezone

from config.settings import asset_class_for


def _decimal_hour(now: datetime) -> float:
    return now.hour + now.minute / 60.0


def is_market_open_for(pair: str, now: datetime | None = None) -> bool:
    """Retourne True si le marché du symbole est normalement ouvert à l'instant now.

    Règles Pepperstone (UTC) :
    - crypto        : 24/7
    - forex         : dim 22:00 → ven 22:00, sans interruption
    - metal (XAU..) : dim 22:00 → ven 21:00, daily break 21:00-22:00 UTC
    - equity_index  : dim 22:00 → ven 21:00, daily break 21:00-22:00 UTC
    - equity (US)   : lun-ven 13:30-20:00 UTC seulement (NYSE/NASDAQ core session)
    - energy (WTI)  : dim 23:00 → ven 22:00, daily break 22:00-23:00 UTC
    """
    now = now or datetime.now(timezone.utc)
    wd = now.weekday()          # 0=lundi ... 5=samedi, 6=dimanche
    t = _decimal_hour(now)
    ac = asset_class_for(pair)

    if ac == "crypto":
        return True

    if ac == "forex":
        if wd == 5:
            return False
        if wd == 6 and t < 22:
            return False
        if wd == 4 and t >= 22:
            return False
        return True

    if ac == "metal" or ac == "equity_index":
        if wd == 5:
            return False
        if wd == 6 and t < 22:
            return False
        if wd == 4 and t >= 21:
            return False
        if 21 <= t < 22:
            return False
        return True

    if ac == "equity":
        # US individual stocks NYSE/NASDAQ : core session lun-ven 13:30 → 20:00 UTC
        if wd >= 5:
            return False
        if not (13.5 <= t < 20.0):
            return False
        return True

    if ac == "energy":
        if wd == 5:
            return False
        if wd == 6 and t < 23:
            return False
        if wd == 4 and t >= 22:
            return False
        if 22 <= t < 23:
            return False
        return True

    return True


def is_market_open_for_destination(
    pair: str,
    destination_id: str = "",
    now: datetime | None = None,
) -> bool:
    """Variante destination-aware de :func:`is_market_open_for`.

    ⛔ **Le LIEU décide, pas la paire.** Un perpétuel listé sur Kraken Futures
    cote 24/7 quel que soit son sous-jacent : `PF_XAUUSD` y tourne le samedi,
    alors que le CFD or de MT5 ferme le vendredi soir. Juger sur
    `asset_class_for(pair)` répondait donc « marché fermé » pour de l'or sur
    Kraken tout le week-end — un refus permanent, sur une place ouverte.

    Constaté le 2026-08-29, en ouvrant l'or et l'argent sur Kraken : la même
    erreur de principe venait d'être corrigée le jour même dans
    `cote_en_continu`, qui gouverne la grille de séance. Les deux fonctions
    posent la même question ; une seule y répondait bien.

    ⇒ On délègue à `cote_en_continu`, qui exige DEUX conditions : un lieu qui
    tourne en continu, et un sous-jacent qui ne dépend pas d'une bourse.

    ⚠️ Le cas `admin_kraken_stocks` reste : ses xStocks SONT adossés à une
    bourse, donc `cote_en_continu` répond False, et c'est bien
    ``KRAKEN_STOCKS_ALLOW_24_7`` qui tranche — un opt-in assumé, au prix d'un
    spread dégradé hors heures principales.
    """
    if destination_id == "admin_kraken_stocks" and asset_class_for(pair) == "equity":
        import os
        if os.getenv("KRAKEN_STOCKS_ALLOW_24_7", "false").lower() == "true":
            return True
    if destination_id:
        from backend.services.destinations_registry import cote_en_continu
        if cote_en_continu(destination_id):
            return True
    return is_market_open_for(pair, now)
