"""Pure macro scoring - no I/O.

Given a trade setup (pair, direction) and a MacroContext snapshot, returns:
- a multiplier to apply to the base confidence score (0.75 <= mult <= 1.2)
- a boolean veto flag for extreme conditions
- a list of structured primaries (dicts) describing per-indicator alignment

No state, no side effects. Fully table-driven via apply().
"""
from __future__ import annotations

from config.settings import MACRO_DXY_VETO_SIGMA
from backend.models.macro_schemas import (
    MacroContext,
    MacroDirection,
    RiskRegime,
    VixLevel,
)


_USD_MAJOR = {"EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF"}
_USD_COMMODITY = {"USD/CAD"}
_COMMODITY_CURRENCY = {"AUD/USD", "NZD/USD"}
_JPY_PAIR = {"USD/JPY", "EUR/JPY", "GBP/JPY"}
_EUR_PAIR = {"EUR/USD", "EUR/GBP", "EUR/JPY", "EUR/CHF"}
_CHF_PAIR = {"USD/CHF", "EUR/CHF"}
_XAU = {"XAU/USD"}
_XAG = {"XAG/USD"}

# New multi-asset classes
_CRYPTO_PREFIXES = ("BTC", "ETH", "LTC", "XRP", "SOL", "ADA", "DOGE")
_ENERGY_PREFIXES = ("WTI", "BRENT", "XTI", "XBR", "NGAS", "NATGAS")
_EQUITY_INDICES = {
    "SPX", "NDX", "DJI", "RUT",
    "DAX", "N225", "NIKKEI", "FTSE", "CAC40",
    "UK100", "US30", "US500", "NAS100", "DE40", "EU50", "JP225",
}


def _is_crypto(pair_u: str) -> bool:
    return any(pair_u.startswith(pfx) for pfx in _CRYPTO_PREFIXES)


def _is_energy(pair_u: str) -> bool:
    return any(pair_u.startswith(pfx) for pfx in _ENERGY_PREFIXES)


def _dir_sign(d: MacroDirection) -> int:
    if d in (MacroDirection.STRONG_UP, MacroDirection.UP):
        return 1
    if d in (MacroDirection.STRONG_DOWN, MacroDirection.DOWN):
        return -1
    return 0


def _setup_sign(direction: str) -> int:
    return 1 if direction.lower() == "buy" else -1


def _pair_is_usd_long_on_buy(pair: str) -> int:
    base, _, quote = pair.partition("/")
    if base == "USD":
        return 1
    if quote == "USD":
        return -1
    return 0


