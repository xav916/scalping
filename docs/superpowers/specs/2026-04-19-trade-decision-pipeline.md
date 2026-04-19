# Spec fonctionnelle — Pipeline de décision d'un trade

**Date** : 2026-04-19
**Nature** : spec fonctionnelle rétrospective

---

## Vue d'ensemble

Ce document décrit **comment un setup de trade est construit**, depuis la détection du pattern jusqu'à la décision d'exécution (push Telegram, auto-exec, ou rien). C'est le cœur de la valeur ajoutée du radar.

## Étapes du pipeline (dans l'ordre)

```
1. Fetch des données    ─> 2. Détection patterns ─> 3. Calcul du setup brut
                                                            │
4. Filtrage des setups <─  5. Enrichissement scoring <──────┘
         │                              ▲
         │                              │
         ▼                       6. Macro scoring
                                        │
7. Verdict (TAKE/WAIT/SKIP) <───────────┘
         │
         ├──> Push WebSocket (dashboard)
         ├──> Push Telegram (si conf ≥ 80 et TAKE/WAIT)
         └──> Push MT5 bridge (si conf ≥ 60 et TAKE)
```

## Étape 1 — Fetch des données

Voir `2026-04-19-data-sources.md` pour le détail.

En sortie : pour chaque paire de `WATCHED_PAIRS`, on a :
- ~50 bougies 5min (liste d'OHLC)
- ~50 bougies 1h (pour confirmation multi-timeframe)
- Un `VolatilityLevel` (LOW/MEDIUM/HIGH)
- Les événements économiques à venir (30 min)
- Un `MacroContext` snapshot (si Vague 1 activée)

## Étape 2 — Détection des patterns

**Module** : `backend/services/pattern_detector.py`

Pour chaque paire, sur les bougies 5min, on cherche 6 types de patterns :

| Pattern | Description | Confidence de base |
|---|---|---|
| `breakout_up` | Clôture au-dessus de la résistance récente | 0.6 + ajustement ATR |
| `breakout_down` | Clôture sous le support récent | Idem |
| `momentum_up` | Suite de 3+ bougies haussières avec volume croissant | 0.55-0.75 |
| `momentum_down` | Idem baisse | Idem |
| `engulfing_bullish` | Bougie englobante haussière (retournement) | 0.6-0.8 selon taille |
| `pin_bar` | Mèche longue indiquant rejet du niveau | 0.55-0.7 |

Chaque pattern a son propre calcul de **confidence** (0.0 à 1.0) basé sur l'intensité technique.

**Sortie** : liste de `PatternDetection` (zéro ou plusieurs par paire par cycle).

## Étape 3 — Calcul du setup brut

**Module** : `backend/services/pattern_detector.py::calculate_trade_setup`

À partir d'un pattern, on construit un objet `TradeSetup` avec :

| Champ | Calcul |
|---|---|
| `pair`, `direction` | Dérivé du pattern (ex : `breakout_up` → `buy`) |
| `entry_price` | Dernière clôture (ou breakout point) |
| `stop_loss` | Distance ATR × 1.5 dans le sens opposé |
| `take_profit_1` | Entry + 1× (entry-SL) → R:R = 1 |
| `take_profit_2` | Entry + 2× (entry-SL) → R:R = 2 |
| `risk_pips`, `reward_pips_1/2` | Distances en pips |
| `risk_reward_1/2` | Ratio R:R |
| `pattern` | Référence vers le PatternDetection |

À ce stade, le setup n'a **pas encore de score de confidence**.

## Étape 4 — Enrichissement scoring

**Module** : `backend/services/analysis_engine.py::enrich_trade_setup`

C'est l'étape clé qui attribue un **score sur 100** au setup, basé sur 5 facteurs pondérés :

| Facteur | Poids max | Condition pour max |
|---|---|---|
| **Pattern** | 30 | confidence interne du pattern ≥ 0.85 |
| **Risk/Reward** | 25 | R:R ≥ 2.0 (ou 1.5 partiel) |
| **Volatilité** | 20 | HIGH (vs baseline paire) |
| **Tendance MTF** | 15 | Trend 1h alignée avec la direction du setup |
| **Contexte éco** | 10 | Pas d'événement rouge dans les 30 min |
| **Total max** | **100** |  |

Exemple :
```
Setup = breakout_up sur EUR/USD
  Pattern conf = 0.78 × 30 = 23.4 pts
  R:R 1 = 2.0             = 25 pts
  Vol = HIGH               = 20 pts
  Trend 1h = bullish, aligné = 15 pts
  Éco = aucun event rouge  = 10 pts
  TOTAL = 93.4 / 100
```

Chaque facteur produit un `ConfidenceFactor(name, score, detail, positive, source)` stocké dans `setup.confidence_factors` (pour traçabilité UI).

## Étape 5 — Macro scoring (Vague 1)

**Module** : `backend/services/macro_scoring.py`

Si `MACRO_SCORING_ENABLED=true` et qu'un snapshot `MacroContext` frais (< 2h) existe :

1. `apply(pair, direction, snapshot)` retourne `(multiplier, veto, primaries)`
2. Le `confidence_score` final = `base_score × multiplier`, clampé [0, 100]
3. Un 6e `ConfidenceFactor` avec `source="macro"` est ajouté, `score=(mult-1)×100` (+/-)
4. Les `primaries` (DXY, SPX, VIX, etc. avec leur alignement) sont stockées dans `metadata` pour rendu UI

**Effet concret** sur l'exemple précédent :
```
Base = 93.4
DXY strong_up + setup long EUR/USD (contre USD) → multiplier = 0.75
Final = 93.4 × 0.75 = 70.1
```

Si `MACRO_VETO_ENABLED=true` et qu'une condition de veto est hit (VIX > 30 contre risk, DXY > 2σ intraday contre) → `verdict_action` forcé à `"SKIP"`.

Détails complets : `2026-04-19-macro-context-scoring-design.md`.

## Étape 6 — Filtrage des setups

**Module** : `backend/services/analysis_engine.py::filter_high_confidence_setups`

On garde uniquement les setups avec `confidence_score ≥ MIN_CONFIDENCE_SCORE` (75 par défaut).

Les autres sont loggés mais pas affichés dans la section principale (ils peuvent apparaître dans une section "setups faibles" si activée).

## Étape 7 — Verdict final (coaching)

**Module** : `backend/services/coaching.py`

Un module de "coach" construit le verdict final à 3 valeurs :

| Verdict | Signification | Action pour l'utilisateur |
|---|---|---|
| `TAKE` | "Prends ce trade" | Peut être exécuté automatiquement |
| `WAIT` | "Attends confirmation" | Alerte, mais pas d'auto-exec |
| `SKIP` | "Passe ton tour" | Pas d'alerte, setup faible ou bloqué |

Le verdict est calculé selon :
- Le score final
- La trend MTF (1h aligne-t-elle ?)
- Les warnings / blockers (ex : news dans 20 min, R:R faible)
- Le veto macro (si activé)

Le coach produit aussi :
- `verdict_summary` : phrase courte en français
- `verdict_reasons` : liste des raisons positives
- `verdict_warnings` : points d'attention
- `verdict_blockers` : raisons de SKIP

## Distribution du setup

Une fois le setup enrichi, il est :

1. **Toujours** broadcast en WebSocket aux clients connectés (UI temps réel)
2. **Toujours** loggé (dashboard "Mes trades" via backtest, pas personal_trades — sauf auto-exec)

Puis, conditionnellement :

### Push Telegram

Si toutes ces conditions :
- `verdict_action` ∈ `TELEGRAM_SETUP_VERDICTS` (default `TAKE,WAIT`)
- `confidence_score` ≥ `TELEGRAM_SETUP_MIN_CONFIDENCE` (actuellement 50)
- Dedup OK (pas déjà envoyé aujourd'hui pour `(date, pair, direction, entry)`)
- User pas en silent mode
- Daily loss pas atteinte pour ce user

Alors push Telegram individualisé (un message par user dans `TELEGRAM_CHATS`).

### Push MT5 bridge

Si toutes ces conditions :
- `MT5_BRIDGE_ENABLED=true`
- `verdict_action == "TAKE"`
- `confidence_score` ≥ `MT5_BRIDGE_MIN_CONFIDENCE` (actuellement 60)
- Dedup OK (pas d'ordre identique dans les 5 min — géré côté bridge)

Alors le backend POST `/order` au bridge avec :
- `pair`, `direction`, `entry`, `sl`, `tp`
- `risk_money` (= capital × risk_pct)
- `client_comment` (trace du setup source)

## Récapitulatif des seuils (snapshot 2026-04-19)

| Seuil | Valeur | Rôle |
|---|---|---|
| `MIN_CONFIDENCE_SCORE` | 75 | Filtre affichage UI principal |
| `TELEGRAM_SETUP_MIN_CONFIDENCE` | 50 | Abaissé pour phase observation (normalement 80) |
| `MT5_BRIDGE_MIN_CONFIDENCE` | 60 | Abaissé pour phase observation (normalement 90) |
| `RISK_PER_TRADE_PCT` | 1.0 | 1% du capital risqué par trade |
| `DAILY_LOSS_LIMIT_PCT` | 3.0 | Silent mode si -3% dans la journée |

⚠️ Les valeurs 50 et 60 sont **intentionnellement basses** pour accumuler des données en phase d'observation. Elles devront être remontées à 80 et 90 avant tout passage en live.

## Stockage pour analyse post-mortem

Chaque trade auto (et potentiellement chaque trade manuel) est persisté dans `personal_trades` avec :

- Les champs du setup (pair, direction, entry, SL, TP, size, pattern, confidence)
- Un snapshot JSON du contexte macro au moment du trade (`context_macro` column)
- L'exit_price, le pnl, le statut (OPEN/CLOSED)
- Un flag `is_auto` pour distinguer

Cette base alimentera les futures phases ML (analyse win rate par régime macro, par pattern, par heure, etc.).

## Détecteur d'erreurs (UI)

Le dashboard a une section "Détecteur d'erreurs" qui compare **setups détectés** vs **trades pris** :

- Setups TAKE ≥ 80 qui n'ont pas été pris (manqués)
- Trades pris sur SKIP (user est allé contre le conseil)
- Trades pris hors hours (si TRADING_HOURS défini)

C'est un outil de discipline, pas un bloquant.

## Points de friction connus

- Le plafonnement observé à **confidence 66** sur les 22 trades historiques vient du calcul `pattern.confidence × 30` qui plafonne souvent à 20/30 en pratique (patterns rarement à 0.85+). À investiguer structurellement.
- Les setups EUR/JPY dominent (77% des signaux historiques) — à creuser : biais de volatilité Mataf ? Biais du pattern detector ?
- Win rate historique : 1/17 trades clos = 6% → clairement le scoring actuel ne filtre pas assez. C'est précisément ce que la Vague 1 macro cherche à corriger.

## Ce qui n'est pas fait

- **Pas de ML** sur le scoring (besoin de 200+ trades réels avant)
- **Pas de backtest historique** automatique sur données étendues (1 an)
- **Pas de mode "simulation uniquement"** côté UI (les setups simulated sont mélangés aux réels, flaggés par un badge)
- **Pas de feedback loop** explicite : l'user ne peut pas noter "ce signal était bon/mauvais" pour entraîner le modèle

## Références

- Pattern detector : `backend/services/pattern_detector.py`
- Analysis engine : `backend/services/analysis_engine.py`
- Macro scoring : `backend/services/macro_scoring.py`
- Coaching / verdict : `backend/services/coaching.py`
- Backtest : `backend/services/backtest_service.py`
- Trade log : `backend/services/trade_log_service.py`
