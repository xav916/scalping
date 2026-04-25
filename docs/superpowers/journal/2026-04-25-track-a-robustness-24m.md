# Expérience #3 — Track A — Robustesse 24 mois sur XAU/XAG/ETH

**Date début :** 2026-04-25
**Date fin :** 2026-04-25 (~18h Paris)
**Track :** A (Horizon expansion)
**Numéro d'expérience :** 3
**Statut :** `closed-positive` *(avec modération du verdict #1)*
**Précédentes :** #1 (spike multi-TF), #2 (direction × pattern)

---

## Hypothèse

> "Si l'edge détecté sur la fenêtre 12 mois (2025-04 → 2026-04) est un pattern méthodologique stable et pas un artefact d'une période propice (bull cycle métaux+crypto 2025), alors sur la fenêtre 24 mois (2024-04 → 2026-04) le PF baseline sur XAU H4, XAG H4 et ETH Daily reste ≥ 1.10."

Caveat #2 et #3 de l'expérience #1 testés ici.

## Motivation / contexte

L'exp #2 a confirmé que l'edge n'est pas (totalement) du carry pour XAU et ETH (SELLs PF ≥ 1.0). Mais ne dit rien sur la stabilité **temporelle**. Si l'edge n'apparaît que sur 12 mois récents, c'est probablement un artefact du régime macro 2025 et il s'effondrera en out-of-sample futur.

## Données

- DB : identique
- **Période étendue** : 2024-04-25 → 2026-04-25 (24 mois, soit 2x la fenêtre de exp #1)
- Pairs : XAU/USD, XAG/USD (H4) et ETH/USD (Daily) — uniquement les 3 winners
- Coûts : 0.02% (identique)

## Protocole

Re-run `track_a_backtest.py --start 2024-04-25 --pair X --timeframe Y --deep` sur les 3 winners.
Comparaison directe : **PF 12M vs PF 24M** sur baseline + chaque pattern × direction.

## Critère go/no-go (FIXÉ AVANT EXÉCUTION)

| Sortie | Condition | Verdict |
|---|---|---|
| **Robuste** | PF 24M baseline ≥ 1.10 sur ≥2 des 3 winners | Edge stable, prêt pour Phase 3 finale (création V2_FILTERED) |
| **Partiellement robuste** | PF 24M ∈ [1.05, 1.10] sur ≥1, ou ≥2 patterns universels stables | Edge fragile mais existant ; documenter les conditions |
| **Non-robuste** | PF 24M < 1.05 sur les 3 winners ET aucun pattern stable | Edge était un artefact 2025. Fermer Phase 3 horizon, basculer vers Tracks B/C. |

## Résultats — comparaison 12M vs 24M

### XAU/USD H4

| Mesure | 12M (n) | 24M (n) | Δ |
|---|---|---|---|
| BASELINE PF | 1.24 (866) | **1.09** (1671) | -0.15 |
| BUY PF | 1.35 (475) | 1.29 (907) | -0.06 ✓ |
| SELL PF | 1.09 (391) | **0.86** (764) | -0.23 ✗ |
| `momentum_up` BUY PF | 1.36 (171) | 1.22 (338) | -0.14 ✓ |
| `engulfing_bullish` BUY PF | 1.72 (77) | **1.68** (135) | stable ✓ |
| `breakout_up` BUY PF | 2.25 (70) | **1.84** (128) | -0.41, n→2× ✓ |
| `breakout_down` SELL PF | 2.74 (27) | **1.68** (45) | dégrade mais reste positif |
| `pin_bar_down` SELL PF | 0.58 (63) | 0.61 (114) | toxique stable |

**Verdict XAU :** baseline tombe à 1.09 (sous 1.15) mais **les patterns LONG porteurs tiennent** (engulfing_bullish 1.68, breakout_up 1.84, momentum_up 1.22). L'edge est **filtre-dépendant** sur 24M.

### XAG/USD H4

| Mesure | 12M (n) | 24M (n) | Δ |
|---|---|---|---|
| BASELINE PF | 1.28 (827) | **1.17** (1607) | -0.11, **reste > 1.15** ✓ |
| BUY PF | 1.79 (465) | 1.47 (882) | -0.32 ✓ |
| SELL PF | 0.75 (362) | 0.83 (725) | légère amélioration mais < 1.0 |
| `momentum_up` BUY PF | 2.93 (166) | **2.09** (288) | dégrade mais reste excellent ✓ |
| `range_bounce_down` SELL PF | 1.16 (166) | **1.16** (316) | parfaitement stable ✓ |
| `range_bounce_up` BUY PF | 1.69 (63) | 1.32 (175) | dégrade mais reste positif ✓ |
| V2_PATTERN | 0.99 (?) | **1.06** (611) | légèrement mieux 24M ✓ |
| RB_DOWN_SELL only | 0.95 (?) | **1.16** (316) | clairement mieux 24M ✓ |

**Verdict XAG :** **edge le plus robuste** des 3 — baseline reste au-dessus du seuil 1.15 sur 24M, et plusieurs patterns sont stables ou s'améliorent. Carry partiel confirmé (SELLs faibles), mais le `range_bounce_down` SELL prouve qu'on peut shorter XAG sur certains setups.

### ETH/USD Daily

| Mesure | 12M (n) | 24M (n) | Δ |
|---|---|---|---|
| BASELINE PF | 1.29 (149) | **1.10** (314) | -0.19 |
| BUY PF | 1.44 (76) | **0.89** (146) | **-0.55, INVERSION** ✗ |
| SELL PF | 1.15 (73) | **1.31** (168) | inversion symétrique +0.16 |
| `engulfing_bullish` BUY PF | 3.33 (12) | **0.98** (22) | -2.35, **artefact 12M** ✗ |
| `momentum_up` BUY PF | 1.86 (29) | 1.09 (46) | dégrade fortement |
| `engulfing_bearish` SELL PF | 1.29 (10) | **2.37** (28) | s'améliore (mais petits n) |
| `breakout_down` SELL PF | 2.88 (8) | 2.03 (15) | reste excellent (mais petits n) |

**Verdict ETH :** **non-robuste**. Inversion complète BUY↔SELL entre 2024-2025 et 2025-2026. Le pattern `engulfing_bullish` qui semblait superstar (PF 3.33 sur 12M) tombe à PF 0.98 sur 24M. Petits échantillons. C'est un signal **non exploitable tel quel**. Hypothèse : ETH a deux régimes très différents et le pattern detector réagit différemment selon le régime.

## Verdict

> Hypothèse **PARTIELLEMENT CONFIRMÉE** :
> - **XAG/USD H4** : edge **robuste** sur 24M (PF baseline 1.17 ≥ 1.15) — meilleur candidat
> - **XAU/USD H4** : edge **filtre-dépendant** sur 24M (PF baseline 1.09, mais patterns LONG core tiennent à PF 1.2-1.84)
> - **ETH/USD Daily** : edge **non-robuste** — inversion complète BUY/SELL entre périodes, artefacts d'échantillons. **À retirer du périmètre Track A.**

### Patterns transversaux **stables 24M** (cross-asset)

- `momentum_up` BUY : XAU 1.22 (n=338), XAG 2.09 (n=288) — robuste sur métaux
- `engulfing_bullish` BUY : XAU 1.68 (n=135) — robuste mono-asset
- `breakout_up` BUY : XAU 1.84 (n=128), XAG 1.19 (n=118) — robuste sur métaux
- `range_bounce_down` SELL : XAG 1.16 (n=316) — l'unique pattern SHORT robuste

### Patterns à exclure (toxiques cross-asset, stables 24M)

- `pin_bar_down` SELL : XAU 0.61, XAG 0.91, ETH 0.98 — perdant
- `breakout_down` SELL sur XAG : 0.52 (catastrophique)
- `momentum_down` SELL : XAU 0.74, XAG 0.72 — toxique sur métaux

## Conséquences actées

### Pour Track A
- **XAG/USD H4** confirmé comme candidat #1 — edge baseline robuste 24M
- **XAU/USD H4** candidat #2 — edge sur patterns filtrés (engulfing_bullish, breakout_up, momentum_up BUY)
- **ETH/USD Daily** **retiré** du périmètre Track A. Trop fragile.
- **Prochaine étape Phase 3 (exp #4)** : créer un `V2_FILTERED` ad-hoc qui combine les patterns survivants (`momentum_up`, `engulfing_bullish`, `breakout_up` BUY + `range_bounce_down` SELL pour XAG) sur XAU H4 et XAG H4, et mesurer le PF combiné sur 24M. Cible : PF > 1.30 avec maxDD < 50%.

### Pour Track B
- L'edge persistant sur métaux H4 sur 24M est cohérent avec un facteur macro stable (force du dollar inverse à l'or, demande industrielle XAG, etc.). Track B (alt-data) devrait prioriser **DXY, real yields 10Y, et ETF flows GLD/SLV** comme features critiques pour potentialiser cet edge.

### Pour Track C
- **Trend-following sur XAU + XAG H4** est *exactement* le scénario où Track C devrait briller. À tester avec un signal `momentum_up` discret + sizing vol target.

### Pour le code prod
- Aucun changement V1 (gel toujours actif).

## Artefacts

- Logs runs 24M : `/tmp/track_a_{xau,xag,eth}_24m.log` (éphémères)
- Commit : à venir avec ce journal
