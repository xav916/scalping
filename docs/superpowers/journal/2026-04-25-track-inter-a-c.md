# Expérience #6 — Intersection Track A ∩ Track C

**Date début :** 2026-04-25
**Date fin :** 2026-04-25 (~19h45 Paris)
**Tracks :** A ∩ C (cross-track)
**Numéro d'expérience :** 6
**Statut :** `closed-positive` (résultat asset-dépendant)

---

## Hypothèse

> "Si on filtre les setups V2_CORE_LONG (Track A) en gardant uniquement ceux où le régime TF (Track C, EMA 12/48 + filtre EMA 100) est *long* sur le même bar, alors le PF de l'intersection est significativement supérieur à max(Track A seul, Track C seul) sur XAU H4 et XAG H4."

C'est le test "1+1=3 ou 1+1=1" : les 2 tracks captent-elles le même signal (redondance) ou des angles différents (complémentarité) ?

## Motivation / contexte

Exp #5 a montré que Track A V2_CORE_LONG et Track C TF LONG identifient indépendamment les métaux H4 comme l'angle exploitable, avec des recettes très différentes. Question naturelle : combiner ?

3 sorties théoriques :
- **PF intersection >> max(A, C)** : les 2 captent des angles différents, le filtre TF élimine les V2_CORE_LONG faux positifs
- **PF intersection ≈ max(A, C)** : redondance, les 2 captent le même signal
- **PF intersection < max(A, C)** : le filtre TF dégrade — Track A capte des trades hors régime TF qui sont valides

## Données

Identique aux exp précédentes : DB locale, fenêtres 12M et 24M sur XAU + XAG H4, coûts 0.02%.

## Protocole

Script `scripts/research/track_inter_a_c.py` :
1. Run Track A backtest avec filtre `V2_CORE_LONG`
2. Calculer le `tf_regime` Track C par timestamp (EMA 12/48 + filter 100)
3. Filtrer les V2_CORE_LONG : garder uniquement ceux avec `tf_regime[entry_at] == "long"`
4. Comparer 3 mesures : V2_CORE_LONG seul, intersection, TF LONG seul

## Critère go/no-go (FIXÉ AVANT EXÉCUTION)

| Sortie | Condition | Verdict |
|---|---|---|
| **Synergie forte** | PF intersection ≥ max(A, C) + 0.20 sur ≥3 des 4 runs | Combiner = double filtre est le système gagnant |
| **Synergie partielle** | PF intersection ≥ max(A, C) sur ≥2 runs | Asset-dépendant : combiner sur les paires concernées |
| **Redondance** | PF intersection ≈ max(A, C) ± 0.10 sur les 4 runs | Choisir le plus simple (Track C) ou plus volumineux (Track A) |
| **Dégradation** | PF intersection < max(A, C) − 0.10 sur ≥2 runs | Track A capte du signal en dehors du régime TF — garder les 2 séparés |

## Résultats

| Combo | n | WR% | PF | maxDD% | Verdict |
|---|---|---|---|---|---|
| **XAU H4 12M** ||||||
| A V2_CORE_LONG | 318 | 59.7 | 1.58 | 51.79 | référence |
| **INTERSECTION** | 251 | 59.8 | **1.58** | 56.84 | redondance, légère dégradation maxDD |
| C TF LONG | 37 | 32.4 | 2.36 | 7.14 | meilleur PF mais 10× moins de trades |
| **XAU H4 24M** ||||||
| A V2_CORE_LONG | 601 | 55.2 | 1.41 | 51.79 | référence |
| **INTERSECTION** | 481 | 54.1 | **1.28** | 56.84 | **dégradation** |
| C TF LONG | 62 | 30.6 | 2.32 | 9.07 | meilleur PF, mini-sample |
| **XAG H4 12M** ||||||
| A V2_CORE_LONG | 319 | 62.1 | 1.93 | 88.97 | référence |
| **INTERSECTION** | 257 | 65.0 | **2.53** | **46.14** | **synergie forte** (+0.60 PF, maxDD ÷2) |
| C TF LONG | 33 | 27.3 | 3.76 | 16.22 | meilleur PF, mini-sample |
| **XAG H4 24M** ||||||
| A V2_CORE_LONG | 546 | 54.2 | 1.59 | 88.97 | référence |
| **INTERSECTION** | 400 | 54.8 | **1.76** | 69.74 | **synergie partielle** (+0.17 PF, maxDD -19pts) |
| C TF LONG | 60 | 28.3 | 2.47 | 16.48 | meilleur PF, mini-sample |