def _primaries_for(pair: str, ctx: MacroContext, setup_sign: int) -> list[tuple[str, int, str]]:
    """Return list of (indicator_name, alignment_sign, reason) tuples.

    alignment_sign = +1 if macro supports setup direction, -1 if against, 0 if neutral.
    Zero-alignment primaries are filtered out of the output list.
    """
    result: list[tuple[str, int, str]] = []
    used: set[str] = set()
    pair_u = pair.upper()

    # --- Forex-family mappings (unchanged) ----------------------
    if pair_u in _USD_MAJOR or pair_u in _USD_COMMODITY or pair_u in _COMMODITY_CURRENCY:
        if "dxy" not in used:
            usd_long_on_buy = _pair_is_usd_long_on_buy(pair_u)
            setup_usd_sign = setup_sign * usd_long_on_buy
            align = setup_usd_sign * _dir_sign(ctx.dxy_direction)
            if align != 0:
                reason = f"DXY {ctx.dxy_direction.value}"
                result.append(("dxy", align, reason))
            used.add("dxy")

    if pair_u in _USD_COMMODITY:
        if "oil" not in used:
            align = -setup_sign * _dir_sign(ctx.oil_direction)
            if align != 0:
                result.append(("oil", align, f"Oil {ctx.oil_direction.value}"))
            used.add("oil")

    if pair_u in _COMMODITY_CURRENCY:
        if "spx" not in used:
            align = setup_sign * _dir_sign(ctx.spx_direction)
            if align != 0:
                result.append(("spx", align, f"SPX {ctx.spx_direction.value}"))
            used.add("spx")
        if "gold" not in used:
            align = setup_sign * _dir_sign(ctx.gold_direction)
            if align != 0:
                result.append(("gold", align, f"Gold {ctx.gold_direction.value}"))
            used.add("gold")

    if pair_u in _JPY_PAIR:
        if "vix" not in used:
            vix_sign = 1 if ctx.vix_level in (VixLevel.ELEVATED, VixLevel.HIGH) else (
                -1 if ctx.vix_level == VixLevel.LOW else 0
            )
            align = -setup_sign * vix_sign
            if align != 0:
                result.append(("vix", align, f"VIX {ctx.vix_level.value}"))
            used.add("vix")
        if "nikkei" not in used:
            align = setup_sign * _dir_sign(ctx.nikkei_direction)
            if align != 0:
                result.append(("nikkei", align, f"Nikkei {ctx.nikkei_direction.value}"))
            used.add("nikkei")

    if pair_u in _EUR_PAIR:
        if "us_de_spread" not in used:
            base, _, quote = pair_u.partition("/")
            eur_long_on_buy = 1 if base == "EUR" else (-1 if quote == "EUR" else 0)
            spread_sign = {"narrowing": 1, "flat": 0, "widening": -1}[ctx.us_de_spread_trend]
            align = setup_sign * eur_long_on_buy * spread_sign
            if align != 0:
                result.append(("us_de_spread", align, f"Spread US-DE {ctx.us_de_spread_trend}"))
            used.add("us_de_spread")

    if pair_u in _CHF_PAIR and "vix" not in used:
        base, _, quote = pair_u.partition("/")
        chf_long_on_buy = 1 if base == "CHF" else (-1 if quote == "CHF" else 0)
        vix_sign = 1 if ctx.vix_level in (VixLevel.ELEVATED, VixLevel.HIGH) else (
            -1 if ctx.vix_level == VixLevel.LOW else 0
        )
        align = setup_sign * chf_long_on_buy * vix_sign
        if align != 0:
            result.append(("vix", align, f"VIX {ctx.vix_level.value} (CHF refuge)"))
        used.add("vix")

    if pair_u in _XAU:
        if "vix" not in used:
            vix_sign = 1 if ctx.vix_level in (VixLevel.ELEVATED, VixLevel.HIGH) else (
                -1 if ctx.vix_level == VixLevel.LOW else 0
            )
            align = setup_sign * vix_sign
            if align != 0:
                result.append(("vix", align, f"VIX {ctx.vix_level.value} (refuge)"))
            used.add("vix")
        if "dxy" not in used:
            align = -setup_sign * _dir_sign(ctx.dxy_direction)
            if align != 0:
                result.append(("dxy", align, f"DXY {ctx.dxy_direction.value}"))
            used.add("dxy")
        if "us10y" not in used:
            align = -setup_sign * _dir_sign(ctx.us10y_trend)
            if align != 0:
                result.append(("us10y", align, f"US10Y {ctx.us10y_trend.value}"))
            used.add("us10y")

    # --- New: XAG/USD (silver) -- treat like gold refuge --------
    if pair_u in _XAG:
        if "vix" not in used:
            vix_sign = 1 if ctx.vix_level in (VixLevel.ELEVATED, VixLevel.HIGH) else (
                -1 if ctx.vix_level == VixLevel.LOW else 0
            )
            align = setup_sign * vix_sign
            if align != 0:
                result.append(("vix", align, f"VIX {ctx.vix_level.value} (silver refuge)"))
            used.add("vix")
        if "dxy" not in used:
            align = -setup_sign * _dir_sign(ctx.dxy_direction)
            if align != 0:
                result.append(("dxy", align, f"DXY {ctx.dxy_direction.value}"))
            used.add("dxy")

    # --- New: Crypto (BTC, ETH, ...) ----------------------------
    # Buy crypto favored in risk-on, penalized in risk-off.
    if _is_crypto(pair_u):
        if "spx" not in used:
            # SPX up = risk-on = crypto up. Aligned with buy.
            align = setup_sign * _dir_sign(ctx.spx_direction)
            if align != 0:
                result.append(("spx", align, f"SPX {ctx.spx_direction.value} (crypto risk-on)"))
            used.add("spx")
        if "vix" not in used:
            # VIX up = risk-off = crypto down. Inversely aligned.
            vix_sign = 1 if ctx.vix_level in (VixLevel.ELEVATED, VixLevel.HIGH) else (
                -1 if ctx.vix_level == VixLevel.LOW else 0
            )
            align = -setup_sign * vix_sign
            if align != 0:
                result.append(("vix", align, f"VIX {ctx.vix_level.value} (crypto)"))
            used.add("vix")
        if "dxy" not in used:
            # Strong DXY hurts crypto. Inversely aligned.
            align = -setup_sign * _dir_sign(ctx.dxy_direction)
            if align != 0:
                result.append(("dxy", align, f"DXY {ctx.dxy_direction.value} (crypto)"))
            used.add("dxy")

    # --- New: Equity indices (SPX, NDX, ...) --------------------
    # Buy equity favored in low VIX + rising SPX (SPX is partly self-referential,
    # but for non-SPX indices it still signals global risk).
    if pair_u in _EQUITY_INDICES:
        if "vix" not in used:
            vix_sign = 1 if ctx.vix_level in (VixLevel.ELEVATED, VixLevel.HIGH) else (
                -1 if ctx.vix_level == VixLevel.LOW else 0
            )
            align = -setup_sign * vix_sign
            if align != 0:
                result.append(("vix", align, f"VIX {ctx.vix_level.value} (equity)"))
            used.add("vix")
        # For non-SPX indices, SPX direction is a useful tell.
        if pair_u != "SPX" and "spx" not in used:
            align = setup_sign * _dir_sign(ctx.spx_direction)
            if align != 0:
                result.append(("spx", align, f"SPX {ctx.spx_direction.value} (equity benchmark)"))
            used.add("spx")

    # --- New: Energy (WTI, Brent, ...) --------------------------
    # Oil priced in USD: strong DXY hurts. Risk-on boosts demand.
    if _is_energy(pair_u):
        if "dxy" not in used:
            align = -setup_sign * _dir_sign(ctx.dxy_direction)
            if align != 0:
                result.append(("dxy", align, f"DXY {ctx.dxy_direction.value} (oil priced USD)"))
            used.add("dxy")
        if "spx" not in used:
            # SPX up = risk-on = demand for oil (global growth). Aligned with buy.
            align = setup_sign * _dir_sign(ctx.spx_direction)
            if align != 0:
                result.append(("spx", align, f"SPX {ctx.spx_direction.value} (risk-on demand)"))
            used.add("spx")

    return result


