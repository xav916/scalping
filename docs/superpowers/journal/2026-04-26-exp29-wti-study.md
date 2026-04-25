# Expérience #29 — Étude WTI/USD H4 comme 3e candidat

**Date :** 2026-04-26 (~04h Paris, après-midi UTC)
**Tracks :** Phase 4 extension portefeuille
**Numéro d'expérience :** 29 (renumérotée vu la nouvelle insertion ; cf INDEX.md)
**Statut :** `closed-positive` *(candidat retenu avec filter spécifique)*

---

## Hypothèse

> "Si V2_CORE_LONG (XAU+XAG H4) capture un edge méthodologique structurel sur les actifs continus 24/5 'safe haven', alors WTI/USD H4 (pétrole, USD-priced commodity, inflation hedge) montrerait un edge similaire avec PF ≥ 1.15 sur ≥ 1 fenêtre."

## Motivation / contexte

User a explicitement demandé une étude approfondie sur le pétrole avant toute autre extension. Pétrole est :
- USD-priced (mécanique inverse-dollar comme métaux)
- Inflation hedge (driver macro partagé avec or)
- Safe haven en geopolitical stress (Iran, Russie, OPEC+)
- Mais MOINS contrôlé par real yields, plus politique

Risque attendu : si V2_CORE_LONG marche dessus → 3e candidat précieux (diversification au-delà des métaux corrélés à 0.62). Sinon → on confirme que l'edge est spécifique aux métaux.

## Données

- Source : Twelve Data Grow (WTI/USD = "Crude Oil WTI Spot" + USD)
- Fetch local : `python scripts/fetch_historical_backtest.py --pair WTI/USD --interval 1h --days 2200 --db _macro_veto_analysis/backtest_candles.db --env .env`
- **Période disponible** : 2020-10-04 → 2026-04-24 = **5.5 ans** (Twelve Data ne remonte pas avant 2020-10 pour WTI)
- 32 574 H1 candles + 5min en cours de fetch (2 ans+ déjà disponibles)

## Régimes pétrole couverts dans 5.5 ans

- **2020 Q4** : recovery post-crash COVID (WTI a touché -37 USD en avril 2020, exclu de notre fenêtre)
- **2021** : recovery + reflation (60-80 USD)
- **2022** : invasion Ukraine (WTI > 120 USD), forte volatilité
- **2023** : OPEC+ cuts, swing 70-90 USD
- **2024-25** : tensions Iran, sanctions Russie continuent, swing 75-90 USD
- **2026 Q1** : tensions geopolitical (WTI ~95 USD au moment du fetch)

3 régimes très différents (recovery, war shock, range trading) — base de validation cross-régime.

## Protocole

1. Fetch H1 + 5min via `scripts/fetch_historical_backtest.py`
2. Étendre `track_a_backtest.py` avec WTI/USD dans PAIRS
3. Run V2_CORE_LONG sur 4 fenêtres : 5.5 ans cumul, 12M, 24M, pré-bull 3.5 ans (2020-10 → 2024-04)
4. Comparer aux cibles XAU/XAG (PF ≥ 1.15)
5. Si rejet V2_CORE_LONG : analyser breakdown patterns + tester filter spécifique WTI

## Critère go/no-go (FIXÉ AVANT)

| Sortie | Condition | Verdict |
|---|---|---|
| **Candidat solide** | PF V2_CORE_LONG ≥ 1.15 sur ≥3 des 4 fenêtres | Ajouter au système avec V2_CORE_LONG identique XAU/XAG |
| **Candidat conditionnel** | V2_CORE_LONG ne passe pas, mais filter spécifique passe seuil sur ≥3 fenêtres | Ajouter avec filter dédié + sizing prudent |
| **Rejeté** | Aucun filter ne passe ≥1.15 cross-régime | Confirmer XAU+XAG comme unique périmètre |

## Résultats

### V2_CORE_LONG (filter XAU/XAG transposé)

