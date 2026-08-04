"""Sizing dynamique du montant risque par trade.

Le bridge MT5 calcule les lots a partir de `risk_money` + specs du symbole
chez le broker (trade_tick_value, volume_step, etc.). Ce service calcule
ce `risk_money` en le modulant selon :

1. Capital actuel (realised PnL du jour inclus).
2. Base : `RISK_PER_TRADE_PCT` du capital.
3. Multiplicateur de confiance : un signal a 90/100 merite plus qu'un
   signal a 60/100. Echelle lineaire entre 0.5x et 1.5x sur la plage
   60→95 (au-dela, plafonne).
4. Drawdown-aware reducer : si le PnL realise sur les 7 derniers jours
   est negatif, on divise le risque par 2. Evite les "revenge trades"
   amplifies quand le modele sous-performe.
5. Session multiplier : l'overlap London/NY a un edge historique (60%
   du volume daily forex), la session asian est plus calme. On pondere
   0.7x-1.2x selon la fenetre, 0.0x le weekend.
6. Macro alignment : si le setup va contre le contexte macro (ex: long
   index en risk_off + VIX HIGH, short USD en DXY STRONG_UP), on
   reduit le risque. Si aligne, legere bonification.

Le but : faire travailler le capital plus fort quand le signal est fort
et le contexte favorable, et freiner quand on encaisse des pertes.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def confidence_multiplier(score: float | None) -> float:
    """Mappe un confidence_score 0-100 vers un multiplicateur de risque :
    - < 60  → 0.5x (clamp bas)
    - 60-95 → lineaire de 0.5x a 1.5x
    - >= 95 → 1.5x (clamp haut)

    Choix lineaire plutot que sigmoide : transparent, debuggable, et une
    relation plus complexe n'a pas de base statistique tant qu'on n'a
    pas 500+ trades pour calibrer."""
    if score is None:
        return 1.0
    if score < 60:
        return 0.5
    if score >= 95:
        return 1.5
    return _clamp(0.5 + (score - 60) / 35.0, 0.5, 1.5)


def recent_pnl_multiplier(days: int = 7) -> float:
    """1.0 si le PnL cumule des `days` derniers jours est >= 0,
    0.5 sinon. "Capital preservation mode" quand le modele est en
    perte recente."""
    try:
        from backend.services.trade_log_service import _DB_PATH
    except Exception:
        return 1.0

    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        with sqlite3.connect(_DB_PATH) as c:
            row = c.execute(
                "SELECT COALESCE(SUM(pnl), 0) FROM personal_trades "
                "WHERE status = 'CLOSED' AND closed_at >= ?",
                (since,),
            ).fetchone()
        pnl = float(row[0] or 0)
    except Exception as e:
        logger.debug(f"sizing: recent_pnl lookup failed: {e}")
        return 1.0
    return 1.0 if pnl >= 0 else 0.5


def compute_risk_money(setup, dest=None) -> dict:
    """Retourne un dict complet des multiplicateurs + risk_money final
    pour l'envoi au bridge et le logging.

    ``dest`` (2026-08-04) : le capital est résolu **par destination**, cf.
    ``destination_capital``. Sans ``dest``, comportement legacy inchangé
    (capital global).

    ⚠️ Si le capital d'une destination à solde interrogeable n'est pas
    disponible, ``risk_money`` vaut 0 : les clients de bridge rejettent alors
    l'ordre (``qty <= 0``). C'est délibéré — retomber sur le capital global
    reproduirait le défaut qui envoyait des ordres de 10 000 USD sur un
    compte de 103 USD.
    """
    from backend.services import macro_alignment, session_service
    from config.settings import RISK_PER_TRADE_PCT

    capital, capital_source = destination_capital(dest)
    if capital is None:
        return {
            "risk_money": 0.0, "base": 0.0,
            "conf_mult": 0.0, "pnl_mult": 0.0, "session_mult": 0.0,
            "session": session_service.label(), "macro_mult": 0.0,
            "macro_reasons": [], "final_mult": 0.0,
            "capital": None, "capital_source": capital_source,
            "risk_pct": RISK_PER_TRADE_PCT,
        }
    base = capital * (RISK_PER_TRADE_PCT / 100.0)
    conf_mult = confidence_multiplier(getattr(setup, "confidence_score", None))
    pnl_mult = recent_pnl_multiplier()
    session_mult = session_service.activity_multiplier(pair=getattr(setup, "pair", None))
    session_label = session_service.label()
    direction = (
        setup.direction.value
        if hasattr(getattr(setup, "direction", None), "value")
        else str(getattr(setup, "direction", ""))
    )
    macro = macro_alignment.alignment_for(getattr(setup, "pair", ""), direction)
    macro_mult = macro["multiplier"]

    final_mult = conf_mult * pnl_mult * session_mult * macro_mult
    risk_money = round(base * final_mult, 2)
    return {
        "risk_money": risk_money,
        "base": round(base, 2),
        "conf_mult": round(conf_mult, 2),
        "pnl_mult": round(pnl_mult, 2),
        "session_mult": round(session_mult, 2),
        "session": session_label,
        "macro_mult": round(macro_mult, 2),
        "macro_reasons": macro["reasons"],
        "final_mult": round(final_mult, 2),
        "capital": capital,
        "capital_source": capital_source,
        "risk_pct": RISK_PER_TRADE_PCT,
    }


# ─── Capital par destination (2026-08-04) ──────────────────────────────
#
# ⚠️ Jusqu'ici `compute_risk_money` sizait TOUJOURS sur le `TRADING_CAPITAL`
# global (3 000 €). Sur une destination dont le compte vaut 103 USD, cela
# produisait des ordres de ~10 000 USD de notionnel — vingt fois la capacité
# du compte. Kraken les rejetait en `invalidSize`, ce qui explique qu'aucun
# ordre n'y soit jamais passé.
#
# Les bridges MT5 s'en tiraient parce qu'ils ramènent le volume au minimum
# du broker côté bridge ; les bridges crypto, eux, envoient la quantité telle
# quelle.
#
# Principe retenu : **en cas de doute, refuser de trader**. Retomber sur le
# global reproduirait exactement le défaut — c'est la leçon de la journée,
# un repli qui élargit n'est pas un repli sûr.

_BALANCE_CACHE: dict[str, tuple[float, float]] = {}  # dest_id -> (capital, expire_at)
_BALANCE_TTL_SEC = 300.0

# Types de bridge dont le solde est interrogeable via /account. Les bridges
# MT5 gardent le capital global : leur sizing est reclampé côté bridge.
LIVE_BALANCE_BRIDGE_TYPES = frozenset({"kraken", "kraken_spot", "binance"})

CAPITAL_UNAVAILABLE = "unavailable"


def _cache_get(dest_id: str) -> float | None:
    import time
    hit = _BALANCE_CACHE.get(dest_id)
    if hit and hit[1] > time.monotonic():
        return hit[0]
    return None


def _cache_put(dest_id: str, capital: float) -> None:
    import time
    _BALANCE_CACHE[dest_id] = (capital, time.monotonic() + _BALANCE_TTL_SEC)


async def refresh_destination_capital(dest) -> float | None:
    """Interroge ``/account`` du bridge et met le capital en cache.

    À appeler depuis le chemin async AVANT ``compute_risk_money``, qui lira
    ensuite le cache de façon synchrone. Évite un appel HTTP bloquant au
    milieu du calcul de sizing.

    Retourne le capital, ou ``None`` si indisponible (le sizing refusera
    alors de produire un ordre).
    """
    import httpx
    dest_id = getattr(dest, "destination_id", "")
    cached = _cache_get(dest_id)
    if cached is not None:
        return cached
    url = (getattr(dest, "bridge_url", "") or "").rstrip("/")
    if not url:
        return None
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(
                f"{url}/account",
                headers={"X-Bridge-Key": getattr(dest, "bridge_api_key", "") or ""},
            )
        if r.status_code != 200:
            logger.warning(
                f"sizing[{dest_id}]: /account HTTP {r.status_code} — sizing refusé"
            )
            return None
        # `portfolio_value_usd` est la clé commune aux bridges Kraken Futures,
        # Kraken Spot et Binance. On ne devine pas au-delà.
        value = (r.json() or {}).get("portfolio_value_usd")
        capital = float(value) if value is not None else 0.0
        if capital <= 0:
            logger.warning(f"sizing[{dest_id}]: solde nul ou absent — sizing refusé")
            return None
        _cache_put(dest_id, capital)
        return capital
    except Exception as e:
        logger.warning(f"sizing[{dest_id}]: /account injoignable ({type(e).__name__}) — sizing refusé")
        return None


def destination_capital(dest) -> tuple[float | None, str]:
    """Capital à utiliser pour cette destination, et sa provenance.

    Cascade :
      1. ``dest is None``            -> global (chemin legacy mono-tenant)
      2. ``dest.trading_capital``    -> surcharge explicite
      3. bridge à solde interrogeable -> cache alimenté par
         ``refresh_destination_capital``. Absent du cache -> ``None``,
         donc refus de trader.
      4. sinon                       -> global (bridges MT5)
    """
    from config.settings import TRADING_CAPITAL
    if dest is None:
        return TRADING_CAPITAL, "global"
    explicite = getattr(dest, "trading_capital", None)
    if explicite:
        return float(explicite), "destination"
    if getattr(dest, "bridge_type", "mt5") in LIVE_BALANCE_BRIDGE_TYPES:
        cached = _cache_get(getattr(dest, "destination_id", ""))
        if cached is None:
            return None, CAPITAL_UNAVAILABLE
        return cached, "live"
    return TRADING_CAPITAL, "global"
