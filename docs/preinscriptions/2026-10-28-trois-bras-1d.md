# Pré-inscription — TROIS BRAS explicites sur le `1d`, et un contrôle de reproduction qui TIENT

**Date** : 2026-10-28 · **Écrit AVANT la mesure.** · **Fichier NEUF, commité une fois.**
**Origine** : correction `f36faed`. Le garde-fou du banc précédent s'était
déclenché sur une incohérence **réelle**, mais j'en avais publié une **cause
fausse**. Ce banc remplace le mot ambigu « STOCKE » par **trois bras nommés**.

## ⛔ DIVULGATION EN TÊTE : ce banc est CONFIRMATOIRE, pas prédictif

J'ai **déjà mesuré** presque tout ce qu'il va rendre :

```
1d  ISSUE_STOCKEE        -0,064062   (= la reference publiee, a l identique)
1d  GEOMETRIE_RECALCULEE -0,052925
1d  FILL_OUVERTURE       +0,154197
    artefact -0,207122   ecart FILL +0,112848   t +4,524
    desaccord d issue stocke/recalcule : 16 / 1362 = 1,2 %, tous SL -> TIMEOUT
4h  reproduction du bras recalcule : 0,001 %
```

⇒ **`P1`, `P2`, `P4` portent sur des valeurs que je connais** et je ne les
compterai **pas** à mon crédit. Restent **réellement aveugles** : `P3` (le taux
de désaccord du `4h`) et `P5` (la reproduction du placebo `1d`).

🔑 **Ce que le banc apporte malgré ça** : un **contrôle de reproduction valide**
sous des chiffres déjà mesurés, trois bras **nommés sans ambiguïté**, et la mise
au jour d'une **asymétrie de provenance dans les bancs publiés** (ci-dessous).

## 🔴 CE QUE LA CORRECTION A RÉVÉLÉ, et qui dépasse le `1d`

Les critères `1d`, `4h` et `5min` **en échantillon** n'ont **pas** de
`source_bras_reel` ⇒ valeur par défaut **`STOCKE`** ⇒ **leur bras réel vient des
issues de la BASE**, tandis que **leur placebo est SIMULÉ**.

⇒ 🔴 **C'est l'asymétrie de provenance du 27/10, présente dans les trois
verdicts publiés** — identifiée alors pour le `5min` hors échantillon (corrigée
par `RECALCULE` en `d591d42`) et **jamais corrigée pour les trois autres**.

Ampleur mesurée du désaccord stocké/recalculé : **1,2 %** sur le `1d`,
**24,5 %** sur le `5min` hors échantillon. ⇒ L'effet sur le `1d` est **petit**
(+0,011 R) mais **non nul**, et **il va dans le sens qui rend le `1d` plus
mauvais qu'il n'est**.

## Les trois bras, nommés

| bras | entrée | issue | rôle |
|---|---|---|---|
| **`ISSUE_STOCKEE`** | — | **`pnl_pct_net` de la base** | **contrôle de reproduction** |
| **`GEOMETRIE_RECALCULEE`** | `entry` d'août | **rejouée** sur les bougies | le bras **comparable au placebo** |
| **`FILL_OUVERTURE`** | **ouverture** de sa bougie | rejouée | la spécification **réalisable** |

Le placebo (`UNIFORME`, 200 tirages, comme les bancs publiés) est **simulé**
dans tous les cas ⇒ **seul `GEOMETRIE_RECALCULEE` partage sa provenance.**

