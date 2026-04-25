# Expérience #2 — Track A — Décomposition direction × pattern sur les 3 winners

**Date début :** 2026-04-25
**Date fin :** 2026-04-25 (~17h30 Paris)
**Track :** A (Horizon expansion)
**Numéro d'expérience :** 2
**Statut :** `closed-positive`
**Précédente :** #1 — Spike H4 vs H1 vs Daily

---

## Hypothèse

> "Si l'edge détecté en exp #1 sur XAU/USD H4 (PF 1.24), XAG/USD H4 (PF 1.28) et ETH/USD Daily (PF 1.29) est un vrai edge méthodologique et non un artefact de carry/buy-and-hold, alors les trades **SELL** doivent avoir un PF supérieur à 0.85 (proche du break-even ou positif), pas catastrophique."

Test direct du caveat #1 de l'expérience précédente.

## Motivation / contexte

Sur la fenêtre 2025-04-25 → 2026-04-25, les 3 actifs winners ont eu des bull runs :
- XAU/USD : ~+25%
- XAG/USD : ~+30%
- ETH/USD : ~+15%

Si les patterns sont structurellement biaisés long, le baseline PF positif peut être largement dû au carry haussier. Pour invalider ce biais : si les SELLs ont aussi un PF acceptable, l'edge n'est pas pur carry.

## Données

Identique à exp #1 : 12 mois 2025-04-25 → 2026-04-25, db `_macro_veto_analysis/backtest_candles.db`, coûts 0.02%.

## Protocole

Étendre `scripts/research/track_a_backtest.py` avec un flag `--deep` qui imprime, en plus du baseline, les breakdown :
- Par direction (buy/sell)
- Par pattern (12 types possibles)
- Par direction × pattern (croisé)

Lancer le script sur les 3 winners : `--pair XAU/USD --timeframe 4h --deep`, idem XAG H4 et ETH 1d.

## Critère go/no-go (FIXÉ AVANT EXÉCUTION)

| Sortie | Condition | Verdict |
|---|---|---|
| **Edge réel** | SELLs PF > 0.85 sur ≥2 des 3 winners | Continuer Track A — l'edge n'est pas du carry |
| **Carry partiel** | SELLs PF entre 0.7 et 0.85 sur 1-2 winners, > 0.85 sur les autres | Documenter, continuer mais filtre obligatoire (long only sur les actifs concernés) |
| **Carry pur** | SELLs PF < 0.7 sur ≥2 des 3 winners | Edge n'est qu'un buy-and-hold camouflé. Fermer ou pivoter vers Track C (TF systématique multi-asset) qui captera mieux le trend. |

## Résultats

### XAU/USD H4 — n=866 baseline

```
=== BASELINE — breakdown par direction (TF=4h) ===
  buy                      n=  475  wr= 52.2%  PnL=+106.18%  PF=1.35  maxDD=76.25%
  sell                     n=  391  wr= 35.3%  PnL= +21.55%  PF=1.09  maxDD=69.78%
```

**Verdict XAU :** SELLs PF=1.09 → **edge réel, pas de carry**.

Top patterns :
| Pattern | Direction | n | WR% | PF | PnL% |
|---|---|---|---|---|---|
| `breakout_up` | BUY | 70 | 64.3 | **2.25** | +45.35 |
| `engulfing_bullish` | BUY | 77 | 57.1 | **1.72** | +24.58 |
| `momentum_up` | BUY | 171 | 59.1 | **1.36** | +49.43 |
| `pin_bar_up` | BUY | 71 | 47.9 | 1.16 | +7.36 |
| `breakout_down` | SELL | 27 | 37.0 | **2.74** | +31.76 |
| `engulfing_bearish` | SELL | 63 | 41.3 | **1.24** | +9.08 |

Patterns toxiques :
| Pattern | Direction | n | PF | Notes |
|---|---|---|---|---|
| `pin_bar_down` | SELL | 63 | 0.58 | catastrophique |
| `range_bounce_up` | BUY | 83 | 0.61 | perdant |

### XAG/USD H4 — n=827 baseline

```
=== BASELINE — breakdown par direction (TF=4h) ===
  buy                      n=  465  wr= 58.1%  PnL=+413.61%  PF=1.79  maxDD=118.14%
  sell                     n=  362  wr= 32.9%  PnL=-126.40%  PF=0.75  maxDD=213.31%
```

**Verdict XAG :** SELLs PF=**0.75** → **carry partiel détecté**. L'edge baseline +287% est ~80% expliqué par les BUYs ; les SELLs ont perdu 126%, ils tirent vers le bas.