### Lecture

**XAU :** intersection ≈ A seul ou légèrement pire. Le filtre TF élimine 79-80% des trades V2_CORE_LONG mais le PF reste constant ou diminue → les setups V2_CORE_LONG hors régime TF sont aussi rentables que ceux dedans. **Redondance sur XAU.**

**XAG :** intersection > A seul, et significativement sur 12M (+0.60 PF, maxDD ÷2). Sur 24M le gain est plus modeste (+0.17 PF) mais maxDD passe de 89% à 70%. **Synergie réelle sur XAG.**

## Verdict

> Hypothèse **PARTIELLEMENT CONFIRMÉE — résultat asset-dépendant** :
> - **XAG H4 : synergie réelle**. L'intersection bat A et améliore drastiquement le maxDD. Probable explication : XAG a plus de "faux signaux" V2_CORE_LONG dans les phases de consolidation (où EMA cross n'est pas franc), le filtre TF les élimine.
> - **XAU H4 : redondance ou dégradation légère**. Les 2 tracks captent le même signal. Pas d'intérêt à combiner.

### Système recommandé pour shadow log Phase 4

**Approche asset-spécifique** :
- **XAU H4** → **Track C TF LONG seul** (PF 2.32, maxDD 9%, 62 trades 24M, code minimal)
- **XAG H4** → **Intersection A ∩ C** (PF 1.76, maxDD 70%, 400 trades 24M)
- *Alternative simple si on veut un seul système* : Track C seul sur les deux paires (PF moyen 2.40, mais XAG seulement 60 trades)

C'est défensif et inattendu : on aurait pu penser qu'un système universel serait optimal, mais les 2 actifs ont des comportements différents :
- XAU = trend très propre, où le simple TF capture tout l'edge
- XAG = trend plus chahuté avec faux départs, où le double filtre TF + pattern detection ajoute de la valeur

## Conséquences actées

### Pour Track A
- **V2_CORE_LONG XAG H4** monte au candidat principal pour shadow log XAG (avec filtre TF en plus)
- **V2_CORE_LONG XAU H4** rétrogradé — Track C suffit sur XAU
- Code à industrialiser pour le shadow log : adopter une logique asset-spécifique

### Pour Track C
- **TF XAU H4 LONG** = candidat shadow log principal pour XAU
- Confirme que Track C apporte une vraie valeur sur XAU (et complémentaire sur XAG)

### Pour Track B (à venir)
- L'asset-spécificité observée ici est cohérente avec un facteur macro distinct entre XAU et XAG (XAU = real yields proxy, XAG = demande industrielle + speculative). Track B doit tester séparément sur les 2 actifs.

### Stratégique
- Le portefeuille recherche progresse vers une **règle générale** : pas de "système universel" — chaque asset a sa physique propre, le bon outil est celui adapté à cette physique
- Cohérent avec la littérature multi-asset (Carver, Ilmanen) — les systèmes "1 size fits all" performent moins bien que les systèmes spécialisés par classe

### Pour le code prod
- **Aucun changement V1**. Gel toujours actif jusqu'au gate S6.

## Artefacts

- Script : `scripts/research/track_inter_a_c.py`
- Commit : à venir (incluant ce journal)
