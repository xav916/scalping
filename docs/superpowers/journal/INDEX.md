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
- Expériences fermées : 1 (infrastructure)
- **Phase 1 close — pipeline data opérationnel** : 5 symboles macro (VIX/DXY/SPX/TNX/BTC), 6 ans d'history daily, cache local SQLite, no look-ahead.
- Signal détecté (edge) : pas encore — Phase 2 = re-extraction features + re-train ML.
- Décision intermédiaire (J1) : Phase 2 demain ou plus tard. Étendre `scripts/ml_extract_features.py` pour ajouter les features macro, re-runner training, comparer AUC vs 0.526 V1.

### Track C — Trend-following systématique
- Expériences fermées : 1
- **Signal détecté : OUI sur métaux H4** (XAU + XAG), avec règles plus simples que Track A
  - XAU LONG 24M : PF 2.32, maxDD 9.1%, n=62
  - XAG LONG 24M : PF 2.47, maxDD 16.5%, n=60
  - SHORTs catastrophiques (PF 0.42-0.61) → essentiellement long-only bull cycle
  - Cross-asset : forex/crypto à plat, edge concentré métaux uniquement
- **Track C bat Track A** sur les 2 mêmes paires : +0.88 à +0.91 PF, maxDD écrasé (-42 à -72 points)
- Décision intermédiaire (J1) : Phase 1 close "Strong". Phase 2 = vol target sizing + extension portefeuille (commodities). Phase 3 = intersection Track A ∩ Track C (double filtre).

## Gate de décision (planifié fin S6 = ~2026-06-06)

À remplir au gate :
- Verdict global :
- Track(s) survivante(s) :
- Décision passage prod :
