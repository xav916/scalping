"""Tests du filtre cross-asset macro_alignment."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

from backend.models.macro_schemas import (
    MacroContext,
    MacroDirection,
    RiskRegime,
    VixLevel,
)
from backend.services import macro_alignment


def _snapshot(**overrides) -> MacroContext:
    defaults = dict(
        fetched_at=datetime.now(timezone.utc),
        dxy_direction=MacroDirection.NEUTRAL,
        spx_direction=MacroDirection.NEUTRAL,
        vix_level=VixLevel.NORMAL,
        vix_value=16.0,
        us10y_trend=MacroDirection.NEUTRAL,
        de10y_trend=MacroDirection.NEUTRAL,
        us_de_spread_trend="flat",
        oil_direction=MacroDirection.NEUTRAL,
        nikkei_direction=MacroDirection.NEUTRAL,
        gold_direction=MacroDirection.NEUTRAL,
        risk_regime=RiskRegime.NEUTRAL,
    )
    defaults.update(overrides)
    return MacroContext(**defaults)


def _patch_snap(snap):
    return patch.multiple(
        "backend.services.macro_context_service",
        get_macro_snapshot=lambda: snap,
        is_fresh=lambda _: True,
    )


def test_no_snapshot_returns_neutral():
    with patch(
        "backend.services.macro_context_service.get_macro_snapshot",
        return_value=None,
    ):
        result = macro_alignment.alignment_for("EUR/USD", "buy")
    assert result["multiplier"] == 1.0
    assert result["reasons"] == []


def test_dxy_strong_up_boosts_usd_longs():
    """sell EUR/USD = long USD ; DXY STRONG_UP → alignement 1.1x."""
    with _patch_snap(_snapshot(dxy_direction=MacroDirection.STRONG_UP)):
        result = macro_alignment.alignment_for("EUR/USD", "sell")
    assert result["multiplier"] == 1.1
    assert any("DXY strong_up" in r for r in result["reasons"])


def test_dxy_strong_up_penalizes_usd_shorts():
    """buy EUR/USD = short USD ; DXY STRONG_UP → contra 0.7x."""
    with _patch_snap(_snapshot(dxy_direction=MacroDirection.STRONG_UP)):
        result = macro_alignment.alignment_for("EUR/USD", "buy")
    assert result["multiplier"] == 0.7
    assert any("DXY strong_up" in r for r in result["reasons"])


def test_dxy_direction_inverted_on_usdxxx_pairs():
    """USD/JPY : buy = long USD. DXY DOWN → contra."""
    with _patch_snap(_snapshot(dxy_direction=MacroDirection.DOWN)):
        result = macro_alignment.alignment_for("USD/JPY", "buy")
    assert result["multiplier"] == 0.7


def test_long_index_in_high_vix_is_heavily_penalized():
    """Long SPX + VIX HIGH → 0.5x."""
    with _patch_snap(
        _snapshot(vix_level=VixLevel.HIGH, risk_regime=RiskRegime.RISK_OFF)
    ):
        result = macro_alignment.alignment_for("SPX", "buy")
    assert result["multiplier"] == 0.5
    assert any("long index" in r for r in result["reasons"])


def test_gold_long_penalized_when_yields_up():
    with _patch_snap(_snapshot(us10y_trend=MacroDirection.STRONG_UP)):
        result = macro_alignment.alignment_for("XAU/USD", "buy")
    assert result["multiplier"] == 0.7


def test_gold_short_boosted_when_yields_up():
    with _patch_snap(_snapshot(us10y_trend=MacroDirection.UP)):
        result = macro_alignment.alignment_for("XAU/USD", "sell")
    assert result["multiplier"] == 1.1


def test_crypto_long_penalized_in_risk_off():
    with _patch_snap(_snapshot(risk_regime=RiskRegime.RISK_OFF)):
        result = macro_alignment.alignment_for("BTC/USD", "buy")
    assert result["multiplier"] == 0.7


def test_multiplicative_combination_floors_at_point_3():
    """Un actif doublement contra (ex: long BTC en risk_off + ?) doit
    respecter le plancher 0.3."""
    # Empile deux contras (forex + gold) pour tester le floor.
    # XAU/USD buy + DXY UP (pair USD short...) + US10Y UP (gold long penalite)
    with _patch_snap(
        _snapshot(
            dxy_direction=MacroDirection.STRONG_UP,
            us10y_trend=MacroDirection.STRONG_UP,
        )
    ):
        result = macro_alignment.alignment_for("XAU/USD", "buy")
    # 0.7 (DXY contra USD long proxy) * 0.7 (gold long vs yields) = 0.49
    assert result["multiplier"] >= 0.3
    assert result["multiplier"] == 0.49


def test_sizing_compute_uses_macro_alignment(tmp_path, monkeypatch):
    """sizing.compute_risk_money doit ajouter macro_mult au pipeline."""
    from backend.services import session_service, sizing, trade_log_service
    from types import SimpleNamespace

    monkeypatch.setattr(trade_log_service, "_DB_PATH", tmp_path / "t.db")
    trade_log_service._init_schema()

    setup = SimpleNamespace(
        pair="XAU/USD",
        direction=SimpleNamespace(value="buy"),
        confidence_score=80,
    )
    with _patch_snap(_snapshot(us10y_trend=MacroDirection.STRONG_UP)), patch.object(
        session_service, "activity_multiplier", return_value=1.0
    ), patch.object(session_service, "label", return_value="london"):
        result = sizing.compute_risk_money(setup)

    assert result["macro_mult"] == 0.7
    assert any("gold" in r for r in result["macro_reasons"])
    # final_mult intègre le macro
    assert result["final_mult"] < result["conf_mult"]
