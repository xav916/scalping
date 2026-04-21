"""Cross-asset macro alignment : module de confiance selon DXY / VIX /
risk_regime / yields.

Les actifs ne bougent pas en isolation. Un long USD/JPY prend plus de
sens quand le DXY est en forte hausse que quand il est baissier. Un
long SPX sous VIX HIGH est generalement un pari perdant (il y a une
raison pour que le VIX soit haut).

Ce module traduit le macro_context en un multiplicateur de risque
supplementaire pour `sizing.py`, compris entre 0.5x (setup contra
fort) et 1.1x (setup aligne). Volontairement modeste : on biaise
dans le bon sens, on ne tente pas encore de bloquer (tant qu'on n'a
pas 500+ trades pour calibrer).

Regles (volontairement tres simples, auditables en 1 coup d'oeil) :

1. Pairs avec USD (forex + XAU/USD + indices US) : s'aligne avec la
   tendance DXY.
   - Long USD + DXY UP (ex: sell EUR/USD)     → 1.1x
   - Short USD + DXY UP (ex: buy EUR/USD)     → 0.7x (contra fort)
   - Idem symetrique pour DXY DOWN.

2. Equity indices (SPX, NDX, DAX, CAC40...) : sensibles au VIX.
   - Long index + VIX HIGH ou risk_off        → 0.5x (tres contra)
   - Short index + VIX LOW et risk_on         → 0.7x (contra)
   - Sinon                                    → 1.0x

3. Or (XAU/USD) : inverse aux real yields (proxy US10Y).
   - Long gold + US10Y UP                     → 0.7x
   - Short gold + US10Y UP                    → 1.1x
   - Idem symetrique pour US10Y DOWN.

4. Crypto : inverse au risk_regime.
   - Long crypto + risk_off                   → 0.7x
   - Short crypto + risk_on                   → 0.8x

Non couvert (intentionnellement, pour rester simple) : yields cross
(US-DE spread), oil pour CAD, Nikkei pour JPY. A ajouter plus tard
avec des donnees pour valider chaque regle.
"""
from __future__ import annotations

import logging

from backend.models.macro_schemas import MacroContext, MacroDirection, RiskRegime, VixLevel

logger = logging.getLogger(__name__)


_USD_INDICES = {"SPX", "NDX", "DJI", "RUT", "US30", "US500", "NAS100"}
_EU_INDICES = {"DAX", "CAC40", "UK100", "FTSE", "DE40", "EU50"}
_ALL_INDICES = _USD_INDICES | _EU_INDICES | {"N225", "NIKKEI", "JP225"}
_CRYPTO_BASES = {"BTC", "ETH", "LTC", "XRP", "SOL", "ADA", "DOGE"}


def _pair_parts(pair: str) -> tuple[str, str]:
    if "/" in pair:
        base, quote = pair.upper().split("/", 1)
        return base, quote
    return pair.upper(), ""


def _is_strong(direction: MacroDirection) -> bool:
    return direction in (MacroDirection.STRONG_UP, MacroDirection.STRONG_DOWN)


def _is_up(direction: MacroDirection) -> bool:
    return direction in (MacroDirection.UP, MacroDirection.STRONG_UP)


def _is_down(direction: MacroDirection) -> bool:
    return direction in (MacroDirection.DOWN, MacroDirection.STRONG_DOWN)


def _usd_role(pair: str, direction: str) -> str | None:
    """Retourne 'long_usd' / 'short_usd' / None selon la direction + role USD
    dans la paire. Sert a evaluer l'alignement avec DXY."""
    base, quote = _pair_parts(pair)
    dir_lower = direction.lower()
    up = pair.upper()
    if up in _USD_INDICES:
        # SPX/NDX cote en USD mais refletent les actions US, pas le dollar.
        # On ne les juge pas via DXY.
        return None
    if base == "USD":
        return "long_usd" if dir_lower == "buy" else "short_usd"
    if quote == "USD":
        return "long_usd" if dir_lower == "sell" else "short_usd"
    return None


