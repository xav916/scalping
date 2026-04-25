# Expérience #16 — Test extension pin_bar_up dans V2_CORE_LONG

**Date :** 2026-04-26 (~01h45 Paris)
**Tracks :** Phase 4 calibration
**Numéro d'expérience :** 16
**Statut :** `closed-negative` *(extension pas justifiée)*

---

## Hypothèse

> "Pin_bar_up BUY a PF 1.34 sur 4 ans pré-bull XAU H4 (exp #15 découverte bonus). Si on l'ajoute aux 3 patterns CORE (momentum_up, engulfing_bullish, breakout_up), V2_CORE_LONG_EXTENDED bat V2_CORE_LONG sur ≥3 des 4 fenêtres testées."

## Critère go/no-go

| Sortie | Condition | Verdict |
|---|---|---|
| **Extension justifiée** | PF EXT ≥ PF CORE + 0.05 sur ≥3 des 4 fenêtres | Modifier shadow log live |
| **Neutre** | Δ entre -0.05 et +0.05 | Garder V2_CORE_LONG actuel |
| **Dégradation** | PF EXT < PF CORE - 0.05 sur ≥2 fenêtres | Ne pas étendre |

## Résultats — XAU H4

| Période | V2_CORE (3pat) | V2_EXT (4pat) | Δ |
|---|---|---|---|
| 12M (TEST 2025-26) | PF 1.58 (n=318) | PF 1.50 (n=389) | -0.08 |
| 24M (TRAIN+TEST 2024-26) | PF 1.41 (n=601) | PF 1.32 (n=739) | -0.09 |
| 6 ans (2020-26) | PF 1.33 (n=1441) | PF 1.29 (n=1813) | -0.04 |
| 4 ans pré-bull (2020-24) | PF 1.26 (n=837) | PF 1.27 (n=1069) | +0.01 |

## Verdict

> Hypothèse **INFIRMÉE** : pin_bar_up dilue le risk-adjusted return dans 3 des 4 fenêtres (Δ -0.04 à -0.09). L'extension n'est pas justifiée.

## Lecture

Pin_bar_up BUY isolé sur 4 ans pré-bull XAU = PF 1.34 (exp #15). Mais comparé aux 3 patterns "stars" :
- `momentum_up` BUY : PF 1.36-2.93 selon fenêtre
- `engulfing_bullish` BUY : PF 1.26-3.33 selon fenêtre
- `breakout_up` BUY : PF 1.11-2.25 selon fenêtre

Pin_bar_up à PF 1.34 est *au-dessus du seuil 1.15* mais *en dessous* des 3 stars. L'inclure baisse la moyenne pondérée du set.

**Principe émergent :** dans une stratégie de filtrage par patterns, **moins est plus**. Garder uniquement les patterns au-dessus de la moyenne du set, pas tous ceux au-dessus du seuil de break-even.

## Conséquences actées

- **V2_CORE_LONG actuel (3 patterns) reste l'optimum** — le système deployed en Phase 4 est bien calibré
- Pas de re-deploy nécessaire
- Économie d'effort : pas de re-test en live de la version étendue

## Bonus pour exp future

Si on voulait creuser, on pourrait :
- Tester un V2_CORE_LONG_TIGHT à 2 patterns seulement (les 2 top : momentum_up + engulfing_bullish)
- Mesurer si la concentration extrême améliore encore le PF (au prix du volume)
- Hypothèse : PF 1.50+ sur 24M, n=400 → ~17 trades/mois XAU

À faire en Phase 4 future si l'observation live suggère qu'on a trop de variance.

## Artefacts

- Modifié : `scripts/research/track_a_backtest.py` (+ filter_v2_extended_long pour traçabilité)
- Commit : à venir
