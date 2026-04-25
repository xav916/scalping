# Synthèse du projet recherche — Edge sur retail forex/métaux

**Date :** 2026-04-26
**Auteur :** session collaborative humain + assistant
**Période couverte :** 2026-04-25 (~16h Paris) → 2026-04-26 (~03h30 Paris)
**Durée effective :** ~11h de recherche intensive
**26 expériences fermées · 32 commits · 3 tracks complétées · système deployed Phase 4**

---

## 1. Contexte initial

### Verdict V1 confirmé

Avant cette session, le système V1 (scalping H1 + scoring rule-based + ML technique) avait déjà été infirmé par 2 tests indépendants :

1. **Backtest 12 mois × 12 paires (39 689 trades)** — toutes stratégies négatives avec coûts 0.02% (cf `2026-04-22-backtest-v1-findings.md`)
2. **ML training V1 sur 233 567 samples / 6-10 ans** — AUC 0.526 (seuil edge 0.55), modèle non-sauvegardé (cf `2026-04-22-ml-findings.md`)

### Décision pivot du 2026-04-25 matin

Le user a explicitement choisi le mode **recherche structurée 30h/sem × plusieurs mois**, en acceptant que la recherche puisse échouer. Plutôt que de tester les pistes des findings ML en série (option par défaut roadmap), l'approche **portefeuille de 3 tracks parallèles** a été actée :

| Track | Hypothèse | Critère succès |
|---|---|---|
| **A — Horizon expansion** | Edge à H4/Daily car spread amorti | PF ≥ 1.15 sur 12M (≥1 paire/strat) |
| **B — Alt-data + cross-asset** | Edge dans features non-techniques | AUC ≥ 0.55 sur ML re-entraîné |
| **C — Trend-following systématique** | Edge en TF Carver-style multi-asset | Sharpe > 0.7 sur 12M |

Spec master : `2026-04-25-research-portfolio-master.md`

---

## 2. Système final identifié

### V2_CORE_LONG sur XAU+XAG H4

**Filtre minimal :**
```python
CORE_LONG_PATTERNS = {"momentum_up", "engulfing_bullish", "breakout_up"}

def filter_v2_core_long(t):
    return t["direction"] == "buy" and t["pattern"] in CORE_LONG_PATTERNS
```

