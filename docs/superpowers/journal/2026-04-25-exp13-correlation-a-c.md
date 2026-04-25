# Expérience #13 — Corrélation Track A × Track C

**Date début :** 2026-04-25
**Date fin :** 2026-04-25 (~23h45 Paris)
**Tracks :** A + C (cross-track)
**Numéro d'expérience :** 13
**Statut :** `closed-positive` *(simplification recommandation Phase 4)*

---

## Hypothèse

> "Si Track A V2_CORE_LONG et Track C TF LONG capturent des angles méthodologiques différents du même edge sur métaux H4 (pattern detection vs trend-following), alors la corrélation Pearson de leurs monthly returns est inférieure à 0.5, ce qui valide la diversification du portefeuille combiné et un Sharpe boost significatif."

C'est le test direct de l'allocation 50/30/20 recommandée à la fin d'exp #12.

## Données

- 4 séries monthly returns (en €) sur 24 mois (2024-04 → 2026-04)
- Vol target sizing : capital 10k€, risque 1% par trade

## Protocole

1. Pour chaque (pair, system), apply_vol_target_sizing → group by month → série de PnL mensuels
2. Aligner les 4 séries sur les mêmes 24 mois (mois sans trade = 0)
3. Calculer corrélation Pearson sur les paires :
   - Track A XAU × Track C XAU (intra-pair, inter-system)
   - Track A XAG × Track C XAG (intra-pair, inter-system)
   - Track A XAU × Track A XAG (cross-pair, intra-system)
   - Track C XAU × Track C XAG (cross-pair, intra-system)
4. Calculer Sharpe combiné 50/50 sur PnL summé monthly

## Critère go/no-go

| Sortie | Condition | Verdict |
|---|---|---|
| **Diversification réelle** | \|ρ(A, C)\| < 0.5 | Allocation 50/30/20 justifiée, Sharpe combiné > Sharpe individuel |
| **Corrélation modérée** | 0.5 ≤ \|ρ\| < 0.75 | Bénéfice diversif partiel, allocation à reconsidérer |
| **Redondance** | \|ρ\| ≥ 0.75 | Les 2 systèmes captent le même signal, simplification possible |

## Résultats

### Corrélations Pearson (monthly returns en €)

| Combo | Pearson | Lecture |
|---|---|---|
| Track A XAU × Track C XAU | **+0.634** | Modérée |
| Track A XAG × Track C XAG | **+0.560** | Modérée |
| Track A XAU × Track A XAG | +0.616 | Modérée — métaux corrélés |
| Track C XAU × Track C XAG | +0.682 | Modérée — métaux corrélés |

### Sharpe combiné 50/50 (PnL summé monthly)

| Combo | Sharpe combiné | Sharpe meilleur solo | Δ |
|---|---|---|---|
| Track A XAU + Track C XAU | 1.61 | 1.59 (Track A) | +0.02 |
| Track A XAG + Track C XAG | 1.61 | 1.55 (Track A) | +0.06 |

## Verdict

> Hypothèse **INFIRMÉE niveau "Diversification réelle"** : corrélations 0.56-0.68 entre Track A et Track C → corrélation **modérée** sur les 2 paires.
>
> **Implication concrète** : le Sharpe combiné 50/50 ne booste que de +0.02 à +0.06 vs le meilleur système solo. La diversification réelle est **faible**.

### Lecture économique

Les 2 systèmes capturent en grande partie le **même** signal (trend bull métaux 2024-2026), juste sous 2 angles méthodologiques différents :
- Track A V2_CORE_LONG : pattern detection (cherche les setups "entry") sur la trend
- Track C TF LONG : EMA cross + filter (suit la trend en mode "régime LONG")

Les deux convergent quand la trend est claire (la plupart du temps en bull cycle métaux), divergent rarement. Donc **leurs PnL mensuels bougent ensemble** la majorité du temps.

C'est cohérent avec l'observation exp #6 (Track A ∩ Track C) : sur XAU, l'intersection ne change rien (redondance). Sur XAG, l'intersection apporte un peu (les 2 systèmes ne convergent pas toujours en condition chahutée).

### Conséquence pour la stratégie

La diversification multi-système **n'est pas la bonne réponse** pour booster le risk-adjusted return ici. Pour vraiment réduire le risque, il faudrait soit :
1. **Diversifier par classe d'actif** (commodities, indices, FX) — mais Track A et C sur forex à plat (exp #1, #5)
2. **Diversifier par horizon** (H4 + Daily + Weekly) — pas testé
3. **Filtre macro régime-conditionnel** (Track B exp #9) — fonctionne en régime spécifique

La meilleure simplification pratique : **prendre Track A V2_CORE_LONG XAU H4 seul** et accepter le maxDD 20%, en sachant que le Sharpe combiné n'apporte que +0.02.

## Conséquences actées

### Phase 4 shadow log spec — VERSION SIMPLIFIÉE

**Système v1 (à démarrer)** :
- **1 seul stream** : Track A V2_CORE_LONG XAU H4
- 100% du capital alloué (pas de fragmentation)
- Risque par trade : 0.5% (vs 1% backtest, conservateur pour démarrer)
- Sharpe attendu : 1.5-1.6 in-regime, probable 0.8-1.2 cross-régime

**Si maxDD live > 25% (douleureux)** :
- Ajouter Track C XAU H4 comme 2e stream avec 30% du capital
- Track A passe à 70%
- Sharpe attendu reste similaire (~1.61) mais drawdown amorti par Track C maxDD 4.7%

**XAG reporté indéfiniment** :
- Corrélation 0.62 avec Track A XAU + 0.68 avec Track C XAU = double exposition métaux peu utile
- À envisager seulement si XAU stream montre des limites (saturation positions, slippage XAU spécifique)

### Track A
- Confirmé candidat #1 single. Track C devient un "backup amortisseur" optionnel.

### Track B
- Le filtre macro reste optionnel (régime-conditionnel). Pas obligatoire pour shadow log v1.

### Pour le code prod
- Aucun changement V1.
- Phase 4 implémentation = endpoint shadow log dédié au scheduler live, qui logge les setups V2_CORE_LONG XAU H4 sans modifier le scoring V1.

## Caveats

1. **Corrélation calculée sur 24 mois** est noisy — IC 95% sur Pearson(0.6, n=24) typiquement [0.3, 0.8].
2. **Régime-spécifique** : la corrélation pourrait être plus faible en régime calme/mean-reverting (Track A et Track C divergent plus). En bull cycle (2024-2026), elle est forcément haute (les 2 suivent le trend).
3. **Sharpe combiné calculé en somme PnL pas en allocation 50/50 capital** — l'allocation 50/50 capital donnerait des Sharpes individuels plus bas (moins de risque par trade) mais une corrélation identique. La conclusion ne change pas.
4. **Track A XAG correlation avec Track A XAU = 0.62** — l'exposition XAG ajoute peu de diversif vs XAU. Renforce la décision de skip XAG.

## Artefacts

- Script : `scripts/research/track_a_c_correlation.py`
- Output complet : voir résultats ci-dessus
- Commit : à venir
