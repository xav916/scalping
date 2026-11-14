"""Simulateur stochastique de cours — N chemins Monte Carlo.

## Pourquoi

Les 14 skills ``trader-*`` existantes couvrent analyse passée, détection
présente, exécution et gestion portefeuille, mais AUCUNE ne génère des
estimations probabilistes du cours FUTUR. Toutes les stratégies de
trading décident "TAKE" sur base de signaux déterministes (RSI, ATR,
pattern) sans quantifier la probabilité que le TP soit touché avant le
SL dans une distribution plausible de trajectoires de prix.

Ce module comble ce trou avec une simulation Monte Carlo configurable :
GBM (Geometric Brownian Motion) ou bootstrap des rendements historiques.

## Usage

```python
from backend.services import trader_price_simulator as sim

result = await sim.simulate_future_paths(
    pair="XAU/USD",
    current_price=3900.0,
    sl=3892.0,
    tp=3916.0,
    direction="buy",
    horizon_minutes=60,
    n_paths=500,
    model="historical_bootstrap",  # ou "gbm"
)

print(f"P(TP first) = {result['p_tp_first']:.1%}")
print(f"P(SL first) = {result['p_sl_first']:.1%}")
print(f"P(neither in horizon) = {result['p_neither']:.1%}")
```

## Intégration suggérée

Avant chaque décision TAKE dans auto_trader ou les pipelines MT5 :

```python
sim_result = await simulate_future_paths(pair, current, sl, tp, direction, 60, 500)
if sim_result['p_tp_first'] < 0.55:  # seuil configurable
    reject_signal("sim_tp_proba_insuffisante")
```

## Fail-open

Toute exception retourne un résultat "neutre" (0.5/0.5) pour ne pas
bloquer le trading sur un bug du simulateur. Les stats de l'erreur sont
loguées pour audit.
"""
from __future__ import annotations

import logging
import math
import os
import random
from typing import Any, Literal

logger = logging.getLogger(__name__)


ModelName = Literal["gbm", "historical_bootstrap"]


DEFAULT_N_PATHS = int(os.getenv("SIMULATOR_DEFAULT_N_PATHS", "500"))
DEFAULT_HORIZON_MINUTES = int(os.getenv("SIMULATOR_DEFAULT_HORIZON_MIN", "60"))
# Granularité des pas : plus fin = plus précis mais plus coûteux.
# Défaut 1 pas = 1 minute (cohérent avec bougies 1min).
DEFAULT_STEP_MINUTES = int(os.getenv("SIMULATOR_STEP_MINUTES", "1"))


def _neutral_result(reason: str) -> dict[str, Any]:
    """Résultat neutre quand la simulation ne peut pas tourner — fail-open."""
    return {
        "n_paths": 0,
        "model": "neutral_fallback",
        "p_tp_first": 0.5,
        "p_sl_first": 0.5,
        "p_neither": 0.0,
        "mean_terminal": None,
        "var95_terminal": None,
        "var99_terminal": None,
        "max_up": None,
        "max_down": None,
        "error": reason,
    }


def _log_returns(prices: list[float]) -> list[float]:
    """Log returns pour une série de prix."""
    out = []
    for i in range(1, len(prices)):
        p0 = prices[i - 1]
        p1 = prices[i]
        if p0 > 0 and p1 > 0:
            out.append(math.log(p1 / p0))
    return out


def _mean_std(xs: list[float]) -> tuple[float, float]:
    if not xs:
        return 0.0, 0.0
    m = sum(xs) / len(xs)
    var = sum((x - m) ** 2 for x in xs) / max(len(xs) - 1, 1)
    return m, math.sqrt(max(var, 0.0))


def _simulate_one_path_gbm(
    current: float, mu: float, sigma: float,
    sl: float, tp: float, direction: str, n_steps: int,
    rng: random.Random,
) -> tuple[str, float, float, float]:
    """Simule un chemin GBM. Retourne (outcome, terminal, max_up, max_down).

    outcome ∈ {"tp", "sl", "neither"}
    """
    price = current
    max_up = current
    max_down = current
    for _ in range(n_steps):
        z = rng.gauss(0.0, 1.0)
        price *= math.exp((mu - 0.5 * sigma * sigma) + sigma * z)
        max_up = max(max_up, price)
        max_down = min(max_down, price)
        if direction == "buy":
            if price <= sl:
                return "sl", price, max_up, max_down
            if price >= tp:
                return "tp", price, max_up, max_down
        else:  # sell
            if price >= sl:
                return "sl", price, max_up, max_down
            if price <= tp:
                return "tp", price, max_up, max_down
    return "neither", price, max_up, max_down