def _multiplier_from_alignment(avg: float) -> float:
    if avg >= 0.6:
        return 1.2
    if avg >= 0.2:
        return 1.1
    if avg > -0.2:
        return 1.0
    if avg > -0.6:
        return 0.9
    return 0.75


def _check_vetoes(pair: str, direction: str, ctx: MacroContext) -> list[str]:
    reasons: list[str] = []
    setup_sign = _setup_sign(direction)
    pair_u = pair.upper()

    if ctx.vix_value > 30.0 and ctx.risk_regime == RiskRegime.RISK_OFF:
        if pair_u in _COMMODITY_CURRENCY and setup_sign == 1:
            reasons.append(f"VIX={ctx.vix_value:.1f}>30 and risk_off, against commodity currency buy")
        elif pair_u in _JPY_PAIR and setup_sign == 1 and pair_u.startswith(("USD", "EUR", "GBP")):
            reasons.append(f"VIX={ctx.vix_value:.1f}>30 and risk_off, against XXX/JPY buy")

    if ctx.dxy_intraday_sigma >= MACRO_DXY_VETO_SIGMA:
        usd_long_on_buy = _pair_is_usd_long_on_buy(pair_u)
        if usd_long_on_buy != 0:
            setup_usd_sign = setup_sign * usd_long_on_buy
            dxy_sign = _dir_sign(ctx.dxy_direction)
            if setup_usd_sign * dxy_sign < 0:
                reasons.append(
                    f"DXY intraday moved {ctx.dxy_intraday_sigma:.1f}sigma {ctx.dxy_direction.value}, "
                    f"setup against"
                )

    return reasons


def apply(pair: str, direction: str, ctx: MacroContext) -> tuple[float, bool, list[dict]]:
    """Return (multiplier, veto, primaries) where `primaries` is a list of
    dicts: {"indicator": str, "alignment": int (-1|0|1), "reason": str, "is_veto": bool}.

    For backward compatibility, a veto primary is appended when a veto triggers."""
    setup_sign = _setup_sign(direction)
    primaries_raw = _primaries_for(pair, ctx, setup_sign)

    if not primaries_raw:
        veto_reasons = _check_vetoes(pair, direction, ctx)
        veto = len(veto_reasons) > 0
        primaries: list[dict] = []
        if veto:
            for vr in veto_reasons:
                primaries.append({"indicator": "veto", "alignment": -1, "reason": vr, "is_veto": True})
        return 1.0, veto, primaries

    primaries = [
        {"indicator": ind, "alignment": align, "reason": reason, "is_veto": False}
        for ind, align, reason in primaries_raw
    ]

    # Same averaging logic as before — excluding zero-alignment primaries from denominator
    non_zero = [p for p in primaries if p["alignment"] != 0]
    if non_zero:
        avg = sum(p["alignment"] for p in non_zero) / len(non_zero)
        multiplier = _multiplier_from_alignment(avg)
    else:
        multiplier = 1.0

    # Drop zero-alignment primaries from the output to match previous UI/reason semantics
    primaries = non_zero

    veto_reasons = _check_vetoes(pair, direction, ctx)
    veto = len(veto_reasons) > 0
    if veto:
        for vr in veto_reasons:
            primaries.append({"indicator": "veto", "alignment": -1, "reason": vr, "is_veto": True})

    return multiplier, veto, primaries
