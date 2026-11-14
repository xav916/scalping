"""Tests du simulateur stochastique de cours."""
from __future__ import annotations

import pytest

from backend.services import trader_price_simulator as sim


# ══════════════════════════════════════════════════════════════════════
# Validation inputs — fail-open
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_prix_zero_retourne_neutral():
    res = await sim.simulate_future_paths(
        pair="X/Y", current_price=0.0, sl=1.0, tp=2.0,
        direction="buy", horizon_minutes=60, n_paths=10,
    )
    assert res["p_tp_first"] == 0.5
    assert res["p_sl_first"] == 0.5
    assert "error" in res


@pytest.mark.asyncio
async def test_direction_invalide_retourne_neutral():
    res = await sim.simulate_future_paths(
        pair="X/Y", current_price=100.0, sl=95.0, tp=105.0,
        direction="invalid", horizon_minutes=60, n_paths=10,
    )
    assert res["p_tp_first"] == 0.5
    assert "error" in res


@pytest.mark.asyncio
async def test_horizon_zero_retourne_neutral():
    res = await sim.simulate_future_paths(
        pair="X/Y", current_price=100.0, sl=95.0, tp=105.0,
        direction="buy", horizon_minutes=0, n_paths=10,
    )
    assert res["p_tp_first"] == 0.5
    assert "error" in res


# ══════════════════════════════════════════════════════════════════════
# Logique de path simulation — testée isolément sans fetch_candles
# ══════════════════════════════════════════════════════════════════════


def test_gbm_path_hit_tp_sur_drift_positif_fort():
    """Avec mu positif grand, le prix doit souvent monter et toucher TP d'un buy."""
    import random
    rng = random.Random(42)
    oc, term, up, dn = sim._simulate_one_path_gbm(
        current=100.0, mu=0.01, sigma=0.001,  # drift fort, peu de vol
        sl=90.0, tp=105.0, direction="buy", n_steps=1000, rng=rng,
    )
    assert oc == "tp"
    assert term >= 105.0


def test_gbm_path_hit_sl_sur_drift_negatif_fort():
    """Avec mu négatif grand, le prix descend et touche SL d'un buy."""
    import random
    rng = random.Random(42)
    oc, term, up, dn = sim._simulate_one_path_gbm(
        current=100.0, mu=-0.01, sigma=0.001,
        sl=90.0, tp=105.0, direction="buy", n_steps=1000, rng=rng,
    )
    assert oc == "sl"


def test_bootstrap_path_sans_historique_retourne_neither():
    import random
    rng = random.Random(42)
    oc, term, up, dn = sim._simulate_one_path_bootstrap(
        current=100.0, returns_pool=[],
        sl=90.0, tp=105.0, direction="buy", n_steps=100, rng=rng,
    )
    assert oc == "neither"
    assert term == 100.0


def test_bootstrap_path_avec_returns_mixtes():
    """Pool avec des rendements mixtes donne un résultat plausible."""
    import random
    import math
    rng = random.Random(42)
    # Pool : 60% +0.005, 40% -0.005 (biais haussier léger)
    pool = [math.log(1.005)] * 60 + [math.log(0.995)] * 40
    oc, term, up, dn = sim._simulate_one_path_bootstrap(
        current=100.0, returns_pool=pool,
        sl=95.0, tp=105.0, direction="buy", n_steps=500, rng=rng,
    )
    # Avec 500 steps et drift + léger, devrait terminer par un outcome
    assert oc in ("tp", "sl", "neither")
    assert dn <= term <= up or math.isclose(dn, up)


# ══════════════════════════════════════════════════════════════════════
# Helpers math
# ══════════════════════════════════════════════════════════════════════


def test_log_returns():
    out = sim._log_returns([100.0, 101.0, 102.0])
    import math
    assert len(out) == 2
    assert out[0] == pytest.approx(math.log(1.01))
    assert out[1] == pytest.approx(math.log(102 / 101))


def test_log_returns_skip_zeros():
    out = sim._log_returns([100.0, 0.0, 102.0])
    # 100→0 skippé (p1=0), 0→102 skippé (p0=0)
    assert out == []


def test_mean_std():
    m, s = sim._mean_std([1.0, 2.0, 3.0, 4.0, 5.0])
    assert m == pytest.approx(3.0)
    assert s > 1.5 and s < 1.7  # écart-type ≈ 1.58


def test_mean_std_empty():
    m, s = sim._mean_std([])
    assert m == 0.0
    assert s == 0.0


# ══════════════════════════════════════════════════════════════════════
# Reproductibilité via seed
# ══════════════════════════════════════════════════════════════════════


def test_seed_meme_reproductibilite():
    """Deux simulations GBM avec même seed donnent le même path."""
    import random
    rng1 = random.Random(123)
    rng2 = random.Random(123)
    oc1, term1, _, _ = sim._simulate_one_path_gbm(
        100.0, 0.0, 0.01, 95.0, 105.0, "buy", 100, rng1,
    )
    oc2, term2, _, _ = sim._simulate_one_path_gbm(
        100.0, 0.0, 0.01, 95.0, 105.0, "buy", 100, rng2,
    )
    assert oc1 == oc2
    assert term1 == term2
