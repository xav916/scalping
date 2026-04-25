# Expérience #34 — Extensions NatGas / Crypto Daily / USD-MXN

**Date :** 2026-04-26 (~00h30 Paris)
**Tracks :** Phase 4 extensions portefeuille
**Statut :** `closed-positive (1/3)` — ETH/USD retenu, NatGas non-testable, USD/MXN rejeté

---

## Hypothèse globale

> "Au moins un candidat parmi NatGas H4 / Crypto Daily V2 / Forex emerging USD-MXN H4 capture un edge V2_CORE_LONG (ou V2_WTI_OPTIMAL) avec PF ≥ 1.15 sur ≥3 des 4 fenêtres."

## Test 1/3 — NatGas H4

### Verdict : **NON TESTABLE**

Twelve Data Grow ne fournit pas le NatGas spot ni les futures NG=F. Seulement des ETFs leveraged (BOIL = 2x long natgas, KOLD = -2x short natgas) qui distordent la mesure d'edge.

→ Reportable si on bascule vers une source de données qui couvre NG=F (broker direct, IBKR, Yahoo Finance) — chantier dépendant du gate S6.

### Conséquence

Le candidat "diversification non-métaux/non-pétrole" reste à explorer plus tard. ETH (test 2/3) capture une partie de cette diversification crypto.

---

## Test 2/3 — Crypto Daily V2_CORE_LONG

### Données

- BTC/USD H1 : 2021-05 → 2026-04 (5 ans), 43k candles
- ETH/USD H1 : 2021-09 → 2026-04 (4.6 ans), 40k candles
- 5min : 2023-04 → 2026-04 (3 ans, suffisant pour simulation forward)

### Résultats — V2_CORE_LONG (momentum_up + engulfing_bullish + breakout_up BUY) sur Daily

#### ETH/USD Daily

| Fenêtre | n | WR% | PF | PnL | maxDD% | Verdict |
|---|---|---|---|---|---|---|
| 12M récent | 48 | 58.3 | **1.74** ✓ | +121% | 94 | excellent |
| 3y cumul | 144 | 49.3 | **1.28** ✓ | +140% | 158 | confirmé |
| pré-bull 1y (2023-04→2024-04) | 54 | 53.7 | **1.75** ✓ | +108% | 49 | confirmé |
| 24M | 86 | 46.5 | **1.06** ❌ | +20% | 122 | sous seuil |

**3/4 fenêtres ≥ 1.15** — critère success atteint. Le 24M est mécanique (moyenne pré-bull + 12M, la zone faible 2024-04→2025-04 le tire vers le bas).

#### BTC/USD Daily

| Fenêtre | n | WR% | PF | PnL | maxDD% | Verdict |
|---|---|---|---|---|---|---|
| 12M récent | 44 | 40.9 | **0.47** ❌ | -74% | 89 | catastrophique |
| 24M | 106 | 51.9 | **1.19** ✓ | +47% | 99 | marginal |
| 3y cumul | 173 | 54.9 | **1.47** ✓ | +182% | 99 | confirmé |
| pré-bull 1y | 61 | 60.7 | **2.23** ✓ | +145% | 44 | excellent |

3/4 fenêtres ≥ 1.15 mais 12M récent **catastrophique** (BTC en correction post-ATH 2024). Régime-dépendant comme Track B macro filter — l'edge a évaporé sur les 12 derniers mois.

→ **BTC = REJETÉ** (cassure récente disqualifiante pour shadow log live).

### Verdict 2/3

> Hypothèse **CONFIRMÉE pour ETH/USD Daily**.
>
> ETH capture un edge V2_CORE_LONG sur 3/4 fenêtres avec PF moyen ~1.5 et WR 46-58%. Le système Daily est plus lent mais cohérent avec les patterns H4 sur métaux (transposition out-of-sample réussie).

### Lecture économique

ETH a une dynamique trend-driven plus stable que BTC sur les 12 derniers mois (BTC a beaucoup pumped/dumped post-ATH, ETH en lag avec moins de pics de FOMO). V2_CORE_LONG attrape les breakouts directionnels sans se faire piéger par les SHORT.

V2_WTI_OPTIMAL marche aussi bien que V2_CORE_LONG sur ETH (PF 1.76 vs 1.74 sur 12M) → la différence range_bounce_up vs breakout_up ne change rien sur ETH (ETH ne range pas comme WTI).

---

## Test 3/3 — USD/MXN H4

### Données

USD/MXN H1 fetched 2021-04 → 2026-04 (5 ans, 31558 candles, 9 requêtes).
Pas de 5min → simulation forward avec `--use-h1-sim` (moins précise mais utilisable pour vérifier l'absence d'edge).

### Résultats

