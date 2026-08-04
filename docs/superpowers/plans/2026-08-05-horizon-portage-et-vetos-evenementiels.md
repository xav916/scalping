# Horizon, portage et vetos événementiels — plan d'implémentation (plan 2 sur 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** brancher le flux long-horizon (4h et 1d) déjà produit en production sur le dispatch, en le faisant passer par une porte d'horizon, un coût de portage et des vetos événementiels bloquants — sans engager un euro.

**Architecture:** l'horizon devient une propriété du setup (`TradeSetup.horizon`), estampillée à la source par chaque générateur, puis un filtre de destination de même nature que `allowed_asset_classes` et `allowed_patterns` qui existent déjà. Le coût de portage s'ajoute au modèle de coût livré par le plan 1, sur la même règle : un coût non calculable vaut `None` et bloque l'argent réel sans bloquer l'observation. Les vetos qui réduisaient la taille deviennent bloquants dès que la position ne peut plus être fermée avant l'événement.

**Tech Stack:** Python 3.14, FastAPI, SQLite, pytest. Aucune dépendance nouvelle.

**Spec :** `docs/superpowers/specs/2026-08-04-trois-routes-horizon-et-couts-design.md`
**Plan précédent :** `docs/superpowers/plans/2026-08-04-modele-de-cout-par-destination.md` (terminé, vérifié en production le 2026-08-05)

---

## Global Constraints

- **Aucun code de refus ne commence par un souligné.** Les codes privés `_xxx` sont supprimés silencieusement — c'est ce qui a rendu AAPL invisible deux jours durant. Tout nouveau code va dans `REASON_LABELS_FR`.
- **Aucune valeur par défaut n'est inventée.** Une grandeur inconnue vaut `None`, jamais `0.0`. Confondre les deux ferait passer une route non mesurée pour une route gratuite.
- **Aucune route ne reçoit d'argent dans ce plan.** Le flux long-horizon s'arrête à l'état `TELEGRAM`. Le passage en `AUTO_EXEC` exige un échantillon propre postérieur au 2026-08-04 et sort du périmètre.
- **MT5 reste inchangé.** `admin_live` et `admin_legacy` ne déclarent ni `cost_model` ni `expected_edge_r`, et ce plan ne leur en ajoute pas. C'est ce qui les met à l'abri par construction.
- **Ne pas rallumer `TELEGRAM_SETUP_VERDICTS`.** Il vaut `` (vide) en production, ce qui éteint les alertes setup temps-réel. Le rallumer produirait ~2000 messages/jour. Le flux long-horizon obtient son propre canal, borné en volume.
- **Les destinations `user:N` ne sont pas touchées.** Leur `allowed_horizons` reste à `None` — Cédric doit continuer à recevoir exactement ce qu'il reçoit aujourd'hui.
- **Suite complète verte avant chaque commit.** Point de départ mesuré le 2026-08-05 : **1517 passed, 5 skipped, 0 échec**. Commande : `python -m pytest backend/tests -q`.
  ⚠️ Ce plan ne prédit pas de total exact après chaque tâche : `@pytest.mark.parametrize` fait qu'un fichier de dix fonctions peut compter vingt-sept tests. **Le critère est : 0 échec, 0 erreur, et un total qui a augmenté.** Un total qui stagne alors qu'on vient d'ajouter un fichier de tests signifie que le fichier n'est pas collecté — le chercher avant de continuer.
- **Si le travail se fait dans un worktree**, y copier `trades.db` et `backtest.db` depuis le dépôt principal AVANT de lancer quoi que ce soit — un worktree ne matérialise que les fichiers suivis, et sans ces bases des tests qui passent en `skipped` sur `main` deviennent des `errors`.

## Provenance des chiffres

| grandeur | valeur | d'où elle vient |
|---|---|---|
| `CANDLE_INTERVAL` production | `5min` | `/opt/scalping/.env`, lu le 2026-08-05 |
| `TELEGRAM_SETUP_MIN_CONFIDENCE` | `61` | idem |
| `TELEGRAM_SETUP_VERDICTS` | vide | idem — alertes setup éteintes |
| horizons présents en base | `4h` (244), `1d` (50) | `shadow_setups.timeframe`, spec §2 |
| systèmes long-horizon actifs | `V2_CORE_LONG_XAUUSD_4H`, `V2_CORE_LONG_XAGUSD_4H`, `V2_WTI_OPTIMAL_WTIUSD_4H`, `V2_CORE_LONG_ETHUSD_1D`, `V2_TIGHT_LONG_XLI_1D`, `V2_WTI_OPTIMAL_XLK_1D` | `SHADOW_CONFIG`, `backend/services/shadow_v2_core_long.py:53-89` |
| plafond du barème v2 sans volatilité | **60 points** | `_factors_v2`, `backend/services/analysis_engine.py:567-575` — la composante Volatilité est sous `if volatility:` |

⚠️ **Le fait le plus important de ce plan.** Le barème v2 vaut `Pattern 60 + Volatilité 40`. La composante Volatilité est conditionnée par `if volatility:`. Un setup enrichi sans `VolatilityData` plafonne donc à **60**, c'est-à-dire un point sous le seuil Telegram de 61. Brancher le flux long-horizon sans lui fournir sa propre volatilité le rendrait **silencieusement invisible** — exactement le motif qui a caché AAPL pendant deux jours. La tâche 5 existe pour cette seule raison.

## Ce qui est déjà fait et ne doit pas être refait

- **L'étiquette d'horizon du shadow V1 dit la vérité** (commit `057def9`). `V1_TIMEFRAME` dérive de `CANDLE_INTERVAL`, la fenêtre de dédup dérive de `V1_DEDUP_WINDOW_HOURS`. C'est le critère 4 de la spec. Ne pas y toucher : ramener la fenêtre de dédup à l'intervalle des bougies recréerait l'inflation ×960.
- **La porte de coût est en production** (commits `02d6ad1`, `fd8f74f`). `cost_in_r`, `exceeds_edge`, `EDGE_COST_MAX_SHARE = 0.30`, `_cost_rejection` branchée en fin de `_check_rejection`. Ce plan l'étend, il ne la réécrit pas.

## Ce que ce plan ne fait pas, et pourquoi

