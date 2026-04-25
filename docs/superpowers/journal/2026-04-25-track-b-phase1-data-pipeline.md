# Expérience #7 — Track B Phase 1 — Pipeline data macro/cross-asset

**Date début :** 2026-04-25
**Date fin :** 2026-04-25 (~20h15 Paris)
**Track :** B (Alt-data + cross-asset features)
**Numéro d'expérience :** 7
**Statut :** `closed-positive` *(infrastructure milestone)*

---

## Hypothèse (infrastructure)

> "On peut construire en quelques heures un pipeline de fetch + cache + lookup pour 5 séries macro/cross-asset (VIX, DXY, SPX, TNX, BTC), opérationnel sans look-ahead, sans clé API supplémentaire ni installation lourde, qui fournit des features alignées à un timestamp T."

Cette expérience est une **étape d'infrastructure** plutôt qu'un test d'edge. Le critère de succès est binaire : ça marche / ça ne marche pas, dans des conditions de fiabilité acceptables.

## Motivation / contexte

Spec Track B (`docs/superpowers/specs/2026-04-25-track-b-altdata-cross-asset.md`) — la phase 1 est la création du pipeline data, prérequis aux phases ML suivantes. Sans ce pipeline, impossible d'ajouter les features alt-data au training ML.

## Choix d'implémentation

### Source de données : Yahoo Finance via httpx direct

3 options envisagées :
- **FRED API** — clé gratuite mais nécessite inscription côté user, infra séparée
- **yfinance lib** — pratique mais tire pandas (déjà là) + html5lib + multitasking → bloat
- **Yahoo Finance v8 chart endpoint via httpx direct** — endpoint public, pas de clé, pas de nouvelles deps (httpx déjà dans requirements.txt)

→ **httpx direct retenu** pour minimiser la friction. Si Yahoo casse l'endpoint un jour, fallback vers fredapi se fera proprement.

### Cache : SQLite local

DB séparée du backtest principal : `data/macro.db` (vs `_macro_veto_analysis/backtest_candles.db`).
- Auto-gitignored (`*.db` pattern)
- Schéma simple : `(symbol, date, OHLCV)` PK composite
- Upsert idempotent (refetch = pas de duplicates)

### Symboles couverts

| Logique | Yahoo | Source | Asset class |
|---|---|---|---|
| `vix` | `^VIX` | CBOE | volatility regime |
| `dxy` | `DX-Y.NYB` | ICE | dollar strength |
| `spx` | `^GSPC` | NYSE | risk on/off |
| `tnx` | `^TNX` | CBOE | 10Y Treasury yield |
| `btc` | `BTC-USD` | crypto | risk-on alternative |

## Données

- Fenêtre fetchée : **2020-01-01 → 2026-04-25** (6.3 ans calendaires)
- Volumes par symbole :
  - VIX, SPX, DXY, TNX : 1586-1588 obs (jours de bourse US) — cohérent
  - BTC : 2307 obs (jours calendaires, crypto trade 24/7)
- Total cache local : 8643 lignes, < 1 MB

## Protocole

1. Implémenter `backend/services/macro_data.py` :
   - `fetch_yahoo_daily(ticker, start, end)` — HTTP GET v8 chart endpoint
   - `upsert_observations(symbol, observations)` — INSERT … ON CONFLICT
   - `get_series(symbol, start, end)` — lookup cache local
   - `get_close_at_or_before(symbol, target_date)` — for asof T-1d
   - `get_macro_features_at(ts)` — point d'entrée principal
2. CLI : `python -m backend.services.macro_data fetch-all` / `features` / `summary`
3. Tests :
   - Smoke : fetch 5d VIX → status 200, latest close raisonnable
   - Full fetch : 5 symboles × 6 ans
   - Features at T = 2026-04-22 14:00 UTC → asof 2026-04-21
   - Vérification non-look-ahead : `get_close_at_or_before(symbol, T-1)` ne retourne jamais une date ≥ T

## Critère go/no-go

| Sortie | Condition | Verdict |
|---|---|---|
| **Succès** | 5/5 symboles fetchent ≥ 1500 obs, features dérivées non-NaN sur date récente, valeurs raisonnables | Pipeline opérationnel |
| **Partiel** | 3-4/5 symboles OK | Documenter les manquants, fallback FRED si nécessaire |
| **Échec** | < 3/5 ou look-ahead détecté | Refactor, réessayer |

## Résultats

### Fetch — 5/5 symboles OK

```
vix: 1586 obs écrites (^VIX 2020-01-01→2026-04-25)
dxy: 1588 obs écrites (DX-Y.NYB 2020-01-01→2026-04-25)
spx: 1586 obs écrites (^GSPC 2020-01-01→2026-04-25)
tnx: 1586 obs écrites (^TNX 2020-01-01→2026-04-25)
btc: 2307 obs écrites (BTC-USD 2020-01-01→2026-04-25)
```