| Fenêtre | V2_CORE_LONG PF | V2_WTI_OPTIMAL PF | BASELINE PF |
|---|---|---|---|
| 5y cumul | 0.92 | 0.88 | 0.90 |
| 24M | 0.93 | 0.96 | 0.84 |
| 12M récent | **0.53** | 0.65 | 0.83 |
| pré-bull 3y | 0.91 | 0.84 | 0.95 |

**Toutes les fenêtres sous 1.** WR 32-42% pour les filters BUY — patterns systématiquement perdants. BASELINE aussi sous 1 → USD/MXN n'a pas d'edge directionnel détectable par patterns.

### Verdict 3/3

> Hypothèse **INFIRMÉE catégoriquement**.
>
> USD/MXN H4 confirme la conclusion forex : aucune des 10 paires forex testées (9 majors + USD/MXN emerging) ne génère d'edge V2 sur H4. Le filter pattern detection est métaux-spécifique + crypto-Daily-spécifique, pas universel.

### Lecture économique

USD/MXN est driven par le différentiel de taux Fed/Banxico + flux pétrole (Mexico = exportateur net). Mais en H4, ces drivers sont noyés dans le bruit FX. Pour exploiter MXN, il faudrait soit Daily (untested) soit features macro-conditionnelles (track B style).

---

## Synthèse globale exp #34

| Candidat | TF | Verdict | Détails |
|---|---|---|---|
| NatGas H4 | H4 | **NON TESTABLE** | Spot indisponible TD Grow |
| ETH/USD Daily | 1d | **RETENU** | 3/4 fenêtres ≥ 1.15, PF moyen 1.5 |
| BTC/USD Daily | 1d | rejeté | 12M récent PF 0.47 catastrophique |
| USD/MXN H4 | H4 | rejeté | Toutes fenêtres < 1, baseline cassé |

**1 nouveau candidat** : ETH/USD Daily V2_CORE_LONG.

## Conséquences pour le portefeuille shadow log

### Avant exp #34

3 candidats : XAU H4, XAG H4 (V2_CORE_LONG) + WTI H4 (V2_WTI_OPTIMAL)

### Après exp #34 (proposé)

4 candidats : ajouter ETH/USD Daily (V2_CORE_LONG)

**Spécifications proposées pour ETH** :
- Timeframe : Daily (1d)
- Filter : V2_CORE_LONG (`momentum_up`, `engulfing_bullish`, `breakout_up` BUY)
- Sizing : **0.25%** (vs 0.5% XAU / 0.3% XAG/WTI) — maxDD 158% sur 3y exige une prudence accrue
- system_id : `V2_CORE_LONG_ETHUSD_1D`

### Implémentation requise

`shadow_v2_core_long.py` actuel ne traite que H4. Pour ETH Daily :
- Ajouter `aggregate_to_daily` (probablement déjà dispo dans `track_a_backtest`)
- Refactor `run_shadow_log` pour supporter timeframe par pair via une config par pair
- Augmenter outputsize H1 pour ETH/USD à ~600 (24 H1 / jour × 25 jours min) si on veut ≥30 Daily

Effort estimé : ~45-60 min.

## Caveats critiques

1. **ETH 24M sous seuil** : PF 1.06 sur 24M. Mécanique mais signe de fragilité régime-dépendante. À surveiller en shadow log.
2. **maxDD ETH élevé** : 158% sur 3y. Sizing 0.25% obligatoire. Capital virtuel 10k€ → max loss 25€ par trade, mais cumul peut être lourd.
3. **Sample size limité** : 144 trades sur 3y = ~50/an. Statistiquement plus faible que XAU H4 (601 sur 24M). Edge moins certain.
4. **Out-of-sample partial** : les patterns V2_CORE_LONG ont été dérivés sur XAU/XAG H4. Sur ETH Daily ils sont out-of-sample temporel mais in-sample structurel (mêmes 3 patterns). À reconfirmer en live.
5. **Pas de filter macro testé** : Track B filter macro pourrait être ré-évalué sur ETH (spread BTC return 5d était la dimension la plus forte exp #8). Hors scope ce soir.

## Pistes restantes

Après exp #34, pistes ordonnées :

1. **Intégrer ETH au shadow log** (~45-60 min) — chantier ingénierie pour multi-TF
2. **Test ETH Daily avec filter macro Track B** (~30 min) — voir si Δ +0.4 comme sur XAU
3. **Forex Daily emerging** (USD/MXN, USD/ZAR Daily) — fetch + backtest, ~1h chacun
4. **Indices internationaux** (DAX/FTSE/NKY H4) — fetch + backtest, mais risque gap équivalent SPX/NDX
5. **NatGas via broker direct** (chantier post-gate S6, dépend du choix broker live)

## Artefacts

- DB local enrichie : USD/MXN H1 31558 candles
- Modifié : aucun code (réutilisation `track_a_backtest.py` + `track_c_trend_following.py`)
- Commit : à venir
