# Checklist de validation finale — Session 2026-04-25/26

État du projet à l'issue de la session de recherche intensive (~12h).

---

## 1. Documentation et spec

### Specs (versionnés et pushés)
- [x] Master plan : `docs/superpowers/specs/2026-04-25-research-portfolio-master.md`
- [x] Track A horizon : `docs/superpowers/specs/2026-04-25-track-a-horizon-h4.md`
- [x] Track B alt-data : `docs/superpowers/specs/2026-04-25-track-b-altdata-cross-asset.md`
- [x] Track C TF : `docs/superpowers/specs/2026-04-25-track-c-trend-following.md`
- [x] Phase 4 shadow log : `docs/superpowers/specs/2026-04-25-phase4-shadow-log-spec.md`
- [x] Synthèse finale : `docs/superpowers/specs/2026-04-26-research-project-synthesis.md`

### Journal d'expériences (29 entrées)
- [x] 27 entrées d'expériences fermées (#1 à #28, sauf #19/#20/#21/#22/#23/#26 qui sont infra/tooling commités)
- [x] Index exhaustif : `docs/superpowers/journal/INDEX.md`
- [x] README convention + template : journal/README.md, _template.md
- [x] Synthèse par track au bas de l'INDEX

## 2. Code recherche (versionné)

- [x] `scripts/research/track_a_backtest.py` (multi-TF + V2_CORE/TIGHT/EXT/ADAPTIVE filters)
- [x] `scripts/research/track_c_trend_following.py` (TF systématique)
- [x] `scripts/research/track_a_inter_a_c.py` (intersection)
- [x] `scripts/research/track_b_macro_buckets.py` (analyse univariée)
- [x] `scripts/research/track_b_macro_filter.py` (filtre OR walk-forward)
- [x] `scripts/research/track_b_pretest_2023.py` (robustesse pré-bull)
- [x] `scripts/research/track_b_walk_forward.py` (refit mensuel)
- [x] `scripts/research/track_a_adaptive.py` (V2_ADAPTIVE régime-aware)
- [x] `scripts/research/track_a_c_sharpe.py` (Sharpe analysis 4 candidats)
- [x] `scripts/research/track_a_c_correlation.py` (Pearson A × C)
- [x] `scripts/research/risk_metrics.py` (vol target + Sharpe + Calmar + maxDD)

## 3. Code production (Phase 4)

### Backend
- [x] `backend/services/macro_data.py` (fetch + cache + features no look-ahead)
- [x] `backend/services/shadow_v2_core_long.py` (run_shadow_log, persist, list, summary avec KPIs avancés)
- [x] `backend/services/shadow_reconciliation.py` (reconcile_pending_setups)
- [x] Hook scheduler dans `backend/services/scheduler.py` (try/except non-bloquant)
- [x] Hook reconciliation auto dans `cockpit_broadcast_cycle` (toutes les ~12 ticks)
- [x] Endpoints `/api/shadow/v2_core_long/{setups,setups.csv,summary}` dans `backend/app.py`

### Frontend
- [x] Page `frontend-react/src/pages/ShadowLogPage.tsx` avec :
  - KPIs synthèse + cibles backtest visuelles
  - Equity curves SVG par paire
  - Bar chart monthly returns SVG
  - Tableau filtré + export CSV
- [x] Composants : `EquityCurveChart.tsx`, `MonthlyReturnsChart.tsx`
- [x] Hook : `useShadowLog.ts` (queries react-query)
- [x] Types : `ShadowSetup`, `ShadowSystemSummary`, `ShadowAdvancedKpis`, `ShadowEquityPoint`, `ShadowMonthlyReturn`
- [x] Lien dans nav Header
- [x] Route `/v2/shadow-log` dans App.tsx

## 4. Tests

- [x] `backend/tests/test_shadow_v2_core_long.py` — 10 tests (aggregate H4, schema, run, list, summary)
- [x] `backend/tests/test_shadow_reconciliation.py` — 6 tests (reconcile + bug fix pending_remaining)
- [x] `backend/tests/test_macro_data.py` — 9 tests (schema, upsert, lookup, no look-ahead, vix regime)
- [x] `backend/tests/test_risk_metrics.py` — 12 tests (vol target, maxDD, Sharpe, Calmar, monthly)
- [x] **37/37 Phase 4 passent en 1.7s**

## 5. Phase 4 deployment status

