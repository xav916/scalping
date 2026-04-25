# Phase 4 — Shadow log V2_CORE_LONG XAU H4 — Spec design

**Date :** 2026-04-25
**Statut :** spec à implémenter
**Master :** `docs/superpowers/specs/2026-04-25-research-portfolio-master.md`
**Précédentes :** journal d'expériences #1 à #13 (J1)
**Système cible :** Track A V2_CORE_LONG XAU H4 seul, validé Sharpe 1.59 / maxDD 20% sur 24M

---

## Objectifs Phase 4

1. **Détecter en live** les setups V2_CORE_LONG sur XAU H4 (et XAG H4 en mode observation secondaire) au moment où ils se produisent
2. **Logger** chaque setup avec entry_price, stop_loss, take_profit, position size virtuelle, contexte macro
3. **NE PAS modifier** le scoring V1 ni l'auto-exec démo Pepperstone existant
4. **Mesurer** les métriques live (volume de setups, fréquence par mois, distribution des PnL "virtuels") et **comparer** au backtest 24M
5. **Décider** au gate S6 (2026-06-06) si les observations live justifient un passage Phase 5 (auto-exec des signaux V2_CORE_LONG sur compte démo)

## Non-objectifs

- Pas d'auto-exécution des setups V2_CORE_LONG dans cette phase
- Pas de modification du scoring V1 ou des filtres anti-saigne actuels
- Pas de notification Telegram automatique (ajout manuel possible plus tard)
- Pas de compte démo dédié — utilisation de la même infra Pepperstone démo en mode lecture-seule

## Architecture

### Vue d'ensemble

```
run_analysis_cycle (existing, scheduler.py)
│
├─ Fetch h1_candles (existing) ←──── déjà fait
│
├─ Branche V1 (existing)
│  ├─ analyze_trend
│  ├─ detect_patterns sur 5min candles
│  ├─ enrich_trade_setup
│  ├─ compute_verdict
│  ├─ ml_predictor shadow log (existing)
│  ├─ filtre is_market_open
│  ├─ filtre _should_push (mt5_bridge)
│  └─ auto-exec si verdict OK   ─────── INCHANGÉ par Phase 4
│
└─ Branche Phase 4 SHADOW (NEW)
   ├─ aggregate_h1_to_h4 sur XAU/USD + XAG/USD
   ├─ detect_patterns sur H4 candles
   ├─ filter_v2_core_long (3 patterns LONG only, direction=buy)
   ├─ calculate_trade_setup pour chaque match
   ├─ snapshot macro_features asof T-1d
   ├─ write to shadow_setups_v2_core_long table
   └─ no auto-exec, no Telegram, no UI alert
```

### Implémentation : branche shadow dans `run_analysis_cycle`

**Fichier :** `backend/services/scheduler.py`

Après le bloc V1 (auto-exec etc.), ajouter (~30 lignes de code) :

```python
# ─── Phase 4 shadow log V2_CORE_LONG ────────────────────────────────────
# Système recherche validé J1 (cf docs/superpowers/journal/INDEX.md exp 1-13)
# Sharpe 1.59, maxDD 20%, robuste cross-régime XAU H4
try:
    await _run_shadow_log_v2_core_long(h1_candles, economic_events)
except Exception as e:
    logger.warning(f"Phase 4 shadow log failed (non-bloquant): {e}")
```

Et dans un nouveau module `backend/services/shadow_v2_core_long.py` :

