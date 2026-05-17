# Rapport hebdo W3 — Shadow log V2_CORE_LONG

**Date :** 2026-05-17 (auto-généré par agent)
**Période :** 2026-05-10 → 2026-05-17 (7 jours, W3)
**Période cumulée Phase 4 :** 2026-04-25 → 2026-05-17 (22 jours)
**Déploiement Phase 4 :** 2026-04-25 17h00 UTC
**Source API :** `app.scalping-radar.online` — HTTP 200 ✅

---

## Santé endpoint public

| Endpoint | Statut | Code HTTP |
|---|---|---|
| `GET /api/shadow/v2_core_long/public-summary` | **OK** | 200 ✅ |
| `GET /v2/` (frontend SPA) | **OK** | 200 ✅ |

---

## KPIs W3 — Tableau progression W1 → W2 → W3

### V2_CORE_LONG_XAUUSD_4H

| Métrique | W1 (J+7) | W2 (J+15) | W3 (J+22) | Cible 21j | Trigger |
|---|---|---|---|---|---|
| n_total | N/A | 9 | **10** | ~18 | OK (∈[9,36]) |
| n_pending | N/A | 6 | **0** | — | — |
| n_tp1 / n_sl / n_timeout | N/A | 2/1/0 | **2/5/3** | — | — |
| net_pnl_eur | N/A | +127.68 | **+12.99** | — | — |
| PF | N/A | 3.51 | **1.051** | 1.32–1.59 | ⚠️ WARNING (0.85–1.15) |
| WR% | N/A | 66.7% | **28.6%** | 50–55% | ⚠️ WARNING |
| Sharpe | N/A | null | **null** | ≥0.8 | ⏳ (< 30 résolus) |
| maxDD% | N/A | 0.5% | **2.0%** | <20% | ✅ OK |
| Dernier signal | — | 2026-05-08 | **2026-05-12** | — | ⚠️ Silence 5j |
| Tendance | — | — | **DÉGRADATION** | — | |

### V2_CORE_LONG_XAGUSD_4H

| Métrique | W1 (J+7) | W2 (J+15) | W3 (J+22) | Cible 21j | Trigger |
|---|---|---|---|---|---|
| n_total | N/A | 10 | **17** | ~18 | ✅ OK (∈[9,36]) |
| n_pending | N/A | 9 | **3** | — | — |
| n_tp1 / n_sl / n_timeout | N/A | 0/1/0 | **4/4/6** | — | — |
| net_pnl_eur | N/A | −30.30 | **+168.35** | — | — |
| PF | N/A | 0.0¹ | **2.318** | 1.32–1.59 | ✅ OK (≥1.15) |
| WR% | N/A | 0.0%¹ | **50.0%** | 49–54% | ✅ OK |
| Sharpe | N/A | null | **null** | ≥0.7 | ⏳ (< 30 résolus) |
| maxDD% | N/A | 0.3% | **0.9%** | <26% | ✅ OK |
| Dernier signal | — | 2026-05-08 | **2026-05-14** | — | — |
| Tendance | — | — | **AMÉLIORATION** | — | |

### V2_WTI_OPTIMAL_WTIUSD_4H

| Métrique | W2 (J+15) | W3 (J+22) | Trigger |
|---|---|---|---|
| n_total | 3 | **4** | ⚠️ WARNING (∈[3,8]) |
| n_tp1 / n_sl / n_timeout | 0/1/1 | **0/2/1** | |
| net_pnl_eur | −48.08 | **−78.21** | |
| PF | 0.0¹ | **0.0** | ⚠️ WARNING² |
| maxDD% | 0.5% | **0.8%** | ✅ OK |
| Tendance | — | **DÉGRADATION** | |

### V2_CORE_LONG_ETHUSD_1D

| Métrique | W2 (J+15) | W3 (J+22) | Trigger |
|---|---|---|---|
| n_total | 2 | **2** | ⚠️ WARNING (∈[3,8])³ |
| n_tp1 / n_sl / n_timeout | 0/0/1 | **0/0/2** | |
| net_pnl_eur | −5.98 | **−24.19** | |
| PF | 0.0 | **0.0** | ⚠️ WARNING² |
| maxDD% | 0.1% | **0.2%** | ✅ OK |
| Tendance | — | **STABLE / légère dégradation** | |

