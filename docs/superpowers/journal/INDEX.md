# Index des expériences — Recherche edge

Ordre chronologique, par track. Mettre à jour à chaque clôture d'expérience.

| # | Date | Track | Titre | Statut | Verdict |
|---|---|---|---|---|---|
| 1 | 2026-04-25 | A | [Spike H4 vs H1 vs Daily](2026-04-25-track-a-spike-h4-vs-h1.md) | closed-positive | XAU H4 PF 1.24 / XAG H4 PF 1.28 / ETH 1d PF 1.29 — **CONFIRMÉE** |
| 2 | 2026-04-25 | A | [Direction × pattern breakdown 3 winners](2026-04-25-track-a-direction-pattern-breakdown.md) | closed-positive | XAU et ETH = edge réel (SELL PF≥1.09), XAG = carry partiel (SELL PF 0.75) — **CONFIRMÉE partiel** |
| 3 | 2026-04-25 | A | [Robustesse 24 mois](2026-04-25-track-a-robustness-24m.md) | closed-positive | XAG H4 robuste (1.17), XAU H4 filtré (1.09 baseline), ETH **NON robuste** — **CONFIRMÉE partiel** |

## Conventions

- **Statut** : `running` / `closed-positive` / `closed-negative` / `closed-neutral` / `abandoned`
- **Verdict** (une phrase courte, chiffre clé) : ex `AUC 0.52 — INFIRMÉE` ou `PF 1.27 sur GBP/USD H4 — CONFIRMÉE partiel`

## Synthèse par track (à mettre à jour S2, S4, S6)

### Track A — Horizon expansion
- Expériences fermées : 3
- **Signal détecté : OUI sur métaux H4** (XAU + XAG), pas sur forex, **pas robuste sur ETH Daily**.
  - XAG/USD H4 baseline : PF 1.17 robuste 24M (n=1607)
  - XAU/USD H4 : edge filtre-dépendant (baseline tombe à 1.09 sur 24M, mais patterns LONG core stables : engulfing_bullish PF 1.68, breakout_up PF 1.84, momentum_up PF 1.22)
  - ETH/USD Daily : **retiré** (inversion BUY/SELL entre périodes, artefact d'échantillons)
- Pattern transversal le plus robuste : `momentum_up` BUY sur métaux (XAU 1.22 / XAG 2.09 sur 24M)
- Pattern toxique cross-asset : `pin_bar_down` SELL (PF 0.6-0.9 partout)
- Décision intermédiaire (J1) : **continuer Phase 3** — exp #4 = construire un V2_FILTERED ad-hoc XAU+XAG H4 avec patterns survivants, cible PF > 1.30 + maxDD < 50%

### Track B — Alt-data + cross-asset
- Expériences fermées : 0
- Signal détecté : —
- Décision intermédiaire : —

### Track C — Trend-following systématique
- Expériences fermées : 0
- Signal détecté : —
- Décision intermédiaire : —

## Gate de décision (planifié fin S6 = ~2026-06-06)

À remplir au gate :
- Verdict global :
- Track(s) survivante(s) :
- Décision passage prod :
