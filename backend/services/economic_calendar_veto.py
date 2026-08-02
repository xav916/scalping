"""Veto pre/post news économiques HIGH impact — soft veto ×0.70 sur le score.

Branché après VIX scoring dans ``analysis_engine.enrich_trade_setup``.
Feature-flagged via ``ECONOMIC_CALENDAR_VETO_ENABLED`` (défaut: true).

## Logique

Pour chaque setup :
1. Query ``economic_calendar_service.get_upcoming_events(within_minutes=30, min_impact='High')``
2. Filtre par currency impactée par la paire :
   - Forex XX/YY  → XX et YY
   - XAU/USD      → USD (+ XAU traité comme USD-sensitive)
   - XAG/USD      → USD
   - WTI/USD      → USD
   - Crypto        → no-op (pas d'événements macro directs)
   - Equity/index  → no-op (géré par VIX + earnings P2)
3. Si event dans ±30 min → soft veto ×0.70 sur le score
   (même multiplicateur que le régime VIX "panic" — impact fort)
4. Metadata : event_name, minutes_delta, impact, currencies_matched

## Design

- No-op silencieux si source indisponible (best-effort).
- No-op sur crypto : pas de publication macro binaire crypto pure.
- No-op sur equity/equity_index : Earnings P2 gère les events stock-specific.
  VIX et macro scoring gèrent l'index-level risk.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Multiplicateur soft veto : ×0.70 = -30% sur le score (filtre fort,
# aligné sur le régime VIX "panic" — symétrie voulue).
_VETO_MULTIPLIER = 0.70

# Asset classes exclues du veto calendrier économique :
# - crypto : pas d'event macro binaire type NFP/CPI/FOMC sur BTC/ETH
# - equity / equity_index : Earnings P2 + VIX gèrent ; le calendrier macro
#   affecte l'indice via macro_scoring déjà intégré.
_EXCLUDED_ASSET_CLASSES = {"crypto", "equity", "equity_index"}


def _currencies_for_pair(pair: str) -> frozenset[str]:
    """Extrait les currencies impactées par un pair.

    Forex XX/YY  → {XX, YY}
    Métaux       → {USD}  (XAU/USD, XAG/USD — price en USD, sensibles USD macro)
    Energy       → {USD}  (WTI/USD — coté en USD)
    Autres       → {} (no-op)
    """
    p = pair.upper()

    # Format XX/YY — forex et métaux coté USD
    if "/" in p:
        parts = p.split("/", 1)
        base, quote = parts[0].strip(), parts[1].strip()
        # Métaux : la "base" n'est pas une currency forex,
        # mais le prix est déterminé par le USD → on filtre sur USD uniquement
        _NON_CURRENCIES = {"XAU", "XAG", "XPT", "XPD", "WTI", "BRENT", "XTI", "XBR"}
        if base in _NON_CURRENCIES:
            return frozenset({quote})
        return frozenset({base, quote})

    # Indices sans slash (SPX, NDX, DAX...) → currency USD pour indices US,
    # mais on les exclut via asset_class → cette branche n'est jamais atteinte
    # en pratique grâce à _EXCLUDED_ASSET_CLASSES. Retourner {} est safe.
    return frozenset()


def apply_economic_veto(
    pair: str,
    direction: str,
    base_score: float,
    now: Optional[datetime] = None,
    within_minutes: int = 30,
) -> tuple[float, dict]:
    """Applique un soft veto ×0.70 si un event HIGH impact est dans ±within_minutes.

    Parameters
    ----------
    pair : str
        Paire du setup (ex. "XAU/USD", "EUR/USD", "BTC/USD").
    direction : str
        "buy" ou "sell".
    base_score : float
        Score de confiance courant (0–100).
    now : datetime | None
        Référence temps (UTC). None → datetime.now(UTC).
    within_minutes : int
        Demi-fenêtre en minutes (défaut 30).

    Returns
    -------
    tuple[float, dict]
        (new_score, metadata)
        - new_score : base_score × _VETO_MULTIPLIER si veto, sinon base_score
        - metadata : dict avec clés ``eco_veto_applied``, ``eco_event_name``,
          ``eco_minutes_delta``, ``eco_impact``, ``eco_currencies``
          (vide si no-op ou erreur)
    """
    if now is None:
        now = datetime.now(timezone.utc)

    try:
        from config.settings import asset_class_for
        asset_class = asset_class_for(pair)
    except Exception as e:
        logger.debug(f"economic_calendar_veto: asset_class_for error: {e}")
        return base_score, {}

    # No-op sur les asset classes exclues
    if asset_class in _EXCLUDED_ASSET_CLASSES:
        return base_score, {}

    # Currencies impactées par ce pair
    pair_currencies = _currencies_for_pair(pair)
    if not pair_currencies:
        return base_score, {}

    # Fetch events depuis le cache SQLite (sync, rapide — pas de réseau)
    try:
        from backend.services import economic_calendar_service
        events = economic_calendar_service.get_upcoming_events(
            within_minutes=within_minutes,
            min_impact="High",
            now=now,
        )
    except Exception as e:
        logger.debug(f"economic_calendar_veto: get_upcoming_events error: {e}")
        return base_score, {}

    if not events:
        return base_score, {}

    # Filtre par currency : on cherche le premier event qui touche ce pair
    matched = None
    for ev in events:
        if ev["currency"] in pair_currencies:
            matched = ev
            break  # le plus proche en temps (ORDER BY ts_utc ASC)

    if matched is None:
        return base_score, {}

    # Soft veto ×0.70
    new_score = round(min(100.0, max(0.0, base_score * _VETO_MULTIPLIER)), 1)

    meta = {
        "eco_veto_applied": True,
        "eco_multiplier": _VETO_MULTIPLIER,
        "eco_event_name": matched["event_name"],
        "eco_minutes_delta": matched["minutes_delta"],
        "eco_impact": matched["impact"],
        "eco_currencies": list(pair_currencies),
        "eco_currency_matched": matched["currency"],
    }

    logger.info(
        f"eco_veto pair={pair} dir={direction} "
        f"event='{matched['event_name']}' currency={matched['currency']} "
        f"delta={matched['minutes_delta']:+.0f}min "
        f"score={base_score}→{new_score}"
    )

    return new_score, meta
