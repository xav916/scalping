"""Pure macro scoring - no I/O.

Given a trade setup (pair, direction) and a MacroContext snapshot, returns:
- a multiplier to apply to the base confidence score (0.75 <= mult <= 1.2)
- a boolean veto flag for extreme conditions
- a list of human-readable reasons (for logs and UI badges)

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
    result: list[tuple[str, int, str]] = []
    used: set[str] = set()

    pair_u = pair.upper()

    if pair_u in _USD_MAJOR or pair_u in _USD_COMMODITY or pair_u in _COMMODITY_CURRENCY:
        if "dxy" not in used:
            usd_long_on_buy = _pair_is_usd_long_on_buy(pair_u)
            setup_usd_sign = setup_sign * usd_long_on_buy
            align = setup_usd_sign * _dir_sign(ctx.dxy_direction)
            reason = f"DXY {ctx.dxy_direction.value}"
            result.append(("dxy", align, reason))
            used.add("dxy")

    if pair_u in _USD_COMMODITY:
        if "oil" not in used:
            align = -setup_sign * _dir_sign(ctx.oil_direction)
            reason = f"Oil {ctx.oil_direction.value}"
            result.append(("oil", align, reason))
            used.add("oil")

    if pair_u in _COMMODITY_CURRENCY:
        if "spx" not in used:
            align = setup_sign * _dir_sign(ctx.spx_direction)
            reason = f"SPX {ctx.spx_direction.value}"
            result.append(("spx", align, reason))
            used.add("spx")
        if "gold" not in used:
            align = setup_sign * _dir_sign(ctx.gold_direction)
            reason = f"Gold {ctx.gold_direction.value}"
            result.append(("gold", align, reason))
            used.add("gold")

    if pair_u in _JPY_PAIR:
        if "vix" not in used:
            vix_sign = 1 if ctx.vix_level in (VixLevel.ELEVATED, VixLevel.HIGH) else (
                -1 if ctx.vix_level == VixLevel.LOW else 0
            )
            align = -setup_sign * vix_sign
            reason = f"VIX {ctx.vix_level.value}"
            result.append(("vix", align, reason))
            used.add("vix")
        if "nikkei" not in used:
            align = setup_sign * _dir_sign(ctx.nikkei_direction)
            reason = f"Nikkei {ctx.nikkei_direction.value}"
            result.append(("nikkei", align, reason))
            used.add("nikkei")

    if pair_u in _EUR_PAIR:
        if "us_de_spread" not in used:
            base, _, quote = pair_u.partition("/")
            eur_long_on_buy = 1 if base == "EUR" else (-1 if quote == "EUR" else 0)
            spread_sign = {"narrowing": 1, "flat": 0, "widening": -1}[ctx.us_de_spread_trend]
            align = setup_sign * eur_long_on_buy * spread_sign
            reason = f"Spread US-DE {ctx.us_de_spread_trend}"
            result.append(("us_de_spread", align, reason))
            used.add("us_de_spread")

    if pair_u in _CHF_PAIR and "vix" not in used:
        base, _, quote = pair_u.partition("/")
        chf_long_on_buy = 1 if base == "CHF" else (-1 if quote == "CHF" else 0)
        vix_sign = 1 if ctx.vix_level in (VixLevel.ELEVATED, VixLevel.HIGH) else (
            -1 if ctx.vix_level == VixLevel.LOW else 0
        )
        align = setup_sign * chf_long_on_buy * vix_sign
        reason = f"VIX {ctx.vix_level.value} (CHF refuge)"
        result.append(("vix", align, reason))
        used.add("vix")

    if pair_u in _XAU:
        if "vix" not in used:
            vix_sign = 1 if ctx.vix_level in (VixLevel.ELEVATED, VixLevel.HIGH) else (
                -1 if ctx.vix_level == VixLevel.LOW else 0
            )
            align = setup_sign * vix_sign
            reason = f"VIX {ctx.vix_level.value} (refuge)"
            result.append(("vix", align, reason))
            used.add("vix")
        if "dxy" not in used:
            align = -setup_sign * _dir_sign(ctx.dxy_direction)
            reason = f"DXY {ctx.dxy_direction.value}"
            result.append(("dxy", align, reason))
            used.add("dxy")
        if "us10y" not in used:
            align = -setup_sign * _dir_sign(ctx.us10y_trend)
            reason = f"US10Y {ctx.us10y_trend.value}"
            result.append(("us10y", align, reason))
            used.add("us10y")

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


def apply(pair: str, direction: str, ctx: MacroContext) -> tuple[float, bool, list[str]]:
    setup_sign = _setup_sign(direction)
    primaries = _primaries_for(pair, ctx, setup_sign)

    # Keep only primaries that actually contributed a signal (non-zero alignment)
    active = [(name, align, reason) for name, align, reason in primaries if align != 0]
    reasons = [r for _, _, r in active]

    if not active:
        multiplier = 1.0
    else:
        avg = sum(align for _, align, _ in active) / len(active)
        multiplier = _multiplier_from_alignment(avg)

    veto_reasons = _check_vetoes(pair, direction, ctx)
    veto = len(veto_reasons) > 0
    if veto:
        reasons.extend(veto_reasons)

    return multiplier, veto, reasons