### V2_WTI_OPTIMAL_XLK_1D

| Métrique | W2 (J+15) | W3 (J+22) | Trigger |
|---|---|---|---|
| n_total | 2 | **4** | ⚠️ WARNING (∈[3,8]) |
| n_tp1 / n_sl / n_timeout | 0/0/0 | **1/0/1** | |
| net_pnl_eur | n/a | **+86.40** | |
| PF | null | **null** (0 SL) | ✅ (pas de perte) |
| WR% | null | **100%** (1 TP1, 0 SL) | ✅ |
| maxDD% | null | **0.0%** | ✅ OK |
| Tendance | — | **AMÉLIORATION** | |

### V2_TIGHT_LONG_XLI_1D

| Métrique | W1 | W2 | W3 | Trigger |
|---|---|---|---|---|
| n_total | 0 | 0 | **0** | 🔴 CRITICAL (< 3) |
| Statut | CRITICAL | CRITICAL | **CRITICAL** | 22j sans signal |

¹ PF/WR W2 calculé sur 1 setup résolu — non représentatif.
² PF=0.0 sur ≤3 résolus — trigger CRITICAL (PF<0.85 sur >40 résolus) non atteint.
³ Horizon 1D : rythme normal ~1 setup/semaine → 2 setups en 22j reste dans le bas du WARNING.

---

## PnL portefeuille consolidé

| Système | W2 net_pnl | W3 net_pnl | Delta W2→W3 |
|---|---|---|---|
| V2_CORE_LONG_XAUUSD_4H | +127.68 € | **+12.99 €** | −114.69 € |
| V2_CORE_LONG_XAGUSD_4H | −30.30 € | **+168.35 €** | +198.65 € |
| V2_WTI_OPTIMAL_WTIUSD_4H | −48.08 € | **−78.21 €** | −30.13 € |
| V2_CORE_LONG_ETHUSD_1D | −5.98 € | **−24.19 €** | −18.21 € |
| V2_WTI_OPTIMAL_XLK_1D | n/a | **+86.40 €** | +86.40 € |
| V2_TIGHT_LONG_XLI_1D | 0 | **0** | 0 |
| **TOTAL** | **+43.32 €** | **+165.34 €** | **+122.02 €** |

**Capital virtuel portefeuille : +165.34 € / 10 000 € fictif = +1.65%** en 22 jours.

---

## Diagnostic cumulé 22 jours

### INFRA — OK ✅

API et frontend HTTP 200. Aucune régression infra. Stable depuis W2.

### DATA FEED — PARTIAL OK ⚠️

- 5/6 systèmes V2 actifs (XLI toujours absent → CRITICAL isolé)
- Volumes cumulés cohérents : XAU n=10 ✅, XAG n=17 ✅ (en bonne trajectoire vers ~18)
- **Signal d'alerte : XAU silencieux depuis 2026-05-12 (5 jours, 0 pending).** Aucun nouveau setup détecté. Cause : marché sans configuration H4 valide, ou impact du veto géopolitique (voir ci-dessous).
- XAG en cours de résolution (3 pending), dernier signal 2026-05-14

### PERFORMANCE — RÉSULTATS CONTRASTÉS

#### XAU : Correction post-pic — WARNING ⚠️

Les 6 setups pending de W2 se sont résolus défavorablement : 0 TP1 supplémentaire, 4 SL, 3 timeout. Le PF s'est effondré de 3.51 à 1.051. Ce n'est pas encore un signal d'alarme (PF>0.85, maxDD<20%, n_resolved=10<40) mais la trajectoire est préoccupante. Le système revient vers un PF plus réaliste — les premiers chiffres W2 (3.51 sur 3 résolus) étaient statistiquement prématurés.

**État réel XAU : PF=1.051 est au-dessus du seuil WARNING (0.85) mais sous la cible (1.32).** Le système reste légèrement profitable en absolu (+12.99 €) mais le signal sur 10 résolus suggère un edge plus modeste que les backtests.

#### XAG : Confirmation prometteuse — OK ✅