| Fenêtre | n | WR% | PF | maxDD% |
|---|---|---|---|---|
| 5.5 ans cumul | 1196 | 48.1 | **1.06** ❌ | 132 |
| 12M récent | 185 | 45.9 | 1.33 ✓ | 83 |
| 24M | 371 | 44.7 | **1.05** ❌ | 85 |
| Pré-bull 3.5 ans | 823 | 49.5 | **1.07** ❌ | 132 |

**Verdict V2_CORE_LONG : ÉCHEC.** Seul 12M récent passe. Les patterns XAU/XAG ne sont pas optimaux pour WTI.

### Breakdown patterns sur 5.5 ans

| Pattern | Direction | n | WR% | PF | Note |
|---|---|---|---|---|---|
| `range_bounce_up` | BUY | 639 | 42.3 | **1.25** | 🔥 productif (vs XAU 0.61 / XAG 1.69) |
| `momentum_up` | BUY | 549 | 52.1 | **1.21** | productif |
| `engulfing_bullish` | BUY | 405 | 44.7 | 1.12 | marginal positif |
| `pin_bar_up` | BUY | 315 | 43.2 | 1.04 | break-even |
| `breakout_up` | BUY | 242 | 44.6 | **0.73** ❌ | TOXIQUE (vs XAU 1.84) |
| `engulfing_bearish` | SELL | 407 | 37.3 | 0.93 | perdant |
| `momentum_down` | SELL | 506 | 45.8 | 0.85 | perdant |
| `range_bounce_down` | SELL | 775 | 33.0 | 0.86 | perdant |
| `breakout_down` | SELL | 162 | 34.6 | **0.45** ❌ | catastrophique |
| `pin_bar_down` | SELL | 458 | 29.0 | **0.48** ❌ | catastrophique |

### Découverte critique : breakout_up TOXIQUE sur WTI

XAU bull 2024-26 : breakout_up BUY = PF 2.25 (star).
WTI 5.5 ans : breakout_up BUY = PF **0.73** (toxique).

**Lecture économique :**
- L'or rallye en breakout = continuation directionnelle (real yields confirment)
- Le pétrole en breakout = souvent reversal sur news OPEC/Iran/Russie qui inverse le mouvement
- WTI est plus politique → fausses cassures fréquentes

→ Filter pour WTI doit **exclure breakout_up**.

### Pattern surprenant productif sur WTI : range_bounce_up

WTI fait beaucoup de **range trading** entre niveaux OPEC implicites (75-90 USD plage typique). Les rebonds depuis support sont productifs (PF 1.25). XAU n'a pas cette dynamique car il a des trends directionnels plus longs.

→ Filter WTI doit **inclure range_bounce_up**.

### V2_WTI_OPTIMAL = momentum_up + engulfing_bullish + range_bounce_up BUY

| Fenêtre | n | WR% | PF | PnL% | maxDD% |
|---|---|---|---|---|---|
| 5.5 ans cumul | 1593 | 46.3 | **1.20** ✓ | +333 | 123 |
| 12M récent | 283 | 48.1 | **1.78** ✓ | +224 | 56 |
| 24M | 612 | 42.5 | **1.20** ✓ | +126 | 104 |
| Pré-bull 3.5 ans | 979 | 48.5 | **1.20** ✓ | +207 | 123 |

**4/4 fenêtres passent le seuil 1.15.** PF 1.20 cumul et PF 1.78 sur 12M récent.

### Direction breakdown 5.5 ans

| Direction | n | WR% | PF | Note |
|---|---|---|---|---|
| BUY | 2151 | 45.7 | **1.11** | profitable |
| SELL | 2314 | 36.0 | **0.74** | perdants |

LONG only confirmé pour WTI (comme XAU/XAG).

## Verdict

> Hypothèse **PARTIELLEMENT CONFIRMÉE — niveau "Candidat conditionnel"** :
> WTI échoue sur V2_CORE_LONG transposé (PF 1.06-1.07 sous le seuil sur 3 des 4 fenêtres),
> mais réussit avec un **filter spécifique V2_WTI_OPTIMAL** (PF 1.20-1.78 sur 4/4 fenêtres).
>
> WTI = **candidat #3 retenu**, avec filter dédié et sizing prudent.