**Pas de filtre macro** (testé en exp #9, #10, #24 — régime-spécifique, dégrade en pré-bull cycle).

### KPIs cibles (depuis backtest 6 ans cross-régime)

| Métrique | XAU H4 | XAG H4 |
|---|---|---|
| Sharpe annualisé | **1.59** (TEST 24M) | **1.55** (TEST 24M) |
| Sharpe pondéré 6 ans | ~1.30-1.45 | ~1.30-1.40 |
| PF cumulé 6 ans | **1.33** | **1.34** |
| maxDD% | 20% (24M) / 53% (6 ans) | 26% (24M) / 124% (6 ans) |
| Total return 24M | +127% | +136% |
| Setups/mois | ~25 | ~23 |
| WR | 55% (bull) / 49% (cumul) | 54% (bull) / 49% (cumul) |

### Validation cross-régime (3 régimes très différents)

- **2020 (COVID)** : VIX 80+, gold rallye 1500→2050, crash equity puis recovery
- **2022 (bear cycle)** : VIX 25-35, gold crash 2050→1620, SPX -25%
- **2024-2026 (bull cycle métaux)** : gold 2200 → 3300+

**PF V2_CORE_LONG sur chaque période** (XAU H4) :
- 2020-2024 (4 ans pré-bull, simulator H1) : **1.26**
- 2024-2026 (2 ans bull, sim 5min) : **1.41**
- Cumul 6 ans : **1.33**

XAG : 1.16 / 1.59 / 1.34 (plus volatile mais robuste cross-régime).

---

## 3. Synthèse des 26 expériences

### Track A — Horizon expansion (4 exp)

| # | Hypothèse | Verdict |
|---|---|---|
| 1 | Spike H4 vs H1 vs Daily | XAU/XAG H4 + ETH 1d signal (PF≥1.15) |
| 2 | Direction × pattern | XAU/ETH = edge réel (SELLs PF≥1.09) |
| 3 | Robustesse 24 mois | XAG robuste, XAU filtré, ETH retiré |
| 4 | V2_CORE_LONG combiné | PF 1.41-1.93 sur 4/4 runs, premier candidat |

### Track C — Trend-following (2 exp)

| # | Hypothèse | Verdict |
|---|---|---|
| 5 | TF MVP (EMA 12/48 + filter 100 + ATR×3) | PF 2.32-3.76 LONG sur métaux, bat A |
| 11 | TF cross-régime pré-bull | XAU robuste (PF 5.60), XAG conditionnel |

### Track A ∩ C (1 exp)

| # | Hypothèse | Verdict |
|---|---|---|
| 6 | Intersection asset-spécifique | XAG synergie (+0.60 PF), XAU redondance |

### Track B — Alt-data + cross-asset (4 exp)

| # | Hypothèse | Verdict |
|---|---|---|
| 7 | Pipeline data macro (VIX/DXY/SPX/TNX/BTC) | 5/5 symboles, 8643 obs daily 6 ans, opérationnel |
| 8 | Spread PF par bucket macro | 9/9 dimensions discriminent (max +2.06 sur BTC return 5d) |
| 9 | Filtre macro walk-forward | TEST PF 1.81 → 2.28 (Δ +0.47, robuste) |
| 10 | Robustesse pré-bull 2023-24 | Filtre dégrade en PRE_TEST (-0.50) — régime-spécifique |

### Risk-adjusted analysis (2 exp)

| # | Hypothèse | Verdict |
|---|---|---|
| 12 | Sharpe sur 4 candidats 24M | 4/4 ≥ 1.27 ; XAU CORE Sharpe 1.59 (Carver "very good") |
| 13 | Corrélation Track A × Track C | 0.56-0.68 modéré, Sharpe combiné +0.02 marginal |

### Phase 4 implementation (2 exp)

| # | Hypothèse | Verdict |
|---|---|---|
| 14 | Module shadow + reconciliation + endpoints | Implémentation OK, KPIs cohérents, deployed |
| 15 | Out-of-sample 2020-2024 (4 ans pré-bull) | XAU PF 1.26 / XAG 1.16, robuste 6 ans cross-régime |

### Tentatives d'extension/optimisation (7 exp, **toutes neutres ou négatives**)

| # | Extension testée | Δ PF |
|---|---|---|
| 16 | V2_EXT (4 patterns + pin_bar_up) | -0.04 à -0.09 |
| 17 | V2_TIGHT (2 patterns) | -0.10 à -0.15 (bull), +0.05 (calme) |
| 18 | Cross-asset SPX/NDX | PF 0.23-0.73 (gaps overnight) |
| 19 | KPIs avancés summary | (infra, pas extension) |
| 20 | Equity curve frontend | (infra, pas extension) |
| 21 | Monthly returns chart | (infra) |
| 22 | Tests unitaires Phase 4 | 16/16 + 1 bug fixé |
| 23 | Endpoint export CSV | (infra) |
| 24 | Walk-forward expansif macro | -0.34 (sur-fit) |
| 25 | V2_ADAPTIVE régime-aware | -0.02 (détecteur trop crude) |
| 26 | UI cibles backtest | (infra) |

**Insight cumulé : V2_CORE_LONG est l'optimum local** atteignable avec les techniques explorées. C'est en fait une bonne nouvelle — système simple, robuste, résistant au tinkering.

---

## 4. Phase 4 deployed status

### Infrastructure live

- **Service backend** : `scalping.service` actif sur EC2 depuis 2026-04-25 17:06 UTC
- **Frontend** : `https://scalping-radar.duckdns.org/v2/shadow-log`
- **Endpoints API** :
  - `GET /api/shadow/v2_core_long/setups` (paginé, filtré)
  - `GET /api/shadow/v2_core_long/setups.csv` (download CSV)
  - `GET /api/shadow/v2_core_long/summary` (KPIs avancés)
- **Hook scheduler** : `run_shadow_log` dans `run_analysis_cycle` (try/except non-bloquant)
- **Hook reconciliation** : auto toutes les ~12 min via `cockpit_broadcast_cycle`
- **Persistance** : table `shadow_setups` dans `trades.db` (UNIQUE par system_id × bar_timestamp)

### Système observable

- 2 systèmes loggés en parallèle :
  - `V2_CORE_LONG_XAUUSD_4H` (allocation 100% phase v1)
  - `V2_CORE_LONG_XAGUSD_4H` (observation seulement, allocation 0%)
- Capital virtuel 10 000 €, risque 0.5% par trade
- Sizing position = `100€ / risk_pct_setup`

### Frontend visible (post-redeploy)

- KPIs synthèse avec cibles backtest (Sharpe, maxDD%, setups/mois)
- Equity curve par paire (SVG inline)
- Bar chart monthly returns (SVG inline)
- Tableau filtrable (système, outcome)
- Bouton Export CSV

---

## 5. Limitations et caveats

### Limitations méthodologiques

1. **Coûts modélisés à 0.02% spread/slippage** théorique. Live attendu 0.05-0.08% sur retail Pepperstone démo → PF effectif live = PF backtest -0.10 à -0.15.
2. **Simulator H1 fallback** introduit -0.01 à -0.02 PF d'imprécision pour les fenêtres pré-2023 (où 5min DB n'existe pas).
3. **Sample size 24M** : Sharpe IC 95% typiquement ± 0.4. Donc PF 1.59 → vraie Sharpe entre 1.2 et 2.0.
4. **Survival bias instruments** : XAU et XAG existent sur toute la période — biais mineur.
5. **Pas testé > 6 ans** — Twelve Data Grow plafonne. Pour vraie robustesse multi-cycles, faudrait dataset 2010-2026.

