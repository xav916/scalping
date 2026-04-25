# Index des expériences — Recherche edge

Ordre chronologique, par track. Mettre à jour à chaque clôture d'expérience.

| # | Date | Track | Titre | Statut | Verdict |
|---|---|---|---|---|---|
| 1 | 2026-04-25 | A | [Spike H4 vs H1 vs Daily](2026-04-25-track-a-spike-h4-vs-h1.md) | closed-positive | XAU H4 PF 1.24 / XAG H4 PF 1.28 / ETH 1d PF 1.29 — **CONFIRMÉE** |
| 2 | 2026-04-25 | A | [Direction × pattern breakdown 3 winners](2026-04-25-track-a-direction-pattern-breakdown.md) | closed-positive | XAU et ETH = edge réel (SELL PF≥1.09), XAG = carry partiel (SELL PF 0.75) — **CONFIRMÉE partiel** |
| 3 | 2026-04-25 | A | [Robustesse 24 mois](2026-04-25-track-a-robustness-24m.md) | closed-positive | XAG H4 robuste (1.17), XAU H4 filtré (1.09 baseline), ETH **NON robuste** — **CONFIRMÉE partiel** |
| 4 | 2026-04-25 | A | [V2_CORE_LONG combiné XAU+XAG H4](2026-04-25-track-a-v2-core-long.md) | closed-positive | XAU PF 1.41-1.58, XAG PF 1.59-1.93, 4/4 cibles atteintes — **premier candidat shadow log** |
| 5 | 2026-04-25 | C | [MVP TF systématique XAU/XAG H4](2026-04-25-track-c-mvp-tf-systematique.md) | closed-positive | XAU LONG PF 2.32 / XAG LONG PF 2.47 — **bat Track A** (+0.88 PF, -72pts maxDD), edge concentré métaux |
| 6 | 2026-04-25 | A∩C | [Intersection A ∩ C](2026-04-25-track-inter-a-c.md) | closed-positive | Asset-dépendant : XAG synergie (+0.60 PF maxDD÷2) ; XAU redondance — système asset-spécifique |
| 7 | 2026-04-25 | B | [Pipeline data macro Phase 1](2026-04-25-track-b-phase1-data-pipeline.md) | closed-positive | 5/5 symboles fetchés (VIX/DXY/SPX/TNX/BTC), 8643 obs daily 6y, features non-look-ahead OK — **pipeline opérationnel** |
| 8 | 2026-04-25 | B | [Macro buckets V2_CORE_LONG](2026-04-25-track-b-exp8-macro-buckets.md) | closed-positive 🔥 | 9/9 dimensions avec spread PF ≥ 0.52, max **+2.06** sur BTC return 5d — **signal macro-conditionnel massif** |
| 9 | 2026-04-25 | B | [Filtre macro walk-forward](2026-04-25-track-b-exp9-macro-filter-walkforward.md) | closed-positive 🎯 | TEST PF 1.81 → **2.28 filtered** (Δ +0.47), 453/637 trades retenus, PnL +509% sur 12M — **système prod-ready** |
| 10 | 2026-04-25 | B | [Robustesse pré-bull cycle 2023-24](2026-04-25-track-b-exp10-pretest-2023.md) | closed-positive | Filtre macro **régime-spécifique** (Δ -0.50 sur PRE_TEST). Mais découverte : V2_CORE_LONG **baseline robuste cross-régime** (PF 1.60 PRE_TEST sans filtre) — système principal réinterprété |
| 11 | 2026-04-25 | C | [Track C TF pré-bull cycle](2026-04-25-track-c-exp11-pretest-2023.md) | closed-positive | XAU LONG PF **5.60** (n=16, robuste) ; XAG LONG PF 1.12 (n=31, régime-dépendant) — asymétrie XAU/XAG cohérente théorie macro |
| 12 | 2026-04-25 | A+C | [Sharpe analysis 4 candidats](2026-04-25-exp12-sharpe-analysis.md) | closed-positive 🚀 | 4/4 candidats Sharpe ≥ 1.27 sur 24M ; Track A XAU **Sharpe 1.59 / maxDD 20%** (Carver "very good") ; Track C XAU **Calmar 4.45** (maxDD 4.7%) |
| 13 | 2026-04-25 | A+C | [Corrélation A × C](2026-04-25-exp13-correlation-a-c.md) | closed-positive | Corrélation 0.56-0.68 (modérée), Sharpe combiné +0.02 marginal — **simplification : Track A XAU SEUL pour Phase 4 v1** |
| 14 | 2026-04-26 | Phase 4 | [Implémentation + validation](2026-04-25-exp14-phase4-implementation-validation.md) | closed-positive | Module shadow + hook scheduler + reconciliation + endpoints OK ; KPIs cohérents avec backtest classique sur même fenêtre (PF 0.47 = drawdown attendu) |
| 15 | 2026-04-26 | Phase 4 | [Out-of-sample 2020-2024](2026-04-25-exp15-out-of-sample-2020-2024.md) | closed-positive 🎯 | XAU H4 PF **1.26** sur 4 ans pré-bull, XAG PF 1.16 — **système validé cross-régime sur 6 ans cumulés** (COVID + bear + bull) |
| 16 | 2026-04-26 | Phase 4 | [Pin_bar_up extension test](2026-04-25-exp16-pin-bar-up-extension.md) | closed-negative | V2_EXT (4pat) dégrade PF -0.04 à -0.09 vs V2_CORE (3pat) sur 3/4 fenêtres — V2_CORE_LONG actuel reste optimum |
| 17 | 2026-04-26 | Phase 4 | [V2_TIGHT (2pat) vs V2_CORE](2026-04-25-exp17-tight-vs-core.md) | closed-positive | Asymétrique : CORE bat TIGHT en bull cycle (Δ -0.10 à -0.15), TIGHT bat CORE en pré-bull (+0.05, maxDD 28% vs 41%) — insight régime-adaptatif futur |
| 18 | 2026-04-26 | Phase 4 | [Cross-asset SPX/NDX](2026-04-25-exp18-cross-asset-spx-ndx.md) | closed-negative | V2_CORE PF 0.23-0.73 sur indices équités H4 (gaps overnight cassent patterns) — confirme XAU+XAG comme unique périmètre |
| 29 | 2026-04-26 | Phase 4 | [Étude WTI/USD pétrole](2026-04-26-exp29-wti-study.md) | closed-positive | V2_CORE échec sur WTI (PF 1.06-1.07) MAIS V2_WTI_OPTIMAL avec range_bounce_up à la place de breakout_up passe **PF 1.20-1.78 sur 4/4 fenêtres** — **3e candidat retenu** avec filter dédié et sizing 0.3% |
| 30-32 | 2026-04-26 | Phase 4 | [Brent/XPT/XPD extensions](2026-04-26-exp30-32-extension-rejets.md) | closed-negative | **0/3 retenus** : Brent doublon WTI (24M PF 1.05), Platinum drift pré-bull (PF 0.92), Palladium PF 0.80-1.03 partout — portefeuille reste **XAU+XAG+WTI seulement** |
| 24 | 2026-04-26 | B | [Walk-forward expansif](2026-04-25-exp24-walk-forward-track-b.md) | closed-negative | Refit mensuel PF 1.60 vs Fixe 1.94 (Δ -0.34) — sur-fit au noise, baseline cross-régime suffit |
| 25 | 2026-04-26 | A | [V2_ADAPTIVE régime-aware](2026-04-25-exp25-v2-adaptive.md) | closed-neutral | Détecteur DXY+TNX trop crude (Δ -0.02) — confirme V2_CORE comme **optimum local atteint** après 7 tentatives d'extension |
| 33 | 2026-04-26 | C | [Track C TF sur WTI/USD](2026-04-26-exp33-track-c-tf-wti.md) | closed-negative | LONG PF 1.58 PRE-BULL → **0.46 BULL CYCLE** — edge inversé vs V2_WTI_OPTIMAL, Track C TF spécifique métaux |
| 34 | 2026-04-26 | Ext | [Extensions NatGas/Crypto/MXN](2026-04-26-exp34-extensions-natgas-crypto-mxn.md) | closed-positive | **ETH/USD Daily** retenu (3/4 fenêtres PF ≥ 1.15) ; BTC, USD/MXN rejetés ; NatGas non-testable TD Grow |
| 35 | 2026-04-26 | Scan | [Scan systématique 57 instruments](2026-04-26-exp35-systematic-scan-57-instruments.md) | closed-positive | **454 cellules pre-screen + 60 deep dive → 28 retenus strict** ; reco shadow log : ajouter **XLI 1d V2_TIGHT_LONG** + **XLK 1d V2_WTI_OPTIMAL** |

