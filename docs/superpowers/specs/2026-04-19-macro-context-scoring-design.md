# Design — Vague 1 : Enrichissement du scoring par contexte macro

**Date** : 2026-04-19
**Auteur** : design validé avec l'utilisateur via brainstorming
**Statut** : design approuvé, prêt pour plan d'implémentation

---

## Contexte et objectif

Le radar Scalping calcule aujourd'hui un `confidence_score` (0-100) par setup, agrégeant 5 facteurs : pattern technique, risk/reward, volatilité, tendance, contexte économique. Les signaux macro globaux (force du dollar, appétit pour le risque, taux, sentiment commodité) n'entrent pas dans le calcul.

Objectif : enrichir le scoring avec un **contexte macro multi-sources** pour filtrer les setups qui vont à contre-courant du régime de marché, sans ajouter de friction quand le contexte est neutre.

Ce document couvre la **Vague 1** d'un plan en 3 vagues (macro → sentiment retail → news sentiment). Les vagues 2 et 3 font l'objet de specs séparés à venir.

## Décisions structurantes (verrouillées)

| Décision | Choix | Justification |
|---|---|---|
| Scope | Phasé, Vague 1 = macro uniquement | Valider l'impact avant d'empiler les sources |
| Modèle d'impact | **Mix multiplicateur + veto** | Nuance sur les cas intermédiaires, veto sur les cas extrêmes |
| Indicateurs trackés | **8 symboles** : DXY, SPX, VIX, US10Y, DE10Y, Oil WTI, Nikkei 225, Gold (XAU) | Couverture complète incluant rotation régionale et mapping Oil→CAD, spread US/DE→EUR |
| Fréquence refresh | **15 min** | Capture les breakouts intraday sans saturer le budget API |
| Mode dégradé | **Fallback cache 2h, sinon neutre** | Le système ne doit jamais être pire avec le module qu'avant |

## Architecture

### Nouveaux fichiers

- `backend/services/macro_context_service.py` — fetch + cache des symboles macro, expose `get_macro_snapshot() -> MacroContext`
- `backend/services/macro_scoring.py` — module pur (sans I/O) : `apply(setup, snapshot) -> (multiplier, veto, reasons)`
- `backend/models/macro_schemas.py` — dataclasses `MacroContext`, `MacroDirection`, `VixLevel`, `RiskRegime`
- `backend/tests/test_macro_scoring.py` — tests table-driven
- `backend/tests/test_macro_context_service.py` — tests fetch + cache

### Fichiers modifiés (edits ciblés)

- `backend/services/scheduler.py` — ajout d'un job `refresh_macro_context` (interval 15 min)
- `backend/services/analysis_engine.py::enrich_trade_setup()` — injection du scoring macro après le calcul des 5 facteurs actuels
- `backend/services/trade_log_service.py` — migration `personal_trades` + colonne `context_macro TEXT`
- `config/settings.py` — nouvelles variables env
- `backend/app.py` — endpoint `GET /debug/macro` (auth admin)
- Frontend (HTML/JS) — affichage du multiplicateur macro + raison sur la carte setup

## Flux de données

```
[Scheduler /15min]
        │
        ▼
[macro_context_service.refresh()]
    └─> Twelve Data API × 8 symboles (prix spot + avg 20 périodes)
    └─> Calcul z-scores + régime de risque
    └─> Cache en RAM (dict avec timestamp)
        │
        ▼
[MacroContext snapshot]
        │
        ├──> exposé via get_macro_snapshot()
        │
        ▼
[enrich_trade_setup(setup, context_eco, events)]
    └─> calcul des 5 facteurs actuels → base_score (0-100)
    └─> snapshot = macro_context_service.get_macro_snapshot()
    └─> if snapshot.age < 2h:
          (mult, veto, reasons) = macro_scoring.apply(setup, snapshot)
          setup.confidence_score = clamp(base_score * mult, 0, 100)
          setup.confidence_factors.append(ConfidenceFactor(name="Contexte macro", source="macro", score=..., reason=...))
          if veto:
              setup.verdict_action = "SKIP"
              setup.verdict_blockers.append(...)
        else:
          log INFO "macro stale, neutral mode"
          # base_score inchangé
        │
        ▼
[Setup enrichi] → notifier WebSocket / Telegram / MT5 bridge / trade_log
```

