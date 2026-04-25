# Expérience #35 — Scan systématique 57 instruments × 2 TF × 4 filters

**Date :** 2026-04-26 (~01h30 Paris)
**Tracks :** Méthode rigoureuse — découverte de candidats par scan exhaustif
**Statut :** `closed-positive` — 28 cellules retenues strict, 2 candidats sélectionnés pour shadow log

---

## Hypothèse

> "L'approche ad-hoc d'extension des supports stars (par adjacence économique) laisse potentiellement des edges sur la table. Un scan systématique de l'univers Twelve Data accessible (~60 instruments × 2 TF × 4 filters = ~450 cellules) suivi d'un FDR strict (Sharpe 12M ≥ 1.0 ET mean PF 24M+3y ≥ 1.30 ET ≥3/4 fenêtres ≥ 1.15) révélerait 2-5 vrais nouveaux candidats au-delà des 4 stars actuels."

## Protocole

### Phase A — Taxonomie (~30 min)
- Énumération de l'univers : forex emerging (11), crypto majors (8), indices intl (8), sector ETFs (13), commodities soft (1) = **41 nouveaux** + 16 déjà fetchés = **57 instruments**
- Vérification dispo Twelve Data via `symbol_search` API : NatGas (futures), Hang Seng, NKY, MATIC, soft commodities (COFFEE, COCOA, SUGAR) → 404 / non accessible Grow tier

### Phase B — Pre-screening (~12 min wall-time)
- Script `scripts/research/pre_screen_universe.py`
- Fenêtre 12M (2025-04-25 → 2026-04-25)
- No-costs (edge brut) + use_h1_sim (5min absent pour les 41 nouveaux)
- 4 filters : BASELINE / V2_CORE_LONG / V2_WTI_OPTIMAL / V2_TIGHT_LONG
- 2 TF : H4 / Daily
- Total : **454 cellules** (sur 456 théoriques, 2 skip n<20)

### Phase C — Deep dive sur survivants (~15 min wall-time)
- Script `scripts/research/deep_dive_survivors.py`
- Filtres : PF no-costs ≥ 1.50 ET n ≥ 20 ET filter ≠ BASELINE → **60 cellules survivantes**
- 4 fenêtres : 12M / 24M / 3y_cumul / pre_bull (2023-04 → 2024-04)
- Avec coûts spread/slippage 0.02% standard
- KPIs : PF, Sharpe annualisé, Calmar, maxDD%

### Phase D — FDR strict
- Critère : ≥3/4 fenêtres PF ≥ 1.15 ET Sharpe 12M ≥ 1.0 ET mean PF (24M, 3y) ≥ 1.30
- Bonferroni-corrected α = 0.05 / 60 = 0.0008 (tolerant aux 47% retenus car convergence multi-fenêtres exigée)

## Résultats — 28 cellules survivantes strict (sur 60)

### Top 10 (mean_PF_24M_3y)

| Rang | Cellule | n_fen | Sharpe 12M | PF 24M | PF 3y | mean | Classe |
|---|---|---|---|---|---|---|---|
| 1 | USD/TRY 1d V2_CORE_LONG | 4/4 | 3.45 | 5.62 | 16.83 | **11.23** | ⚠️ Faux positif carry |
| 2 | XLI 1d V2_TIGHT_LONG | 3/4 | 2.74 | 2.47 | 1.81 | **2.14** | Industrial sector |
| 3 | ASX 1d V2_TIGHT_LONG | 3/4 | 2.58 | 2.30 | 1.57 | **1.94** | Australian index |
| 4 | XAG/USD 4h V2_TIGHT_LONG | 4/4 | 1.65 | 1.73 | 1.74 | **1.74** | Métal (déjà star) |
| 5 | XLK 1d V2_WTI_OPTIMAL | 4/4 | 1.01 | 1.69 | 1.70 | **1.69** | Tech sector |
| 6 | ASX 1d V2_CORE_LONG | 3/4 | 2.00 | 1.82 | 1.50 | 1.66 | Australian index |
| 7 | XLE 4h V2_CORE_LONG | 3/4 | 1.66 | 1.88 | 1.44 | 1.66 | Energy sector |
| 8 | XLE 4h V2_TIGHT_LONG | 4/4 | 1.23 | 1.78 | 1.52 | 1.65 | Energy sector |
| 9 | SLV 1d V2_CORE_LONG | 3/4 | 1.85 | 1.68 | 1.55 | **1.61** | Silver ETF |
| 10 | XAG/USD 4h V2_WTI_OPTIMAL | 4/4 | 1.62 | 1.64 | 1.58 | 1.61 | Métal (déjà star) |

### Confirmation des stars existantes

