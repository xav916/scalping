# Dépouillement du compteur d'essais N

**Date :** 2026-08-26
**Objet :** établir le nombre de configurations réellement examinées depuis avril 2026,
pour alimenter le `bench_trials` du banc d'essai (`backend/services/research_bench.py`).

> **N = 1 226**

Ce document est l'unique justification du chiffre. Il doit rester lisible par un
tiers : sans lui, `N` serait un nombre qu'on ne saurait pas refaire.

---

## Ce qui compte comme un essai

Une **configuration dont la performance a été examinée en vue d'une sélection**.
C'est la définition de Bailey : le plafond du hasard monte avec le nombre de
configurations *essayées*, pas avec le nombre de rapports *écrits*.

Ne comptent donc pas : l'outillage, les pipelines de données, les runbooks, les
rapports de suivi d'un système déjà choisi.

---

## A. Balayages de recherche — 999

Comptés depuis la section « Protocole » de chaque entrée. **Ce sont des estimations
raisonnées, pas des relevés exacts** : les entrées décrivent leurs grilles en prose,
et seule l'expérience #35 énonce son total (454 cellules).

| # | Entrée | Variantes | Base du décompte |
|---|---|---:|---|
| 1 | Spike H4 vs H1 | 180 | 12 paires × 3 granularités × 5 filtres |
| 2 | Direction × motif | 72 | 3 actifs × 2 sens × 12 motifs |
| 3 | Robustesse 24 mois | 72 | même grille, fenêtre 24 M |
| 4 | V2_CORE_LONG | 4 | 2 actifs × 2 fenêtres |
| 5 | Track C — MVP trend-following | 12 | 2 actifs × 2 fenêtres + 4 cross-asset, long/short |
| 6 | Intersection A ∩ C | 4 | 2 actifs × 2 fenêtres |
| 7 | Pipeline données macro | 0 | outillage |
| 8 | Buckets macro | 36 | 9 dimensions × 4 quartiles |
| 9 | Filtre macro walk-forward | 32 | 8 features × 4 quartiles |
| 10 | Pré-test 2023 (Track B) | 3 | 3 fenêtres |
| 11 | Pré-test 2023 (Track C) | 2 | 2 actifs |
| 12 | Analyse Sharpe | 4 | 4 candidats |
| 13 | Corrélation A × C | 2 | 2 actifs |
| 14 | Validation d'implémentation | 0 | outillage |
| 15 | Hors-échantillon 2020-2024 | 24 | 2 actifs × 12 motifs — c'est là qu'est née la « découverte » `pin_bar_up` |
| 16 | Extension `pin_bar_up` | 8 | 2 actifs × 4 fenêtres |
| 17 | TIGHT vs CORE | 8 | 2 actifs × 4 fenêtres |
| 18 | Cross-asset SPX/NDX | 4 | 2 indices × 2 fenêtres |
| 24 | Walk-forward expansif | 3 | 3 stratégies comparées |
| 25 | V2_ADAPTIVE | 3 | 1 détecteur vs 2 références |
| 29 | Étude WTI | 8 | 2 filtres × 4 fenêtres |
| 30-32 | Brent / Platine / Palladium | 12 | 3 actifs × 4 fenêtres |
| 33 | Track C TF sur WTI | 4 | 2 fenêtres × 2 sens |
| 34 | NatGas / Crypto / MXN | 12 | 3 actifs testables × 4 fenêtres |
| **35** | **Scan systématique** | **454** | **57 instruments × 2 TF × 4 filtres — chiffre énoncé dans l'entrée** |
| 36 | Validation des stars sur 20 ans | 36 | 6 stars × 6 régimes |

L'expérience #35 pèse à elle seule **45 %** du total. Elle applique d'ailleurs une
correction de Bonferroni — mais sur les **60** cellules de sa phase C, pas sur les
**454** de sa phase B.

## B. Contrefactuels du veto, relus 14 fois — 14

Quatorze rapports `track-a-veto-counterfactual` entre le 2026-05-09 et le
2026-08-22, chacun rejugeant **la même hypothèse** sur un échantillon qui grossit.
C'est de la relecture répétée, et l'issue est déjà connue : le verdict
`veto_would_help` du 22/08 s'est révélé un faux positif (p = 0,087 ; le groupe qui
décidait comptait 27 setups, pas 879).

Compté **1 par relecture**. Les ventilations par règle et par paire de chaque
rapport (une dizaine de comparaisons supplémentaires à chaque fois) **ne sont pas
comptées** — les inclure porterait N bien au-delà de 1 226.

## C. Buckets du système d'admission — 138

Le contrôleur d'admission note en continu chaque `(paire, sens, destination)` et en
promeut ou en rétrograde selon le score. C'est une **sélection permanente**, pas un
suivi : 138 buckets distincts figurent dans `pair_admission_state`, sur 104 couples
et 49 paires.

Compté **une fois**, pas une fois par cycle horaire ni par rapport hebdomadaire.

## D. Grille de l'audit du 2026-08-25 — 75

9 seuils de confiance × 3 sens × 3 univers = 81 combinaisons, dont 75 comptaient
au moins 30 clôtures. C'est la grille qui a produit le `DSR = 0,350` publié.

---

## ⚠️ Pourquoi 1 226 est un PLANCHER

Sont volontairement comptés **zéro** :

- les 12 rapports hebdomadaires d'admission — des relevés d'état, pas des essais ;
- les 4 rapports hebdomadaires de shadow log — suivi de candidats déjà choisis ;
- les runbooks, le pipeline géopolitique, la calibration de Brier, l'observation de
  drawdown V1, le document de décision du gate S6 ;
- les ventilations par paire et par règle à l'intérieur de chaque rapport ;
- **tout ce qui a été essayé sans laisser de trace au journal.**

Chacune de ces exclusions rend le banc **plus indulgent**, jamais plus sévère. Un
dépouillement plus fin ne pourra que faire monter N.

---

## Conséquence chiffrée

| | N | Plafond du hasard (Sharpe/jour) | DSR de la meilleure variante connue |
|---|---:|---:|---:|
| Avant | 75 | +0,1925 | 0,350 |
| **Après** | **1 226** | **+0,2626** | **0,054** |

⛔ **Lu tel quel, ce seuil correspond à un Sharpe annualisé de 5,0** — hors de portée
d'un système retail. Ce n'est pas une propriété du marché : c'est une propriété de
la manière dont `var_sr` est actuellement figée. Voir la réserve ci-dessous.

## ⛔ Réserve méthodologique — `var_sr` ne doit pas rester figée

Le banc utilise `VAR_SR_REFERENCE = 0.006286`, la variance des Sharpe entre variantes
**mesurée sur des fenêtres de 128 jours**. Or sous l'hypothèse nulle, la variance du
Sharpe estimé vaut approximativement `1/T` : à T = 128, `1/T = 0,0078` — soit
pratiquement la valeur mesurée. *(Au passage : que la dispersion observée entre
variantes coïncide avec ce que le pur bruit prédit est une confirmation de plus de
l'absence d'edge.)*

Conséquence : **le plafond décroît en `1/√T`**. Un essai jugé sur deux ans devrait
affronter un seuil bien plus bas qu'un essai jugé sur quatre mois. En gelant
`var_sr` à sa valeur 128 jours, le banc impose à tous la barre calibrée pour le plus
court — et devient impossible à franchir pour de mauvaises raisons.

**À corriger avant que le premier essai n'arrive à échéance** : dériver `var_sr` de
la longueur d'échantillon de l'essai, ou de ses propres variantes quand il en
déclare plusieurs.