## Schémas de données

### `MacroContext` (dataclass)

```python
@dataclass
class MacroContext:
    fetched_at: datetime           # UTC
    dxy_direction: MacroDirection   # enum
    spx_direction: MacroDirection
    vix_level: VixLevel             # enum : low | normal | elevated | high
    vix_value: float
    us10y_trend: MacroDirection
    de10y_trend: MacroDirection
    us_de_spread_trend: str         # widening | flat | narrowing
    oil_direction: MacroDirection
    nikkei_direction: MacroDirection
    gold_direction: MacroDirection
    risk_regime: RiskRegime         # enum : risk_on | neutral | risk_off
    raw_values: dict[str, float]    # prix spot des 8 symboles pour log
```

### `MacroDirection` (enum)

Dérivée à partir de l'écart du prix actuel à la moyenne des 20 dernières clôtures **journalières (1d)**, normalisé par l'écart-type de la même série (z-score rolling sur 20 jours) :

- `strong_up` : z ≥ +1.5
- `up` : +0.5 ≤ z < +1.5
- `neutral` : -0.5 < z < +0.5
- `down` : -1.5 < z ≤ -0.5
- `strong_down` : z ≤ -1.5

Rationnel : clôtures 1d captent le régime directionnel sans bruit intraday. Pour le DXY spécifiquement, un second calcul intraday (sur la bougie 5min) est utilisé **uniquement pour la condition de veto "DXY bougé > 2σ intraday"** — indépendant du z-score 1d.

### `VixLevel` (seuils absolus)

- `low` : < 15
- `normal` : 15 à 20
- `elevated` : 20 à 30
- `high` : ≥ 30

### `RiskRegime` (agrégat)

Dérivé par règles simples :

- `risk_off` si VIX ≥ elevated ET (SPX down ou strong_down)
- `risk_on` si VIX = low ET SPX up/strong_up
- `neutral` sinon

### Extension `personal_trades`

```sql
ALTER TABLE personal_trades ADD COLUMN context_macro TEXT;
-- JSON nullable avec : dxy, spx, vix_level, vix_value, us_de_spread_trend,
-- risk_regime, macro_multiplier, macro_veto, veto_reasons, fetched_at
```

## Mapping paire → macro (logique de scoring)

Chaque paire a 1 à 3 **indicateurs macro primaires**. L'alignement de chaque primaire avec la direction du setup donne un score -1 / 0 / +1, la moyenne détermine le multiplicateur.

Une paire peut apparaître sous plusieurs classes (ex : EUR/USD est à la fois une USD-majeure et une EUR-pair). Dans ce cas on additionne les primaires des classes applicables en dédoublonnant.

| Classe | Paires concernées | Primaires | Logique |
|---|---|---|---|
| USD-majeure | EUR/USD, GBP/USD, USD/JPY, USD/CHF | **DXY** | DXY up ↔ long USD favorisé ; DXY down ↔ short USD favorisé |
| USD-commodity | USD/CAD | **DXY, Oil (WTI)** | Oil up ↔ CAD fort ↔ short USD/CAD favorisé ; DXY up ↔ long USD/CAD favorisé |
| Commodity-currency | AUD/USD, NZD/USD | **DXY, SPX, Gold** | DXY (vs USD) + risk_on (SPX up, Gold up) ↔ long AUD/NZD favorisé |
| JPY-pair | USD/JPY, EUR/JPY, GBP/JPY | **VIX, Nikkei** (additionnés aux primaires USD/EUR/GBP si applicable) | risk_off (VIX up + Nikkei down) ↔ JPY fort ↔ short JPY pairs favorisé |
| EUR-pair | EUR/USD, EUR/GBP, EUR/JPY | **Spread US10Y−DE10Y** (additionné aux primaires de la classe quote) | Spread narrowing (DE rattrape) ↔ EUR fort ↔ long EUR favorisé |
| XAU/USD (spécial) | XAU/USD | **VIX, DXY, US10Y** | VIX up + DXY down + yields down ↔ long XAU favorisé (refuge activé) |
| CHF-pair | USD/CHF, EUR/CHF | **VIX** (secondaire, additionné à USD-majeure ou EUR-pair) | risk_off ↔ CHF fort (logique similaire JPY, plus molle) |

