"""Module risk_metrics — vol target sizing + Sharpe / Calmar / DD.

Pour passer du PF (rendement brut/risque brut) à des métriques
risk-adjusted comparables aux benchmarks (Sharpe ratio, max drawdown
en %capital, Calmar ratio).

Hypothèse vol target sizing :
- Capital initial fixe (ex: 10 000 €)
- Risque fixe par trade (ex: 1% du capital = 100 €)
- Position size = risk_per_trade_eur / stop_distance_pct
- PnL en € pour chaque trade ramené à un même budget de risque

Si SL = 1% du prix d'entrée → on prend une grosse position pour qu'1 SL
coûte exactement 100 €. Si SL = 5% du prix → on prend une petite position.
Le P&L en % de capital final est donc directement comparable entre trades
de différentes volatilités.

Métriques :
- Equity curve mensuelle
- Sharpe annualisé = mean(monthly_returns) / std(monthly_returns) × sqrt(12)
- Calmar annualisé = annualized_return / |max_drawdown|
- Max drawdown en % du capital
- Total return en % du capital
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from math import sqrt
from statistics import mean, stdev


def apply_vol_target_sizing(
    trades: list[dict],
    capital: float = 10_000.0,
    risk_per_trade_pct: float = 0.01,
) -> list[dict]:
    """Pour chaque trade, calcule la position size et le PnL en € sous
    contrainte risque fixe.

    Suppose que le trade dict contient :
      - risk_pct (distance entry-SL / entry, en fraction)
      - pct (PnL net en %, déjà coût-déduit)
      - entry_at

    Ajoute :
      - position_eur (notional position)
      - pnl_eur (PnL net en €)
      - risk_eur (risque max théorique = capital × risk_per_trade_pct)
    """
    risk_eur = capital * risk_per_trade_pct
    out: list[dict] = []
    for t in trades:
        risk_pct = t.get("risk_pct")
        if risk_pct is None or risk_pct <= 0:
            # fallback : assume 1% stop si non disponible
            risk_pct = 0.01
        # position_eur tel que risk_pct × position_eur = risk_eur
        position_eur = risk_eur / risk_pct
        # pnl_eur = position_eur × (pct / 100) — pct est en %
        pnl_eur = position_eur * (t["pct"] / 100.0)
        enriched = dict(t)
        enriched["position_eur"] = position_eur
        enriched["pnl_eur"] = pnl_eur
        enriched["risk_eur"] = risk_eur
        out.append(enriched)
    return out


def equity_curve(trades: list[dict], capital: float = 10_000.0) -> list[tuple[datetime, float]]:
    """Retourne [(timestamp, equity)] sur les trades sortés par entry_at."""
    sorted_trades = sorted(trades, key=lambda t: t["entry_at"])
    equity = capital
    curve: list[tuple[datetime, float]] = [(sorted_trades[0]["entry_at"], capital)] if sorted_trades else []
    for t in sorted_trades:
        equity += t["pnl_eur"]
        curve.append((t["entry_at"], equity))
    return curve


def max_drawdown_pct(curve: list[tuple[datetime, float]]) -> tuple[float, datetime, datetime]:
    """Max drawdown en % du peak. Retourne (max_dd_pct, peak_at, trough_at)."""
    if not curve:
        return (0.0, datetime.now(), datetime.now())
    peak = curve[0][1]
    peak_at = curve[0][0]
    max_dd = 0.0
    max_peak_at = peak_at
    max_trough_at = peak_at
    for ts, eq in curve:
        if eq > peak:
            peak = eq
            peak_at = ts
        dd = (peak - eq) / peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
            max_peak_at = peak_at
            max_trough_at = ts
    return (max_dd * 100, max_peak_at, max_trough_at)


def monthly_returns(trades: list[dict], capital: float = 10_000.0) -> list[tuple[str, float]]:
    """Returns par mois. Retourne [(month_str 'YYYY-MM', return_pct)].

    Convention : monthly_return_pct = monthly_pnl_eur / capital
    (capital fixe, pas de capitalisation, pour simplicité — Sharpe sera
    calculé sur cette série).
    """
    by_month: dict[str, float] = defaultdict(float)
    for t in trades:
        m = t["entry_at"].strftime("%Y-%m")
        by_month[m] += t["pnl_eur"]
    return [(m, pnl / capital * 100) for m, pnl in sorted(by_month.items())]


def sharpe_annualized(monthly_rets: list[tuple[str, float]]) -> float:
    """Sharpe annualisé depuis la série mensuelle (en %).

    Formule : (mean / std) × sqrt(12). Suppose risk-free = 0 (proxy).
    """
    rets = [r for _, r in monthly_rets]
    if len(rets) < 3:
        return 0.0
    sd = stdev(rets)
    if sd == 0:
        return 0.0
    return (mean(rets) / sd) * sqrt(12)


def calmar_ratio(total_return_pct: float, n_months: int, max_dd_pct: float) -> float:
    """Calmar = annualized return / |max DD|. En % décimaux."""
    if max_dd_pct <= 0 or n_months <= 0:
        return 0.0
    annualized = total_return_pct * (12 / n_months)
    return annualized / max_dd_pct


def print_risk_report(
    label: str,
    trades: list[dict],
    capital: float = 10_000.0,
    risk_per_trade_pct: float = 0.01,
) -> dict:
    """Calcule + imprime un rapport risque complet. Retourne dict des métriques."""
    if not trades:
        print(f"\n=== {label} === (aucun trade)\n")
        return {}

    sized = apply_vol_target_sizing(trades, capital, risk_per_trade_pct)
    curve = equity_curve(sized, capital)
    final_equity = curve[-1][1] if curve else capital
    total_return = (final_equity - capital) / capital * 100

    monthly = monthly_returns(sized, capital)
    sharpe = sharpe_annualized(monthly)

    mdd_pct, peak_at, trough_at = max_drawdown_pct(curve)

    n_months = len(monthly) if monthly else 1
    calmar = calmar_ratio(total_return, n_months, mdd_pct)

    n_pos = sum(1 for m, r in monthly if r > 0)
    n_neg = sum(1 for m, r in monthly if r < 0)
    pct_winning_months = n_pos / max(n_pos + n_neg, 1) * 100

    avg_monthly = mean([r for _, r in monthly]) if monthly else 0
    monthly_std = stdev([r for _, r in monthly]) if len(monthly) >= 2 else 0

    n = len(sized)
    wins = sum(1 for t in sized if t["is_win"])
    wr = wins / n * 100 if n else 0
    avg_trade_eur = mean([t["pnl_eur"] for t in sized]) if sized else 0

    print(f"\n=== {label} ===")
    print(f"  Trades                : {n}")
    print(f"  Window                : {sized[0]['entry_at'].date()} → {sized[-1]['entry_at'].date()}")
    print(f"  Months                : {n_months} ({n_pos} positifs / {n_neg} négatifs = {pct_winning_months:.0f}% winning months)")
    print(f"  Capital initial       : {capital:>10,.0f} €")
    print(f"  Capital final         : {final_equity:>10,.0f} €")
    print(f"  Total return          : {total_return:>+10.1f} %")
    print(f"  Annualized return     : {total_return * 12 / n_months:>+10.1f} %")
    print(f"  Win rate (trades)     : {wr:>10.1f} %")
    print(f"  Avg trade PnL         : {avg_trade_eur:>+10.1f} €")
    print(f"  Avg monthly return    : {avg_monthly:>+10.2f} %")
    print(f"  Monthly std           : {monthly_std:>10.2f} %")
    print(f"  ► Sharpe annualisé    : {sharpe:>10.2f}")
    print(f"  ► Max drawdown        : {mdd_pct:>10.1f} %")
    print(f"  ► Calmar ratio        : {calmar:>10.2f}")
    print(f"  Peak → trough         : {peak_at.date()} → {trough_at.date()}")

    return {
        "n_trades": n, "wr": wr, "total_return_pct": total_return,
        "annualized_return_pct": total_return * 12 / n_months,
        "sharpe": sharpe, "max_dd_pct": mdd_pct, "calmar": calmar,
        "winning_months_pct": pct_winning_months, "n_months": n_months,
    }