Forte inversion : de −30.30 € à +168.35 €, PF=2.318, WR=50%. Les 9 setups pending de W2 ont résolu positivement en agregé. C'est le leader du portefeuille W3. Le PF dépasse la cible haute (1.59) mais reste statistiquement limité (14 résolus). À confirmer sur 20+ résolus.

#### XLK : Surprise positive — WATCH 👀

Premier TP1 en W3 → +86.40 € net. PF techniquement infini (0 SL). 2 setups encore ouverts. Système jeune (démarrage J+9 deploy), mais premier signal de performance réel encourageant.

#### WTI : Dégradation continue — WARNING ⚠️

4 setups, 0 TP1, 2 SL + 1 timeout = −78.21 €. Aucune amélioration. Le detector WTI H4 ne parvient pas à trouver des configurations profitables. À surveiller W4 avant décision d'arrêt.

#### ETH : Stagnation — WARNING ⚠️

Aucun nouveau setup en W3 (horizon 1D, attendu). Les 2 setups résolus sont des timeouts. PF=0. Volume trop faible pour conclure (2 résolus).

### NOUVELLE FEATURE : Systèmes FILTERED (veto géopolitique)

L'API retourne désormais des variantes `_FILTERED` (apparus depuis 2026-05-11) :

| Système | Base PF | Filtered PF | Verdict |
|---|---|---|---|
| XAG 4H | 2.318 | 0.595 (n=6, 4 résolus) | 🔴 Veto contre-productif |
| XAU 4H | 1.051 | 0.0 (n=1, 1 SL) | 🔴 Veto contre-productif |
| XLK 1D | ∞ (0 SL) | null (2 pending) | ⏳ Trop tôt |

Le commit `alert(veto): direction_verdict=veto_would_hurt n=8` du 2026-05-16 confirme que le système lui-même a détecté 8 cas où le veto aurait dégradé la performance. **La fonctionnalité veto géopolitique (GDELT/Polymarket) semble actuellement trop conservatrice** — elle filtre des setups qui auraient été gagnants. À évaluer avant d'activer en mode bloquant.

### NOUVELLES DONNÉES : V1_SHADOW (apparu 2026-05-14)

L'API expose désormais 22+ systèmes `V1_SHADOW_*` (AUD/USD, BTC, ETH, EUR, GBP, NDX, WTI, XAU, XAG…). Tous ont `n_pending = n_total` (0 résolu), apparus le 2026-05-14. Ce sont les systèmes du **Pair Admission Controller** (commits `feat(admission)` W3). Ils loggent les signaux V1 par paire×direction pour permettre l'évaluation de l'admission avant promotion.

Volume notable : certains systèmes comptent 150-630 setups en 3 jours (ex. NDX_sell = 630). Ce volume élevé suggère que ces systèmes capturent des signaux à fréquence courte (non H4) — différent du scope Phase 4. Aucun impact sur l'évaluation V2.

---

## Activité git W2 → W3 (2026-05-10 → 2026-05-17)

**20 commits** pushés sur la période.

| Thème | Commits | Impact Phase 4 shadow |
|---|---|---|
| Pair Admission Controller (state machine, direction, auto-promote) | ~6 | Aucun (scope V1 admission) |
| PnL Regulator par pair (auto-pause fenêtre glissante) | ~3 | Aucun (V1 temps réel) |
| Bridge MT5 : MT5_SYMBOL_MAP + MT5_BRIDGE_BLOCKED_PAIRS | ~2 | Aucun (exécution) |
| EA MQL5 v1.03/1.04 (auto-detect alias + closed-trade hook) | ~2 | Aucun |
| Veto counterfactual alert (veto_would_hurt n=8) | ~1 | ⚠️ Indirect — veto filtre signaux V2 |
| Infra Telegram (cooldown dedup_key) | ~1 | Aucun |
| Docs (admission weekly, veto counterfactual) | ~3 | — |
| Fixes divers | ~2 | — |

> **Observation :** Aucun commit ne touche le scheduler Phase 4, `shadow_setups`, ou la logique de détection V2_CORE_LONG depuis le deploy initial (22 jours). Le pipeline shadow est stable. L'activité W3 est entièrement sur de nouvelles features V1/admission.

---

## Recommandations

### 1. CRITICAL — XLI toujours à 0 setup (22 jours)