```python
"""Phase 4 shadow log V2_CORE_LONG — observation live sans auto-exec.

Détecte les setups Track A V2_CORE_LONG sur bougies H4 (aggrégées depuis
les H1 fetchées par le cycle principal), les logge en DB pour analyse
ultérieure. NE TOUCHE PAS au scoring V1 ni à l'auto-exec.
"""
SHADOW_PAIRS = ["XAU/USD", "XAG/USD"]
CORE_LONG_PATTERNS = {"momentum_up", "engulfing_bullish", "breakout_up"}

async def _run_shadow_log_v2_core_long(h1_candles, economic_events):
    for pair in SHADOW_PAIRS:
        h1 = h1_candles.get(pair, [])
        if len(h1) < 30:
            continue
        h4 = aggregate_to_h4(h1)
        if len(h4) < 30:
            continue
        patterns = detect_patterns(h4, pair)
        for pattern in patterns:
            if pattern.pattern.value not in CORE_LONG_PATTERNS:
                continue
            setup = calculate_trade_setup(pair, pattern, h4)
            if setup is None or setup.direction != TradeDirection.BUY:
                continue
            macro = get_macro_features_at(setup.entry_time or datetime.now(...))
            persist_shadow_setup(setup, pair, "4h", macro, pattern.pattern.value)
```

### Schéma DB — table `shadow_setups`

**Fichier :** schéma à ajouter dans `backend/db.py` (ou équivalent)

```sql
CREATE TABLE IF NOT EXISTS shadow_setups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- Métadonnées
    detected_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    cycle_at TIMESTAMP NOT NULL,            -- timestamp du cycle scheduler
    bar_timestamp TIMESTAMP NOT NULL,       -- timestamp du bar H4 d'entrée
    -- Système d'origine
    system_id TEXT NOT NULL,                -- 'V2_CORE_LONG_XAU_H4' / 'V2_CORE_LONG_XAG_H4'
    pair TEXT NOT NULL,
    timeframe TEXT NOT NULL,                -- '4h'
    -- Setup
    direction TEXT NOT NULL,                -- 'buy'
    pattern TEXT NOT NULL,                  -- 'momentum_up' | 'engulfing_bullish' | 'breakout_up'
    entry_price REAL NOT NULL,
    stop_loss REAL NOT NULL,
    take_profit_1 REAL NOT NULL,
    take_profit_2 REAL,
    risk_pct REAL NOT NULL,                 -- |entry - SL| / entry
    rr REAL NOT NULL,
    -- Vol target sizing virtuel (pour comparabilité backtest)
    sizing_capital_eur REAL NOT NULL DEFAULT 10000,
    sizing_risk_pct REAL NOT NULL DEFAULT 0.005,  -- 0.5% par défaut Phase 4
    sizing_position_eur REAL NOT NULL,      -- = capital × risk_pct / risk_pct_setup
    sizing_max_loss_eur REAL NOT NULL,      -- = capital × risk_pct
    -- Contexte macro asof T-1d (snapshot pour analyse ultérieure)
    macro_vix_level REAL,
    macro_vix_regime TEXT,
    macro_dxy_dist_sma50 REAL,
    macro_tnx_level REAL,
    macro_spx_return_5d REAL,
    macro_btc_return_5d REAL,
    -- Suivi outcome (rempli a posteriori par job de réconciliation)
    outcome TEXT,                           -- NULL → en cours, sinon 'TP1' | 'SL' | 'TIMEOUT'
    exit_at TIMESTAMP,
    exit_price REAL,
    pnl_pct_net REAL,                       -- net après spread 0.02%
    pnl_eur REAL,                           -- pct × position_eur
    -- Index
    UNIQUE (system_id, bar_timestamp)        -- 1 setup par bar H4 par système
);

CREATE INDEX idx_shadow_setups_pair_time ON shadow_setups (pair, bar_timestamp);
CREATE INDEX idx_shadow_setups_system ON shadow_setups (system_id);
CREATE INDEX idx_shadow_setups_outcome ON shadow_setups (outcome);
```