def _dxy_alignment(pair: str, direction: str, dxy: MacroDirection) -> tuple[float, str | None]:
    role = _usd_role(pair, direction)
    if role is None or dxy == MacroDirection.NEUTRAL:
        return 1.0, None
    if _is_up(dxy):
        if role == "long_usd":
            return 1.1, f"USD long + DXY {dxy.value}"
        return 0.7, f"USD short vs DXY {dxy.value}"
    if _is_down(dxy):
        if role == "short_usd":
            return 1.1, f"USD short + DXY {dxy.value}"
        return 0.7, f"USD long vs DXY {dxy.value}"
    return 1.0, None


def _index_alignment(
    pair: str,
    direction: str,
    vix_level: VixLevel,
    risk_regime: RiskRegime,
) -> tuple[float, str | None]:
    if pair.upper() not in _ALL_INDICES:
        return 1.0, None
    is_long = direction.lower() == "buy"
    if is_long and (vix_level == VixLevel.HIGH or risk_regime == RiskRegime.RISK_OFF):
        return 0.5, f"long index + VIX {vix_level.value} / regime {risk_regime.value}"
    if not is_long and vix_level == VixLevel.LOW and risk_regime == RiskRegime.RISK_ON:
        return 0.7, f"short index + VIX {vix_level.value} / regime {risk_regime.value}"
    return 1.0, None


def _gold_alignment(pair: str, direction: str, us10y: MacroDirection) -> tuple[float, str | None]:
    base, _ = _pair_parts(pair)
    if base != "XAU":
        return 1.0, None
    if us10y == MacroDirection.NEUTRAL:
        return 1.0, None
    is_long = direction.lower() == "buy"
    if _is_up(us10y):
        if is_long:
            return 0.7, f"long gold + US10Y {us10y.value}"
        return 1.1, f"short gold + US10Y {us10y.value}"
    if _is_down(us10y):
        if is_long:
            return 1.1, f"long gold + US10Y {us10y.value}"
        return 0.7, f"short gold + US10Y {us10y.value}"
    return 1.0, None


def _crypto_alignment(
    pair: str, direction: str, risk_regime: RiskRegime
) -> tuple[float, str | None]:
    base, _ = _pair_parts(pair)
    if base not in _CRYPTO_BASES:
        return 1.0, None
    is_long = direction.lower() == "buy"
    if is_long and risk_regime == RiskRegime.RISK_OFF:
        return 0.7, f"long crypto + regime {risk_regime.value}"
    if not is_long and risk_regime == RiskRegime.RISK_ON:
        return 0.8, f"short crypto + regime {risk_regime.value}"
    return 1.0, None


def alignment_for(pair: str, direction: str) -> dict:
    """Retourne `{multiplier, reasons}` pour moduler le risque du setup
    selon le contexte macro courant. Neutre (1.0) si le macro_context
    n'est pas disponible ou est stale."""
    try:
        from backend.services import macro_context_service
    except Exception:
        return {"multiplier": 1.0, "reasons": []}

    snap: MacroContext | None = macro_context_service.get_macro_snapshot()
    if snap is None or not macro_context_service.is_fresh(snap.fetched_at):
        return {"multiplier": 1.0, "reasons": []}

    mults: list[float] = []
    reasons: list[str] = []
    for mult, reason in (
        _dxy_alignment(pair, direction, snap.dxy_direction),
        _index_alignment(pair, direction, snap.vix_level, snap.risk_regime),
        _gold_alignment(pair, direction, snap.us10y_trend),
        _crypto_alignment(pair, direction, snap.risk_regime),
    ):
        if mult != 1.0:
            mults.append(mult)
            if reason:
                reasons.append(reason)

    # Combine : produit des multiplicateurs (mais on garde un plancher
    # raisonnable pour ne pas tomber a 0 sur une paire avec plusieurs
    # contra faibles).
    product = 1.0
    for m in mults:
        product *= m
    product = max(0.3, round(product, 2))
    return {"multiplier": product, "reasons": reasons}