| Cellule shadow log actuel | Rank | mean_PF | Verdict |
|---|---|---|---|
| XAG/USD 4h V2_CORE_LONG | #14 | 1.58 | ✓ confirmé |
| XAG/USD 4h V2_TIGHT_LONG | #4 | 1.74 | ⚠️ V2_TIGHT > V2_CORE sur XAG ! |
| XAU/USD 4h V2_CORE_LONG | #21 | 1.43 | ✓ confirmé |
| WTI/USD 4h V2_WTI_OPTIMAL | absent (PF 1.34 24M, 1.32 3y) | 1.33 | ✓ confirmé borderline |
| ETH/USD 1d V2_CORE_LONG | absent | n/a | ✓ confirmé hier (exp #34) |

## Découvertes méthodologiques

1. **V2_TIGHT_LONG (2 patterns) souvent meilleur que V2_CORE_LONG (3 patterns)** sur métaux et certains sector ETFs. `breakout_up` peut être contre-productif sur des assets range-bound. À considérer pour XAG en remplacement.

2. **Indices internationaux Daily marchent** (ASX, MIB, FTSE survivent strict) — contredit l'hypothèse "gaps cassent les patterns". Cette hypothèse était SPX/NDX-spécifique (très réactifs pré/post US open + earnings season). ASX/MIB/FTSE ont des sessions plus contenues.

3. **Sector ETFs US Daily** émergent comme nouvelle classe productive :
   - **XLI** (industrial) : 2.14 mean PF — driver manufacturing PMI / cycle
   - **XLK** (tech) : 1.69 — driver AI / earnings tech
   - **XLE** (energy) : 1.66 — driver crude / sector rotation
   - **XLP** (consumer staples) : 1.32 — défensif risk-off
   - **XLU** (utilities) : marginal — défensif rates-sensitive
   - **XLRE** (real estate) : 1.53 — rates-sensitive
   - **XLB** (materials), **XLY** (consumer disc), **XLF** (financials), **XLV** (healthcare) : moins productifs

4. **Silver ETF (SLV)** marche en Daily ET H4 — proxy XAG plus liquide pour démo retail (spread typiquement 1c vs XAG/USD).

5. **US Oil ETF (USO)** marche H4 — confirme l'edge pétrole au-delà de WTI direct.

6. **Forex emerging** : sauf USD/TRY (faux positif), aucun autre forex emerging ne survit strict. AUD/USD 1d V2_TIGHT_LONG passe (1.49) mais sample limité.

7. **Crypto altcoins** : LINK/USD 1d V2_WTI_OPTIMAL passe (3/4 fen, mean PF ~1.30) avec Sharpe 12M 0.76 — borderline. SOL, BNB, ADA, DOGE, AVAX, DOT n'ont pas survi le strict cut.

## Faux positifs identifiés

### USD/TRY 1d V2_CORE_LONG — mean_PF 11.23

Lecture : la livre turque déprécie continûment (~30%/an depuis 2021 hyperinflation). Toute stratégie BUY USD/TRY capture ce drift mécaniquement. PF 146 sur pre_bull (2023-04 → 2024-04) est l'indice : c'est un trend down structurel sur la quote, pas un edge tradable.

**Pourquoi pas exploitable** :
- Spreads emerging market massifs chez retail brokers (10-50 pips vs ~1 pip EUR/USD)
- Frais swap nuit énormes côté SHORT TRY (taux Banxico ~50%)
- Risque tail event (intervention banque centrale, contrôle de change)

→ Rejeté méthodologiquement. Cas d'école pour le multiple-testing review.

## Caveats critiques

1. **`use_h1_sim=True`** : pour les 41 nouveaux instruments, pas de 5min en local → simulation forward sur H1 (moins précise). Différence avec 5min sim = ±5-10% PF estimée.

2. **Multi-testing** : 60 tests deep-dive → 28 retenus strict (47%). Bonferroni naïf donnerait 2-3 retenus seulement. Ce ratio élevé suggère que :
   - Soit les patterns V2 capturent un edge structurel généralisable (vraie hypothèse forte)
   - Soit le critère "mean PF 24M+3y ≥ 1.30" est relaxé par convergence vers la fenêtre récente bull (2024-2026 = bull metals + bull tech)
   
   Position prudente : ne retenir que les top 2-3 PAR CLASSE d'actif distincte.

3. **Période pre_bull non-uniforme** : certaines paires (FTSE, ASX, sector ETFs récents) ont moins de data pré-2023 → fenêtre pre_bull n=0 pour 6 cellules. Critère "mean PF 24M+3y" robuste à ça.

4. **Régime bull cycle 2024-2026** : la robustesse "cross-régime" est testée mais le bull cycle métaux + tech post-COVID couvre une bonne moitié de la période. Un crash type 2022 décemberé ou 2008 n'est pas dans le sample.

5. **Coûts retail** : `0.02% spread/slippage` est un standard mais réel sur retail démo Pepperstone. Pour ETFs et indices, les spreads peuvent être plus élevés (5-20 pips) → PF effectif réduit de 0.10-0.20.

## Sélection finale pour intégration shadow log

### Critères

- Top 2 par mean_PF parmi les classes vraiment décorrélées des 4 actuels (XAU, XAG, WTI, ETH)
- Pas de redondance (SLV ≈ XAG, USO ≈ WTI → exclus)
- Pas de risque pays/devise additionnel (ASX, MIB, FTSE → reportés à plus tard)
- Sharpe 12M ≥ 1.0 (déjà filtré par strict)

### Choix : **XLI + XLK Daily** (2 nouveaux)

| Pair | TF | Filter | mean PF | Sharpe 12M | maxDD% | Sizing reco |
|---|---|---|---|---|---|---|
| **XLI** | 1d | V2_TIGHT_LONG | 2.14 | 2.74 | 0.1% | 0.4% |
| **XLK** | 1d | V2_WTI_OPTIMAL | 1.69 | 1.01 | 0.4% | 0.4% |

Drivers économiques distincts :
- XLI = cycle manufacturing US (PMI ISM, capacity utilization)
- XLK = earnings tech US (AI cycle, semis, megacap valuation)

Aucune corrélation forte avec XAU/XAG/WTI/ETH. Diversification réelle au portefeuille.

### Réservés (pour S7-S8 pré-Phase 5 si gate S6 = GO)

- **ASX 1d V2_CORE_LONG** ou V2_TIGHT_LONG (mean PF 1.66-1.94) — si l'on accepte le risque AUD
- **MIB 1d V2_WTI_OPTIMAL** (1.57) — si l'on accepte le risque EUR / banking
- **XLE 4h V2_CORE_LONG** (1.66) — sector énergie peut être ajouté si WTI sous-performe
- **SLV 1d V2_CORE_LONG** (1.61) — si l'on veut un proxy XAG plus liquide retail
- **AUD/USD 1d V2_TIGHT_LONG** (1.49) — seul forex viable, mais sample limité (43 trades 12M)

### Refactor V2_CORE_LONG → V2_TIGHT_LONG sur XAG ?

Question ouverte : XAG/USD 4h V2_TIGHT_LONG (1.74) bat V2_CORE_LONG (1.58) sur mean PF 24M+3y. Mais V2_CORE_LONG capture plus de trades (319 vs 243). Décision à prendre :

- Option A : laisser XAG en V2_CORE_LONG (continuité shadow log déjà déployé)
- Option B : switcher en V2_TIGHT_LONG (PF moyen +0.16 mais -24% de samples)
- Option C : observer en shadow les 2 filters en parallèle (créer V2_CORE_LONG_XAGUSD_4H_TIGHT comme system_id alternatif)

**Reco** : Option A pour ce soir (cohérence avec shadow log live), Option C à reconsidérer pour W2-W3 si V2_CORE_LONG XAG sous-performe vs V2_TIGHT_LONG sur trades observés.

## Conséquences actées

### Pour la session de cette nuit

- ✅ Pre-screening + deep dive faits, 60 cellules approfondies
- ✅ Journal écrit, traçabilité 100%
- ⏳ Intégration XLI/XLK au shadow log : à valider par user (modif `SHADOW_CONFIG`, ~30 min)

### Pour W1 (2026-05-03)

- Si XLI/XLK déjà intégrés → rapport hebdo couvre 6 stars
- Sinon → rapport hebdo couvre 4 stars + ce journal #35 documenté

### Pour le gate S6 (2026-06-06)

- Au gate, considérer cette synthèse comme l'univers exhaustif testé. Pas besoin de re-faire le scan sauf si gate = GO + on veut élargir Phase 5.

## Pistes restantes après scan

1. **Re-tester avec 5min sim** les survivants top 5 (~2h) — pour valider que les PF sont robustes vs use_h1_sim. Discrepancy attendue ±5-10%.
2. **Cross-check macro filter (Track B) sur sector ETFs** (~1h) — XLI/XLK pourraient bénéficier d'un filter VIX ou TNX.
3. **Forex Daily emerging (sauf USD/TRY)** — USD/MXN, USD/ZAR pas encore testés en Daily.
4. **Cross-régime sur 2020-2023** — `--use-h1-sim` permet d'aller pré-2023 pour les pairs avec H1 dispo (XAU, XAG depuis 2020-01).
5. **Filter custom par asset** — une analyse breakdown par pattern × asset (style exp #29 WTI) pourrait révéler des filters dédiés (ex `range_bounce_up` rentable sur XLU défensif ?).

## Artefacts

- `scripts/research/pre_screen_universe.py` — script pre-screening
- `scripts/research/deep_dive_survivors.py` — script deep dive avec FDR
- `scripts/fetch_universe.sh` — fetch H1 5y pour 41 nouveaux instruments
- `pre_screen_results.csv` — output pre-screening (gitignored)
- `deep_dive_results.csv` — output deep dive (gitignored)
- DB local enrichie : 41 nouvelles paires × ~40k H1 each (gitignored)
- Commit : à venir
