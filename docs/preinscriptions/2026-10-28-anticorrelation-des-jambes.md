# Pré-inscription — la baisse de 20,2 % de variance vient-elle de l'ANTI-CORRÉLATION des jambes ?

**Date** : 2026-10-28 · **Écrit AVANT la mesure.** · **Fichier NEUF, commité une fois.**
**Origine** : verdict `2613282`. Apparier les deux jambes au même instant a fait
**baisser l'écart-type nul de 20,2 %** (0,020967 → 0,016153), ce qui a porté le
`t` de +4,386 à +5,602 **à écart quasi constant**. J'ai avancé un mécanisme —
les deux jambes opposées ont des issues anti-corrélées — **sans le mesurer**.
Ce banc le mesure, et le rend falsifiable.

## 🔑 La dérivation, qui donne un nombre AVANT la mesure

Population : **N = 4 280** setups sur **2 403** instants, donc **D = 1 877**
duos et **S = 526** groupes à un seul setup (`2D + S = 4 280` ✓).

Si les groupes sont indépendants entre eux et que les deux jambes d'un duo ont
une corrélation `ρ`, la variance de la moyenne d'un tirage vaut :

```
Var = (v / N^2) [ 2D (1 + rho) + S ]
    = (v / N) [ 1 + (2D / N) rho ]
    = (v / N) [ 1 + 0,87710 rho ]
```

À `ρ = 0` on retrouve `v / N` : la formule est bien normalisée.

Le rapport de variance **mesuré** entre le barreau apparié et le barreau
`RESEAU` — le seul qui isole l'appariement, les deux étant sur le réseau
horaire — vaut `(0,016153 / 0,020967)² = 0,59353`. Donc :

```
0,87710 rho = 0,59353 - 1       =>   rho = -0,4634
```