Top patterns :
| Pattern | Direction | n | WR% | PF | PnL% |
|---|---|---|---|---|---|
| `momentum_up` | BUY | 166 | 67.5 | **2.93** | **+324.29** |
| `range_bounce_up` | BUY | 63 | 46.0 | **1.69** | +29.79 |
| `breakout_up` | BUY | 76 | 57.9 | 1.21 | +22.61 |
| `pin_bar_up` | BUY | 82 | 51.2 | 1.18 | +16.84 |
| `range_bounce_down` | SELL | 166 | 34.3 | 1.16 | +20.62 |
| `engulfing_bullish` | BUY | 77 | 54.5 | 1.14 | +15.75 |

Patterns toxiques :
| Pattern | Direction | n | PF | Notes |
|---|---|---|---|---|
| `breakout_down` | SELL | 26 | 0.28 | catastrophique |
| `engulfing_bearish` | SELL | 60 | 0.68 | perdant |
| `momentum_down` | SELL | 64 | 0.71 | perdant |

### ETH/USD Daily — n=149 baseline

```
=== BASELINE — breakdown par direction (TF=1d) ===
  buy                      n=   76  wr= 53.9%  PnL=+110.56%  PF=1.44  maxDD=99.68%
  sell                     n=   73  wr= 43.8%  PnL= +42.42%  PF=1.15  maxDD=121.48%
```

**Verdict ETH :** SELLs PF=**1.15** → **edge réel, pas de carry**.

Top patterns :
| Pattern | Direction | n | WR% | PF | PnL% |
|---|---|---|---|---|---|
| `engulfing_bullish` | BUY | 12 | 66.7 | **3.33** | +49.88 |
| `breakout_down` | SELL | 8 | 62.5 | **2.88** | +49.99 |
| `momentum_up` | BUY | 29 | 62.1 | **1.86** | +90.87 |
| `engulfing_bearish` | SELL | 10 | 40.0 | 1.29 | +9.64 |

Patterns toxiques :
| Pattern | Direction | n | PF | Notes |
|---|---|---|---|---|
| `breakout_up` | BUY | 7 | 0.47 | (échantillon faible) |
| `range_bounce_down` | SELL | 20 | 0.81 | perdant |

## Verdict

> Hypothèse **PARTIELLEMENT CONFIRMÉE** :
> - **XAU/USD H4** : edge réel (SELLs PF 1.09)
> - **ETH/USD Daily** : edge réel (SELLs PF 1.15)
> - **XAG/USD H4** : carry partiel (SELLs PF 0.75) — l'edge baseline est ~80% un buy-and-hold sur l'argent

### Pattern transversal le plus solide

`momentum_up` BUY est le seul pattern à passer le seuil PF > 1.3 sur les 3 actifs simultanément :
- XAU H4 : PF 1.36 (n=171)
- XAG H4 : PF 2.93 (n=166) — superstar
- ETH Daily : PF 1.86 (n=29)

`engulfing_bullish` BUY est second :
- XAU H4 : PF 1.72 (n=77)
- XAG H4 : PF 1.14 (n=77)
- ETH Daily : PF 3.33 (n=12 — petit)

### Patterns à exclure systématiquement

`pin_bar_down` SELL : perdant sur les 3 actifs (0.58 / 0.69 / 0.80).

## Conséquences actées

### Pour Track A
- **XAU et ETH passent au stade Phase 3 robustesse** (test 24 mois, déjà lancé en parallèle dans cette session)
- **XAG passe en mode "long-only filtré"** : si on devait migrer en prod, il faudrait obligatoirement un filtre direction. La version baseline n'est pas fiable hors bull cycle.
- Création d'un **set de patterns "core" recommandé** :
  - LONG : `momentum_up`, `engulfing_bullish`, `breakout_up` (sur métaux et crypto)
  - SHORT : `breakout_down`, `engulfing_bearish` (à valider en robustesse)
  - **Exclure** : `pin_bar_down` SELL, `range_bounce_up` BUY (uniquement sur XAU)

### Pour Track B
- L'edge est concentré sur métaux + crypto. Quand on construira les features alt-data, prioriser des features qui distinguent ces régimes (VIX, DXY pour métaux ; BTC dominance pour crypto).

### Pour Track C
- **Forte synergie** : `momentum_up` BUY est exactement ce qu'un trend-following systématique capterait. Le résultat de Phase 1 valide l'hypothèse Track C — si on construit un signal momentum H4/Daily sur XAU/XAG/ETH, on devrait retrouver de l'edge.

### Pour le code prod
- Aucun changement V1 (gel toujours actif).

## Artefacts

- Script utilisé : `scripts/research/track_a_backtest.py` (extension `--deep`)
- Logs : (output redirigé en stdout, voir résultats ci-dessus)
- Commit : à venir avec ce journal et exp #3 (robustesse 24 mois)
