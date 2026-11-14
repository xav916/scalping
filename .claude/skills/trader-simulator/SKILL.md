---
name: trader-simulator
description: >-
  The Price Simulator. Génère N chemins Monte Carlo du cours futur d'une
  paire (modèle GBM ou bootstrap des rendements historiques) pour estimer
  la probabilité que le TP soit touché avant le SL sur un horizon donné.
  Use when the user says "simule le cours", "proba TP vs SL", "centaines
  d'estimations", "Monte Carlo", "pricing probabiliste du trade", "quelle
  est la chance de toucher le target".
---

# trader-simulator

Les 14 skills existantes couvrent passé (earnings, filings), présent
(news, screener) et exécution. **Aucune ne quantifie la proba qu'un
trade atteigne son TP avant son SL dans une distribution plausible de
trajectoires futures.** Ce skill comble ce trou.

## Module runtime

`backend/services/trader_price_simulator.py`

API :

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
    seed=None,  # optionnel, pour reproductibilité tests
)

# result =
# {
#   "n_paths": 500,
#   "model": "historical_bootstrap",
#   "horizon_minutes": 60,
#   "calibration": {"mean_log_return": ..., "sigma_log_return": ...},
#   "p_tp_first": 0.6240,
#   "p_sl_first": 0.3080,
#   "p_neither": 0.0680,
#   "mean_terminal": 3904.12,
#   "var95_terminal": 3889.3,
#   "var99_terminal": 3878.1,
#   "max_up": 3938.2,
#   "max_down": 3867.5,
# }
```

## Deux modèles

### `gbm` — Geometric Brownian Motion

Classique en finance. Calibre `mu` et `sigma` à partir des log-returns
des N dernières bougies 1min, puis simule chaque pas :

    log(P[t+1]/P[t]) = (mu - sigma²/2) + sigma · Z,  Z ~ N(0,1)

Hypothèses : rendements log-normaux, pas de queue grasse, volatilité
constante. Sur du forex intraday c'est acceptable ; sur crypto en
période de volatilité c'est sous-estimé.

### `historical_bootstrap` — Rééchantillonnage

Tire au hasard parmi les rendements log-réels observés dans les N
dernières bougies. Pas d'hypothèse de distribution. Capture mieux
la queue grasse et le clustering de volatilité. **Défaut recommandé.**

## Fail-open

Toute exception (fetch candles down, historique insuffisant, etc.)
retourne un résultat neutre `p_tp_first=0.5, p_sl_first=0.5` avec champ
`error`. Le call-site qui utilise ce simulateur pour gater une décision
TAKE doit donc décider explicitement quoi faire du cas neutre :

- Conservateur : rejette le signal (traite 0.5 comme en-dessous du seuil)
- Permissif : laisse passer (traite 0.5 comme ni pour ni contre)

## Intégration suggérée (pas encore implémentée)

Dans chaque pipeline, avant d'appeler `_mt5_submit_order` :

```python
from backend.services import trader_price_simulator as sim

sim_result = await sim.simulate_future_paths(
    pair=pair, current_price=entry, sl=sl, tp=tp,
    direction=direction, horizon_minutes=60, n_paths=500,
)
min_proba = float(os.getenv(f"{PREFIX}_SIM_MIN_P_TP", "0.0"))
if sim_result["p_tp_first"] < min_proba:
    action["reason"] = f"sim_p_tp={sim_result['p_tp_first']:.2f} < {min_proba}"
    continue  # skip ce signal
```

Env var `<PREFIX>_SIM_MIN_P_TP` à 0.0 par défaut = pas de filtrage (backward
compat), à 0.55 pour n'accepter que les trades avec >55% proba TP first.

## Tests

`backend/tests/test_trader_price_simulator.py` couvre :

- Fail-open sur inputs invalides (prix=0, direction invalide, horizon=0)
- GBM : drift positif fort → TP hit ; drift négatif fort → SL hit
- Bootstrap : pool vide → neither ; pool mixte → résultat plausible
- Helpers : log_returns, mean_std, skip zeros
- Reproductibilité via seed
