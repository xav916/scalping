# Expérience #5 — Track C — MVP TF systématique XAU/XAG H4

**Date début :** 2026-04-25
**Date fin :** 2026-04-25 (~19h Paris)
**Track :** C (Trend-following systématique)
**Numéro d'expérience :** 5
**Statut :** `closed-positive`

---

## Hypothèse

> "Si on implémente un trend-following Carver-style basique (EMA cross 12/48 + filtre EMA 100, exit signal-reverse OR ATR×3 stop) sans aucune pattern detection, alors sur les mêmes assets/périodes que Track A (XAU H4, XAG H4 sur 12M et 24M), on obtient un PF ≥ 1.30 — au moins équivalent à V2_CORE_LONG, avec idéalement un maxDD inférieur grâce au stop ATR."

## Motivation / contexte

Track A a identifié que les patterns LONG `momentum_up`, `engulfing_bullish`, `breakout_up` portent l'edge sur métaux H4. Mais le pattern detection est complexe (12 types, calculs imbriqués). Si un trend-following simple capte le même edge, on a un système plus robuste et industrialisable.

C'est aussi le test de l'hypothèse Carver/Hurst/Faith sur retail forex+metaux : "le secret du TF n'est pas la sophistication du signal mais la diversification + sizing + discipline".

## Données

- DB : identique aux exp #1-4
- Périodes : 12M (2025-04-25 → 2026-04-25) et 24M (2024-04-25 → 2026-04-25)
- Pairs primaires : XAU/USD H4, XAG/USD H4
- Pairs secondaires (cross-asset check) : EUR/USD, GBP/USD, USD/JPY, BTC/USD H4
- Coûts : 0.02% spread/slippage

## Protocole

### Signal

```python
LONG  : close > EMA(close, 100) AND EMA(close, 12) > EMA(close, 48)
SHORT : close < EMA(close, 100) AND EMA(close, 12) < EMA(close, 48)
sinon : FLAT
```

Entrée à la clôture du bar où le régime change (FLAT→LONG ou FLAT→SHORT).

### Sortie

- **Signal-reverse** : régime change (LONG→FLAT/SHORT, ou SHORT→FLAT/LONG)
- **Stop ATR** : touché en intra-bar 5min, distance = 3 × ATR(14) au moment de l'entrée
- Whichever first

### Sizing

1% risque par trade en valeur abstraite (% PnL relatif). Pas de vol target dynamique pour le MVP — comparaison directe avec V2_CORE_LONG en métriques % de prix.

### Métriques

PF, WR, maxDD, n trades (LONG/SHORT séparés), durée moyenne, % sorties ATR vs signal.

## Critère go/no-go (FIXÉ AVANT EXÉCUTION)

| Sortie | Condition | Verdict |
|---|---|---|
| **Strong** | PF LONG ≥ 1.5 sur ≥3 des 4 runs métaux ET maxDD < 25% | TF simple bat ou égale Track A → candidat principal pour Phase 4 |
| **Acceptable** | PF LONG ≥ 1.30 sur ≥2 runs métaux | TF est un signal complémentaire — combiner avec Track A |
| **Échec** | PF LONG < 1.30 sur les 4 runs | Pattern detection apporte vraiment de la valeur, garder Track A V2_CORE_LONG |

## Résultats

### Métaux primaires (XAU + XAG H4)

| Combo | n | L/S | WR% (LONG) | PF (LONG) | maxDD% (LONG) | PnL% (LONG) |
|---|---|---|---|---|---|---|
| XAU 12M | 77 | 37/40 | 32.4 | **2.36** | 7.1 | +24.85 |
| XAU 24M | 129 | 62/67 | 30.6 | **2.32** | 9.1 | +43.89 |
| XAG 12M | 57 | 33/24 | 27.3 | **3.76** | 16.2 | +91.63 |
| XAG 24M | 119 | 60/59 | 28.3 | **2.47** | 16.5 | +90.00 |

**SHORTs catastrophiques partout** (PF 0.42-0.61) → cohérent avec bull cycle métaux 2024-2026. La stratégie est de fait **long-only métaux**.

### Cross-asset 24M (sanity check)

| Asset | n | LONG PF | SHORT PF | Verdict |
|---|---|---|---|---|
| XAU/USD | 129 | **2.32** | 0.42 | strong |
| XAG/USD | 119 | **2.47** | 0.61 | strong |
| EUR/USD | 137 | 1.31 | 0.58 | marginal |
| GBP/USD | 124 | 0.96 | 0.73 | nul |
| USD/JPY | 129 | 0.91 | 0.62 | nul |
| BTC/USD | 144 | 0.85 | 1.01 | nul |

