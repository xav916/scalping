# Expérience #24 — Walk-forward expansif Track B macro filter

**Date :** 2026-04-26 (~02h45 Paris)
**Tracks :** B Phase 3 calibration
**Numéro d'expérience :** 24
**Statut :** `closed-negative` *(walk-forward dégrade vs filtre fixe)*

---

## Hypothèse

> "Si on refit le filtre macro sur fenêtre glissante 12 mois (au lieu de TRAIN fixe 2024-04 → 2025-04 d'exp #9), le filtre s'adapte au régime courant et performe mieux out-of-sample, dépassant +0.10 PF vs le fixe."

Test pour résoudre le caveat d'exp #10 où le filtre fixe dégradait en pré-bull cycle (régime-spécifique).

## Protocole

Fenêtre out-of-sample : 24 mois 2024-04 → 2026-04.
Pour chaque mois M dans cette fenêtre :
- TRAIN window = [M-12, M-1]
- Refit `build_or_filter_from_train(train_trades)` sur cette fenêtre
- Apply filtre aux trades du mois M
- Cumuler les trades retenus

Comparer 3 stratégies :
- Baseline OOS (pas de filtre)
- Walk-forward (refit mensuel)
- Filtre fixe (rules apprises sur 2024-04→2025-04, apply au reste)

## Critère

| Sortie | Condition | Verdict |
|---|---|---|
| Walk-forward justifié | PF WF ≥ PF Fixe + 0.10 | Migrer vers refit dynamique |
| Égal | Δ entre -0.10 et +0.10 | Garder fixe (KISS) |
| Walk-forward inférieur | Δ < -0.10 | Confirmer que dynamique sur-fitte |

## Résultats

```
Stratégie                            n    PF      PnL%    kept%
─────────────────────────────────────────────────────────────────
BASELINE OOS (no filter, 24M)     1166  1.60   +578%    100%
WALK-FWD (refit chaque mois)       922  1.60   +489%   79.1%
FIXE (TRAIN 24-25 → TEST 25-26)    552  1.94   +472%   85.7%
```

**Δ Walk-forward vs Fixe = -0.34** (largement sous le seuil)
**Δ Walk-forward vs Baseline = 0** (le filtre dynamique n'apporte rien)

## Évolution du nombre de règles par mois (refit walk-forward)

```
2024-04 → 2024-12 : 5-14 règles (régime variable, post-COVID)
2025-01 → 2025-09 : 2-7 règles (régime stable, bull cycle)
2025-10 → 2026-03 : 7-23 règles (régime à nouveau variable)
```

Plus il y a de **variance** dans la fenêtre TRAIN, plus le filtre OR devient permissif (plus de règles), ce qui le rend **moins discriminant**.

## Verdict

> Hypothèse **INFIRMÉE — niveau "Walk-forward inférieur"** : Δ -0.34 PF vs filtre fixe. Le refit dynamique sur fenêtre 12 mois **sur-fitte au noise mensuel**.
>
> Plus largement : le walk-forward est **égal au baseline** (PF 1.60 / 1.60). Le filtre dynamique ne sélectionne pas mieux que ne pas filtrer du tout. C'est statistiquement faible.

## Lecture méthodologique

C'est un cas classique de "less is more" en data science quantitative :
- Ajouter de l'adaptivité ajoute du bruit plus que du signal quand le sample TRAIN n'est pas énorme (12 mois × 2 paires ≈ 500 trades = noisy)
- Le filtre fixe apprend sur un régime *spécifique* (TRAIN 2024-04→2025-04 = milieu de bull cycle), il fonctionne sur le test (2025-04→2026-04 = même régime), mais l'exp #10 montre qu'il dégrade en pré-bull
- Solution honnête : **pas de filtre adaptatif au régime**, le baseline V2_CORE_LONG seul est plus robuste cross-régime

Cohérent avec l'insight d'exp #10 : "le baseline V2_CORE_LONG est lui-même robuste cross-régime (PF 1.60 PRE_TEST sans filtre)".

## Conséquences actées

### Pour Phase 4 (déjà déployée)
- **Confirme la décision Phase 4 v1 sans filtre macro.** Le système live actuel (V2_CORE_LONG seul, pas de filtre) est optimal.
- Pas de re-deploy nécessaire.

### Pour Phase 5 / gate S6
- Inutile d'ajouter un filtre macro adaptatif. Si on veut filtrer un jour, garder le filtre fixe d'exp #9 (PF 1.94 sur 2025-26 régime-conditionnel).
- Mais en réalité, le baseline cross-régime suffit largement.

### Pour Track B globalement
- Phase 3 ML proper (déprioritisé) reste un investissement potentiel pour découvrir des combinations multi-dim non-linéaires. Mais vu les résultats walk-forward, le ML risque de sur-fitter encore plus que les règles OR. À évaluer plus tard sur fenêtre TRAIN beaucoup plus large (5+ ans).

### Insight transversal

Sur tous nos tests d'extension du système V2_CORE_LONG (filtre macro fixe / walk-forward / V2_EXT 4pat / V2_TIGHT 2pat), **rien n'améliore significativement le baseline cross-régime**. Le système est "complet" dans sa version actuelle.

C'est en fait une bonne nouvelle : le système est **simple, robuste, et résistant au tinkering**. Pas de risque de "casser" en ajoutant une couche.

## Artefacts

- Script : `scripts/research/track_b_walk_forward.py`
- Commit : à venir
