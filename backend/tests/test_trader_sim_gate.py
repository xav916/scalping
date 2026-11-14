"""Tests de la gate Monte Carlo (trader_sim_gate.py)."""
from __future__ import annotations

import pytest

from backend.services import trader_sim_gate as sg


PREFIX = "TEST"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(f"{PREFIX}_SIM_MIN_P_TP", raising=False)


# ══════════════════════════════════════════════════════════════════════
# Gate désactivée par défaut
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_gate_desactivee_par_defaut():
    """Pas d'env var → gate désactivée → toujours True."""
    ok, p_tp, reason = await sg.passes_sim_gate(
        prefix=PREFIX, pair="X/Y", current_price=100.0,
        sl=95.0, tp=105.0, direction="buy",
    )
    assert ok is True
    assert p_tp is None
    assert reason == "sim_gate_disabled"


@pytest.mark.asyncio
async def test_gate_desactivee_si_zero(monkeypatch):
    monkeypatch.setenv(f"{PREFIX}_SIM_MIN_P_TP", "0")
    ok, p_tp, reason = await sg.passes_sim_gate(
        prefix=PREFIX, pair="X/Y", current_price=100.0,
        sl=95.0, tp=105.0, direction="buy",
    )
    assert ok is True
    assert reason == "sim_gate_disabled"


# ══════════════════════════════════════════════════════════════════════
# Gate active — mocke le simulateur
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_gate_rejette_si_p_tp_inferieur_seuil(monkeypatch):
    monkeypatch.setenv(f"{PREFIX}_SIM_MIN_P_TP", "0.55")

    # Mock le simulateur pour retourner p_tp_first=0.30
    async def _fake_sim(**kwargs):
        return {"p_tp_first": 0.30, "p_sl_first": 0.60, "p_neither": 0.10}
    from backend.services import trader_price_simulator
    monkeypatch.setattr(
        trader_price_simulator, "simulate_future_paths", _fake_sim,
    )

    ok, p_tp, reason = await sg.passes_sim_gate(
        prefix=PREFIX, pair="X/Y", current_price=100.0,
        sl=95.0, tp=105.0, direction="buy",
    )
    assert ok is False
    assert p_tp == 0.30
    assert "sim_rejected" in reason


@pytest.mark.asyncio
async def test_gate_accepte_si_p_tp_superieur_seuil(monkeypatch):
    monkeypatch.setenv(f"{PREFIX}_SIM_MIN_P_TP", "0.55")

    async def _fake_sim(**kwargs):
        return {"p_tp_first": 0.70, "p_sl_first": 0.20, "p_neither": 0.10}
    from backend.services import trader_price_simulator
    monkeypatch.setattr(
        trader_price_simulator, "simulate_future_paths", _fake_sim,
    )

    ok, p_tp, reason = await sg.passes_sim_gate(
        prefix=PREFIX, pair="X/Y", current_price=100.0,
        sl=95.0, tp=105.0, direction="buy",
    )
    assert ok is True
    assert p_tp == 0.70
    assert "sim_pass" in reason


@pytest.mark.asyncio
async def test_gate_accepte_exactement_au_seuil(monkeypatch):
    """Égalité exacte = ne rejette pas (on veut strict inférieur pour rejeter)."""
    monkeypatch.setenv(f"{PREFIX}_SIM_MIN_P_TP", "0.55")

    async def _fake_sim(**kwargs):
        return {"p_tp_first": 0.55, "p_sl_first": 0.30, "p_neither": 0.15}
    from backend.services import trader_price_simulator
    monkeypatch.setattr(
        trader_price_simulator, "simulate_future_paths", _fake_sim,
    )

    ok, p_tp, _ = await sg.passes_sim_gate(
        prefix=PREFIX, pair="X/Y", current_price=100.0,
        sl=95.0, tp=105.0, direction="buy",
    )
    assert ok is True
    assert p_tp == 0.55


# ══════════════════════════════════════════════════════════════════════
# Fail-open sur exception
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_gate_fail_open_sur_exception_simulateur(monkeypatch):
    monkeypatch.setenv(f"{PREFIX}_SIM_MIN_P_TP", "0.55")

    async def _crashing_sim(**kwargs):
        raise RuntimeError("simulateur mort")
    from backend.services import trader_price_simulator
    monkeypatch.setattr(
        trader_price_simulator, "simulate_future_paths", _crashing_sim,
    )

    ok, p_tp, reason = await sg.passes_sim_gate(
        prefix=PREFIX, pair="X/Y", current_price=100.0,
        sl=95.0, tp=105.0, direction="buy",
    )
    # Fail-open : on laisse passer
    assert ok is True
    assert p_tp is None
    assert "sim_error" in reason


# ══════════════════════════════════════════════════════════════════════
# Seuil conservateur contre fallback neutre
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_seuil_sup_05_rejette_fallback_neutre(monkeypatch):
    """Si seuil > 0.5 et simulateur retourne fallback neutre 0.5, on rejette."""
    monkeypatch.setenv(f"{PREFIX}_SIM_MIN_P_TP", "0.55")

    async def _neutral_fallback(**kwargs):
        # Shape du fallback neutre de simulate_future_paths
        return {
            "p_tp_first": 0.5, "p_sl_first": 0.5, "p_neither": 0.0,
            "error": "historique insuffisant",
        }
    from backend.services import trader_price_simulator
    monkeypatch.setattr(
        trader_price_simulator, "simulate_future_paths", _neutral_fallback,
    )

    ok, p_tp, reason = await sg.passes_sim_gate(
        prefix=PREFIX, pair="X/Y", current_price=100.0,
        sl=95.0, tp=105.0, direction="buy",
    )
    # Seuil 0.55 > 0.5 → rejet conservateur
    assert ok is False
    assert p_tp == 0.5