`V2_TIGHT_LONG_XLI_1D` est absent de la DB depuis le deploy. Actions EC2 toujours recommandées :

```bash
sqlite3 /app/data/trades.db \
  "SELECT system_id, COUNT(*) FROM shadow_setups GROUP BY system_id ORDER BY 2 DESC;"
grep -r 'XLI\|TIGHT_LONG' /app/backend/ --include='*.py'
```

Si XLI n'est pas dans le scheduler Phase 4, ce candidat est disqualifié du gate S6.

### 2. WARNING — Silence XAU depuis 2026-05-12

Aucun nouveau setup XAU H4 depuis 5 jours, 0 pending. Deux causes possibles :
- Marché XAU en consolidation sans configuration H4 valide (acceptable)
- Veto géopolitique filtrant des setups qui auraient été générés (à vérifier via counterfactual endpoint)

À comparer avec le volume XAG (dernier signal 2026-05-14, toujours 3 pending) pour distinguer silence marché vs silence pipeline.

### 3. WARNING — PF XAU sous cible (1.051 vs 1.32)

Le PF réel XAU (10 résolus) est inférieur à la cible backtest. Deux interprétations :
- **Régression statistique normale** : les premiers 3 résolus W2 étaient un biais positif, 10 résolus restent insuffisants pour conclure
- **Edge plus faible que prévu** sur des conditions de marché réelles (vs backtest 20 ans)

Décision : surveiller W4. Si PF reste <1.15 à 20 résolus, revoir les paramètres du detector XAU H4.

### 4. INFO — Veto géopolitique à désactiver ou recalibrer

Les systèmes `_FILTERED` et l'alerte `veto_would_hurt` du 2026-05-16 convergent : le veto GDELT/Polymarket dégrade la performance nette sur XAU et XAG. Recommandation : maintenir en mode **monitoring-only** (pas de blocage), ne pas activer en mode bloquant avant W5-W6.

### 5. INFO — XLK positif mais volume insuffisant

XLK (V2_WTI_OPTIMAL_XLK_1D) affiche un PF infini sur 2 résolus. Encourageant mais trop tôt. Continuer à accumuler (cible : 8 résolus avant W5).

### 6. Gate S6 (2026-06-06) — Horizon 20 jours

| Condition gate S6 | Statut W3 | Trajectoire |
|---|---|---|
| XAU : n_resolved ≥ 20 | 10/20 | ⚠️ Faisable si ~5/semaine (pipeline doit reprendre) |
| XAG : n_resolved ≥ 20 | 14/20 | ✅ 3 pending + ~3/semaine → atteignable W4 |
| XAU PF ≥ 1.32 (sur n≥20) | 1.051 sur 10 | 🔴 Danger — corriger W4-W5 |
| XAG PF ≥ 1.32 (sur n≥20) | 2.318 sur 14 | ✅ Très bien |
| XLI : ≥ 1 setup | 0 | 🔴 Bloquant — corriger en urgence |
| maxDD < seuils | XAU 2.0% / XAG 0.9% | ✅ Stable |

**Le gate S6 est en péril sur deux points : XAU PF et XLI.** XAG et XLK compensent mais ne substituent pas les deux candidats problématiques.

---

## Conclusion W3

**22 jours de Phase 4. Portfolio en territoire positif : +165.34 € (+1.65% sur capital fictif).**

La semaine est contrastée : **XAG confirme** (PF=2.318, WR=50%, premier vrai système performant du portfolio), **XLK surprend positivement** (+86 €, 0 SL), mais **XAU se normalise** vers un PF plus modeste (1.051 vs 3.51 en W2 — correction de la surestimation W2 sur 3 résolus). WTI et ETH restent négatifs. XLI reste le trou noir du portfolio (0 setup en 22 jours).

Le signal le plus préoccupant de W3 est le **silence XAU depuis le 2026-05-12** (0 pending, aucun nouveau setup détecté). Si le pipeline H4 XAU reste muet en W4, le gate S6 devient inaccessible sur la condition n_resolved ≥ 20.

**Prochain jalon : Rapport W4 (2026-05-24)** — attendu avec résolution des 3 pending XAG, reprise potentielle XAU, et décision sur XLI.