**Exemple** : pour EUR/USD on utilise DXY (USD-majeure) + Spread US−DE (EUR-pair) = 2 primaires. Pour EUR/JPY on utilise VIX + Nikkei (JPY-pair) + Spread US−DE (EUR-pair) = 3 primaires.

### Formule multiplicateur

1. Pour chaque primaire de la paire : calculer `alignement ∈ {-1, 0, +1}` vs direction du setup
2. Moyenne des alignements → `avg`
3. Multiplicateur final :
   - `avg ≥ +0.6` → `×1.2`
   - `+0.2 ≤ avg < +0.6` → `×1.1`
   - `-0.2 ≤ avg < +0.2` → `×1.0` (neutre)
   - `-0.6 ≤ avg < -0.2` → `×0.9`
   - `avg < -0.6` → `×0.75`

### Conditions de VETO (une seule suffit)

1. **VIX > 30** ET setup aligné contre le risk_regime détecté
2. **DXY bougé > 2σ intraday** ET setup contre cette direction
3. **Événement rouge ForexFactory** dans les 30 min impliquant une des devises du setup (réactivation d'un filtre déjà existant dans le système)

Le veto force `verdict_action = "SKIP"` et ajoute la raison dans `verdict_blockers`, mais n'efface pas le setup de l'UI (visible pour compréhension).

## Gestion d'erreurs

| Situation | Comportement |
|---|---|
| Erreur HTTP Twelve Data | Log WARN, garde le snapshot précédent, réessaie au cycle suivant (15 min) |
| Snapshot < 2h (weekend OK) | Mode normal, multiplicateur + veto actifs |
| Snapshot > 2h ou cache vide | Mode neutre : multiplicateur = 1.0, aucun veto. Log INFO à chaque application |
| Clé API manquante au boot | Service désactivé, log WARN unique, `MACRO_SCORING_ENABLED` considéré comme `false` |
| Feature flag `MACRO_SCORING_ENABLED=false` | Le service ne tourne pas, `enrich_trade_setup` skip l'appel à macro_scoring |

**Principe directeur** : le système ne doit jamais être pire avec le module macro qu'avant. Aucune situation d'erreur ne doit bloquer les setups.

## Tests

### Tests unitaires (pytest)

`test_macro_scoring.py` — au minimum 20 cas table-driven couvrant :

- Chaque classe de paire × chaque direction × chaque régime macro
- Cas limites des seuils (z-score à la frontière)
- Cas de veto (VIX 30.1, DXY 2.01σ)
- Cas mode neutre (snapshot stale)

`test_macro_context_service.py` :

- Parsing des réponses Twelve Data (JSON mocké)
- Calcul correct des z-scores
- Sélection du bon `MacroDirection` selon z
- Cache stale → comportement attendu
- Erreur HTTP → garde le cache précédent

**Pas de tests d'intégration réseau.** Toutes les dépendances externes sont mockées.

### Tests manuels en shadow mode

- Vérifier que les 8 symboles remontent avec des valeurs plausibles
- Vérifier que `risk_regime` colle à l'intuition (VIX=25 + SPX en baisse → risk_off)
- Pour 5-10 setups réels, comparer multiplicateur calculé vs jugement humain

## Observabilité

- **Logs structurés** par application : `macro_applied pair=EUR/USD dir=sell base=72 mult=0.9 final=65 veto=false reasons=[dxy_strong_up]`
- **Endpoint `GET /debug/macro`** (auth admin) : snapshot courant + âge du cache + 10 derniers snapshots + stats (taux de veto, distribution multiplicateurs)
- **Affichage frontend sur carte setup** : badge "Macro ×0.9 — DXY en forte hausse (contre)" à côté du score, cliquable pour détail. Permet à l'utilisateur de comprendre chaque décision sans aller dans les logs.

## Configuration (nouvelles variables env)

```bash
# Feature flags
MACRO_SCORING_ENABLED=false          # shadow mode par défaut, activer manuellement après validation
MACRO_VETO_ENABLED=false             # activer seulement après phase d'observation multiplicateur

# Fréquence et cache
MACRO_REFRESH_INTERVAL_SEC=900       # 15 min
MACRO_CACHE_MAX_AGE_SEC=7200         # 2h avant fallback neutre

# Symboles Twelve Data (mapping logique → symbole broker)
MACRO_SYMBOL_DXY=DXY
MACRO_SYMBOL_SPX=SPX
MACRO_SYMBOL_VIX=VIX
MACRO_SYMBOL_US10Y=TNX
MACRO_SYMBOL_DE10Y=DE10Y             # Twelve Data plan gratuit ne couvre pas DE10Y de manière fiable. Si absent au démarrage, le spread US−DE est désactivé et les paires EUR retombent sur DXY uniquement comme primaire.
MACRO_SYMBOL_OIL=WTI
MACRO_SYMBOL_NIKKEI=NKY
MACRO_SYMBOL_GOLD=XAU/USD            # déjà tracké via WATCHED_PAIRS

# Seuils (surchargeable pour tuning)
MACRO_ZSCORE_STRONG=1.5
MACRO_VIX_HIGH=30.0
MACRO_DXY_VETO_SIGMA=2.0
```

## Plan de déploiement interne (phases de risque)

1. **Dev local** — tous les fichiers + tests unitaires verts + migration DB
2. **Shadow mode court (1 jour)** — `MACRO_SCORING_ENABLED=false`. On vérifie les snapshots, les parses, le cache, les logs
3. **Shadow mode prolongé (3-5 jours)** — log des scores "avec macro" vs "sans macro" sans appliquer. Comparaison des divergences
4. **Activation multiplicateur** — `MACRO_SCORING_ENABLED=true`, `MACRO_VETO_ENABLED=false`. 2-3 jours d'observation
5. **Activation complète** — vetos on. 2 semaines d'observation minimum avant d'attaquer la Vague 2 (retail sentiment)

**Kill-switch** : passer `MACRO_SCORING_ENABLED=false` désactive instantanément (lu au début de chaque cycle)

## Critères de succès (pour juger si la Vague 1 a apporté de la valeur)

Mesurés sur ~100 trades après activation complète :

- **Réduction du taux de faux positifs** : setups classés TAKE qui finissent en perte → baisse visible vs avant
- **Pas de régression sur les vrais positifs** : taux de gain (sur trades effectivement pris) ≥ baseline
- **Distribution des multiplicateurs cohérente** : majorité autour de 1.0, queues à 0.75 et 1.2 actives mais pas dominantes
- **Vetos rares** : < 10% des setups potentiels (sinon c'est trop agressif, à recalibrer)

## Ce qui n'est pas inclus (YAGNI)

- Pas de modèle ML sur le contexte macro (on logge pour préparer mais on n'entraîne rien)
- Pas de sources macro alternatives (FRED, Bloomberg, Refinitiv) — Twelve Data suffit au démarrage
- Pas de configuration par utilisateur — un seul mapping global
- Pas de visualisation graphique du régime macro dans le dashboard — un simple badge sur les cartes setup
- Pas de backtest historique du scoring macro sur trades passés — le shadow mode live suffit à valider

## Références internes

- Scoring actuel : `backend/services/analysis_engine.py::enrich_trade_setup()` (lignes 389-553)
- Schéma setup : `backend/models/schemas.py::TradeSetup` (lignes 115-149)
- Pattern service externe : `backend/services/mataf_service.py` (fallback robuste à reproduire)
- Prix/bougies : `backend/services/price_service.py` (Twelve Data déjà plombé)