## Caveats critiques

1. **Filter identifié in-sample** — `range_bounce_up` a été retenu après avoir vu son PF élevé sur 5.5 ans. Risque d'overfit. À valider out-of-sample en shadow log live (Phase 4).
2. **maxDD 123% sur 5.5 ans** — niveau XAG, plus élevé que XAU 53%. Sizing 0.3% obligatoire (pas 0.5% XAU).
3. **Sample size 5.5 ans** — pas 6 ans complets car TD WTI ne remonte pas avant 2020-10. Pas testé sur 2020 H1 (crash COVID exclu).
4. **Asymétrie BUY/SELL forte** : SELLs PF 0.74 (catastrophiques). Cohérent LONG only mais limite la diversification (pas de protection en bear cycle pétrole — ex 2026 si récession + pic offre).
5. **Driver politique** — WTI dépend d'OPEC, sanctions, news geopolitical. Le système peut subir des "fat tail" gaps non capturés par le backtest.

## Comparaison portefeuille final (3 candidats)

| Asset | Filter | PF cumul | Sharpe 24M | maxDD% (cumul) | Recommended sizing |
|---|---|---|---|---|---|
| XAU/USD H4 | V2_CORE_LONG | 1.33 | 1.59 | 53 | 0.5% |
| XAG/USD H4 | V2_CORE_LONG | 1.34 | 1.55 | 124 | 0.3% |
| **WTI/USD H4** | **V2_WTI_OPTIMAL** | **1.20** | NA (sample limité) | 123 | **0.3%** |

**Diversification améliorée :** 3 actifs avec drivers macro distincts :
- XAU = real yields proxy
- XAG = gold + industrial demand
- WTI = OPEC + geopolitical + inflation

Corrélation attendue WTI vs XAU : **modérée** (~0.3-0.4 typical) — vrai bénéfice de diversification multi-classe.

## Conséquences actées

### Pour Phase 4 (shadow log live)

- **Étendre `SHADOW_PAIRS` = ["XAU/USD", "XAG/USD", "WTI/USD"]**
- **Filter par pair** dans `shadow_v2_core_long.py` :
  - XAU/USD + XAG/USD → `CORE_LONG_PATTERNS`
  - WTI/USD → `WTI_OPTIMAL_PATTERNS`
- Sizing adaptatif : 0.5% (XAU) / 0.3% (XAG, WTI)
- Re-deploy nécessaire

### Pour Phase 5 (auto-exec démo)

Si gate S6 GO sur XAU+XAG, WTI peut être ajouté avec **20-30% allocation supplémentaire** (séparée des 100% XAU+XAG) en sizing très prudent. Ou WTI mis en attente Phase 5 et activé seulement si Phase 5 XAU+XAG valide pour 2-3 mois.

### Pour Page /v2/supports

Ajouter une 3e card WTI avec :
- Rôle économique : USD-priced commodity + geopolitical hedge + inflation
- Pourquoi ça marche : range trading entre niveaux OPEC, breakouts piégeux mais bounces productifs
- Quand ça galère : événements politiques imprévus (OPEC surprise, sanctions, etc.)
- Filter dédié V2_WTI_OPTIMAL (vs CORE_LONG XAU/XAG)
- Warning level "medium" (entre XAU low et XAG medium)

### Pour les routines W1-W5

Mettre à jour les prompts pour ajouter WTI dans la liste des assets monitored. Le `/api/shadow/v2_core_long/public-summary` retournera maintenant aussi `V2_WTI_OPTIMAL_WTIUSD_4H` dans `systems`.

## Artefacts

- Modifié : `scripts/research/track_a_backtest.py` (ajout WTI dans PAIRS, filter `filter_v2_wti_optimal`)
- DB : 32574 candles WTI H1 + 5min en cours dans `_macro_veto_analysis/backtest_candles.db`
- À venir : modif `backend/services/shadow_v2_core_long.py` pour multi-filter par pair
- Commit : à venir