⇒ **Je prédis `ρ ≈ −0,463`**, avant toute mesure. *(Avec `UNIFORME` comme base
on obtiendrait −0,413 ; `RESEAU` est la bonne base car il ne diffère du barreau
apparié que par l'appariement.)*

🔑 **Le vrai test n'est pas le signe de `ρ`, c'est qu'il REPRODUISE la baisse
observée.** Un `ρ` négatif mais petit laisserait la baisse inexpliquée, et le
mécanisme serait **faux** même avec le bon signe.

⛔ **Et une baisse de variance ne peut PAS venir d'un nombre de tirages réduit.**
Apparier fait passer de 4 280 instants tirés à 2 403 : à issues indépendantes,
moins de tirages donnerait **plus** de variance, pas moins. Le signe de l'effet
exclut donc cette explication d'emblée — c'est ce qui rend l'anti-corrélation la
candidate naturelle.

## Ce qui est mesuré

- **`rho_duos_placebo`** — corrélation entre les R des deux jambes d'un duo,
  sur les tirages du schéma `RESEAU_ET_PAIRES`. ⚠️ L'ordre des deux jambes d'un
  duo est **arbitraire**, donc la corrélation est calculée sous sa forme
  **symétrique** (chaque duo compté dans les deux ordres) — c'est le
  coefficient intra-classe, le seul qui ne dépende pas d'un ordre inventé.
- **`sd_predit`** — l'écart-type nul reconstruit depuis `rho_duos_placebo` par
  la formule ci-dessus, et **`ecart_sd_predit_pct`** son écart relatif à
  l'écart-type **observé dans la même passe**.
- **`rho_duos_reel`** — la même corrélation sur les **duos réels d'août**
  (bras `RECALCULE`). C'est le chiffre qui décrit la **production**.
- **`part_duos_un_tp_un_sl_pct`** — part des duos où une jambe atteint `TP1` et
  l'autre `SL`. Le mécanisme rendu concret.

⛔ **Les deux barreaux sont REJOUÉS dans cette passe**, pas repris de
`2613282` : comparer un `ρ` mesuré ici à un écart-type mesuré là-bas serait la
faute de source du 27/10. D'où la clause de reproduction ci-dessous.

## 🔑 CONTRÔLE D'AMPLITUDE, fait AVANT d'engager les seuils

- **`ρ` vit dans [−1 ; 1].** Les bornes engagées (−0,30 et −0,60) sont
  **strictement intérieures**, et **les deux échecs sont atteignables** :
  mécanisme absent ⇒ `ρ ≈ 0` ⇒ `P1` tombe ; jambes parfaitement en miroir ⇒
  `ρ → −1` ⇒ `P2` tombe.
- **`ecart_sd_predit_pct`** : chaque écart-type estimé sur 200 tirages porte une
  erreur relative de `1/√(2×199) ≈ 5,0 %`, donc l'écart entre prédit et observé
  porte ≈ **7,1 %** de bruit. Le seuil de **15 %** vaut ≈ **2,1 σ** :
  franchissable. **Et s'il n'y avait aucune anti-corrélation**, `sd_predit`
  vaudrait `sd_baseline` et l'écart serait de **29,8 %** — soit **deux fois le
  seuil**. L'instrument discrimine.
- **`part_duos_un_tp_un_sl_pct`** vit dans [0 ; 100], seuil 35 intérieur.

<!-- CRITERE-MACHINE
statistique: anticorrelation_des_jambes_appariees
convention: A
forme: placebo
horizon: 5min
fenetre_heures: 96
source_bras_reel: RECALCULE
placebo_schemas: RESEAU,RESEAU_ET_PAIRES
placebo_decisif: RESEAU_ET_PAIRES
population: resolved_backfill=0 AND timeframe=5min AND pair IN 7_BINANCE AND bar_timestamp < 2026-08-20
fin_chargement: 2026-10-27T18:00:00+00:00
tirages_placebo: 200
graine: 20261027
cellules: 1
reference_ecart_reseau: 0.091961
reference_ecart_reseau_et_paires: 0.090488
reference_sd_baseline: 0.020967
rho_attendu: -0.4634
validite: n_reel >= 3500 ET couverture_bougies_pct > 99 ET duos >= 1877 ET ecart_reproduction_max_pct < 1.0 ET observations_rho >= 100000 ET tirages_aboutis >= 190
admission: rho_duos_placebo < -0.30 ET ecart_sd_predit_pct < 15.0
rejet: rho_duos_placebo > -0.05
P1_rho_placebo_max: -0.30
P2_rho_placebo_plancher: -0.60
P3_ecart_sd_predit_pct_max: 15.0
P4_rho_reel_max: -0.20
P5_part_duos_un_tp_un_sl_pct_min: 35.0
-->

⚠️ **Correspondance des noms** : `admission` = **le mécanisme est CONFIRMÉ**,
c'est-à-dire que l'anti-corrélation mesurée **explique** la baisse de variance.
`rejet` = **réfuté**, il n'y a pas d'anti-corrélation et la baisse vient d'autre
chose. ⛔ **Entre les deux** (`ρ` entre −0,30 et −0,05) `or-verdict` rendra
**REFUS**, et c'est voulu : une anti-corrélation partielle qui n'explique pas la
baisse n'est **ni** une confirmation **ni** une réfutation.

## Prédictions, dites d'avance

1. **`ρ(placebo) < −0,30`** — anti-corrélation franche. Attendu **−0,463**.
2. **`ρ(placebo) > −0,60`** — et pas un miroir parfait : les entrées diffèrent
   dans 94 % des duos et le rapport des `risk_pct` a une médiane de 1,11, donc
   les deux jambes ne sont pas exactement opposées.
3. **`ecart_sd_predit_pct < 15 %`** — 🔑 **LA PRÉDICTION DÉCISIVE** : le `ρ`
   mesuré doit **reconstruire** l'écart-type nul observé. C'est elle qui
   distingue « j'ai trouvé une corrélation » de « j'ai expliqué la baisse ».
4. **`ρ(réel) < −0,20`** — les duos réels d'août sont eux aussi
   anti-corrélés. ⚠️ Moins fortement attendu que le placebo : les bornes réelles
   ont été posées sur des prix d'époque, ce qui disperse la géométrie.
5. **`part_duos_un_tp_un_sl_pct > 35 %`** — le mécanisme concret. Estimation
   ponctuelle ≈ **50 %**. ⚠️ C'est la prédiction dont je suis le moins sûr : la
   règle « SL gagne les ex æquo dans la même bougie » peut tuer **les deux**
   jambes beaucoup plus souvent que je ne l'imagine.

## Ce que chaque issue implique

- **Admission** ⇒ la baisse de variance est **comprise**, et la conclusion de
  `2613282` tient avec son mécanisme : **le placebo uniforme était
  conservateur**, et le `t = +5,60` du barreau apparié est le bon chiffre.
- **Rejet** ⇒ ⛔ **la baisse de 20,2 % reste INEXPLIQUÉE**, et je dois alors
  suspendre la lecture « le placebo uniforme était conservateur » : un
  écart-type nul qui bouge pour une raison inconnue n'est pas un écart-type nul
  sur lequel appuyer un `t`. **Ce serait une rétractation partielle de
  `2613282`.**
- **REFUS (entre-deux)** ⇒ même conséquence que le rejet, en plus honnête : je
  le dirai comme un **« je ne comprends pas encore »**, pas comme une nuance.
- ⚠️ **Si P5 échoue alors que P1 à P3 tiennent**, l'anti-corrélation existe et
  explique la baisse, mais **pas par le mécanisme que j'imaginais** — et il
  faudra chercher lequel.

## ⚠️ Limites, posées d'avance

- **Hors échantillon seulement** (4 280 lignes, 7 paires crypto, 05 → 19/08).
- La formule suppose les **groupes indépendants entre eux**. Ils ne le sont
  pas : les fenêtres de 96 h se recouvrent massivement (cf. `409d194`). ⇒ Le `ρ`
  déduit absorbe une part de cette dépendance inter-groupes, et **`P3` teste la
  formule autant que le mécanisme**. Je le dirai dans le verdict.
- Mesure **descriptive** : elle explique un écart-type, elle ne dit **rien** de
  plus sur l'existence du signal.
- **Une seule cellule**, aucune autre ne sera testée après coup.
- Antériorité du banc partagé : refus pré-annoncé, skill **non modifiée**.