**Edge concentré sur métaux**. Forex à plat, crypto à plat. Cohérent avec exp #1 baseline résultats (forex aucun signal cross-TF non plus).

### Comparaison directe avec Track A V2_CORE_LONG (24M)

| Métrique | Track A V2_CORE_LONG | Track C TF (LONG only) | Δ |
|---|---|---|---|
| n trades XAU | 601 | 62 | -90% |
| PF XAU | 1.41 | **2.32** | +0.91 |
| maxDD XAU | 51.79% | **9.1%** | -42.7pts |
| n trades XAG | 546 | 60 | -89% |
| PF XAG | 1.59 | **2.47** | +0.88 |
| maxDD XAG | 88.97% | **16.5%** | -72.5pts |

Track C bat Track A en **PF** et **maxDD** sur les 2 assets, mais avec **10× moins de trades**.

## Verdict

> Hypothèse **CONFIRMÉE niveau "Strong"** : PF LONG ≥ 2.32 sur les 4 runs métaux, maxDD < 17%. Le TF systématique simple **bat** Track A V2_CORE_LONG en PF (+0.88) et en maxDD (-42 à -72 points).
>
> **MAIS** : Edge limité aux métaux dans le portefeuille testé, et exclusivement sur les LONGs (les SHORTs perdent → c'est essentiellement un long-only bull-trend follower sur métaux).

### Implications stratégiques

**Convergence des 2 tracks** : Track A et Track C identifient indépendamment les métaux H4 comme l'angle exploitable. C'est rassurant — deux méthodologies différentes pointent au même endroit.

**Track C est plus simple à industrialiser** :
- 3 EMAs + ATR au lieu de 12 patterns × 3 directions × ATR/SMAs/RSI/ADX
- Code 200 lignes vs 2000+ lignes pour pattern_detector + scoring
- Logique transparente, débogage facile
- Hyperparams limités (3 EMAs + ATR×K) → moins de risque overfit

**Track C est moins exhaustif** : 10× moins de trades qu'V2_CORE_LONG.
- Si l'edge se déplace dans le temps (régime change), V2_CORE_LONG aura plus de samples pour le détecter
- Si on veut diversifier le risque, V2_CORE_LONG offre plus de granularité

## Conséquences actées

### Pour Track C
- Phase 1 close avec succès "Strong"
- **Phase 2 ouverte** : optimisation hyperparams (vol target sizing à la place du % fixe, test ATR×2 vs ATR×3 vs ATR×4, EMAs alternatives 5/20 vs 12/48 vs 24/96)
- **Phase 2 ouverte aussi** : tester le portefeuille étendu — autres métaux/commodities (Brent, NatGas, Copper si Twelve Data les supporte) pour voir si la diversification multi-asset améliore le Sharpe à la Carver
- **Phase 3 sera** : combinaison Track A ∩ Track C — prendre les setups V2_CORE_LONG **uniquement quand** Track C est aussi en régime LONG. Hypothèse : double filtre élimine les patterns toxiques résiduels et augmente le PF combiné.

### Pour Track A
- L'edge V2_CORE_LONG est **réel mais sous-optimal vs TF simple**.
- Avant d'aller plus loin sur Track A, il faut tester l'intersection avec Track C (cf Phase 3 Track C).

### Pour Track B
- L'edge persistant XAU/XAG sur 24M renforce l'hypothèse macro structurelle. Track B doit absolument tester DXY + real yields 10Y comme features.

### Pour le code prod
- **Aucun changement V1**. Gel toujours actif jusqu'au gate S6.

## Caveats à creuser en Phase 2

1. **Bull cycle 2024-2026** : XAU/XAG ont fait +50% / +38%. Track C est essentiellement un trend-rider sur ce cycle. Test out-of-sample 2020-2024 si data dispo (24-60M).
2. **Petit échantillon** : 60-62 LONG trades sur 24M par paire. Statistiquement OK mais fragile.
3. **Pas de Sharpe annualisé** : le MVP donne PF/PnL/maxDD mais pas de Sharpe direct. À calculer en Phase 2 (sample mensuel de l'équity curve).
4. **Hyperparams par défaut Carver** : EMA(12/48/100), ATR×3. Pas tuning. Risque que ça soit lucky, ou inversement qu'un tuning même léger pousse le PF plus haut.

## Artefacts

- Script : `scripts/research/track_c_trend_following.py`
- Logs : output redirigé en stdout (résultats inline ci-dessus)
- Commit : à venir