**UNIQUE (system_id, bar_timestamp)** : empêche les doublons quand le scheduler tourne plusieurs fois sur le même bar H4 (toutes les 5 minutes le scheduler tourne, mais on ne veut qu'1 entrée par bar H4 fermé).

### Reconciliation des outcomes (job séparé)

**Fichier nouveau :** `backend/services/shadow_reconciliation.py`

Job qui tourne toutes les 1h, parcourt les `shadow_setups` avec `outcome IS NULL` et `bar_timestamp < NOW() - 4 days` (au-delà du timeout 96h H4), simule l'outcome avec les candles 5min disponibles (idem `simulate_trade_forward`).

Triggered par le scheduler dans `cockpit_broadcast_cycle` (existing, toutes les 1h).

### Endpoint API — `GET /api/shadow/v2_core_long/setups`

**Fichier :** `backend/api/routes/shadow.py` (nouveau)

```python
@router.get("/api/shadow/v2_core_long/setups")
def list_shadow_setups(
    since: datetime | None = None,
    until: datetime | None = None,
    system_id: str | None = None,
    outcome: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """Liste les setups shadow log avec filtres optionnels.
    Auth : same-origin cookie (idem dashboard).
    """
```

Et un endpoint synthèse :

```python
@router.get("/api/shadow/v2_core_long/summary")
def shadow_summary() -> dict:
    """Synthèse depuis t0 (premier setup en DB) :
    - n_setups par système
    - n_outcomes resolved vs pending
    - PF observed (sur outcomes resolved)
    - Sharpe annualisé approximatif
    - PnL eur cumulé
    - Comparaison avec attendus backtest (PF target 1.59, ~33 setups/mois XAU)
    """
```

### Frontend (optionnel mais utile)

**Page :** `/v2/shadow-log`

Tableau interactif :
- Liste paginée des setups (latest first)
- Colonnes : detected_at, system, pair, pattern, entry, SL, TP1, RR, position_eur, outcome, pnl_eur
- Filtres : système, paire, outcome, période
- Stats agrégées en haut : n_setups (last 30d), PF observed, taux résolution, comparaison avec backtest

Réutilise les composants V2 existants (Tailwind + react-query).

## Métriques de comparaison live vs backtest

À mesurer mensuellement via le job de monitoring (ou manuellement via `/summary`) :

| Métrique | Cible backtest 24M | Cible live (1 mois) | Cible live (6 mois) |
|---|---|---|---|
| Setups/mois XAU H4 | ~25 | 15-35 (large) | 22-30 (resserré) |
| Setups/mois XAG H4 | ~23 | 15-30 | 20-26 |
| WR XAU H4 (LONG only) | ~55% | 40-70% (large) | 50-60% |
| PF observed XAU | ~1.6 (filtre core) | 1.0+ acceptable | ~1.5 attendu |
| Sharpe annualisé | 1.59 | non calc | 1.0+ acceptable |
| Slippage observé | 0.02% theoretical | mesurer | < 0.05% souhaité |

### Alertes (pas critiques mais utiles)

- Setups/mois en deçà de 15 sur 30 jours → enquêter (data feed, market regime ?)
- WR < 40% sur 30+ trades → flag, possible drift
- Slippage moyen > 0.08% → flag, exécution plus chère qu'attendu

## Critères de migration vers Phase 5

Au gate S6 (2026-06-06, soit 6 semaines après le démarrage Phase 4) :

| Sortie | Condition | Décision |
|---|---|---|
| **GO Phase 5** | Setups XAU H4 ≥ 50 sur la période ET WR ≥ 50% ET PF live ≥ 1.3 ET pas d'incident slippage | Activer auto-exec Phase 5 sur compte démo Pepperstone (séparé de l'auto-exec V1, désactiver V1 au moment du switch) |
| **Délai +6 semaines** | Setups corrects mais PF entre 1.0 et 1.3 | Continuer Phase 4 jusqu'au gate S12 (2026-07-18) |
| **Stop / pivot** | Setups < 30 sur 6 semaines OU WR < 40% OU PF live < 0.9 | Édition shadow log live ne valide pas le backtest. Re-investiguer (Track B walk-forward expansif, Track C Phase 2 vol target, ou pivot Observatoire SaaS-only) |

## Étapes d'implémentation (4-6h estimées)

### Étape 1 — Schéma DB + module shadow (1h)
- Ajouter table `shadow_setups` au schéma SQLite
- Module `backend/services/shadow_v2_core_long.py` avec `_run_shadow_log_v2_core_long`
- Hook dans `run_analysis_cycle` après le bloc V1 (try/except non-bloquant)