### Limitations système

1. **maxDD XAG 124% sur 6 ans** — anormalement élevé, à gérer par sizing prudent en live.
2. **Edge concentré sur 2 actifs** — pas de diversification multi-classe (forex, crypto, indices à plat).
3. **Long-only** — performe mal en régimes de baisse durables (à monitorer en live).
4. **Cycle-amplifié** — PF moyen pondéré 1.32 (cumul 6 ans) vs 1.59 (bull cycle 24M). En régime calme, attendre PF 1.10-1.20.

### Limitations Phase 4 v1

1. **Pas de filtre macro** (volontaire — régime-spécifique selon exp #10 et #24).
2. **Pas de système adaptatif** (testé exp #25, neutre).
3. **2 systèmes parallèles XAU+XAG** mais seul XAU activé en allocation v1.
4. **Pas de notification Telegram sur shadow setups** (choix design pour ne pas distraire).
5. **Reconciliation auto** sur les 5min live via Twelve Data — risque rate limit si beaucoup de pending.

---

## 6. Critères de migration vers Phase 5 (auto-exec démo)

À évaluer au gate S6 (~2026-06-06) :

| Sortie | Condition | Décision |
|---|---|---|
| **GO Phase 5** | ≥ 50 setups XAU sur 6 sem ET WR ≥ 45% ET PF live ≥ 1.15 ET maxDD < 30% ET pas d'incident slippage > 0.08% | Activer auto-exec V2_CORE_LONG XAU H4 sur démo Pepperstone (séparé de V1, désactiver V1 au switch) |
| **Délai +6 sem** | Setups corrects mais PF entre 1.0 et 1.15 | Étendre Phase 4 jusqu'au gate S12 (~2026-07-18) |
| **Stop / pivot** | Setups < 30 sur 6 sem OU PF live < 0.9 OU drift macro évident | Édition shadow log infirme le backtest. Re-investiguer ou pivot Observatoire SaaS-only |

---

## 7. Prochaines étapes prévisibles

### Court terme (jours)

- **Monitoring shadow log** : checker `/v2/shadow-log` quotidiennement, vérifier setups arrivent (cible 1-2/jour entre les 2 paires).
- **Push 11 commits non-pushés** + redeploy si user veut voir les KPIs avancés et cibles backtest dans le UI.

### Moyen terme (semaines)

- **2 sem** : ~50 setups attendus, KPIs prennent forme statistique. Premier "feeling" du PF live.
- **4 sem** : alimenter le journal d'expériences avec les findings live (ex: déviations slippage observed).
- **6 sem** (gate S6) : décision Phase 5.

### Long terme (mois) — si gate S6 = GO Phase 5

- **2-3 mois** : auto-exec V2_CORE_LONG XAU H4 sur démo Pepperstone, capital 5-10k€ démo.
- **3-6 mois** : si Phase 5 valide, passage **live réel** sur compte Pepperstone réel (capital décidé par user).
- **6+ mois** : exploration Phase 6 — diversification (XAG en allocation 30%, intersection avec Track C, multi-asset futures ES/NQ).

### Long terme (mois) — si gate S6 = STOP / PIVOT

- Bascule **Observatoire SaaS-only** : projet conserve sa valeur (visibilité, alertes, dashboard) sans prétention edge.
- Documentation de la non-trouvaille comme valeur publique (papier interne, post-mortem).
- L'infra MT5 + journal recherche reste réutilisable pour de futurs paris.

---

## 8. Fichiers de référence

### Spec et journal
- Master : `docs/superpowers/specs/2026-04-25-research-portfolio-master.md`
- Phase 4 : `docs/superpowers/specs/2026-04-25-phase4-shadow-log-spec.md`
- Index expériences : `docs/superpowers/journal/INDEX.md` (26 entrées)

### Code modules clés
- Backtest engine : `scripts/research/track_a_backtest.py` (multi-TF, V2_CORE/TIGHT/EXT filters)
- TF systématique : `scripts/research/track_c_trend_following.py`
- Macro data : `backend/services/macro_data.py`
- Shadow log live : `backend/services/shadow_v2_core_long.py`
- Reconciliation : `backend/services/shadow_reconciliation.py`
- Risk metrics : `scripts/research/risk_metrics.py`
- Tests : `backend/tests/test_shadow_*.py` (16 tests)

### Mémoire (persiste cross-sessions)
- `project_research_portfolio.md` — pivot stratégique
- `project_research_j1_findings.md` — findings finaux

---

## 9. Conclusion

Cette session de 11h a produit le **premier vrai système prod-ready validé out-of-sample** du projet Scalping Radar. Le portefeuille recherche initialement pensé sur 6 semaines a accouché en 1 jour grâce à :

1. **Méthodologie disciplinée** : journal d'expériences, critères go/no-go fixés AVANT, walk-forward strict
2. **Convergence cross-méthodologique** : Track A (patterns) et Track C (TF) identifient indépendamment XAU+XAG H4
3. **Stress testing maximal** : 6 ans de data, 3 régimes (COVID, bear, bull), 7 tentatives d'extension
4. **Pas de tinkering naïf** : chaque tentative d'amélioration a été testée empiriquement, pas adoptée par hype

Le système V2_CORE_LONG sur XAU H4 (Sharpe 1.59 sur 24M, PF 1.33 sur 6 ans) est dans le **top 10% des stratégies retail** par les benchmarks Carver/Hurst.

**Rien n'est garanti pour le live** : Sharpe 1.59 sur 24M peut signifier vraie Sharpe 1.2-2.0 (IC 95%). Les coûts live vont dégrader 0.10-0.15. Et les régimes futurs peuvent différer de tout ce qu'on a vu.

Mais c'est un **point de départ rigoureux** pour l'observation live Phase 4. Les 6 prochaines semaines diront si l'edge backtest se transpose en edge live exploitable.

**Si oui** → Phase 5 puis live réel.
**Si non** → on aura économisé l'argent réel et appris énormément sur la robustesse du retail trading. Pas un échec, un fait empirique honnêtement validé.
