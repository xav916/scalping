# Expérience #25 — V2_ADAPTIVE régime-aware TIGHT/CORE

**Date :** 2026-04-26 (~03h Paris)
**Tracks :** A Phase 4 calibration finale
**Numéro d'expérience :** 25
**Statut :** `closed-neutral` *(détecteur trop crude)*

---

## Hypothèse

> "Si on switche entre V2_CORE (3 patterns) en bull cycle et V2_TIGHT (2 patterns) en marché calme, basé sur un détecteur simple `tnx_level < 4.5 AND |dxy_dist_sma50| < 2`, alors V2_ADAPTIVE bat max(CORE, TIGHT) de ≥ +0.05 PF sur 3 ans (2023-04 → 2026-04)."

Test du dernier "extension" non-encore-essayé après 6 échecs.

## Résultats (XAU+XAG H4, 2023-04 → 2026-04, 3 ans)

| Stratégie | n | PF | PnL% |
|---|---|---|---|
| V2_CORE | 1564 | 1.53 | +638% |
| V2_TIGHT | 1226 | **1.59** | +542% |
| V2_ADAPTIVE | 1473 | 1.57 | +641% |

Δ ADAPTIVE vs max(CORE, TIGHT) = **-0.02** (négligeable).

### Breakdown ADAPTIVE par régime détecté

```
BULL_CYCLE selected (CORE applied) : n=1101  PF=1.82
CALM selected (TIGHT applied)      : n=372   PF=0.84
```

Le détecteur identifie 70% des trades comme BULL_CYCLE → CORE → PF 1.82 (bien).
Les 30% identifiés CALM → TIGHT → PF 0.84 (catastrophique).

## Verdict

> Hypothèse **NEUTRE / quasi-INFIRMÉE** : le détecteur simple ne capture pas correctement le régime "marché calme métaux".

## Lecture

L'insight d'exp #17 (TIGHT bat CORE en marché calme avec maxDD ÷1.5) était observé sur **4 ans pré-bull** (2020-2024). Mon détecteur tournait sur **3 ans 2023-2026** (mixte 1 an pré-bull + 2 ans bull). Le test n'est pas pleinement comparable.

Plus important : le détecteur "calme = `tnx<4.5 AND |dxy_dist|<2`" sélectionne des phases où DXY/TNX sont *quantitativement* dans un range, mais ce n'est pas la même chose que "marché calme pour les métaux". Les métaux peuvent être très volatils même quand DXY/TNX sont stables.

Pour faire un détecteur correct, il faudrait probablement :
- ATR rolling sur métaux (vol conditionnelle aux métaux eux-mêmes)
- Volume / news flow récent
- Position SPX dans son cycle

C'est un chantier non trivial, et vu les multiples échecs d'extension précédents, l'**ROI est faible**.

## Conséquences actées

### Pour le système live (déjà déployé)
- **V2_CORE_LONG seul reste optimal.** Pas de changement à apporter.

### Conclusion cumulée des 7 tentatives d'extension

| # | Extension testée | Résultat |
|---|---|---|
| #9 | Filtre macro OR fixe (2024-25 TRAIN) | +0.47 PF sur TEST 25-26, mais régime-spécifique |
| #10 | Apply filtre fixe à PRE_TEST 23-24 | -0.50 PF (carry partiel) |
| #16 | V2_EXT (4 patterns + pin_bar_up) | -0.04 à -0.09 PF |
| #17 | V2_TIGHT (2 patterns) | Asymétrique (CORE bull, TIGHT calme) |
| #18 | Cross-asset SPX/NDX | PF 0.23-0.73 (gaps cassent patterns) |
| #24 | Walk-forward expansif macro | -0.34 PF (sur-fit noise) |
| #25 | V2_ADAPTIVE régime-aware | -0.02 (détecteur trop crude) |

**Insight final : V2_CORE_LONG sur XAU+XAG H4 est l'optimum local atteignable avec les techniques explorées.**

Pour aller au-delà, il faudrait probablement changer fondamentalement le paradigme :
- ML proper avec feature engineering avancé (pas juste filtres OR)
- Asset autres (futures équités ES/NQ pour 23/5 continu)
- Signaux non-technique (sentiment retail Myfxbook, volume flow, etc.)

Mais ces chantiers sont 5-10× plus longs et l'edge marginal n'est pas garanti. Le système actuel (Sharpe 1.59, PF 1.32 cumul 6 ans) est **commercialement exploitable tel quel** dès que la phase shadow log valide les chiffres live.

## Artefacts

- Script : `scripts/research/track_a_adaptive.py`
- Commit : à venir