- [x] Service backend deployed sur EC2 le 2026-04-25 17:06 UTC
- [x] Frontend bundle index-CqZCs8gN.js déployé (avant les améliorations)
- [x] Endpoint `/api/health` répond
- [x] Page `/v2/shadow-log` accessible (200)
- [x] Scheduler tourne avec hook shadow log + reconciliation auto
- [x] Schema DB shadow_setups créé via ensure_schema()

## 6. Mémoire (persiste cross-sessions)

- [x] `feedback_dont_tell_user_to_stop.md` — règle anti-stop
- [x] `feedback_always_state_recos.md` — toujours énoncer reco
- [x] `project_research_portfolio.md` — pivot stratégique
- [x] `project_research_j1_findings.md` — findings finaux + Phase 4 deployed
- [x] `MEMORY.md` index à jour

## 7. Commits

- [x] **34 commits totaux** sur la session
- [x] **22 commits pushés** sur main (avant le push refusé)
- [x] **12 commits en local non pushés** (depuis le seuil de push refusé)

### Commits en local à pousser (12)

```
eeef9d3 test(phase-4): tests unitaires macro_data (9) + risk_metrics (12)
16e26b8 docs(synthesis): white paper interne — 26 expériences
3ec2682 feat(shadow-ui): KPI cards comparées aux cibles backtest
edc0d99 research(adaptive): exp #25 — V2_ADAPTIVE neutre
1e62b44 research(walk-forward): exp #24 — refit dynamique INFÉRIEUR
1e423d4 feat(shadow-export): endpoint CSV + bouton dans ShadowLogPage
243767c test(phase-4): tests unitaires shadow + fix bug pending_remaining
2b689c8 feat(shadow-ui): bar chart monthly returns
16f62ab feat(shadow-ui): equity curve chart + Sharpe/Calmar/maxDD
cba743f feat(shadow): KPIs avancés summary
091ecde research(cross-asset): exp #18 — V2_CORE NE marche PAS sur indices
d78d07f feat(ui): ajoute lien Shadow dans le Header nav
```

À pusher manuellement par user : `git push origin main` (le harness avait refusé le push direct après 22 push consécutifs).

## 8. Actions restantes (par ordre)

### Immédiates (5 min, à faire manuellement par user)

- [ ] `git push origin main` — pousser les 12 commits en local
- [ ] `bash deploy-v2.sh` — redéployer pour activer les améliorations frontend (KPIs avancés, equity curve, monthly chart, export CSV, lien Header, comparaison cibles)

### Court terme (jours)

- [ ] **Monitoring quotidien** : checker `/v2/shadow-log` une fois par jour, vérifier setups arrivent (cible 1-2/jour entre XAU+XAG)
- [ ] Si 0 setup en 3+ jours → enquêter (data feed Twelve Data, scheduler down ?)

### Moyen terme (semaines)

- [ ] **2 semaines** : ~50 setups attendus, premier feel du PF live
- [ ] **4 semaines** : alimenter le journal avec findings live (déviations slippage, etc.)
- [ ] **6 semaines** : gate S6 (~2026-06-06), décision Phase 5 selon critères dans white paper

### Long terme (mois)

- [ ] Si gate S6 = GO Phase 5 : auto-exec V2_CORE_LONG XAU H4 sur démo Pepperstone
- [ ] Si gate S6 = STOP / PIVOT : bascule Observatoire SaaS-only

## 9. Métriques cibles à monitorer (post-redeploy)

Visibles directement dans `/v2/shadow-log` :

| Métrique | Cible (XAU) | Cible (XAG) | Source |
|---|---|---|---|
| Setups/mois | ~25 | ~23 | Backtest 24M |
| Sharpe annualisé | 1.59 | 1.55 | Backtest 24M |
| PF observed | 1.32-1.59 | 1.32-1.59 | Cumul 6 ans |
| maxDD% | < 20% | < 26% | Backtest 24M |
| WR% | 50-55% | 49-54% | Backtest 24M |

## 10. Limitations et risques connus

- [x] Risque slippage live > 0.02% (attendu 0.05-0.08%) → PF live -0.10 à -0.15
- [x] Sample 24M : Sharpe IC 95% ± 0.4
- [x] maxDD XAG 124% sur 6 ans → sizing prudent en live
- [x] Edge cycle-amplifié : PF moyen 1.32 (cumul) vs 1.59 (bull)
- [x] Long-only : performe mal en bear durables
- [x] 7 tentatives d'extension toutes neutres ou négatives → optimum local atteint

---

**Date de validation :** 2026-04-26 (~03h45 Paris)
**Statut global :** ✅ Phase 4 implémentation et deployment complets · 12 commits frontend en attente de push/redeploy