- **Le swap MT5 n'est pas modélisé.** La spec §3.2 le cite, mais il n'a aucun consommateur : la spec §3.3 restreint MT5 à l'horizon `5min`, et `admin_live` ne déclare volontairement aucun `cost_model` (décision du plan 1, commit `c34971e`, mesure à l'appui : 0,022 R absorbés dans le spread). Lui ajouter une composante de portage contredirait cette décision sans rien changer à aucune décision de dispatch. **Condition de réveil** : le jour où une destination MT5 reçoit `4h` ou `1d` dans son `allowed_horizons`. Il faudra alors exposer `swap_long`/`swap_short` via `/symbol_specs` du bridge (`mt5-bridge/bridge.py:1013`, qui ne les expose pas aujourd'hui) et déployer sur le VPS Windows.
- **Le passage en `AUTO_EXEC` du flux long-horizon.** Il exige un échantillon propre postérieur au 2026-08-04, qui n'existe pas encore.
- **Les ordres maker sur Kraken.** Ils diviseraient peut-être les frais par deux, mais mélanger ce changement avec le portage rendrait impossible d'attribuer l'effet.
- **Aucun générateur de signaux nouveau.** Les systèmes V2 existent et tournent.

## File Structure

| fichier | responsabilité | tâche |
|---|---|---|
| `backend/services/horizon.py` **(créé)** | vocabulaire d'horizon : normalisation, classification long/court, durée d'une bougie. Module pur — ni base, ni réseau, ni horloge. | 1 |
| `backend/models/schemas.py` | `TradeSetup.horizon` | 2 |
| `backend/services/analysis_engine.py` | estampille l'horizon V1 par défaut ; ne l'écrase jamais | 2 |
| `backend/services/shadow_v2_core_long.py` | estampille l'horizon V2, calcule score et verdict, notifie | 2, 5, 6 |
| `backend/services/bridge_destinations.py` | champ `allowed_horizons`, valeurs par destination | 3 |
| `backend/services/mt5_bridge.py` | portes `horizon_not_allowed`, `weekend_hold_blocked`, `earnings_blackout` ; portage dans `_cost_rejection` | 3, 4, 7 |
| `backend/services/rejection_service.py` | libellés FR des nouveaux codes | 3, 7 |
| `backend/services/cost_model.py` | composante de portage | 4 |
| `backend/services/kraken_funding_scoring.py` | accesseur public du taux de funding | 4 |
| `backend/services/backtest_engine.py` | `compute_volatility` accepte son étiquette de timeframe | 5 |
| `backend/services/telegram_service.py` | canal long-horizon, sans toucher au gate global | 6 |
| `backend/services/earnings_veto.py` | veto bloquant à horizon long | 7 |
| `config/settings.py` | `TELEGRAM_LONG_HORIZON_ENABLED`, `TELEGRAM_LONG_HORIZON_MIN_CONFIDENCE` | 6 |

Tests créés : `test_horizon.py`, `test_setup_horizon_stamp.py`, `test_dispatch_porte_horizon.py`, `test_cost_model_portage.py`, `test_long_horizon_scoring.py`, `test_telegram_long_horizon.py`, `test_vetos_horizon_long.py`.

---

### Task 1 : Le vocabulaire d'horizon

Un module pur qui répond à trois questions : cette étiquette est-elle un horizon connu, combien de minutes dure sa bougie, et cet horizon est-il « long » au sens du portage. Tout le reste du plan en dépend, donc il vient en premier et ne connaît rien du domaine trading.

**Files:**
- Create: `backend/services/horizon.py`
- Test: `backend/tests/test_horizon.py`

**Interfaces:**
- Consomme : rien.
- Produit :
  - `HORIZONS: tuple[str, ...]` — `("5min", "15min", "1h", "4h", "1d")`
  - `LONG_HORIZONS: frozenset[str]` — `{"4h", "1d"}`
  - `normalize(label: str | None) -> str | None`
  - `bar_minutes(horizon: str | None) -> int | None`
  - `is_long(horizon: str | None) -> bool`

- [ ] **Step 1: Écrire le test qui échoue**

```python
# backend/tests/test_horizon.py
"""Vocabulaire d'horizon — module pur, socle du routage (2026-08-05)."""
import pytest

from backend.services.horizon import (
    HORIZONS, LONG_HORIZONS, bar_minutes, is_long, normalize,
)


@pytest.mark.parametrize("brut,attendu", [
    ("5min", "5min"),
    ("5MIN", "5min"),
    (" 5min ", "5min"),
    ("5m", "5min"),
    ("15min", "15min"),
    ("1h", "1h"),
    ("1H", "1h"),
    ("4h", "4h"),
    ("4H", "4h"),
    ("1d", "1d"),
    ("1D", "1d"),
    ("1day", "1d"),
    ("daily", "1d"),
])
def test_normalize_reconnait_les_ecritures_du_code_existant(brut, attendu):
    # "1H" vient de VolatilityData.timeframe, "1day" de l'appel Twelve Data
    # dans run_shadow_log, "4h"/"1d" de SHADOW_CONFIG. Les trois cohabitent
    # deja en base : normalize est le point ou elles se rejoignent.
    assert normalize(brut) == attendu


@pytest.mark.parametrize("brut", [None, "", "  ", "2h", "3min", "1w", "inconnu"])
def test_normalize_rend_none_sur_inconnu_jamais_une_valeur_par_defaut(brut):
    # Regle globale du projet : inconnu vaut None, jamais une valeur inventee.
    # Rendre "5min" par defaut ferait passer un setup non etiquete pour du
    # scalping et le router vers de l'argent reel.
    assert normalize(brut) is None


def test_bar_minutes():
    assert bar_minutes("5min") == 5
    assert bar_minutes("15min") == 15
    assert bar_minutes("1h") == 60
    assert bar_minutes("4h") == 240
    assert bar_minutes("1d") == 1440


def test_bar_minutes_rend_none_sur_inconnu():
    assert bar_minutes("2h") is None
    assert bar_minutes(None) is None


def test_bar_minutes_accepte_les_ecritures_non_normalisees():
    # Un appelant ne doit pas avoir a normaliser avant d'interroger.
    assert bar_minutes("4H") == 240
    assert bar_minutes("1day") == 1440


def test_is_long_separe_le_portage_du_scalping():
    # Le portage (funding, swap, gap de week-end) n'existe qu'a partir de 4h.
    assert is_long("4h") is True
    assert is_long("1d") is True
    assert is_long("1h") is False
    assert is_long("5min") is False


def test_is_long_est_faux_sur_inconnu_et_ne_leve_pas():
    # Fail-safe : un horizon inconnu n'active pas les regles de portage,
    # mais la porte de la tache 3 le bloquera de toute facon.
    assert is_long(None) is False
    assert is_long("inconnu") is False


def test_tous_les_horizons_declares_sont_mesurables():
    # Garde-fou : ajouter un horizon a HORIZONS sans lui donner sa duree
    # ferait rendre None a bar_minutes en production, silencieusement.
    for h in HORIZONS:
        assert bar_minutes(h) is not None, h
        assert normalize(h) == h, h


def test_les_horizons_longs_sont_un_sous_ensemble_des_horizons():
    assert LONG_HORIZONS <= set(HORIZONS)
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `python -m pytest backend/tests/test_horizon.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.services.horizon'`

- [ ] **Step 3: Écrire l'implémentation**

```python
# backend/services/horizon.py
"""Vocabulaire d'horizon d'analyse.

Trois écritures du même horizon cohabitent déjà dans le code, pour des
raisons historiques légitimes :

- ``SHADOW_CONFIG`` utilise ``"4h"`` / ``"1d"``
- ``VolatilityData.timeframe`` utilise ``"1H"``
- l'appel Twelve Data de ``run_shadow_log`` utilise ``"1day"``

Ce module est le point où elles se rejoignent. Il est volontairement pur :
ni base, ni réseau, ni horloge — ce qui le rend testable sans fixture et
utilisable depuis le dispatch, où chaque milliseconde compte.

⚠️ ``normalize`` rend ``None`` sur une étiquette inconnue, jamais une valeur
par défaut. Rendre ``"5min"`` ferait passer un setup non étiqueté pour du
scalping et le router vers de l'argent réel.
"""
from __future__ import annotations

# Horizons connus, du plus court au plus long.
HORIZONS: tuple[str, ...] = ("5min", "15min", "1h", "4h", "1d")

# Horizons à partir desquels une position se **détient** : elle paie un
# portage (funding, swap) et traverse des événements (earnings, week-end)
# qu'une position de scalping ne rencontrait jamais.
LONG_HORIZONS: frozenset[str] = frozenset({"4h", "1d"})

_MINUTES: dict[str, int] = {
    "5min": 5,
    "15min": 15,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}

# Écritures alternatives rencontrées dans le code existant, en minuscules.
_ALIASES: dict[str, str] = {
    "5m": "5min",
    "15m": "15min",
    "60min": "1h",
    "1hour": "1h",
    "4hour": "4h",
    "1day": "1d",
    "daily": "1d",
}


def normalize(label: str | None) -> str | None:
    """Ramène une étiquette d'horizon à sa forme canonique, ou ``None``."""
    if not label:
        return None
    cle = str(label).strip().lower()
    if not cle:
        return None
    cle = _ALIASES.get(cle, cle)
    return cle if cle in _MINUTES else None


def bar_minutes(horizon: str | None) -> int | None:
    """Durée d'une bougie de cet horizon, en minutes. ``None`` si inconnu."""
    canonique = normalize(horizon)
    return _MINUTES.get(canonique) if canonique else None


def is_long(horizon: str | None) -> bool:
    """``True`` si une position à cet horizon se détient plutôt qu'elle ne se scalpe.

    Fail-safe : un horizon inconnu rend ``False`` — il n'active pas les
    règles de portage. Il sera bloqué en amont par la porte d'horizon.
    """
    canonique = normalize(horizon)
    return canonique in LONG_HORIZONS if canonique else False
```

- [ ] **Step 4: Lancer le test pour vérifier qu'il passe**

Run: `python -m pytest backend/tests/test_horizon.py -q`
Expected: PASS (10 tests, dont 13 cas paramétrés)

- [ ] **Step 5: Commit**

```bash
git add backend/services/horizon.py backend/tests/test_horizon.py
git commit -m "Vocabulaire d'horizon : une seule ecriture pour trois notations"
```

---

### Task 2 : L'horizon devient une propriété du setup

Aujourd'hui l'horizon n'existe que dans `shadow_setups.timeframe`, c'est-à-dire **après** la persistance. Le dispatch, lui, reçoit un `TradeSetup` qui ne sait pas sur quelles bougies il a été détecté. Cette tâche le lui apprend, à la source, chez chaque générateur.

La règle d'écrasement est le point délicat : `enrich_trade_setup` est traversé par les deux flux. Il estampille **seulement si le champ est vide**, sinon il écraserait le `4h` du flux V2 par le `5min` de la configuration globale.

**Files:**
- Modify: `backend/models/schemas.py:117-152` (ajout d'un champ à `TradeSetup`)
- Modify: `backend/services/analysis_engine.py:613-625` (début de `enrich_trade_setup`)
- Modify: `backend/services/shadow_v2_core_long.py:472-476` (après `calculate_trade_setup`)
- Test: `backend/tests/test_setup_horizon_stamp.py`

**Interfaces:**
- Consomme : `backend.services.horizon.normalize` (tâche 1).
- Produit : `TradeSetup.horizon: str | None` — lu par les tâches 3, 4, 5, 6 et 7.

- [ ] **Step 1: Écrire le test qui échoue**

```python
# backend/tests/test_setup_horizon_stamp.py
"""L'horizon est estampillé à la source, et jamais écrasé (2026-08-05).

`enrich_trade_setup` est traversé par les deux générateurs. S'il estampillait
inconditionnellement, il écraserait le `4h` du flux V2 par le `CANDLE_INTERVAL`
global — et le routage par horizon enverrait des setups 4h sur la route
scalping. Le test `n_ecrase_pas` verrouille ce comportement.
"""
from datetime import datetime, timezone

from backend.models.schemas import (
    Candle, PatternDetection, PatternType, TradeDirection, TradeSetup,
)


def _setup(horizon=None) -> TradeSetup:
    pattern = PatternDetection(
        pair="XAU/USD",
        pattern=PatternType.MOMENTUM_UP,
        confidence=0.8,
        description="momentum haussier",
        detected_at=datetime.now(timezone.utc),
    )
    return TradeSetup(
        pair="XAU/USD",
        direction=TradeDirection.BUY,
        pattern=pattern,
        entry_price=2000.0,
        stop_loss=1990.0,
        take_profit_1=2015.0,
        take_profit_2=2025.0,
        risk_pips=10.0,
        reward_pips_1=15.0,
        reward_pips_2=25.0,
        risk_reward_1=1.5,
        risk_reward_2=2.5,
        message="test",
        timestamp=datetime.now(timezone.utc),
        horizon=horizon,
    )


def test_le_champ_horizon_existe_et_vaut_none_par_defaut():
    # None, pas "5min" : un setup non estampille est un setup d'horizon
    # inconnu, et la porte de la tache 3 doit pouvoir le voir comme tel.
    assert _setup().horizon is None


def test_enrich_estampille_l_horizon_v1_quand_il_est_vide(monkeypatch):
    from backend.services import analysis_engine

    monkeypatch.setattr(analysis_engine, "CANDLE_INTERVAL", "5min", raising=False)
    enrichi = analysis_engine.enrich_trade_setup(_setup(), None, None, [])
    assert enrichi.horizon == "5min"


def test_enrich_n_ecrase_pas_un_horizon_deja_pose(monkeypatch):
    # LE test de cette tache. Le flux V2 estampille "4h" AVANT d'enrichir.
    from backend.services import analysis_engine

    monkeypatch.setattr(analysis_engine, "CANDLE_INTERVAL", "5min", raising=False)
    enrichi = analysis_engine.enrich_trade_setup(_setup(horizon="4h"), None, None, [])
    assert enrichi.horizon == "4h"


def test_enrich_normalise_une_ecriture_exotique(monkeypatch):
    from backend.services import analysis_engine

    monkeypatch.setattr(analysis_engine, "CANDLE_INTERVAL", "5MIN", raising=False)
    assert analysis_engine.enrich_trade_setup(_setup(), None, None, []).horizon == "5min"


def test_enrich_laisse_none_si_candle_interval_est_inintelligible(monkeypatch):
    # Plutot un horizon absent qu'un horizon faux : la porte bloquera.
    from backend.services import analysis_engine

    monkeypatch.setattr(analysis_engine, "CANDLE_INTERVAL", "3min", raising=False)
    assert analysis_engine.enrich_trade_setup(_setup(), None, None, []).horizon is None


def test_le_flux_v2_estampille_son_propre_horizon():
    # Verification par inspection : run_shadow_log doit poser setup.horizon
    # depuis cfg["tf"] avant tout enrichissement. Une estampille posee apres
    # l'enrichissement arriverait trop tard — le score et le verdict de la
    # tache 5 en dependent.
    import inspect

    from backend.services import shadow_v2_core_long

    src = inspect.getsource(shadow_v2_core_long.run_shadow_log)
    assert "setup.horizon" in src, "run_shadow_log n'estampille pas l'horizon"
    i_stamp = src.index("setup.horizon")
    i_persist = src.index("_persist_setup")
    assert i_stamp < i_persist, "l'estampille doit precede la persistance"
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `python -m pytest backend/tests/test_setup_horizon_stamp.py -q`
Expected: FAIL — `TradeSetup` n'accepte pas `horizon`

- [ ] **Step 3: Ajouter le champ au schéma**

Dans `backend/models/schemas.py`, à la fin de la classe `TradeSetup`, juste après `asset_class` :

```python
    asset_class: str = "forex"  # "forex" | "metal" | "crypto" | "equity_index" | "energy"
    # Horizon d'analyse : sur quelles bougies ce setup a été détecté
    # ("5min", "4h", "1d"…). Estampillé à la source par chaque générateur,
    # lu par la porte d'horizon du dispatch.
    #
    # ⚠️ `None` (horizon inconnu) et `"5min"` sont deux états distincts. Un
    # défaut à `"5min"` ferait passer un setup non étiqueté pour du scalping
    # et le router vers de l'argent réel.
    horizon: str | None = None
```

- [ ] **Step 4: Estampiller le flux V1 dans `enrich_trade_setup`**

Dans `backend/services/analysis_engine.py`, au tout début du corps de `enrich_trade_setup`, avant la ligne `if not getattr(setup, "asset_class", None)` :

```python
    # Horizon d'analyse (2026-08-05). Estampillé ici parce que c'est le seul
    # point traversé par tous les setups V1, quel que soit leur chemin.
    #
    # ⚠️ **Seulement si le champ est vide.** Le flux V2 long-horizon traverse
    # aussi cette fonction et pose son propre `4h` / `1d` en amont. Estampiller
    # inconditionnellement l'écraserait par le CANDLE_INTERVAL global, et le
    # routage enverrait des setups 4h sur la route scalping.
    if not getattr(setup, "horizon", None):
        from backend.services.horizon import normalize as _normalize_horizon
        setup.horizon = _normalize_horizon(CANDLE_INTERVAL)
```

Vérifier que `CANDLE_INTERVAL` est bien importé au niveau module dans `analysis_engine.py` ; s'il ne l'est pas, l'ajouter à l'import existant depuis `config.settings`. L'import au niveau module est nécessaire pour que le `monkeypatch.setattr(analysis_engine, "CANDLE_INTERVAL", ...)` des tests morde.

- [ ] **Step 5: Estampiller le flux V2**

Dans `backend/services/shadow_v2_core_long.py`, dans `run_shadow_log`, immédiatement après le bloc :

```python
            setup = calculate_trade_setup(pair, pattern, signal_candles)
            if setup is None:
                continue
            if setup.direction != TradeDirection.BUY:
                continue
```

ajouter :

```python
            # Horizon d'analyse : ce setup a été détecté sur des bougies `tf`,
            # pas sur le CANDLE_INTERVAL global. Posé AVANT tout enrichissement
            # pour qu'`enrich_trade_setup` ne l'écrase pas.
            from backend.services.horizon import normalize as _normalize_horizon
            setup.horizon = _normalize_horizon(tf)
```

- [ ] **Step 6: Lancer les tests pour vérifier qu'ils passent**

Run: `python -m pytest backend/tests/test_setup_horizon_stamp.py -q`
Expected: PASS (6 tests)

- [ ] **Step 7: Lancer la suite complète**

Run: `python -m pytest backend/tests -q`
Expected: 0 echec, 0 erreur, total superieur aux 1517 de depart

- [ ] **Step 8: Commit**

```bash
git add backend/models/schemas.py backend/services/analysis_engine.py \
        backend/services/shadow_v2_core_long.py backend/tests/test_setup_horizon_stamp.py
git commit -m "Un setup sait sur quelles bougies il a ete detecte"
```

---

### Task 3 : La porte d'horizon au dispatch

Le filtre lui-même. De même nature que `allowed_asset_classes` et `allowed_patterns` qui existent déjà sur `BridgeConfig` — même forme, même point d'application, même traçabilité.

Placée **tôt** dans `_check_rejection`, à l'inverse de la porte de coût qui est en dernier : une appartenance à un `frozenset` ne coûte rien, là où la porte de coût appelle le sizing qui peut interroger le bridge en HTTP.

**Pourquoi le fail-closed est sûr sur MT5 — vérifié le 2026-08-05.** Déclarer `allowed_horizons` sur `admin_live` revient à parier que tout setup qui atteint le dispatch porte bien son horizon. Si un seul chemin produisait des setups non estampillés, MT5 s'arrêterait net en production. Deux faits l'excluent :

1. `mt5_bridge.send_setups` n'a **qu'un seul appelant** : `backend/services/scheduler.py:272`. Vérifié par `grep -rn "mt5_bridge_send_setups\|send_setups(" backend/ --include=*.py`.
2. Sur ce chemin, `enrich_trade_setup` est appelé **inconditionnellement** entre `calculate_trade_setup` et `all_trade_setups.append(setup)` (`scheduler.py:183-213`) — donc l'estampille de la tâche 2 est posée sur 100 % des setups dispatchés.

Si un futur chantier ajoute un second appelant de `send_setups`, il doit estampiller l'horizon ou la porte le refusera. C'est le comportement voulu.

**Files:**
- Modify: `backend/services/bridge_destinations.py` (champ + valeurs par destination)
- Modify: `backend/services/mt5_bridge.py` (≈ ligne 452, juste avant le bloc `allowed_patterns`)
- Modify: `backend/services/rejection_service.py:48` (libellé FR)
- Test: `backend/tests/test_dispatch_porte_horizon.py`

**Interfaces:**
- Consomme : `TradeSetup.horizon` (tâche 2), `backend.services.horizon.normalize` (tâche 1).
- Produit :
  - `BridgeConfig.allowed_horizons: frozenset[str] | None`
  - `mt5_bridge._horizon_rejection(setup, dest) -> str | None` — rend `"horizon_not_allowed"` ou `None`

- [ ] **Step 1: Écrire le test qui échoue**

```python
# backend/tests/test_dispatch_porte_horizon.py
"""Porte d'horizon au dispatch (2026-08-05).

Une destination déclare les horizons qu'elle accepte. MT5 est dimensionné
pour le scalping, Kraken pour la détention. Router un setup 4h vers une
route scalping enverrait un ordre dont le sizing, les stops et les frais
ont été pensés pour une autre échelle de temps.
"""
from types import SimpleNamespace

import pytest

from backend.services.mt5_bridge import _horizon_rejection


def _setup(horizon):
    return SimpleNamespace(pair="XAU/USD", horizon=horizon, entry_price=2000.0,
                           stop_loss=1990.0, confidence_score=80.0)


def _dest(allowed):
    return SimpleNamespace(destination_id="test", allowed_horizons=allowed,
                           auto_exec_enabled=True)


def test_horizon_admis_passe():
    assert _horizon_rejection(_setup("5min"), _dest(frozenset({"5min"}))) is None


def test_horizon_non_admis_refuse():
    assert _horizon_rejection(_setup("4h"), _dest(frozenset({"5min"}))) == "horizon_not_allowed"


def test_ecriture_non_normalisee_admise_quand_meme():
    # Le setup porte "4H", la destination declare "4h" : c'est le meme
    # horizon. La normalisation evite un refus sur une difference de casse.
    assert _horizon_rejection(_setup("4H"), _dest(frozenset({"4h"}))) is None


def test_destination_sans_declaration_ne_filtre_rien():
    # allowed_horizons=None => comportement d'avant le 2026-08-05. C'est ce
    # qui garantit que les destinations user:N (Cedric) ne changent pas.
    assert _horizon_rejection(_setup("4h"), _dest(None)) is None
    assert _horizon_rejection(_setup(None), _dest(None)) is None


def test_horizon_inconnu_bloque_quand_la_porte_est_active():
    # Fail-closed, comme la whitelist de patterns : declarer allowed_horizons
    # est un opt-in explicite. Un setup sans horizon face a une porte active
    # est un setup qu'on ne sait pas router — on ne devine pas.
    assert _horizon_rejection(_setup(None), _dest(frozenset({"5min"}))) == "horizon_not_allowed"
    assert _horizon_rejection(_setup("2h"), _dest(frozenset({"5min"}))) == "horizon_not_allowed"


def test_destination_absente_ne_filtre_rien():
    assert _horizon_rejection(_setup("4h"), None) is None


def test_la_porte_est_reellement_appelee_par_check_rejection():
    # Une fonction qui existe sans etre appelee ne protege de rien. Meme
    # verification par inspection que pour la porte de cout du plan 1.
    import inspect

    from backend.services import mt5_bridge

    src = inspect.getsource(mt5_bridge._check_rejection)
    assert "_horizon_rejection" in src


def test_le_code_de_refus_est_public_et_libelle():
    # Un code prefixe `_` serait supprime silencieusement — c'est ce qui a
    # rendu AAPL invisible deux jours durant.
    from backend.services.rejection_service import REASON_LABELS_FR

    assert not "horizon_not_allowed".startswith("_")
    assert "horizon_not_allowed" in REASON_LABELS_FR


def test_les_destinations_reelles_declarent_les_horizons_de_la_spec(monkeypatch):
    # Les valeurs de la spec section 3.3 : MT5 scalping, Kraken detention.
    from backend.services import bridge_destinations as bd

    monkeypatch.setenv("MT5_BRIDGE_URL", "http://x")
    monkeypatch.setenv("MT5_BRIDGE_API_KEY", "k")
    live = bd._admin_live_destination()
    if live is not None:
        assert live.allowed_horizons == frozenset({"5min"})


def test_kraken_declare_les_horizons_longs():
    from backend.services import bridge_destinations as bd

    kraken = bd._admin_kraken_destination()
    if kraken is not None:
        assert kraken.allowed_horizons == frozenset({"4h", "1d"})


def test_les_destinations_user_ne_filtrent_pas_l_horizon():
    # Cedric doit continuer a recevoir exactement ce qu'il recoit.
    import inspect

    from backend.services import bridge_destinations as bd

    src = inspect.getsource(bd._user_destinations)
    assert "allowed_horizons" not in src, (
        "les destinations user ne doivent pas declarer d'horizon"
    )
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `python -m pytest backend/tests/test_dispatch_porte_horizon.py -q`
Expected: FAIL — `ImportError: cannot import name '_horizon_rejection'`

- [ ] **Step 3: Ajouter le champ à `BridgeConfig`**

Dans `backend/services/bridge_destinations.py`, dans la dataclass `BridgeConfig`, juste après le bloc `cost_model` / `expected_edge_r` ajouté par le plan 1 :

```python
    # ── Horizon (2026-08-05) ─────────────────────────────────────────
    # Horizons d'analyse que cette route accepte. `None` = pas de filtre,
    # c'est-à-dire le comportement d'avant le 2026-08-05 — c'est ce qui
    # garantit que les destinations `user:N` ne changent pas.
    #
    # ⚠️ Déclarer un `frozenset` est un opt-in **fail-closed** : un setup
    # d'horizon inconnu face à une porte active est refusé, comme pour la
    # whitelist de patterns. On ne devine pas l'échelle de temps d'un ordre.
    allowed_horizons: frozenset[str] | None = None
```

- [ ] **Step 4: Écrire la fonction de refus**

Dans `backend/services/mt5_bridge.py`, juste avant `def _check_rejection` (donc après `_cost_rejection`) :

```python
def _horizon_rejection(setup, dest) -> str | None:
    """Refuse un setup dont l'horizon d'analyse n'est pas servi par la route.

    Extraite comme `_cost_rejection` pour être testable sans base ni réseau.

    Une route dimensionnée pour le scalping et une route dimensionnée pour la
    détention n'ont ni le même sizing, ni les mêmes stops, ni les mêmes frais.
    Router un setup 4h vers MT5 enverrait un ordre pensé pour une autre
    échelle de temps.

    `dest.allowed_horizons is None` ⇒ aucun filtre, comportement d'avant le
    2026-08-05. Sinon **fail-closed** : horizon absent ou inconnu = refus.
    """
    if dest is None:
        return None
    admis = getattr(dest, "allowed_horizons", None)
    if not admis:
        return None

    from backend.services.horizon import normalize as _normalize_horizon

    h = _normalize_horizon(getattr(setup, "horizon", None))
    if h is None or h not in admis:
        return "horizon_not_allowed"
    return None
```

- [ ] **Step 5: Brancher la porte**

Dans `backend/services/mt5_bridge.py`, dans `_check_rejection`, **juste avant** le bloc de la whitelist de patterns (le commentaire `# Whitelist de patterns (2026-08-04).`, ≈ ligne 445) :

```python
    # Porte d'horizon (2026-08-05). Placée TÔT, à l'inverse de la porte de
    # coût qui est en dernier : une appartenance à un frozenset ne coûte
    # rien, là où la porte de coût appelle le sizing, qui peut interroger le
    # solde du bridge en HTTP. Inutile de payer ce prix pour un signal qui
    # n'est de toute façon pas à la bonne échelle de temps.
    horizon_reason = _horizon_rejection(setup, dest)
    if horizon_reason:
        return horizon_reason
```

- [ ] **Step 6: Déclarer le libellé du code de refus**

Dans `backend/services/rejection_service.py`, dans `REASON_LABELS_FR`, à la suite de la ligne `fees_exceed_edge` :

```python
    "horizon_not_allowed": "horizon non servi par cette route",
```

- [ ] **Step 7: Renseigner les destinations réelles**

Dans `backend/services/bridge_destinations.py` :

`_admin_legacy_destination` et `_admin_live_destination` — ajouter au `BridgeConfig(...)` :

```python
        # MT5 est dimensionné pour le scalping : SL serrés, TP à quelques
        # dixièmes de pourcent, frais absorbés dans le spread (0,022 R mesuré).
        allowed_horizons=frozenset({"5min"}),
```

`_admin_kraken_destination` :

```python
        # Kraken n'est viable qu'en détention : ses 0,10 % d'aller-retour
        # valent 2,6 fois l'edge à l'échelle du scalping. Le restreindre aux
        # horizons longs coupe le flux 5 min à la porte la moins chère,
        # avant même la porte de coût.
        allowed_horizons=frozenset({"4h", "1d"}),
```

`_admin_kraken_spot_destination` et `_admin_kraken_stocks_destination` — même valeur `frozenset({"4h", "1d"})` avec le même motif.

**Ne rien ajouter à `_user_destinations`** — un test le verrouille.

⚠️ `_admin_binance_destination` reste sans déclaration (`None`) : la route est désactivée et lui donner un horizon maintenant serait une décision non mesurée.

- [ ] **Step 8: Lancer les tests pour vérifier qu'ils passent**

Run: `python -m pytest backend/tests/test_dispatch_porte_horizon.py -q`
Expected: PASS (11 tests)

- [ ] **Step 9: Vérifier par mutation**

Commenter les deux lignes du Step 5 (`horizon_reason = ...` et le `if`), relancer :

Run: `python -m pytest backend/tests/test_dispatch_porte_horizon.py -q`
Expected: FAIL sur `test_la_porte_est_reellement_appelee_par_check_rejection`

Si ce test passe encore, la vérification par inspection ne mord pas — la corriger avant d'aller plus loin. Puis **décommenter**.

- [ ] **Step 10: Lancer la suite complète**

Run: `python -m pytest backend/tests -q`
Expected: 0 echec, 0 erreur, total en hausse

⚠️ Si des tests existants cassent ici, lire l'échec avant de le « réparer » : un test de dispatch qui construit un setup sans horizon et attend un push est précisément le cas que la porte fail-closed doit refuser sur `admin_live`. La bonne correction est d'ajouter `horizon="5min"` à la fixture, pas d'affaiblir la porte.

- [ ] **Step 11: Commit**

```bash
git add backend/services/bridge_destinations.py backend/services/mt5_bridge.py \
        backend/services/rejection_service.py backend/tests/test_dispatch_porte_horizon.py
git commit -m "Porte d'horizon : chaque route declare l'echelle de temps qu'elle sert"
```

---

### Task 4 : Le coût de portage

À 4h ou 1d, une position paie aussi sa **détention**. Sur les perpétuels Kraken, c'est le funding. Ce coût n'existe nulle part dans le code aujourd'hui : le funding est collecté, mais seulement comme *feature de scoring*. Sans lui, le modèle sous-estimerait Kraken précisément là où il doit être sévère.

Le point de conception : la durée de détention attendue n'est **pas connue** pour 4h et 1d. Tout l'historique shadow antérieur au 2026-08-04 est à écarter (bug de dédup ×960), donc aucune médiane fiable n'existe. Conformément à la règle globale, elle vaut `None` — et un coût non calculable bloque l'argent réel sans bloquer l'observation. C'est exactement la sémantique posée par le plan 1.

**Files:**
- Modify: `backend/services/cost_model.py`
- Modify: `backend/services/kraken_funding_scoring.py` (accesseur public)
- Modify: `backend/services/bridge_destinations.py` (déclaration Kraken)
- Modify: `backend/services/mt5_bridge.py` (`_cost_rejection`)
- Test: `backend/tests/test_cost_model_portage.py`

**Interfaces:**
- Consomme : `CostModel`, `cost_in_r`, `exceeds_edge` (plan 1) ; `horizon.is_long` (tâche 1) ; `TradeSetup.horizon` (tâche 2).
- Produit :
  - `CostModel.funding_interval_hours: float = 0.0`
  - `holding_cost_in_r(entry, stop_loss, rate_per_interval, interval_hours, holding_hours) -> float | None`
  - `median_holding_hours(system_id, min_sample=30, db_path=None) -> float | None`
  - `kraken_funding_scoring.get_funding_rate_for_pair(pair) -> float | None`

- [ ] **Step 1: Écrire le test qui échoue**

```python
# backend/tests/test_cost_model_portage.py
"""Coût de portage — le prix de la détention (2026-08-05).

Le scalping ne payait pas ce coût : une position ouverte et fermée dans la
même heure ne traverse aucune échéance de funding. À 4h et 1d, si.
"""
import sqlite3

import pytest

from backend.services.cost_model import (
    CostModel, holding_cost_in_r, median_holding_hours,
)


def test_le_portage_est_proportionnel_a_la_duree():
    # entry/distance = 2000/10 = 200. rate 0,0001 par heure, 24 heures.
    # 200 * 0,0001 * 24 = 0,48 R
    r = holding_cost_in_r(entry=2000.0, stop_loss=1990.0,
                          rate_per_interval=0.0001, interval_hours=1.0,
                          holding_hours=24.0)
    assert r == pytest.approx(0.48)


def test_doubler_la_duree_double_le_cout():
    a = holding_cost_in_r(2000.0, 1990.0, 0.0001, 1.0, 12.0)
    b = holding_cost_in_r(2000.0, 1990.0, 0.0001, 1.0, 24.0)
    assert b == pytest.approx(2 * a)


def test_le_portage_ne_depend_pas_de_la_taille_de_position():
    # Meme propriete que le cout proportionnel du plan 1 : le risque se
    # simplifie. C'est la raison mathematique pour laquelle plus de capital
    # ne sauvera pas une route dont le portage est trop cher.
    serre = holding_cost_in_r(2000.0, 1998.0, 0.0001, 1.0, 24.0)
    large = holding_cost_in_r(2000.0, 1990.0, 0.0001, 1.0, 24.0)
    # Un stop 5x plus serre coute 5x plus cher en R, a duree egale.
    assert serre == pytest.approx(5 * large)


def test_un_funding_negatif_ne_devient_jamais_un_credit():
    # Un funding negatif rapporte au long. Le compter comme un gain
    # financerait une position sur une recette qui peut s'inverser d'une
    # heure a l'autre. Plancher a zero : on ne facture pas, on ne credite pas.
    r = holding_cost_in_r(2000.0, 1990.0, -0.0005, 1.0, 24.0)
    assert r == 0.0


def test_duree_inconnue_rend_none_jamais_zero():
    assert holding_cost_in_r(2000.0, 1990.0, 0.0001, 1.0, None) is None


def test_taux_inconnu_rend_none_jamais_zero():
    assert holding_cost_in_r(2000.0, 1990.0, None, 1.0, 24.0) is None


def test_entree_ou_stop_invalides_rendent_none():
    assert holding_cost_in_r(0.0, 1990.0, 0.0001, 1.0, 24.0) is None
    assert holding_cost_in_r(2000.0, 2000.0, 0.0001, 1.0, 24.0) is None


def test_intervalle_nul_rend_none():
    # Une route sans echeance de funding ne se modelise pas en divisant par zero.
    assert holding_cost_in_r(2000.0, 1990.0, 0.0001, 0.0, 24.0) is None


def test_le_modele_de_cout_declare_son_intervalle_de_funding():
    assert CostModel().funding_interval_hours == 0.0
    assert CostModel(funding_interval_hours=1.0).funding_interval_hours == 1.0


def _base(tmp_path, lignes):
    db = tmp_path / "t.db"
    with sqlite3.connect(db) as c:
        c.execute("""CREATE TABLE shadow_setups (
            id INTEGER PRIMARY KEY, system_id TEXT, bar_timestamp TIMESTAMP,
            detected_at TIMESTAMP, outcome TEXT, exit_at TIMESTAMP)""")
        c.executemany(
            "INSERT INTO shadow_setups (system_id, bar_timestamp, detected_at,"
            " outcome, exit_at) VALUES (?,?,?,?,?)", lignes)
    return db


def test_median_holding_hours_rend_none_sous_l_echantillon_minimum(tmp_path):
    # Deux trades ne mesurent rien. Rendre leur mediane serait inventer.
    lignes = [("S", "2026-08-05T00:00:00+00:00", "2026-08-05T00:00:00+00:00",
               "TP1", "2026-08-05T06:00:00+00:00")] * 2
    db = _base(tmp_path, lignes)
    assert median_holding_hours("S", min_sample=30, db_path=db) is None


def test_median_holding_hours_mesure_quand_l_echantillon_suffit(tmp_path):
    lignes = [("S", "2026-08-05T00:00:00+00:00", "2026-08-05T00:00:00+00:00",
               "TP1", "2026-08-05T06:00:00+00:00")] * 30
    db = _base(tmp_path, lignes)
    assert median_holding_hours("S", min_sample=30, db_path=db) == pytest.approx(6.0)


def test_median_holding_hours_ignore_l_historique_corrompu(tmp_path):
    # Tout le shadow anterieur au 2026-08-05 est a ecarter : la deduplication
    # comptait un meme setup jusqu'a 960 fois. L'inclure biaiserait la mediane
    # vers le comportement d'une poignee de setups sur-representes.
    vieux = [("S", "2026-07-01T00:00:00+00:00", "2026-07-01T00:00:00+00:00",
              "TP1", "2026-07-01T01:00:00+00:00")] * 100
    recent = [("S", "2026-08-05T00:00:00+00:00", "2026-08-05T00:00:00+00:00",
               "TP1", "2026-08-05T06:00:00+00:00")] * 30
    db = _base(tmp_path, vieux + recent)
    assert median_holding_hours("S", min_sample=30, db_path=db) == pytest.approx(6.0)


def test_median_holding_hours_ignore_les_setups_non_resolus(tmp_path):
    lignes = [("S", "2026-08-05T00:00:00+00:00", "2026-08-05T00:00:00+00:00",
               "TP1", "2026-08-05T06:00:00+00:00")] * 30
    lignes += [("S", "2026-08-05T00:00:00+00:00", "2026-08-05T00:00:00+00:00",
                None, None)] * 50
    db = _base(tmp_path, lignes)
    assert median_holding_hours("S", min_sample=30, db_path=db) == pytest.approx(6.0)


def test_kraken_declare_son_intervalle_de_funding():
    from backend.services import bridge_destinations as bd

    k = bd._admin_kraken_destination()
    if k is not None:
        assert k.cost_model.funding_interval_hours == 1.0
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `python -m pytest backend/tests/test_cost_model_portage.py -q`
Expected: FAIL — `ImportError: cannot import name 'holding_cost_in_r'`

- [ ] **Step 3: Écrire l'implémentation dans `cost_model.py`**

Ajouter le champ à la dataclass `CostModel`, après `min_per_order` :

```python
    funding_interval_hours: float = 0.0
    """Périodicité de l'échéance de funding, en heures. ``0.0`` = route sans
    funding (CFD MT5, compte cash IBKR). Kraken Futures : 1,0."""
```

Puis, après `cost_in_r` :

```python
def holding_cost_in_r(
    entry: float,
    stop_loss: float,
    rate_per_interval: float | None,
    interval_hours: float,
    holding_hours: float | None,
) -> float | None:
    """Coût de **détention** d'une position, exprimé en unités de risque.

    Le scalping ne payait pas ce coût : une position ouverte et fermée dans
    la même heure ne traverse aucune échéance de funding. À 4h et 1d, si.

    Même structure que la part proportionnelle de ``cost_in_r`` — le risque
    en devise se simplifie, donc le coût **ne dépend pas de la taille de
    position**. Plus de capital ne sauve pas une route dont le portage est
    trop cher.

    ⚠️ **Plancher à zéro.** Un funding négatif rapporte au détenteur d'une
    position longue. Le compter comme un gain financerait une position sur
    une recette qui peut s'inverser d'une heure à l'autre. On ne facture pas
    un crédit, on l'ignore.

    Retourne ``None`` — jamais ``0.0`` — dès qu'une composante manque. Une
    durée de détention inconnue est le cas nominal tant qu'aucun échantillon
    propre postérieur au 2026-08-04 n'existe.
    """
    if rate_per_interval is None or holding_hours is None:
        return None
    if not entry or entry <= 0:
        return None
    distance = abs(entry - stop_loss)
    if distance <= 0:
        return None
    if interval_hours is None or interval_hours <= 0:
        return None
    if holding_hours < 0:
        return None

    echeances = holding_hours / interval_hours
    cout = (entry / distance) * rate_per_interval * echeances
    return max(0.0, cout)


# Échantillon minimal pour qu'une durée de détention médiane veuille dire
# quelque chose. Même ordre de grandeur que les autres seuils d'échantillon
# du projet, et volontairement au-dessus du bruit d'une poignée de trades.
HOLDING_MIN_SAMPLE = 30

# Tout le shadow antérieur à cette date est à écarter : la déduplication
# comptait un même setup jusqu'à 960 fois (corrigé le 2026-08-04). L'inclure
# biaiserait toute médiane vers le comportement des setups sur-représentés.
SHADOW_CLEAN_SINCE = "2026-08-05"


def median_holding_hours(
    system_id: str,
    min_sample: int = HOLDING_MIN_SAMPLE,
    db_path=None,
) -> float | None:
    """Durée de détention médiane observée pour un système, en heures.

    Mesurée sur les setups shadow **résolus** et **postérieurs à
    l'échantillon propre**. Retourne ``None`` sous ``min_sample`` : une
    médiane sur trois trades n'est pas une mesure, et l'inventer ferait
    passer une route non mesurée pour une route évaluable.
    """
    import sqlite3
    from pathlib import Path

    chemin = db_path
    if chemin is None:
        chemin = Path("/app/data/trades.db") if Path("/app").exists() else Path("trades.db")
    try:
        with sqlite3.connect(chemin) as c:
            rows = c.execute(
                """SELECT (julianday(exit_at) - julianday(bar_timestamp)) * 24.0
                     FROM shadow_setups
                    WHERE system_id = ?
                      AND outcome IS NOT NULL
                      AND exit_at IS NOT NULL
                      AND substr(bar_timestamp, 1, 10) >= ?
                 ORDER BY 1""",
                (system_id, SHADOW_CLEAN_SINCE),
            ).fetchall()
    except Exception:
        return None

    durees = [r[0] for r in rows if r[0] is not None and r[0] >= 0]
    if len(durees) < min_sample:
        return None
    n = len(durees)
    milieu = n // 2
    if n % 2:
        return float(durees[milieu])
    return float((durees[milieu - 1] + durees[milieu]) / 2.0)
```

⚠️ Le `SELECT` compare `substr(bar_timestamp, 1, 10)` et non `bar_timestamp >= datetime(...)`. `datetime('now')` rend `YYYY-MM-DD HH:MM:SS` avec un espace alors que `bar_timestamp` est en ISO avec un `T` — la comparaison de chaînes laisserait passer toute la journée.

- [ ] **Step 4: Exposer un accesseur public du funding Kraken**

Dans `backend/services/kraken_funding_scoring.py`, après `_get_funding_rate` :

```python
def get_funding_rate_for_pair(pair: str) -> float | None:
    """Taux de funding Kraken pour une paire interne (``"BTC/USD"``), ou ``None``.

    Accesseur public — le modèle de coût a besoin du taux comme **coût**,
    là où ce module l'utilisait jusqu'ici seulement comme feature de scoring.
    Best-effort : toute erreur rend ``None``, jamais ``0.0``.
    """
    try:
        symbol = _PAIR_TO_SYMBOL.get(pair)
        if not symbol:
            return None
        return _get_funding_rate(symbol)
    except Exception:
        return None
```

- [ ] **Step 5: Déclarer l'intervalle de funding sur Kraken**

Dans `backend/services/bridge_destinations.py`, `_admin_kraken_destination`, remplacer la déclaration du `cost_model` par :

```python
        # 0,05 % par jambe (taker). Donne 0,288 R au SL médian mesuré.
        # `funding_interval_hours=1.0` : les perpétuels Kraken règlent leur
        # funding toutes les heures. Vérifié au Step 6 contre l'API.
        cost_model=CostModel(
            proportional_rate_per_leg=0.0005,
            funding_interval_hours=1.0,
        ),
```

Faire de même pour `_admin_kraken_spot_destination` **seulement si** le spot Kraken est margé ; le spot non margé ne paie pas de funding, donc y laisser `funding_interval_hours=0.0`. Vérification au Step 6.

- [ ] **Step 6: Vérifier la périodicité de funding contre l'API Kraken**

Cette valeur ne doit pas rester une croyance. La confirmer une fois, et consigner l'observation dans le commentaire du Step 5 :

```bash
python -c "
import json, urllib.request
u='https://futures.kraken.com/derivatives/api/v3/tickers'
d=json.loads(urllib.request.urlopen(u, timeout=10).read())
t=[x for x in d.get('tickers',[]) if x.get('symbol')=='PF_XBTUSD']
print(json.dumps(t[0], indent=2)[:1200] if t else 'PF_XBTUSD absent')
"
```

Lire les champs `fundingRate` et `fundingRatePrediction`. Si la documentation ou la réponse indiquent une périodicité différente de l'heure, **corriger `funding_interval_hours` et le commentaire** avant de continuer — une périodicité fausse d'un facteur 4 fausse le coût de portage du même facteur.

- [ ] **Step 7: Brancher le portage dans `_cost_rejection`**

Dans `backend/services/mt5_bridge.py`, dans `_cost_rejection`, **après** le calcul de `cout_r` et **avant** l'appel à `exceeds_edge` :

```python
    # Coût de portage (2026-08-05). N'existe qu'à horizon long : une position
    # de scalping ne traverse aucune échéance de funding.
    #
    # La durée de détention attendue n'est pas connue tant qu'aucun
    # échantillon propre postérieur au 2026-08-04 n'existe. Elle vaut donc
    # `None`, ce qui rend le coût total non calculable — et `exceeds_edge`
    # bloque alors l'argent réel sans bloquer l'observation. C'est le
    # comportement voulu : ces routes restent en état TELEGRAM.
    if modele is not None and getattr(modele, "funding_interval_hours", 0.0) > 0:
        from backend.services.horizon import is_long as _is_long

        if _is_long(getattr(setup, "horizon", None)):
            from backend.services.cost_model import (
                holding_cost_in_r, median_holding_hours,
            )
            from backend.services.kraken_funding_scoring import (
                get_funding_rate_for_pair,
            )

            systeme = getattr(setup, "shadow_system_id", None)
            duree = median_holding_hours(systeme) if systeme else None
            portage = holding_cost_in_r(
                entry=getattr(setup, "entry_price", 0) or 0,
                stop_loss=getattr(setup, "stop_loss", 0) or 0,
                rate_per_interval=get_funding_rate_for_pair(getattr(setup, "pair", "")),
                interval_hours=float(modele.funding_interval_hours),
                holding_hours=duree,
            )
            # Un portage non calculable rend le coût TOTAL non calculable.
            # L'ignorer sous-estimerait la route exactement là où le modèle
            # doit être sévère.
            cout_r = None if portage is None else (cout_r or 0.0) + portage
```

⚠️ `setup.shadow_system_id` n'existe pas encore — il est ajouté par la tâche 5, qui estampille le `system_id` du générateur V2 sur le setup routé. Tant qu'il vaut `None`, `duree` vaut `None`, donc `portage` vaut `None`, donc le coût total vaut `None` : la route reste bloquée en argent réel. C'est le comportement voulu et il est déjà correct avant la tâche 5.

- [ ] **Step 8: Lancer les tests pour vérifier qu'ils passent**

Run: `python -m pytest backend/tests/test_cost_model_portage.py backend/tests/test_cost_model.py -q`
Expected: PASS

- [ ] **Step 9: Lancer la suite complète**

Run: `python -m pytest backend/tests -q`
Expected: 0 echec, 0 erreur, total en hausse

- [ ] **Step 10: Commit**

```bash
git add backend/services/cost_model.py backend/services/kraken_funding_scoring.py \
        backend/services/bridge_destinations.py backend/services/mt5_bridge.py \
        backend/tests/test_cost_model_portage.py
git commit -m "Cout de portage : une position tenue paie sa detention"
```

---

### Task 5 : Score et verdict du flux long-horizon

**La tâche qui décide si tout le reste sert à quelque chose.**

Les setups V2 sortent de `calculate_trade_setup`, qui ne renseigne pas `confidence_score` — il vaut donc `0.0`. Et le barème v2 conditionne sa composante Volatilité à `if volatility:` : enrichir sans `VolatilityData` plafonne le score à **60**, un point sous le seuil Telegram de **61**.

Autrement dit, brancher le flux long-horizon sans lui fournir sa propre volatilité le rendrait invisible **sans produire le moindre refus** — le motif exact qui a caché AAPL pendant deux jours.

La volatilité doit être calculée sur **les bougies de détection** (H4 agrégées, ou Daily), pas sur les bougies 5 minutes du flux V1 : ce serait mesurer une autre échelle de temps.

**Files:**
- Modify: `backend/services/backtest_engine.py:125-160` (`compute_volatility` accepte son étiquette)
- Modify: `backend/services/shadow_v2_core_long.py` (`run_shadow_log`)
- Modify: `backend/models/schemas.py` (`TradeSetup.shadow_system_id`)
- Test: `backend/tests/test_long_horizon_scoring.py`

**Interfaces:**
- Consomme : `enrich_trade_setup`, `compute_verdict`, `compute_volatility`, `TradeSetup.horizon` (tâche 2).
- Produit :
  - `compute_volatility(candles, pair, timeframe="1H")`
  - `TradeSetup.shadow_system_id: str | None` — lu par la tâche 4 (durée de détention) et la tâche 6 (dédup)
  - des setups V2 portant `confidence_score`, `verdict_action`, `horizon`, `shadow_system_id`

- [ ] **Step 1: Écrire le test qui échoue**

```python
# backend/tests/test_long_horizon_scoring.py
"""Le flux long-horizon doit être scoré, sinon il est invisible (2026-08-05).

`calculate_trade_setup` ne renseigne pas `confidence_score`. Et le barème v2
conditionne sa composante Volatilité à `if volatility:` — enrichir sans
`VolatilityData` plafonne le score à 60, un point SOUS le seuil Telegram de 61.

Brancher le flux long-horizon sans sa volatilité le rendrait invisible sans
produire le moindre refus.
"""
from datetime import datetime, timedelta, timezone

import pytest

from backend.models.schemas import (
    Candle, PatternDetection, PatternType, TradeDirection, TradeSetup,
)
from backend.services.backtest_engine import compute_volatility


def _bougies(n=60, base=2000.0, pas=1.0):
    t0 = datetime(2026, 8, 5, tzinfo=timezone.utc)
    return [
        Candle(
            timestamp=t0 + timedelta(hours=4 * i),
            open=base + i * pas, high=base + i * pas + 5,
            low=base + i * pas - 5, close=base + i * pas + 1, volume=100,
        )
        for i in range(n)
    ]


def _setup(horizon="4h"):
    pattern = PatternDetection(
        pair="XAU/USD", pattern=PatternType.MOMENTUM_UP, confidence=0.9,
        description="momentum haussier", detected_at=datetime.now(timezone.utc),
    )
    return TradeSetup(
        pair="XAU/USD", direction=TradeDirection.BUY, pattern=pattern,
        entry_price=2000.0, stop_loss=1990.0, take_profit_1=2015.0,
        take_profit_2=2025.0, risk_pips=10.0, reward_pips_1=15.0,
        reward_pips_2=25.0, risk_reward_1=1.5, risk_reward_2=2.5,
        message="test", timestamp=datetime.now(timezone.utc), horizon=horizon,
    )


def test_le_piege_sans_volatilite_le_score_plafonne_a_60(monkeypatch):
    # CE test documente POURQUOI la tache existe. S'il se met a echouer,
    # c'est que le bareme a change : relire la tache avant de le "reparer".
    monkeypatch.setenv("CONFIDENCE_SCORE_V2", "true")
    from backend.services import analysis_engine

    monkeypatch.setattr(analysis_engine, "CONFIDENCE_SCORE_V2", True, raising=False)
    enrichi = analysis_engine.enrich_trade_setup(_setup(), None, None, [])
    assert enrichi.confidence_score <= 60.0, (
        "sans volatilite le bareme v2 plafonne a 60 — un point sous le seuil "
        "Telegram de 61"
    )


def test_avec_sa_volatilite_le_score_peut_depasser_le_seuil_telegram():
    from backend.services import analysis_engine

    vol = compute_volatility(_bougies(), "XAU/USD", timeframe="4h")
    enrichi = analysis_engine.enrich_trade_setup(_setup(), vol, None, [])
    assert enrichi.confidence_score > 60.0


def test_compute_volatility_etiquette_le_timeframe_qu_on_lui_donne():
    # Meme lecon que le correctif d'etiquette du shadow V1 : une etiquette
    # qui ment se propage. Ici elle irait dans le score d'un setup 4h en
    # pretendant decrire du 1H.
    vol = compute_volatility(_bougies(), "XAU/USD", timeframe="4h")
    assert vol.timeframe == "4h"


def test_compute_volatility_garde_son_defaut_historique():
    # Les appelants existants ne passent pas de timeframe et doivent
    # continuer a produire "1H".
    assert compute_volatility(_bougies(), "XAU/USD").timeframe == "1H"


def test_compute_volatility_etiquette_meme_sur_serie_trop_courte():
    # La branche "moins de 15 bougies" construisait un VolatilityData en dur
    # avec timeframe="1H" — elle doit honorer le parametre elle aussi.
    assert compute_volatility(_bougies(3), "XAU/USD", timeframe="1d").timeframe == "1d"


def test_le_setup_porte_le_systeme_qui_l_a_produit():
    s = _setup()
    s.shadow_system_id = "V2_CORE_LONG_XAUUSD_4H"
    assert s.shadow_system_id == "V2_CORE_LONG_XAUUSD_4H"


def test_shadow_system_id_vaut_none_par_defaut():
    assert _setup().shadow_system_id is None


def test_run_shadow_log_score_et_juge_avant_de_persister():
    # Verification par inspection : l'enrichissement et le verdict doivent
    # exister dans la fonction, et la volatilite doit etre calculee sur les
    # bougies de detection (signal_candles), pas ailleurs.
    import inspect

    from backend.services import shadow_v2_core_long

    src = inspect.getsource(shadow_v2_core_long.run_shadow_log)
    assert "enrich_trade_setup" in src, "le flux V2 n'est pas score"
    assert "compute_verdict" in src, "le flux V2 n'a pas de verdict"
    assert "compute_volatility(signal_candles" in src, (
        "la volatilite doit etre calculee sur les bougies de detection"
    )
    assert "shadow_system_id" in src
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `python -m pytest backend/tests/test_long_horizon_scoring.py -q`
Expected: FAIL — `compute_volatility() got an unexpected keyword argument 'timeframe'`

- [ ] **Step 3: Rendre `compute_volatility` honnête sur son étiquette**

Dans `backend/services/backtest_engine.py`, remplacer la signature et les deux constructions de `VolatilityData` :

```python
def compute_volatility(
    candles_1h: list[Candle], pair: str, timeframe: str = "1H",
) -> VolatilityData:
    """Volatility via ATR : current (14-bar) vs average (50-bar). Ratio
    classe en LOW/MEDIUM/HIGH.

    ``timeframe`` est purement descriptif : le calcul est agnostique à
    l'échelle de temps, seule l'étiquette change. Le défaut ``"1H"`` préserve
    les appelants existants.

    ⚠️ L'étiquette doit dire la vérité. Elle finit dans le score d'un setup,
    et une étiquette fausse s'y propage silencieusement — même leçon que le
    correctif d'horizon du shadow V1 (commit ``057def9``).
    """
```

Dans les **deux** `return VolatilityData(...)` de la fonction, remplacer `timeframe="1H"` par `timeframe=timeframe`.

- [ ] **Step 4: Ajouter `shadow_system_id` au schéma**

Dans `backend/models/schemas.py`, juste après le champ `horizon` :

```python
    # Système générateur pour les setups issus du shadow V2 long-horizon
    # ("V2_CORE_LONG_XAUUSD_4H"…). Sert à retrouver la durée de détention
    # médiane du système (coût de portage) et à dédupliquer les notifications.
    shadow_system_id: str | None = None
```

- [ ] **Step 5: Scorer et juger le flux V2**

Dans `backend/services/shadow_v2_core_long.py`, dans `run_shadow_log`, remplacer le bloc d'estampille ajouté à la tâche 2 par :

```python
            # Horizon d'analyse : ce setup a été détecté sur des bougies `tf`.
            # Posé AVANT l'enrichissement pour qu'il ne soit pas écrasé.
            from backend.services.horizon import normalize as _normalize_horizon
            setup.horizon = _normalize_horizon(tf)
            setup.shadow_system_id = cfg["system_id"]

            # Score et verdict (2026-08-05). `calculate_trade_setup` ne
            # renseigne pas `confidence_score` : sans cet enrichissement, tout
            # le flux long-horizon vaudrait 0 et serait refusé en
            # `below_confidence`.
            #
            # ⚠️ La volatilité est calculée sur `signal_candles`, les bougies
            # sur lesquelles le setup a été DÉTECTÉ. Le barème v2 conditionne
            # sa composante Volatilité à `if volatility:` — sans elle le score
            # plafonne à 60, soit un point sous le seuil Telegram de 61, et le
            # flux serait invisible sans produire le moindre refus.
            try:
                from backend.services.analysis_engine import enrich_trade_setup
                from backend.services.backtest_engine import compute_volatility
                from backend.services.coaching import compute_verdict

                volatilite = compute_volatility(signal_candles, pair, timeframe=tf)
                enrich_trade_setup(setup, volatilite, None, [])
                verdict = compute_verdict(setup, volatility=volatilite, events=[])
                setup.verdict_action = verdict.get("action", "")
                setup.verdict_summary = verdict.get("summary", "") or ""
            except Exception as e:
                # Best-effort : un échec de scoring ne doit pas empêcher la
                # persistance shadow, qui reste la source de mesure.
                logger.warning(f"shadow: scoring {cfg['system_id']} {pair} a échoué: {e}")
```

- [ ] **Step 6: Lancer les tests pour vérifier qu'ils passent**

Run: `python -m pytest backend/tests/test_long_horizon_scoring.py -q`
Expected: PASS (8 tests)

- [ ] **Step 7: Vérifier par mutation que le piège est bien gardé**

Remplacer temporairement `compute_volatility(signal_candles, pair, timeframe=tf)` par `None` dans le Step 5, puis :

Run: `python -m pytest backend/tests/test_long_horizon_scoring.py -q`
Expected: FAIL sur `test_run_shadow_log_score_et_juge_avant_de_persister`

Puis **rétablir**.

- [ ] **Step 8: Lancer la suite complète**

Run: `python -m pytest backend/tests -q`
Expected: 0 echec, 0 erreur, total en hausse

⚠️ Surveiller `backend/tests/test_shadow_v2_core_long.py` et `test_phase4_e2e.py` : ils appellent `run_shadow_log` et vont maintenant traverser l'enrichissement. S'ils échouent sur un appel réseau (macro, VIX), c'est que le scoring tente une couche externe — le `try/except` du Step 5 doit l'absorber. Si l'échec persiste, lire la trace avant de neutraliser le test.

- [ ] **Step 9: Commit**

```bash
git add backend/services/backtest_engine.py backend/services/shadow_v2_core_long.py \
        backend/models/schemas.py backend/tests/test_long_horizon_scoring.py
git commit -m "Le flux long-horizon est score sur ses propres bougies"
```

---

### Task 6 : Rendre le flux long-horizon visible, sans rallumer le reste

Critère 3 de la spec : les setups 4h atteignent l'état `TELEGRAM` et sont visibles.

Le chemin évident — `send_setup` — est **fermé** : `TELEGRAM_SETUP_VERDICTS` vaut `` (vide) en production, ce qui éteint toutes les alertes setup temps-réel. Le rallumer produirait ~2000 messages/jour.

Le flux long-horizon, lui, est minuscule : 244 setups `4h` et 50 `1d` sur toute la période observée, soit quelques-uns par jour. Il mérite son propre canal, borné, indépendant du gate global.

La déduplication est gratuite : `_persist_setup` respecte `UNIQUE (system_id, bar_timestamp)` et rend `True` seulement pour une ligne réellement nouvelle. Notifier sur cette valeur de retour suffit — aucun état de dédup à inventer.

**Files:**
- Modify: `config/settings.py` (deux réglages)
- Modify: `backend/services/telegram_service.py` (émetteur dédié)
- Modify: `backend/services/shadow_v2_core_long.py` (appel après persistance réussie)
- Test: `backend/tests/test_telegram_long_horizon.py`

**Interfaces:**
- Consomme : `TradeSetup.horizon`, `.shadow_system_id`, `.confidence_score`, `.verdict_action` (tâches 2 et 5) ; `send_sales_text` (existant, `telegram_service.py:192`).
- Produit : `telegram_service.send_long_horizon_setup(setup) -> bool`

- [ ] **Step 1: Écrire le test qui échoue**

```python
# backend/tests/test_telegram_long_horizon.py
"""Canal dédié au flux long-horizon (2026-08-05).

`send_setup` est fermé en production (TELEGRAM_SETUP_VERDICTS vide) et le
rallumer produirait ~2000 messages/jour. Le flux long-horizon est minuscule
— quelques setups par jour — et obtient son propre canal.
"""
from datetime import datetime, timezone

import pytest

from backend.models.schemas import (
    PatternDetection, PatternType, TradeDirection, TradeSetup,
)


def _setup(horizon="4h", score=75.0, verdict="TAKE"):
    pattern = PatternDetection(
        pair="XAU/USD", pattern=PatternType.MOMENTUM_UP, confidence=0.9,
        description="momentum haussier", detected_at=datetime.now(timezone.utc),
    )
    s = TradeSetup(
        pair="XAU/USD", direction=TradeDirection.BUY, pattern=pattern,
        entry_price=2000.0, stop_loss=1990.0, take_profit_1=2015.0,
        take_profit_2=2025.0, risk_pips=10.0, reward_pips_1=15.0,
        reward_pips_2=25.0, risk_reward_1=1.5, risk_reward_2=2.5,
        message="test", timestamp=datetime.now(timezone.utc), horizon=horizon,
    )
    s.confidence_score = score
    s.verdict_action = verdict
    s.shadow_system_id = "V2_CORE_LONG_XAUUSD_4H"
    return s


@pytest.mark.asyncio
async def test_un_setup_long_horizon_part(monkeypatch):
    envoyes = []
    from backend.services import telegram_service as tg

    async def _faux(text, parse_mode="HTML"):
        envoyes.append(text)
        return True

    monkeypatch.setattr(tg, "send_sales_text", _faux)
    monkeypatch.setattr(tg, "TELEGRAM_LONG_HORIZON_ENABLED", True, raising=False)
    monkeypatch.setattr(tg, "TELEGRAM_LONG_HORIZON_MIN_CONFIDENCE", 61.0, raising=False)

    assert await tg.send_long_horizon_setup(_setup()) is True
    assert len(envoyes) == 1
    assert "XAU/USD" in envoyes[0]
    assert "4h" in envoyes[0]


@pytest.mark.asyncio
async def test_un_setup_de_scalping_ne_part_pas_par_ce_canal(monkeypatch):
    # Ce canal existe pour le flux long-horizon. Y laisser passer le
    # scalping recreerait les ~2000 messages/jour qu'on evite.
    from backend.services import telegram_service as tg

    monkeypatch.setattr(tg, "TELEGRAM_LONG_HORIZON_ENABLED", True, raising=False)
    assert await tg.send_long_horizon_setup(_setup(horizon="5min")) is False


@pytest.mark.asyncio
async def test_sous_le_seuil_de_confiance_rien_ne_part(monkeypatch):
    from backend.services import telegram_service as tg

    monkeypatch.setattr(tg, "TELEGRAM_LONG_HORIZON_ENABLED", True, raising=False)
    monkeypatch.setattr(tg, "TELEGRAM_LONG_HORIZON_MIN_CONFIDENCE", 61.0, raising=False)
    assert await tg.send_long_horizon_setup(_setup(score=42.0)) is False


@pytest.mark.asyncio
async def test_le_drapeau_coupe_le_canal(monkeypatch):
    from backend.services import telegram_service as tg

    monkeypatch.setattr(tg, "TELEGRAM_LONG_HORIZON_ENABLED", False, raising=False)
    assert await tg.send_long_horizon_setup(_setup()) is False


@pytest.mark.asyncio
async def test_le_canal_global_reste_ferme(monkeypatch):
    # Garde-fou : ce canal ne doit PAS dependre de TELEGRAM_SETUP_VERDICTS,
    # et surtout ne pas le rallumer.
    import inspect

    from backend.services import telegram_service as tg

    src = inspect.getsource(tg.send_long_horizon_setup)
    assert "TELEGRAM_SETUP_VERDICTS" not in src


@pytest.mark.asyncio
async def test_un_echec_d_envoi_ne_leve_pas(monkeypatch):
    from backend.services import telegram_service as tg

    async def _casse(text, parse_mode="HTML"):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(tg, "send_sales_text", _casse)
    monkeypatch.setattr(tg, "TELEGRAM_LONG_HORIZON_ENABLED", True, raising=False)
    monkeypatch.setattr(tg, "TELEGRAM_LONG_HORIZON_MIN_CONFIDENCE", 61.0, raising=False)
    assert await tg.send_long_horizon_setup(_setup()) is False


@pytest.mark.asyncio
async def test_le_message_est_echappe_en_html(monkeypatch):
    # send_sales_text envoie en HTML : un `<` non echappe fait rejeter le
    # message entier par l'API Telegram, silencieusement du point de vue
    # de l'appelant.
    envoyes = []
    from backend.services import telegram_service as tg

    async def _faux(text, parse_mode="HTML"):
        envoyes.append(text)
        return True

    monkeypatch.setattr(tg, "send_sales_text", _faux)
    monkeypatch.setattr(tg, "TELEGRAM_LONG_HORIZON_ENABLED", True, raising=False)
    monkeypatch.setattr(tg, "TELEGRAM_LONG_HORIZON_MIN_CONFIDENCE", 61.0, raising=False)

    s = _setup()
    s.pair = "A<B>&C"
    await tg.send_long_horizon_setup(s)
    assert "<B>" not in envoyes[0]
    assert "&lt;" in envoyes[0] or "&amp;" in envoyes[0]


def test_le_flux_v2_notifie_seulement_les_lignes_nouvelles():
    # `_persist_setup` respecte UNIQUE (system_id, bar_timestamp) et rend
    # True seulement pour une ligne reellement nouvelle. Notifier sur cette
    # valeur suffit — aucun etat de dedup a inventer.
    import inspect

    from backend.services import shadow_v2_core_long

    src = inspect.getsource(shadow_v2_core_long.run_shadow_log)
    assert "send_long_horizon_setup" in src
    i_persist = src.index("if _persist_setup(")
    i_notif = src.index("send_long_horizon_setup")
    assert i_persist < i_notif, "la notification doit suivre la persistance reussie"
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `python -m pytest backend/tests/test_telegram_long_horizon.py -q`
Expected: FAIL — `AttributeError: module ... has no attribute 'send_long_horizon_setup'`

- [ ] **Step 3: Ajouter les deux réglages**

Dans `config/settings.py`, à la suite du bloc `TELEGRAM_SETUP_VERDICTS` :

```python
# ── Canal long-horizon (2026-08-05) ──────────────────────────────────────
# Le flux 4h/1d obtient son propre canal parce que `TELEGRAM_SETUP_VERDICTS`
# est vide en production : les alertes setup temps-réel sont éteintes et les
# rallumer produirait ~2000 messages/jour. Le flux long-horizon, lui, pèse
# quelques setups par jour.
TELEGRAM_LONG_HORIZON_ENABLED = os.getenv(
    "TELEGRAM_LONG_HORIZON_ENABLED", "true"
).strip().lower() in ("1", "true", "yes")
TELEGRAM_LONG_HORIZON_MIN_CONFIDENCE = float(
    os.getenv("TELEGRAM_LONG_HORIZON_MIN_CONFIDENCE", "61")
)
```

- [ ] **Step 4: Écrire l'émetteur**

Dans `backend/services/telegram_service.py`, après `send_sales_text`, et en ajoutant les deux noms à l'import depuis `config.settings` en tête de fichier :

```python
async def send_long_horizon_setup(setup) -> bool:
    """Annonce un setup 4h / 1d sur le canal sales, hors gate global.

    Ce canal est **indépendant** de `TELEGRAM_SETUP_VERDICTS`, qui vaut `` en
    production et éteint toutes les alertes setup temps-réel. Le rallumer
    produirait ~2000 messages/jour ; le flux long-horizon en pèse quelques-uns.

    Rend `True` si un message est parti. Best-effort : jamais d'exception
    propagée — le shadow log ne doit pas dépendre de Telegram.
    """
    try:
        if not TELEGRAM_LONG_HORIZON_ENABLED:
            return False

        from backend.services.horizon import is_long as _is_long

        if not _is_long(getattr(setup, "horizon", None)):
            return False
        score = getattr(setup, "confidence_score", None) or 0
        if score < TELEGRAM_LONG_HORIZON_MIN_CONFIDENCE:
            return False

        import html as _html

        def _e(v) -> str:
            return _html.escape(str(v), quote=False)

        direction = getattr(getattr(setup, "direction", None), "value", "")
        lignes = [
            f"<b>Horizon {_e(setup.horizon)} — {_e(setup.pair)}</b>",
            f"{_e(str(direction).upper())} · confiance {score:.0f}/100"
            f" · verdict {_e(getattr(setup, 'verdict_action', '') or 'n/a')}",
            f"Entrée {setup.entry_price:.4f} · SL {setup.stop_loss:.4f}"
            f" · TP1 {setup.take_profit_1:.4f}",
            f"<i>{_e(getattr(setup, 'shadow_system_id', '') or '')}</i>",
            "",
            "Observation seule — aucune position n'est ouverte.",
        ]
        return bool(await send_sales_text("\n".join(lignes), parse_mode="HTML"))
    except Exception as e:
        logger.warning(f"send_long_horizon_setup a échoué: {e}")
        return False
```

⚠️ `send_sales_text` émet en **HTML**, pas en Markdown. Ne pas réutiliser `md_safe()` ici : c'est `html.escape` qu'il faut. Un `<` non échappé fait rejeter le message entier par l'API Telegram, et l'appelant ne voit rien.

- [ ] **Step 5: Notifier depuis le flux V2**

Dans `backend/services/shadow_v2_core_long.py`, dans le bloc `if _persist_setup(...)` de `run_shadow_log`, après le `logger.info` existant du nouveau setup :

```python
                # Notification long-horizon. Placée sous `_persist_setup`, qui
                # rend True seulement pour une ligne réellement nouvelle
                # (UNIQUE system_id, bar_timestamp) : la déduplication est
                # celle de la base, il n'y a pas d'état à inventer.
                try:
                    from backend.services.telegram_service import (
                        send_long_horizon_setup,
                    )
                    await send_long_horizon_setup(setup)
                except Exception as e:
                    logger.warning(f"shadow: notif long-horizon a échoué: {e}")
```

- [ ] **Step 6: Lancer les tests pour vérifier qu'ils passent**

Run: `python -m pytest backend/tests/test_telegram_long_horizon.py -q`
Expected: PASS (8 tests)

- [ ] **Step 7: Lancer la suite complète**

Run: `python -m pytest backend/tests -q`
Expected: 0 echec, 0 erreur, total en hausse

- [ ] **Step 8: Commit**

```bash
git add config/settings.py backend/services/telegram_service.py \
        backend/services/shadow_v2_core_long.py backend/tests/test_telegram_long_horizon.py
git commit -m "Canal long-horizon : quelques setups par jour, sans rallumer les 2000"
```

---

### Task 7 : Les vetos qui réduisaient deviennent bloquants

Principe de la spec §3.5 : **à horizon long, un veto qui réduit la taille ne suffit plus.** Un événement connu à l'avance et tombant pendant la détention doit empêcher l'ouverture, puisqu'on ne peut plus sortir avant.

Deux règles, deux codes de refus publics.

**Files:**
- Modify: `backend/services/earnings_veto.py` (fonction bloquante)
- Modify: `backend/services/mt5_bridge.py` (portes au dispatch, ≈ ligne 405)
- Modify: `backend/services/rejection_service.py` (libellés)
- Test: `backend/tests/test_vetos_horizon_long.py`

**Interfaces:**
- Consomme : `horizon.is_long` (tâche 1), `TradeSetup.horizon` (tâche 2), `earnings_calendar_service` (existant).
- Produit :
  - `earnings_veto.blocks_at_long_horizon(pair, now=None) -> bool`
  - codes `earnings_blackout`, `weekend_hold_blocked`

- [ ] **Step 1: Écrire le test qui échoue**

```python
# backend/tests/test_vetos_horizon_long.py
"""À horizon long, un veto qui réduit ne suffit plus (2026-08-05).

Une position de scalping se ferme avant l'événement. Une position tenue
quatre heures ou un jour le traverse. Le multiplicateur ×0,60 devient donc
un refus, et le gel énergie du vendredi se généralise à toute détention
qui franchit la clôture.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from backend.services.mt5_bridge import _event_rejection


def _setup(horizon="4h", pair="AAPL"):
    return SimpleNamespace(pair=pair, horizon=horizon, entry_price=200.0,
                           stop_loss=198.0, confidence_score=80.0)


def _dest():
    return SimpleNamespace(destination_id="admin_live", auto_exec_enabled=True)


# ── Earnings ────────────────────────────────────────────────────────────

def test_earnings_bloque_a_horizon_long(monkeypatch):
    from backend.services import earnings_veto

    monkeypatch.setattr(earnings_veto, "blocks_at_long_horizon",
                        lambda pair, now=None: True)
    assert _event_rejection(_setup("4h"), _dest()) == "earnings_blackout"


def test_earnings_ne_bloque_pas_a_horizon_court(monkeypatch):
    # En scalping la position se ferme avant. Le veto doux existant
    # (multiplicateur x0,60) continue de s'appliquer en amont, au scoring.
    from backend.services import earnings_veto

    monkeypatch.setattr(earnings_veto, "blocks_at_long_horizon",
                        lambda pair, now=None: True)
    assert _event_rejection(_setup("5min"), _dest()) is None


def test_hors_fenetre_earnings_rien_ne_bloque(monkeypatch):
    from backend.services import earnings_veto

    monkeypatch.setattr(earnings_veto, "blocks_at_long_horizon",
                        lambda pair, now=None: False)
    assert _event_rejection(_setup("4h"), _dest()) is None


def test_blocks_at_long_horizon_est_best_effort(monkeypatch):
    # Le calendrier earnings depend de yfinance. Indisponible, il ne doit
    # ni lever ni bloquer tout le flux equity.
    from backend.services import earnings_veto

    def _casse(*a, **k):
        raise RuntimeError("yfinance down")

    monkeypatch.setattr(earnings_veto, "_next_earnings_at", _casse, raising=False)
    assert earnings_veto.blocks_at_long_horizon("AAPL") is False


# ── Gel de week-end ─────────────────────────────────────────────────────

def _vendredi_soir():
    # 2026-08-07 est un vendredi. 19h UTC > seuil par defaut de 18h.
    return datetime(2026, 8, 7, 19, 0, tzinfo=timezone.utc)


def _mardi_midi():
    return datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)


def test_detention_longue_bloquee_le_vendredi_soir(monkeypatch):
    monkeypatch.setattr("backend.services.mt5_bridge._now_utc", _vendredi_soir,
                        raising=False)
    assert _event_rejection(_setup("4h", "XAU/USD"), _dest()) == "weekend_hold_blocked"


def test_scalping_non_bloque_le_vendredi_soir(monkeypatch):
    # Le gel energie existant continue de traiter WTI a part ; le scalping
    # sur les autres classes se ferme avant la cloture.
    monkeypatch.setattr("backend.services.mt5_bridge._now_utc", _vendredi_soir,
                        raising=False)
    assert _event_rejection(_setup("5min", "XAU/USD"), _dest()) is None


def test_detention_longue_non_bloquee_en_semaine(monkeypatch):
    monkeypatch.setattr("backend.services.mt5_bridge._now_utc", _mardi_midi,
                        raising=False)
    assert _event_rejection(_setup("4h", "XAU/USD"), _dest()) is None


def test_la_crypto_ne_subit_pas_le_gel_de_week_end(monkeypatch):
    # Le marche crypto ne ferme pas : il n'y a pas de gap de reouverture.
    monkeypatch.setattr("backend.services.mt5_bridge._now_utc", _vendredi_soir,
                        raising=False)
    assert _event_rejection(_setup("4h", "BTC/USD"), _dest()) is None


# ── Traçabilité et branchement ──────────────────────────────────────────

def test_les_codes_sont_publics_et_libelles():
    from backend.services.rejection_service import REASON_LABELS_FR

    for code in ("earnings_blackout", "weekend_hold_blocked"):
        assert not code.startswith("_")
        assert code in REASON_LABELS_FR


def test_la_porte_est_reellement_appelee():
    import inspect

    from backend.services import mt5_bridge

    assert "_event_rejection" in inspect.getsource(mt5_bridge._check_rejection)
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `python -m pytest backend/tests/test_vetos_horizon_long.py -q`
Expected: FAIL — `ImportError: cannot import name '_event_rejection'`

- [ ] **Step 3: Rendre le veto earnings capable de bloquer**

Dans `backend/services/earnings_veto.py`, ajouter après `apply_earnings_veto` :

```python
def _next_earnings_at(pair: str):
    """Prochaine publication de résultats pour cette paire, ou ``None``.

    Isolé pour être remplaçable en test — le calendrier dépend de yfinance,
    donc du réseau.
    """
    from backend.services import earnings_calendar_service

    return earnings_calendar_service.get_next_earnings(pair)


def blocks_at_long_horizon(pair: str, now: Optional[datetime] = None) -> bool:
    """``True`` si une position tenue à horizon long traverserait des earnings.

    À horizon court, le veto reste **doux** : la position se ferme avant la
    publication, et le multiplicateur ×0,60 appliqué au scoring suffit. À 4h
    ou 1d, la position traverse l'événement et ne peut plus être fermée
    avant — un veto qui réduit la taille ne protège plus de rien.

    Best-effort : toute erreur rend ``False``. Le calendrier dépend de
    yfinance, et une indisponibilité ne doit pas couper tout le flux equity.
    """
    try:
        from config.settings import EARNINGS_VETO_ENABLED

        if not EARNINGS_VETO_ENABLED:
            return False
        from config.settings import asset_class_for

        if asset_class_for(pair) != _EQUITY_CLASS:
            return False
        maintenant = now or datetime.now(timezone.utc)
        prochain = _next_earnings_at(pair)
        if prochain is None:
            return False
        delta = (prochain - maintenant).total_seconds() / 3600.0
        return 0 <= delta <= _WINDOW_HOURS
    except Exception as e:
        logger.debug(f"earnings_veto.blocks_at_long_horizon({pair}): {e}")
        return False
```

`earnings_calendar_service.get_next_earnings(symbol) -> Optional[datetime]` existe sous ce nom exact (`backend/services/earnings_calendar_service.py:176`) et rend un `datetime` conscient du fuseau ou `None`. Son voisin `get_last_earnings` couvre la fenêtre post-publication, non utilisée ici : après les résultats, le gap a déjà eu lieu et une nouvelle position ne le traverse plus.

- [ ] **Step 4: Écrire la porte événementielle**

Dans `backend/services/mt5_bridge.py`, avant `_check_rejection` :

```python
def _now_utc():
    """Horloge isolée pour que les portes temporelles soient testables."""
    from datetime import datetime as _dt, timezone as _tz

    return _dt.now(_tz.utc)


def _event_rejection(setup, dest) -> str | None:
    """Refuse une détention longue qui traverserait un événement connu.

    Principe : à horizon long, un veto qui réduit la taille ne suffit plus.
    Un événement connu à l'avance et tombant pendant la détention doit
    empêcher l'ouverture, puisqu'on ne peut plus sortir avant.

    Ne s'applique qu'aux horizons longs : en scalping la position se ferme
    avant l'événement, et les vetos doux existants continuent de jouer au
    scoring.
    """
    from backend.services.horizon import is_long as _is_long

    if not _is_long(getattr(setup, "horizon", None)):
        return None
    pair = getattr(setup, "pair", "") or ""

    # 1. Earnings — la publication tombe pendant la détention.
    try:
        from backend.services import earnings_veto

        if earnings_veto.blocks_at_long_horizon(pair, now=_now_utc()):
            return "earnings_blackout"
    except Exception as e:
        logger.debug(f"_event_rejection earnings {pair}: {e}")

    # 2. Gap de week-end — généralisation du gel énergie du vendredi
    #    (incident 2026-08-03 : 2 positions WTI tenues 3 nuits, SL à 83,15
    #    exécuté à 79,57 au gap de réouverture, −20,75 € au lieu de −4 à −5).
    #    Une détention ouverte vendredi soir franchit la clôture par
    #    construction, quelle que soit la classe d'actif qui ferme.
    try:
        from config.settings import (
            NO_FRIDAY_LATE_OPEN_ENERGY_HOUR_UTC,
            asset_class_for as _acf,
        )
    except Exception:
        NO_FRIDAY_LATE_OPEN_ENERGY_HOUR_UTC = 18

        def _acf(_p):
            return "forex"

    if _acf(pair) != "crypto":
        # Le marché crypto ne ferme pas : pas de gap de réouverture.
        maintenant = _now_utc()
        if maintenant.weekday() == 4 and maintenant.hour >= NO_FRIDAY_LATE_OPEN_ENERGY_HOUR_UTC:
            return "weekend_hold_blocked"
    return None
```

- [ ] **Step 5: Brancher la porte**

Dans `backend/services/mt5_bridge.py`, dans `_check_rejection`, **juste après** la porte d'horizon ajoutée à la tâche 3 :

```python
    # Portes événementielles (2026-08-05). Après l'horizon — inutile
    # d'interroger le calendrier earnings pour un setup que la route ne sert
    # pas — et avant la porte de coût, qui est la plus chère.
    event_reason = _event_rejection(setup, dest)
    if event_reason:
        return event_reason
```

- [ ] **Step 6: Déclarer les libellés**

Dans `backend/services/rejection_service.py`, `REASON_LABELS_FR` :

```python
    "earnings_blackout": "résultats publiés pendant la détention",
    "weekend_hold_blocked": "détention à travers le week-end",
```

- [ ] **Step 7: Lancer les tests pour vérifier qu'ils passent**

Run: `python -m pytest backend/tests/test_vetos_horizon_long.py -q`
Expected: PASS (11 tests)

- [ ] **Step 8: Lancer la suite complète**

Run: `python -m pytest backend/tests -q`
Expected: 0 echec, 0 erreur, total en hausse

- [ ] **Step 9: Commit**

```bash
git add backend/services/earnings_veto.py backend/services/mt5_bridge.py \
        backend/services/rejection_service.py backend/tests/test_vetos_horizon_long.py
git commit -m "A horizon long, un veto qui reduit la taille devient un refus"
```

---

### Task 8 : Vérification en production

Aucun fichier modifié. Déploiement et observation. Aucun argent n'est engagé : le flux long-horizon s'arrête à Telegram, et les routes Kraken restent bloquées par la porte de coût du plan 1.

**Interfaces:**
- Consomme : tout ce qui précède.
- Produit : la preuve que le flux 4h atteint Telegram, que le 5 min crypto est coupé par la porte la moins chère, et que MT5 est intact.

- [ ] **Step 1: Pousser et déployer**

```bash
git push origin main
bash deploy-v2.sh
```

Le push est obligatoire avant le déploiement : `deploy-v2.sh` fait un `git pull` côté serveur.

- [ ] **Step 2: Vérifier que les destinations déclarent bien leurs horizons**

```bash
ssh -i scalping-key.pem ec2-user@100.103.107.75 \
  "sudo docker exec scalping-radar python3 -c \"
from backend.services import bridge_destinations as bd
for n in dir(bd):
    if n.startswith('_admin'):
        d = getattr(bd, n)()
        print(f'{n:38} ->', 'desactive' if d is None else
              f'{d.destination_id} horizons={d.allowed_horizons}')
\""
```

Attendu : `admin_live` et `admin_legacy` à `frozenset({'5min'})`, `admin_kraken` à `frozenset({'4h', '1d'})`.

- [ ] **Step 3: Observer les refus d'horizon pendant une heure**

```bash
ssh -i scalping-key.pem ec2-user@100.103.107.75 \
  "sudo docker exec scalping-radar python3 -c \"
import sqlite3
c = sqlite3.connect('/app/data/trades.db')
for r in c.execute('''SELECT destination_id, reason_code, COUNT(*)
                        FROM signal_rejections
                       WHERE substr(created_at,1,10) >= date('now','-1 day')
                         AND reason_code IN ('horizon_not_allowed',
                             'fees_exceed_edge','earnings_blackout',
                             'weekend_hold_blocked')
                    GROUP BY 1,2 ORDER BY 3 DESC'''):
    print(r)
\""
```

Attendu : `admin_kraken | horizon_not_allowed | n` avec n > 0 — le flux crypto 5 min est désormais coupé par la porte la moins chère, **avant** la porte de coût.

⚠️ Le comptage de `fees_exceed_edge` sur `admin_kraken` doit **tomber à zéro ou presque** : les signaux qui l'atteignaient étaient des setups 5 min, maintenant arrêtés en amont. Ce n'est pas une régression, c'est le résultat attendu.

⚠️ Piège de dates : `datetime('now')` rend `YYYY-MM-DD HH:MM:SS` avec un espace alors que `created_at` est en ISO avec un `T`. D'où le `substr(created_at,1,10)`.

- [ ] **Step 4: Vérifier que MT5 n'est pas affecté**

```bash
ssh -i scalping-key.pem ec2-user@100.103.107.75 \
  "sudo docker exec scalping-radar python3 -c \"
import sqlite3
c = sqlite3.connect('/app/data/trades.db')
for r in c.execute('''SELECT reason_code, COUNT(*) FROM signal_rejections
                       WHERE destination_id IN ('admin_live','admin_legacy')
                         AND substr(created_at,1,10) >= date('now','-1 day')
                    GROUP BY 1 ORDER BY 2 DESC'''):
    print(r)
print('pushes:', c.execute('''SELECT COUNT(*) FROM mt5_pushes
      WHERE destination_id='admin_live'
        AND substr(pushed_at,1,10) >= date('now','-1 day')''').fetchone())
\""
```

Attendu : **aucune** ligne `horizon_not_allowed` sur `admin_live` ni `admin_legacy`, et un compte de pushes non nul si le marché est ouvert.

⚠️ Si `horizon_not_allowed` apparaît sur MT5, l'estampille V1 ne se pose pas — `CANDLE_INTERVAL` en production vaut `5min`, et `normalize("5min")` doit rendre `"5min"`. Revenir à la tâche 2 avant toute autre chose.

- [ ] **Step 5: Vérifier que le flux long-horizon est visible**

Observer le canal sales pendant une journée complète. Attendu : quelques messages `Horizon 4h — …`, pas des centaines.

```bash
ssh -i scalping-key.pem ec2-user@100.103.107.75 \
  "sudo docker exec scalping-radar python3 -c \"
import sqlite3
c = sqlite3.connect('/app/data/trades.db')
for r in c.execute('''SELECT timeframe, COUNT(*) FROM shadow_setups
                       WHERE substr(detected_at,1,10) >= date('now','-1 day')
                    GROUP BY 1'''):
    print(r)
\""
```

Si le compte `4h` est non nul mais qu'aucun message n'est parti, vérifier les scores : le plafond à 60 sans volatilité est le suspect numéro un.

- [ ] **Step 6: Consigner le résultat**

Écrire le verdict en mémoire projet : ce qui tient, ce qui ne tient pas, et la mesure qui l'établit.

---

## Ce que ce plan ne fait pas

- **Le passage en `AUTO_EXEC` du flux long-horizon.** Il exige un échantillon propre postérieur au 2026-08-04, et `median_holding_hours` rendra `None` — donc la porte de coût bloquera — tant que 30 setups résolus par système n'existent pas.
- **Le swap MT5.** Justifié en tête de plan : aucun consommateur tant que MT5 reste à l'horizon `5min`.
- **L'élargissement du routage** — BTC sur Kraken, titres individuels sur IBKR (spec §3.4). Ce sont des ajouts de configuration une fois la plomberie posée, pas du code.
- **Les ordres maker sur Kraken.**
- **Toute modification du barème de confiance v2.**

## Vérification finale du plan (spec §5)

| critère de la spec | où il est tenu |
|---|---|
| 1. frais > 30 % de l'edge ⇒ `fees_exceed_edge`, rien n'est envoyé | plan 1, vérifié en production le 2026-08-05 |
| 2. `KRAKEN_BRIDGE_ENABLED=true` ne suffit plus à trader à perte | plan 1, vérifié ; renforcé ici par `horizon_not_allowed` |
| 3. les setups 4h atteignent l'état `TELEGRAM` et sont visibles | tâches 5 et 6 |
| 4. l'horizon enregistré correspond à l'intervalle réellement analysé | commit `057def9` (V1) + tâche 2 (V2, dispatch) |
| 5. la suite de tests passe entièrement | chaque tâche : 0 échec, 0 erreur |