### Features dérivées — sample at 2026-04-22 14:00 UTC (asof 2026-04-21)

```
asof_date              2026-04-21
vix_level                  19.500
vix_delta_1d                3.339   %
vix_return_5d               6.209   %
vix_dist_sma50            -13.033   %
vix_regime             normal

dxy_level                  98.410
dxy_delta_1d                0.367   %
dxy_dist_sma50             -0.301   %

spx_level                7064.010
spx_delta_1d               -0.635   %
spx_return_5d               1.387   %
spx_dist_sma50              4.220   %

tnx_level                   4.292   (% yield 10Y)
tnx_delta_1d                0.988   %
tnx_dist_sma50              1.891   %

btc_level               76352.773
btc_delta_1d                0.633   %
btc_return_5d               1.598   %
btc_dist_sma50              7.979   %
```

### Sanity check valeurs

- VIX 19.5 → régime "normal" cohérent avec un marché calme post-pic vol
- DXY 98.4 → cohérent avec niveau dollar Q1 2026
- SPX 7064 → cohérent avec ATH récent
- TNX 4.29% → cohérent avec rates context Q1 2026
- BTC 76k → cohérent avec niveaux récents (pas de bull mania ni de bear)

### Non-look-ahead

`get_macro_features_at(T)` utilise `target_date = ts.date() - timedelta(days=1)` puis `get_close_at_or_before(symbol, target_date)`. Au moment T, on ne consulte que des observations daily fermées strictement avant T. Vérifié manuellement : pour T = 2026-04-22 (mercredi), asof_date = 2026-04-21 (mardi, daily fermé US à 21h UTC, antérieur à n'importe quel T mercredi).

## Verdict

> Hypothèse **CONFIRMÉE**. Pipeline data macro **opérationnel**, 5/5 symboles, sans look-ahead, sans clé API extra, sans installation de deps lourdes. Temps total < 1h de code + < 1 min de fetch.

## Conséquences actées

### Pour Track B
- **Phase 1 close en succès.** Pipeline data ready pour les phases ML suivantes.
- **Phase 2 ouvre** :
  - Étendre `scripts/ml_extract_features.py` pour appeler `get_macro_features_at()` à chaque setup et ajouter les features macro
  - Re-extraire les 233k samples avec features étendues (~2-4h estimées)
  - Re-runner le training ML (~30 min) sur le dataset étendu
  - Comparer AUC V1 (0.526) vs V2_macro
- **Si Phase 2 donne un edge sur le pattern detection global** → Phase 3 sera de tester l'intersection avec Track A (quels patterns survivants × quel régime macro = meilleur PF ?)
- **Si Phase 2 ne donne rien** sur le pattern detection global → tester ciblé sur les **métaux H4** (où on a déjà identifié l'edge structurel via Tracks A + C). Hypothèse : DXY et real yields TNX devraient être très prédictifs sur XAU spécifiquement.

### Pour Tracks A et C
- **Synergie possible Phase 3** : ajouter un filtre macro aux signaux V2_CORE_LONG (Track A) et TF LONG (Track C), par exemple "n'entrer en LONG métaux que si vix_regime ≠ high" ou "uniquement quand dxy_dist_sma50 < 0".
- À tester quand Track B Phase 2 aura confirmé quelles features ont le plus de pouvoir prédictif.

### Pour le code prod
- Aucun changement V1.
- Le service `macro_data.py` est dans `backend/services/` mais **n'est pas appelé par le scoring live**. Ça pourrait servir au gate S6 si on voulait alimenter le scheduler, mais c'est une décision séparée.

## Artefacts

- Service : `backend/services/macro_data.py` (~280 lignes)
- DB cache : `data/macro.db` (~1 MB, gitignored)
- Commit : à venir

## Caveats

1. **Yahoo endpoint stabilité** — l'endpoint v8 chart est public et stable depuis 2017+, mais Yahoo l'a cassé une fois en 2017 (yfinance avait dû patcher). Risque faible mais non nul. Si ça arrive, fallback FRED API documenté dans la spec Track B.
2. **Pas de check de freshness** — le service ne vérifie pas si le cache est à jour. Pour le re-fetch quotidien du live, il faudra un cron ou un appel manuel `fetch-all`.
3. **Holidays partiels** — certains jours, Yahoo retourne `close=null` (ex : early close Thanksgiving). Le service skip silencieusement (cf `if c_val is None: continue`). À monitorer si ça crée des trous gênants pour le forward-fill.
4. **Granularité daily uniquement** — pas d'intraday macro pour l'instant. Si Phase 2 a besoin de granularité plus fine (ex: VIX intraday), refactor à prévoir.