<!-- CRITERE-MACHINE
statistique: trois_bras_et_reproduction_valide
convention: A
forme: placebo
cellules_horizon: 1d,4h
placebo_schema: UNIFORME
bras: ISSUE_STOCKEE,GEOMETRIE_RECALCULEE,FILL_OUVERTURE
bras_reproduction: ISSUE_STOCKEE
bras_comparable: GEOMETRIE_RECALCULEE
horizon_1d: 1d
population_1d: resolved_backfill=1 AND timeframe=1d
fenetre_heures_1d: 240
reference_issue_stockee_1d: -0.064062
reference_placebo_1d: 0.041348
horizon_4h: 4h
population_4h: resolved_backfill=1 AND timeframe=4h
fenetre_heures_4h: 96
reference_issue_stockee_4h: -0.266410
reference_placebo_4h: -0.244334
tirages_placebo: 200
graine: 20261027
cellules: 2
tolerance_reproduction_pct: 0.5
divulgation: docs/preinscriptions/2026-10-28-trois-bras-1d.md#divulgation
validite: n_reel >= 1000 ET couverture_min_pct > 99 ET reproduction_issue_stockee_max_pct < 0.5 ET part_entree_hors_bougie_fill_max_pct < 0.5 ET tirages_aboutis_min >= 190
admission: ecart_fill_1d > 0 ET t_fill_1d > 2.00
rejet: abs(t_fill_1d) < 2.00
P1_reproduction_issue_stockee_max_pct: 0.5
P2_desaccord_1d_pct_plafond: 3.0
P3_desaccord_4h_pct_plafond: 0.5
P4_t_fill_1d_min: 2.00
P5_reproduction_placebo_max_pct: 2.0
-->

⚠️ **Correspondance des noms** : `admission` = **sous une exécution réalisable,
le `1d` présente un écart positif et significatif** — c'est-à-dire que le `1d`
et le `5min` **échangent bien leurs places**. `rejet` = **ils ne l'échangent
pas**.

🔑 **La porte qui compte est `reproduction_issue_stockee_max_pct < 0,5 %`** :
elle prouve que je lis **les mêmes lignes** que les bancs publiés. C'est elle
qui manquait au banc précédent, où je comparais un bras recalculé à une
référence stockée.

## Prédictions

1. **`ISSUE_STOCKEE` reproduit à < 0,5 %** sur les deux cellules. ⛔ *Connue.*
2. **désaccord `1d` ≤ 3 %** (mesuré 1,2 %). ⛔ *Connue.*
3. **désaccord `4h` ≤ 0,5 %** — ✅ **AVEUGLE.** Déduit de ce que le bras
   recalculé du `4h` reproduisait à 0,001 %, mais **jamais mesuré directement**.
4. **`t(FILL) 1d` > 2,00** (mesuré +4,524). ⛔ *Connue.*
5. **le placebo reproduit à < 2 %** sur les deux cellules — ✅ **AVEUGLE**, et
   c'est un vrai test : le placebo des bancs publiés n'avait **pas** de
   `fin_chargement`, donc il a pu dériver.

## Ce que chaque issue implique

- **Admission, `P5` tenue** ⇒ 🔴 **le `1d` et le `5min` échangent bien leurs
  places selon la spécification d'exécution** ⇒ **aucune des deux conventions ne
  démontre d'information à l'entrée**, et les **trois** verdicts d'espérance
  mesurent une **convention**. Ce serait la conclusion la plus lourde de la
  série, et elle **confirmerait** le retrait du `5min` tout en **interdisant**
  de revendiquer un signal `1d`.
- **Admission mais `P5` violée** ⇒ le placebo publié a dérivé, donc **les écarts
  publiés eux-mêmes** sont à rejouer avant toute conclusion.
- **Rejet** ⇒ le `1d` reste négatif sous les deux spécifications, et
  l'« échange » n'existe pas. ⇒ Le retrait du `5min` tient, et le `1d` reste
  simplement **pire que le hasard**.
- ⚠️ **Si `P1` échoue**, je ne lis pas les mêmes lignes que les bancs publiés et
  **rien** de ce banc n'est interprétable. Arrêt.

## ⚠️ Limites

- **Je ne corrige pas les critères publiés.** Ce banc **mesure** l'asymétrie de
  provenance des `1d`/`4h`/`5min`-en-échantillon ; les rejouer proprement
  demanderait **trois pré-inscriptions neuves**.
- `risk_pct` du `1d` à **9,33 %** : les trois bras y sont peu sensibles aux
  petits décalages, ce qui rend le **−0,207** d'artefact d'autant plus
  surprenant et mérite son propre examen.
- Populations **36 paires** (`1d`) et **10** (`4h`) contre **7** pour le `5min`
  ⇒ **univers différents**, la comparaison inter-horizons reste **indicative**.
- Dépendance à **Twelve Data** (un `429` est déjà survenu ; réessai réussi).
- Antériorité du banc partagé : refus pré-annoncé, skill **non modifiée**.
