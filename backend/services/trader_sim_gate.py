"""Gate Monte Carlo : refuse les signaux dont P(TP first) < seuil.

## Pourquoi

Les 9 pipelines MT5 et auto_trader génèrent des signaux déterministes
(RSI, ATR, screener) sans quantifier la probabilité qu'un trade
atteigne son TP avant son SL. Les 4567 trades envoyés sur le compte
RÉEL ont perdu -1046 EUR, en partie parce qu'aucun filtre probabiliste
n'était en place.

Cette gate utilise ``trader_price_simulator`` pour simuler N chemins
futurs et rejeter les signaux dont ``p_tp_first < <PREFIX>_SIM_MIN_P_TP``.

## Config par pipeline

Env var ``<PREFIX>_SIM_MIN_P_TP`` (défaut **0.0** = pas de filtrage,
backward compat parfait).

Exemples :
- ``M5_SIM_MIN_P_TP=0.55`` : ne prend un trade M5 que si proba TP ≥ 55%
- ``SCALP_SIM_MIN_P_TP=0.50`` : plus permissif
- ``WEEKLY_SIM_MIN_P_TP=0.60`` : plus restrictif (hold long = plus de
  conséquences d'un mauvais signal)

## Fail-open

Toute exception (fetch candles down, simulateur crashed, etc.) retourne
``(True, None, "sim_error")`` pour ne pas bloquer le trading sur un bug.
Si le simulateur retourne un fallback neutre (0.5), on compare 0.5 au
seuil : si seuil > 0.5, le signal est rejeté (conservateur).

## Usage

```python
from backend.services.trader_sim_gate import passes_sim_gate

ok, p_tp, reason = await passes_sim_gate(
    prefix="M5",
    pair="XAU/USD",
    current_price=3900.0,
    sl=3892.0, tp=3916.0,
    direction="buy",
    horizon_minutes=60,
)
if not ok:
    skip_signal(reason)
```
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


async def passes_sim_gate(
    prefix: str,
    pair: str,
    current_price: float,
    sl: float,
    tp: float,
    direction: str,
    horizon_minutes: int = 60,
    n_paths: int = 500,
    model: str = "historical_bootstrap",
) -> tuple[bool, float | None, str]:
    """Vérifie si un signal passe le filtre Monte Carlo.

    Returns:
        (passes, p_tp_first, reason)
        - ``passes``: True si le signal doit être pris, False si rejeté
        - ``p_tp_first``: proba estimée (None si gate désactivé ou erreur)
        - ``reason``: explication courte
    """
    min_p = _env_float(f"{prefix}_SIM_MIN_P_TP", 0.0)
    if min_p <= 0.0:
        return True, None, "sim_gate_disabled"

    try:
        from backend.services import trader_price_simulator as sim
        res = await sim.simulate_future_paths(
            pair=pair,
            current_price=current_price,
            sl=sl, tp=tp,
            direction=direction,
            horizon_minutes=horizon_minutes,
            n_paths=n_paths,
            model=model,
        )
        p_tp = float(res.get("p_tp_first", 0.5))
        if p_tp < min_p:
            return False, p_tp, (
                f"sim_rejected: p_tp={p_tp:.2%} < seuil {min_p:.2%}"
            )
        return True, p_tp, f"sim_pass: p_tp={p_tp:.2%} ≥ {min_p:.2%}"

    except Exception as e:  # noqa: BLE001
        # Fail-open : un bug du simulateur ne doit pas bloquer le trading
        logger.error(
            "trader_sim_gate: exception, fail-open — %s", e,
        )
        return True, None, f"sim_error: {e}"