def _simulate_one_path_bootstrap(
    current: float, returns_pool: list[float],
    sl: float, tp: float, direction: str, n_steps: int,
    rng: random.Random,
) -> tuple[str, float, float, float]:
    """Simule un chemin par bootstrap des rendements historiques."""
    if not returns_pool:
        return "neither", current, current, current
    price = current
    max_up = current
    max_down = current
    for _ in range(n_steps):
        r = rng.choice(returns_pool)
        price *= math.exp(r)
        max_up = max(max_up, price)
        max_down = min(max_down, price)
        if direction == "buy":
            if price <= sl:
                return "sl", price, max_up, max_down
            if price >= tp:
                return "tp", price, max_up, max_down
        else:
            if price >= sl:
                return "sl", price, max_up, max_down
            if price <= tp:
                return "tp", price, max_up, max_down
    return "neither", price, max_up, max_down


async def simulate_future_paths(
    pair: str,
    current_price: float,
    sl: float,
    tp: float,
    direction: str,
    horizon_minutes: int = DEFAULT_HORIZON_MINUTES,
    n_paths: int = DEFAULT_N_PATHS,
    model: ModelName = "historical_bootstrap",
    history_candles: int = 100,
    seed: int | None = None,
) -> dict[str, Any]:
    """Simule ``n_paths`` chemins futurs du prix ``pair`` sur ``horizon_minutes``.

    Args:
        pair: ex "XAU/USD".
        current_price: prix spot au moment de la simulation.
        sl / tp: niveaux cible.
        direction: "buy" ou "sell".
        horizon_minutes: fenêtre temporelle max de la simulation.
        n_paths: nombre de chemins Monte Carlo.
        model: "gbm" (Geometric Brownian Motion) ou "historical_bootstrap"
               (rééchantillonne les rendements 1min passés).
        history_candles: nombre de bougies 1min à fetch pour calibrer
                         mu/sigma (GBM) ou peupler le pool bootstrap.
        seed: optionnel, pour reproductibilité.

    Returns:
        dict avec ``p_tp_first``, ``p_sl_first``, ``p_neither``,
        ``mean_terminal``, ``var95_terminal``, ``var99_terminal``,
        ``max_up``, ``max_down``, ``n_paths``, ``model``.

    Fail-open : toute exception → résultat neutre 0.5/0.5 avec champ ``error``.
    """
    if current_price <= 0 or sl <= 0 or tp <= 0:
        return _neutral_result("prix invalides (<=0)")
    if direction not in ("buy", "sell"):
        return _neutral_result(f"direction invalide : {direction!r}")
    if horizon_minutes <= 0 or n_paths <= 0:
        return _neutral_result("horizon ou n_paths <= 0")

    try:
        # Calibration depuis l'historique 1min
        from backend.services import price_service
        candles, _is_sim = await price_service.fetch_candles(
            pair, "1min", history_candles,
        )
        if not candles or len(candles) < 10:
            return _neutral_result("historique insuffisant")

        closes = [float(c.close) for c in candles if c.close]
        returns = _log_returns(closes)
        if not returns:
            return _neutral_result("rendements vides")

        mu, sigma = _mean_std(returns)
        rng = random.Random(seed)
        n_steps = max(1, horizon_minutes // DEFAULT_STEP_MINUTES)

        outcomes = {"tp": 0, "sl": 0, "neither": 0}
        terminals = []
        max_ups = []
        max_downs = []

        for _ in range(n_paths):
            if model == "gbm":
                oc, term, mu_up, mu_dn = _simulate_one_path_gbm(
                    current_price, mu, sigma, sl, tp, direction, n_steps, rng,
                )
            else:  # historical_bootstrap
                oc, term, mu_up, mu_dn = _simulate_one_path_bootstrap(
                    current_price, returns, sl, tp, direction, n_steps, rng,
                )
            outcomes[oc] += 1
            terminals.append(term)
            max_ups.append(mu_up)
            max_downs.append(mu_dn)

        terminals.sort()

        def _pct(x: int) -> float:
            return x / n_paths if n_paths else 0.0

        def _quantile(sorted_xs: list[float], q: float) -> float:
            if not sorted_xs:
                return 0.0
            idx = max(0, min(len(sorted_xs) - 1, int(q * (len(sorted_xs) - 1))))
            return sorted_xs[idx]

        return {
            "n_paths": n_paths,
            "model": model,
            "horizon_minutes": horizon_minutes,
            "calibration": {
                "n_history_candles": len(candles),
                "mean_log_return": round(mu, 8),
                "sigma_log_return": round(sigma, 8),
            },
            "p_tp_first": round(_pct(outcomes["tp"]), 4),
            "p_sl_first": round(_pct(outcomes["sl"]), 4),
            "p_neither": round(_pct(outcomes["neither"]), 4),
            "mean_terminal": round(sum(terminals) / len(terminals), 5),
            "var95_terminal": round(_quantile(terminals, 0.05), 5),
            "var99_terminal": round(_quantile(terminals, 0.01), 5),
            "max_up": round(max(max_ups), 5),
            "max_down": round(min(max_downs), 5),
        }
    except Exception as e:  # noqa: BLE001
        logger.error("trader_price_simulator: exception fail-open — %s", e)
        return _neutral_result(f"exception: {e}")
