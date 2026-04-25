"""Tests Phase 4 — module scripts.research.risk_metrics."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


# ─── Imports ────────────────────────────────────────────────────────────────


def test_imports():
    """Le module charge sans erreur."""
    from scripts.research import risk_metrics
    assert hasattr(risk_metrics, "apply_vol_target_sizing")
    assert hasattr(risk_metrics, "equity_curve")
    assert hasattr(risk_metrics, "max_drawdown_pct")
    assert hasattr(risk_metrics, "monthly_returns")
    assert hasattr(risk_metrics, "sharpe_annualized")
    assert hasattr(risk_metrics, "calmar_ratio")


# ─── apply_vol_target_sizing ────────────────────────────────────────────────


def test_vol_target_sizing_basic():
    """Position_eur = risk_eur / risk_pct. PnL = position_eur × pct."""
    from scripts.research.risk_metrics import apply_vol_target_sizing

    trades = [
        {"entry_at": datetime(2026, 1, 1), "risk_pct": 0.01, "pct": 1.5, "is_win": True},
    ]
    sized = apply_vol_target_sizing(trades, capital=10_000, risk_per_trade_pct=0.01)
    assert len(sized) == 1
    s = sized[0]
    # risk_eur = 10000 × 0.01 = 100
    # position_eur = 100 / 0.01 = 10_000
    # pnl_eur = 10000 × (1.5 / 100) = 150
    assert s["risk_eur"] == 100.0
    assert s["position_eur"] == 10_000.0
    assert s["pnl_eur"] == pytest.approx(150.0, rel=0.01)


def test_vol_target_sizing_fallback_risk_pct():
    """Si risk_pct manquant ou invalide, fallback à 1%."""
    from scripts.research.risk_metrics import apply_vol_target_sizing

    trades_no_risk = [
        {"entry_at": datetime(2026, 1, 1), "pct": 1.0, "is_win": True},
    ]
    sized = apply_vol_target_sizing(trades_no_risk, capital=10_000, risk_per_trade_pct=0.01)
    # Avec fallback risk_pct=0.01 : position_eur = 100/0.01 = 10000, pnl = 100
    assert sized[0]["position_eur"] == 10_000.0
    assert sized[0]["pnl_eur"] == pytest.approx(100.0, rel=0.01)


# ─── max_drawdown_pct ────────────────────────────────────────────────────────


def test_max_drawdown_pct_no_drawdown():
    """Equity monotone croissante → maxDD ≈ 0."""
    from scripts.research.risk_metrics import max_drawdown_pct

    curve = [
        (datetime(2026, 1, 1), 10_000),
        (datetime(2026, 1, 2), 10_500),
        (datetime(2026, 1, 3), 11_000),
        (datetime(2026, 1, 4), 12_000),
    ]
    dd_pct, _, _ = max_drawdown_pct(curve)
    assert dd_pct == pytest.approx(0.0)


def test_max_drawdown_pct_simple():
    """Peak 12000 → trough 9000 → maxDD = 25%."""
    from scripts.research.risk_metrics import max_drawdown_pct

    curve = [
        (datetime(2026, 1, 1), 10_000),
        (datetime(2026, 1, 2), 12_000),  # peak
        (datetime(2026, 1, 3), 11_000),
        (datetime(2026, 1, 4), 9_000),   # trough = (12000-9000)/12000 = 25%
        (datetime(2026, 1, 5), 9_500),
    ]
    dd_pct, peak_at, trough_at = max_drawdown_pct(curve)
    assert dd_pct == pytest.approx(25.0, rel=0.01)
    assert peak_at == datetime(2026, 1, 2)
    assert trough_at == datetime(2026, 1, 4)


def test_max_drawdown_pct_empty():
    from scripts.research.risk_metrics import max_drawdown_pct
    dd, _, _ = max_drawdown_pct([])
    assert dd == 0.0


# ─── sharpe_annualized ──────────────────────────────────────────────────────


def test_sharpe_annualized_positive():
    """Returns positifs réguliers → Sharpe > 0."""
    from scripts.research.risk_metrics import sharpe_annualized

    # 12 mois, return constant +1%, std = 0 → division par 0 → 0
    monthly_constant = [(f"2026-{m:02d}", 1.0) for m in range(1, 13)]
    s_constant = sharpe_annualized(monthly_constant)
    assert s_constant == 0.0  # std = 0 → fallback 0

    # Returns variés positifs en moyenne
    monthly_pos = [(f"2026-{m:02d}", r) for m, r in zip(range(1, 13), [2, 3, -1, 4, 1, 0, 2, -2, 3, 1, 2, 3])]
    s_pos = sharpe_annualized(monthly_pos)
    assert s_pos > 0


def test_sharpe_annualized_negative():
    """Returns négatifs → Sharpe < 0."""
    from scripts.research.risk_metrics import sharpe_annualized

    monthly_neg = [(f"2026-{m:02d}", r) for m, r in zip(range(1, 13), [-2, -3, 1, -4, -1, 0, -2, 2, -3, -1, -2, -3])]
    s_neg = sharpe_annualized(monthly_neg)
    assert s_neg < 0


def test_sharpe_annualized_short_sample():
    """< 3 returns → fallback 0."""
    from scripts.research.risk_metrics import sharpe_annualized
    assert sharpe_annualized([("2026-01", 1.0)]) == 0.0
    assert sharpe_annualized([("2026-01", 1.0), ("2026-02", 2.0)]) == 0.0


# ─── calmar_ratio ───────────────────────────────────────────────────────────


def test_calmar_ratio_basic():
    """Calmar = annualized return / |maxDD|."""
    from scripts.research.risk_metrics import calmar_ratio

    # +60% sur 12 mois, maxDD 20% → Calmar = 60 / 20 = 3.0
    c = calmar_ratio(total_return_pct=60.0, n_months=12, max_dd_pct=20.0)
    assert c == pytest.approx(3.0, rel=0.01)

    # +30% sur 6 mois (= 60% annualisé), maxDD 30% → Calmar = 60 / 30 = 2.0
    c = calmar_ratio(total_return_pct=30.0, n_months=6, max_dd_pct=30.0)
    assert c == pytest.approx(2.0, rel=0.01)


def test_calmar_ratio_no_drawdown():
    """maxDD = 0 → Calmar = 0 (évite division par 0)."""
    from scripts.research.risk_metrics import calmar_ratio
    assert calmar_ratio(total_return_pct=50.0, n_months=12, max_dd_pct=0.0) == 0.0


# ─── monthly_returns ────────────────────────────────────────────────────────


def test_monthly_returns_grouping():
    """Trades sur plusieurs mois → returns par mois."""
    from scripts.research.risk_metrics import monthly_returns

    trades = [
        {"entry_at": datetime(2026, 1, 5), "pnl_eur": 100},
        {"entry_at": datetime(2026, 1, 15), "pnl_eur": 50},
        {"entry_at": datetime(2026, 2, 3), "pnl_eur": -75},
        {"entry_at": datetime(2026, 2, 20), "pnl_eur": 200},
    ]
    months = monthly_returns(trades, capital=10_000)
    assert len(months) == 2
    # Janvier : 150 €
    jan = [m for m in months if m[0] == "2026-01"][0]
    assert jan[1] == pytest.approx(1.5)  # 150/10000 * 100 = 1.5%
    # Février : 125 €
    feb = [m for m in months if m[0] == "2026-02"][0]
    assert feb[1] == pytest.approx(1.25)