## Conventions

- **Statut** : `running` / `closed-positive` / `closed-negative` / `closed-neutral` / `abandoned`
- **Verdict** (une phrase courte, chiffre clé) : ex `AUC 0.52 — INFIRMÉE` ou `PF 1.27 sur GBP/USD H4 — CONFIRMÉE partiel`

## Synthèse par track (à mettre à jour S2, S4, S6)

### Track A — Horizon expansion
- Expériences fermées : 4
- **Signal détecté : OUI sur métaux H4** (XAU + XAG) avec filtre V2_CORE_LONG.
- **Candidat shadow log** : V2_CORE_LONG = `momentum_up` + `engulfing_bullish` + `breakout_up` BUY sur XAU H4 + XAG H4
  - Performance combinée 24M : 1147 trades, PnL +508%, WR > 54%, PF entre 1.41 et 1.93 selon paire/période
  - maxDD borderline (XAU 52%, XAG 89%)
- ETH/USD Daily retiré (non-robuste)
- Forex : pas de signal à aucun timeframe (PF 0.6-0.99 partout)
- **Décision J1 (2026-04-25) : Phase 3 close avec succès partiel.** Phase 4 = shadow log live XAU+XAG H4 V2_CORE_LONG sur 4-8 semaines avant le gate S6.

