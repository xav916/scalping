# Pré-inscription — un placebo FIDÈLE : mesurer le bon `t` au lieu de le dériver

**Date** : 2026-10-28 · **Écrit AVANT la mesure.** · **Fichier NEUF, commité une fois.**
**Origine** : verdict `8935497`. J'y ai corrigé le `t` de +5,602 à **≈ +4,58** en
injectant le `ρ` réel dans une **formule**. Cette formule suppose la variance
**par jambe** identique entre schémas, ce que je n'ai pas vérifié — j'ai donc
publié un chiffre **approché** en le disant.

🔑 **Plutôt que de vérifier les hypothèses de la formule, je construis le
placebo qui rend la formule inutile** : un barreau qui reproduit la dissymétrie
réelle des deux jambes. Son écart-type devient alors la **bonne référence
nulle**, et le `t` est **mesuré** et non plus dérivé.

## ✅ PRÉMISSE VÉRIFIÉE AVANT TOUT CODE

Pourquoi les duos réels sont-ils moins anti-corrélés (`−0,127`) que le placebo
apparié (`−0,443`) ? Parce que le placebo donne **la même entrée** aux deux
jambes (l'ouverture de la bougie tirée) alors que le réel donne à chacune **son
prix d'août**. Mesure du décalage, sur les 4 280 lignes :

```
ratio  entry_stocke / open(bougie apres la barre)
  p1 0,993727   p25 0,999338   median 1,000000   p75 1,000668   p99 1,006110
  min 0,981470  max 1,031379   part a plus de 0,5 % de 1 : 3,1 %
```

⚠️ **Minuscule en prix, ÉNORME en unités de risque.** Le `risk_pct` médian vaut
**0,2106 %**, donc un décalage de 0,067 % (les quartiles) représente déjà
**≈ ⅓ de la distance au stop**, et à `p99` (0,61 %) il **dépasse la distance au
stop d'un facteur 3**.

⇒ **La prémisse tient, et elle est quantitativement suffisante** pour expliquer
la perte d'anti-corrélation. Sans ce contrôle, j'aurais pu construire un barreau
dont les décalages auraient été négligeables, donc indiscernable du précédent.

## La conception : un troisième barreau, et la formule devient inutile

| barreau | instant | entrée de chaque jambe |
|---|---|---|
| `RESEAU` | un par setup | ouverture de la bougie tirée |
| `RESEAU_ET_PAIRES` | **un par duo** | ouverture de la bougie tirée — **miroir** |
| **`RESEAU_PAIRES_DECALAGE`** | **un par duo** | **ouverture × son propre ratio d'août** |

Le ratio de chaque jambe est calculé **une fois** comme
`entry_stocke / open(bougie après sa barre)`, puis appliqué à la bougie tirée.
⇒ Les deux jambes d'un duo restent ouvertes **au même instant** mais à des
niveaux **dissymétriques dans la même proportion qu'au réel**.

⛔ **Les trois barreaux sont REJOUÉS dans la même passe**, avec un contrôle de
reproduction contre `2613282` — comparer un barreau d'ici à un écart-type de
là-bas serait la faute de source du 27/10.

## 🔑 CONTRÔLE D'AMPLITUDE, fait AVANT d'engager les seuils

- **`|ρ(DECALAGE) − ρ(REEL)|`** vit dans [0 ; 2]. Le seuil de **0,10** est
  intérieur, et **l'échec est atteignable** : si le barreau ne reproduisait rien,
  l'écart vaudrait `|−0,443 − (−0,127)| = **0,32**`, soit **trois fois** le
  seuil.
- **`v(DECALAGE)/v(RESEAU)`** : la variance par jambe est estimée sur
  `4 280 × 200 = 856 000` observations, donc son bruit est négligeable. La bande
  **[0,95 ; 1,05]** teste un écart **systématique**, pas du bruit.
- **`t`** n'est pas plafonné ; la bande **[+4,2 ; +5,0]** encadre le +4,58
  dérivé, et les deux bords sont franchissables (le miroir donnait +5,52, le
  non-apparié +4,32).
- **`|ρ(RESEAU)|`** : sur 375 400 observations l'erreur-type vaut ≈ 0,0016, donc
  le seuil de **0,05** est un vrai test et non une tautologie.

<!-- CRITERE-MACHINE
statistique: placebo_fidele_a_la_dissymetrie_des_jambes
convention: A
forme: placebo
horizon: 5min
fenetre_heures: 96
source_bras_reel: RECALCULE
placebo_schemas: RESEAU,RESEAU_ET_PAIRES,RESEAU_PAIRES_DECALAGE
placebo_decisif: RESEAU_PAIRES_DECALAGE
population: resolved_backfill=0 AND timeframe=5min AND pair IN 7_BINANCE AND bar_timestamp < 2026-08-20
fin_chargement: 2026-10-27T18:00:00+00:00
tirages_placebo: 200
graine: 20261027
cellules: 1
reference_ecart_reseau: 0.091961
reference_ecart_reseau_et_paires: 0.090488
reference_rho_reel: -0.1273
reference_t_derive: 4.579
validite: n_reel >= 3500 ET couverture_bougies_pct > 99 ET duos >= 1877 ET ecart_reproduction_max_pct < 1.0 ET part_ratio_non_unitaire_pct > 40 ET tirages_aboutis >= 190
admission: abs(rho_duos_decalage - rho_duos_reel) < 0.10
rejet: abs(rho_duos_decalage - rho_duos_reel) >= 0.10
P1_ecart_rho_decalage_reel_max: 0.10
P2_rapport_variance_par_jambe_plancher: 0.95
P3_rapport_variance_par_jambe_plafond: 1.05
P4_rho_reseau_abs_max: 0.05
P5_mediane_decalage_sur_risque_min: 0.15
-->

⚠️ **Correspondance des noms** : `admission` = **le barreau fidèle reproduit la
structure réelle**, donc son écart-type est la bonne référence nulle et le `t`
qu'il rend est **mesuré**. `rejet` = **il ne la reproduit pas**, et le `t` reste
**approché** par la formule — avec sa limite assumée.

🔑 **`part_ratio_non_unitaire_pct > 40` vérifie que le correctif a AGI** : si les
ratios valaient tous 1, ce barreau serait identique au précédent et le résultat
aurait l'air normal. C'est la garde du 13/10 — un interrupteur armé et inerte ne
plante pas.

## Prédictions, dites d'avance

1. **`|ρ(DECALAGE) − ρ(REEL)| < 0,10`** — 🔑 **LA PRÉDICTION DÉCISIVE** : le
   barreau fidèle doit retrouver l'anti-corrélation **réelle** (−0,127), pas
   celle du miroir (−0,443).
2. **`v(DECALAGE)/v(RESEAU) ≥ 0,95`** et
3. **`≤ 1,05`** — la variance **par jambe** ne dépend pas du schéma. ⇒ **C'est
   l'hypothèse de ma formule, enfin testée.** Si elle tombe, mon `+4,58`
   dérivé était faux **en plus** d'être approché, et je le dirai.
4. **`|ρ(RESEAU)| < 0,05`** — contrôle négatif : sans appariement, pas de
   corrélation intra-duo. ⛔ Si elle n'est pas nulle, c'est que les deux jambes
   sont corrélées par autre chose que l'instant partagé, et toute l'analyse
   change.
5. **`médiane(|décalage| / risk_pct) > 0,15`** — le décalage est matériellement
   grand devant la distance au stop. Estimation ponctuelle ≈ **0,3**.

## Ce que chaque issue implique

- **Admission, `P2`/`P3` tenues** ⇒ le `t` du barreau fidèle est **le bon
  chiffre, mesuré**. Je **remplace** le `≈ +4,58` dérivé par cette valeur et
  retire la mention « approché ». ✅ **La limite la plus sérieuse de `8935497`
  serait levée.**
- **Admission mais `P2`/`P3` violées** ⇒ le barreau fidèle reste la bonne
  référence (il ne dépend d'aucune formule), **mais** mon `+4,58` dérivé était
  biaisé. ⇒ Je publierais l'écart entre les deux comme **mesure de mon erreur**.
- **Rejet** ⇒ ⛔ **je ne sais pas reproduire la structure réelle**, et le `t`
  reste approché. Je laisserais alors `8935497` tel quel, **limite comprise**,
  et je dirais que j'ai échoué à la lever.
- ⚠️ **Si `P4` échoue**, tout le raisonnement de `8935497` est suspect : une
  corrélation intra-duo **sans** instant partagé signifierait que les deux
  jambes sont liées par leur géométrie seule. **Ce serait le résultat le plus
  important de ce banc**, et le plus dérangeant.

## ⚠️ Limites, posées d'avance

- **Hors échantillon seulement** (4 280 lignes, 7 paires crypto, 05 → 19/08).
- Le ratio est calculé contre `open(bougie après la barre)` — **une** référence
  possible parmi d'autres. Un autre choix (clôture de la barre, VWAP) donnerait
  des ratios légèrement différents ; je n'en teste **qu'un**, celui qui
  correspond à l'instant d'entrée simulé.
- Le barreau fidèle **ne corrige pas l'espacement** entre instants successifs :
  le placebo par **blocs** reste à faire.
- **Trois barreaux, une cellule décisive**, aucune autre ne sera testée après
  coup.
- Antériorité du banc partagé : refus pré-annoncé, skill **non modifiée**.