### Étape 2 — Reconciliation des outcomes (1h)
- Module `backend/services/shadow_reconciliation.py`
- Job triggered par `cockpit_broadcast_cycle` (toutes les 1h)
- Update outcome / exit_at / exit_price / pnl_eur dans `shadow_setups`

### Étape 3 — Endpoints API (45 min)
- `GET /api/shadow/v2_core_long/setups` (liste filtrable)
- `GET /api/shadow/v2_core_long/summary` (KPIs)
- Auth cookie session same-origin (idem dashboard)
- Tests unitaires basiques

### Étape 4 — Frontend (1-2h)
- Page `/v2/shadow-log` avec tableau + filtres + KPIs
- Réutilise composants Tailwind/Bento existants

### Étape 5 — Tests + déploiement (1h)
- Tests intégration : forcer un cycle scheduler en local, vérifier 1 setup loggé
- Backfill : optionnellement re-runner les 14 derniers jours pour pré-remplir
- Deploy EC2 via `bash deploy-v2.sh` (gel V1 levé seulement pour ce module shadow)

### Étape 6 — Monitoring (continu)
- Vérifier setups arrivent quotidiennement
- Hebdo : check synthèse `/api/shadow/v2_core_long/summary` vs cibles backtest

## Risques & mitigations

1. **Aggrégation H1 → H4 dans le scheduler** ajoute une charge CPU minime (4 paires × 100 candles ≈ 400 ops simples par cycle). Négligeable.
2. **DB shadow_setups grandit** ~25-30 lignes/mois × 2 paires = ~50/mois. Sur 1 an : 600 lignes. Stockage négligeable (~50 KB).
3. **Bug dans la branche shadow** ne doit pas casser le cycle V1. **try/except autour** + logger.warning si fail.
4. **Décalage timing** : le scheduler tourne toutes les 5 min sur 5min candles, mais H4 candles ne ferment qu'aux heures pleines /4. La logique `aggregate_to_h4` doit gérer les bars partiels (skip ceux non fermés). À tester en local.
5. **Rate limit Twelve Data** : pas d'impact, on réutilise les `h1_candles` déjà fetchés par le cycle V1. Aucun fetch supplémentaire.

## Ce qui n'est PAS dans Phase 4

- Pas de Telegram alert sur shadow setups (ajout manuel post-Phase 4 si voulu)
- Pas d'export CSV (ajout post si demandé)
- Pas de comparaison automatisée live vs backtest (le `/summary` donne les KPIs, mais analyse mensuelle reste manuelle)
- Pas d'intégration ML (`ml_predictor` reste sur cycle V1)
- Pas de filtre macro (Track B exp #9 reporté car régime-spécifique)

## Décision finale

Au gate S6, **3 sorties possibles** :

1. **GO Phase 5 auto-exec** — V2_CORE_LONG XAU H4 prend le relais de V1 sur compte démo Pepperstone, capital 5-10k€ démo, risque 0.5%/trade. Phase 6 (live réel) suivrait ~3 mois plus tard si Phase 5 valide.
2. **Continue shadow** — données live ambiguës, on étend de 6 semaines.
3. **Stop / pivot** — données live infirment le backtest, on bascule vers Observatoire SaaS-only.

## Artefacts à produire

- `backend/services/shadow_v2_core_long.py`
- `backend/services/shadow_reconciliation.py`
- `backend/api/routes/shadow.py`
- Schema migration : ajout table `shadow_setups`
- Frontend : `frontend-v2/src/pages/ShadowLog.tsx`
- Tests : `backend/tests/test_shadow_v2_core_long.py`

## Documentation associée

- Master plan recherche : `docs/superpowers/specs/2026-04-25-research-portfolio-master.md`
- Track A spec : `docs/superpowers/specs/2026-04-25-track-a-horizon-h4.md`
- Findings J1 : `docs/superpowers/journal/INDEX.md` (13 expériences)
- Système de risque : `scripts/research/risk_metrics.py` (vol target sizing à reproduire en prod)