### Track B — Alt-data + cross-asset
- Expériences fermées : 4
- **Phase 1 close** — pipeline data opérationnel (5 symboles VIX/DXY/SPX/TNX/BTC daily 6y).
- **Phase 2 close avec résultat révélateur** :
  - Exp #9 : filtre macro walk-forward TRAIN→TEST améliore PF 1.81 → **2.28** sur 2025-2026 (Δ +0.47, robuste).
  - Exp #10 : filtre **dégrade en PRE_TEST 2023-2024** (Δ -0.50). Le filtre est **régime-spécifique** au bull cycle métaux 2024-2026.
  - **Découverte parallèle** : le baseline V2_CORE_LONG est **robuste cross-régime** (PF 1.60 PRE_TEST sans filtre). C'est le vrai edge méthodologique.
- **Reco shadow log mise à jour** : système principal = V2_CORE_LONG seul (PF 1.60-1.93 cross-régime). Filtre macro = boost optionnel régime-conditionnel.
- Phase 3 (ML proper) : **dépriorité** — le baseline simple est déjà robuste, le filtre est optionnel. ML pourrait extraire des règles régime-adaptives mais sur-complexité.

### Track C — Trend-following systématique
- Expériences fermées : 2
- **Phase 1 close "Strong"** (exp #5) : signal sur métaux H4, bat Track A en PF + maxDD
- **Robustesse cross-régime asymétrique** (exp #11) :
  - **XAU H4 LONG** : PF 5.60 PRE_TEST (n=16) → 2.36 TEST → **robuste cross-régime** (real yields proxy structurel)
  - **XAG H4 LONG** : PF 1.12 PRE_TEST (n=31) → 3.76 TEST → **régime-dépendant** (industrial demand cycle-driven)
- Lecture économique cohérente : XAU = mécanique stable, XAG = amplification cycle.
- Décision intermédiaire (J1) : XAU = candidat #1 indépendamment du système. XAG = à utiliser plus prudemment, idéalement avec filtre macro régime-conditionnel.

## Synthèse globale au J1 (2026-04-25)

**Système prod-ready validé sous 2 angles méthodologiques + risk-adjusted :**

| Candidat | n_24M | Sharpe | maxDD% | Calmar | TotRet 24M | Profil |
|---|---|---|---|---|---|---|
| Track A V2_CORE_LONG XAU H4 | 601 | **1.59** | 20.0 | 3.18 | +127% | high return + manageable vol |
| Track A V2_CORE_LONG XAG H4 | 546 | 1.55 | 25.7 | 2.65 | +136% | high return + higher vol |
| Track C TF LONG XAU H4 | 62 | 1.27 | **4.7** | **4.45** | +38% | moderate return + ultra-low vol |
| Track C TF LONG XAG H4 | 60 | 1.31 | 5.8 | 3.55 | +38% | moderate return + low vol |

**Allocation Phase 4 shadow log — SIMPLIFIÉE après exp #13 :**
- **v1 (à démarrer)** : Track A V2_CORE_LONG XAU H4 **SEUL**, 100% capital, 0.5% risk/trade
- **v2 (fallback maxDD)** : ajouter Track C XAU à 30% si maxDD live > 25%
- **XAG reporté indéfiniment** (corrélation 0.62 avec Track A XAU = double exposition métaux peu utile)

Justification : la corrélation Track A × Track C = 0.56-0.68 (modérée). Le Sharpe combiné 50/50 ne booste que +0.02 vs Track A solo. Diversification multi-système faible → préférer la simplicité opérationnelle.

## Gate de décision (planifié fin S6 = ~2026-06-06)

À remplir au gate :
- Verdict global :
- Track(s) survivante(s) :
- Décision passage prod :
