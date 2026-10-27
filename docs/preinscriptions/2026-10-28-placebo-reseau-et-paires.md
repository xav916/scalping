# Pré-inscription — le signal `5min` survit-il à un placebo qui respecte la STRUCTURE du réel ?

**Date** : 2026-10-28 · **Écrit AVANT toute mesure de ces cellules.**
⛔ **Fichier NEUF, commité une seule fois.** Le 27/10 j'ai amendé un critère en
place et `or-verdict` a refusé à raison : amender détruit l'empreinte qui est
toute la valeur du dispositif. Ce fichier ne sera pas réécrit — s'il faut le
corriger, ce sera un autre fichier, et le présent restera au dépôt.

## Ce qui a déclenché cette pré-inscription

Le verdict `409d194` cherchait le recouvrement des fenêtres. Il a trouvé que la
dépendance est portée **à l'identique** par le placebo — mais la vérification de
la cadence a mis au jour **deux asymétries que je n'avais pas vues**, et
l'inspection des instants une **troisième** :

1. 🔴 **Réseau horaire dur** : **100,0 %** des barres sont à la minute `:00`
   (1 seule minute distincte sur 4 904 lignes). Le placebo tire
   `uniform(min, max)` puis tombe sur la bougie 5 min suivante ⇒ ses entrées se
   répartissent sur les **douze** créneaux de l'heure, le réel sur **un seul**.
2. 🔴 **Appariement des deux jambes, vérifié à 100 %** : **2 403 instants
   distincts pour 4 280 setups**, dont **1 877 portant exactement 2 setups** —
   et ces duos sont **de sens opposés 1 877 fois sur 1 877**. Le système ouvre
   donc **un achat ET une vente sur la même barre**, systématiquement. Le
   placebo conserve le sens de chaque setup mais **disperse les deux jambes sur
   des instants différents**, détruisant ce **chevauchement**.
   ⚠️ Les deux jambes ne sont pas un miroir exact : le prix d'entrée diffère
   dans **94 %** des duos (1 759 / 1 877) et le rapport des `risk_pct` entre
   jambes a une médiane de **1,11**.
3. ⚠️ Et donc le `n` réel n'est pas 4 280 observations mais **2 403 instants**
   portant 1 ou 2 setups.

🔑 **Chacune de ces trois différences peut à elle seule produire l'écart
publié** (+0,0874 R hors échantillon, +0,0557 R en échantillon). Le banc croyait
tester « l'instant choisi par le détecteur » ; il testait **l'instant choisi, ET
la position dans l'heure, ET l'appariement**.

## La conception : une ÉCHELLE de placebos, pas un seul

Trois schémas, chacun restituant une pièce de plus de la structure réelle, tous
calculés **dans la même passe** sur **les mêmes bougies** :

| schéma | instant tiré | conserve en plus |
|---|---|---|
| `UNIFORME` | `uniform(min, max)` par setup | — *(le placebo publié, rejoué comme témoin)* |
| `RESEAU` | une **heure pleine** tirée uniformément dans l'étendue de la paire | la **position dans l'heure** |
| `RESEAU_ET_PAIRES` | idem, **un seul instant par groupe `(paire, barre)`** | + l'**appariement des jambes** |

⇒ La décroissance de l'écart le long de l'échelle **attribue** la contribution de
chaque asymétrie. Un seul placebo « tout corrigé » dirait que l'écart tombe sans
dire **pourquoi**.

⛔ **`UNIFORME` est rejoué ici, pas recopié depuis `c5c68dc`.** Comparer un
nouveau chiffre à un ancien, fût-il le mien, est exactement la faute de source
du 27/10. Les trois barreaux doivent partager la passe.

⛔ **Le tirage se fait parmi TOUTES les heures pleines de l'étendue**, pas parmi
les heures où le détecteur a effectivement tiré. Rééchantillonner les instants
réels rendrait le placebo ≈ au réel et l'écart ≈ 0 **par construction** : ce
serait un seuil impossible, pas une mesure.

✅ **Bras réel `RECALCULE`**, comme en `d591d42` : les deux bras partagent le
même instantané de donnée.

## ⚠️ DIVULGATION : ce que j'attends, et je n'en suis pas sûr

Je n'ai **pas** de dérivation de la réponse, contrairement au banc du 27/10. Mon
raisonnement :

- La **position dans l'heure** devrait compter un peu : les clôtures de bougies
  horaires attirent de l'activité, donc entrer à `:05` après une barre horaire
  n'est pas neutre. **Contribution attendue : modeste.**
- L'**appariement** devrait compter davantage. Deux jambes opposées au même
  instant, stop à 1,0 d et objectif à 1,8 d, forment un **chevauchement** dont
  l'issue jointe est fortement contrainte — et la règle « SL gagne les ex æquo
  dans la même bougie » s'y applique **deux fois au même moment**. Le placebo
  dissocie ce couplage. **Contribution attendue : la plus grande des trois.**
- **Estimation d'ensemble** : l'écart tombe de **+0,0874** à ≈ **+0,040 R**,
  soit un peu moins de la moitié conservée, et reste significatif.

## 🔑 CONTRÔLE D'AMPLITUDE, fait AVANT d'engager les seuils

La leçon du 28/10 : vérifier le domaine de la formule ne suffit pas, il faut la
plage que la **densité des données** rend accessible.

- L'écart est une **différence d'espérances en R**, non bornée. Les valeurs déjà
  mesurées sur cette série vont de **−0,27** à **+0,24 R** : les seuils **0**,
  **0,029** et **0,0874** sont tous **strictement intérieurs**.
- L'écart-type du placebo vaut ≈ **0,0202 R** (déduit de `t = 4,32` pour
  `0,0874`). Une différence de **0,029 R** entre deux barreaux vaut donc
  ≈ **1,4 σ** : **détectable**, et pas exigée au-delà du mesurable.
- Le `t` n'est pas plafonné : la barre de **2,00** est atteignable des deux
  côtés.

⇒ **Aucun des cinq seuils n'est infalsifiable, ni impossible à tenir.**

<!-- CRITERE-MACHINE
statistique: ecart_signal_le_long_de_l_echelle_de_placebos
convention: A
forme: placebo
horizon: 5min
fenetre_heures: 96
source_bras_reel: RECALCULE
placebo_schemas: UNIFORME,RESEAU,RESEAU_ET_PAIRES
placebo_decisif: RESEAU_ET_PAIRES
population: resolved_backfill=0 AND timeframe=5min AND pair IN 7_BINANCE AND bar_timestamp < 2026-08-20
fin_chargement: 2026-10-27T18:00:00+00:00
tirages_placebo: 200
graine: 20261027
cellules: 3
correction_multiplicite: PLAFOND_PAR_PERMUTATION_200_TIRAGES
reference_ecart_uniforme_publie: 0.0874
validite: n_reel >= 3500 ET couverture_bougies_pct > 99 ET part_entrees_reseau_pct > 99 ET part_placebo_reseau_pct > 99 ET abs(instants_distincts_placebo_apparie - instants_distincts_reel) < 1 ET tirages_aboutis >= 190
admission: ecart_signal_reseau_et_paires > 0 ET t_contre_placebo_reseau_et_paires > 2.00 ET tirages_battus_pct_reseau_et_paires >= 95.0
rejet: abs(t_contre_placebo_reseau_et_paires) < 2.00
P1_ecart_reseau_max: 0.0874
P2_ecart_reseau_et_paires_max: 0.0874
P3_ecart_reseau_et_paires_min: 0.0
P4_t_reseau_et_paires_min: 2.00
P5_ecart_reseau_et_paires_plancher: 0.029
-->

⚠️ **Correspondance des noms** : `admission` = **le signal SURVIT** au placebo
qui respecte la structure. `rejet` = **le signal était un artefact de
structure** — position dans l'heure, appariement, ou les deux.

### 🔑 Les TROIS clauses de validité qui vérifient que le correctif a bien AGI

Un placebo qui aurait **silencieusement** continué à tirer à l'uniforme rendrait
un résultat d'apparence normale. D'où :

- **`part_entrees_reseau_pct > 99`** — le **réel** est bien sur le réseau.
- **`part_placebo_reseau_pct > 99`** — le **placebo** l'est aussi.
- **`abs(instants_distincts_placebo_apparie − instants_distincts_reel) < 1`** —
  le placebo apparié produit **exactement autant d'instants distincts** que le
  réel, donc le regroupement par `(paire, barre)` a réellement été appliqué.

⛔ Sans ces trois clauses, c'est le défaut du 13/10 qui se rejoue : un
interrupteur **armé et INERTE**, qui ne plante pas.

## Prédictions, dites d'avance

1. **`écart(RESEAU) < 0,0874`** — la position dans l'heure contribue à l'écart
   publié. *(Si elle est dépassée, entrer à `:00` est au contraire défavorable,
   et je l'aurai pris à l'envers.)*
2. **`écart(RESEAU_ET_PAIRES) < 0,0874`** — l'appariement y contribue aussi.
3. **`écart(RESEAU_ET_PAIRES) > 0`** — quelque chose survit.
4. **`t(RESEAU_ET_PAIRES) > 2,00`** — et ça reste significatif.
5. **`écart(RESEAU_ET_PAIRES) > 0,029 R`** — au moins **un tiers** de l'écart
   publié survit. Estimation ponctuelle : ≈ **+0,040 R**.

⚠️ **P5 est la prédiction que je tiens pour la plus fragile**, et c'est voulu :
c'est elle qui dirait « l'écart était presque entièrement structurel » sans pour
autant tomber sous la barre de significativité.

## Ce que chaque issue implique

- **Admission, P5 tenue** ⇒ le signal `5min` existe **après** contrôle des trois
  asymétries connues. La réplication de `c5c68dc` devient **nettement plus
  solide**. ⛔ Et toujours **non exploitable** : le coût hors échantillon vaut
  **0,0950 R**, donc à +0,040 R la stratégie **perd encore**.
- **Admission, P5 violée** (écart entre 0 et 0,029, `t` > 2) ⇒ le signal est
  **réel mais marginal**, et l'essentiel de l'écart publié était structurel.
  **Je corrige le chiffre publié**, à la baisse, en clair.
- **Rejet** (`abs(t) < 2`) ⇒ ⛔ **je RETIRE la réplication du `5min`**, et avec
  elle le dernier résultat positif du mur. **Aucun horizon n'aurait alors
  d'information démontrée à l'entrée.** Ce serait une rétractation, pas une
  nuance, et je l'écrirai comme telle.
- ⚠️ **Si `écart(RESEAU)` ≈ `écart(UNIFORME)` mais `écart(RESEAU_ET_PAIRES)`
  s'effondre**, la cause est l'**appariement** seul — et c'est alors le
  **dispositif de trading** qui est en cause, pas la mesure.
  🔑 **Dans tous les cas, ouvrir les deux sens sur la même barre 1 877 fois
  mérite son propre examen** : c'est deux spreads payés pour une exposition
  nette quasi nulle, la même arithmétique qui avait tué la règle de contre-fil
  du 08/10 (quatre demi-spreads pour une exposition nette NULLE). ⛔ Et cet
  examen aura sa propre pré-inscription — il n'est pas testé ici.

## ⚠️ Limites, posées d'avance

- **Hors échantillon SEULEMENT** (4 280 lignes, 05 → 19/08). L'en échantillon
  (18 668 lignes) **n'est pas couvert par ce critère** et demandera sa propre
  pré-inscription. Je m'y tiens pour ne pas multiplier les cellules.
- L'**asymétrie résiduelle** reste : bornes décidées en août sur des prix
  d'époque, issues jugées sur des bougies du jour. Commune à toute la série.
- Le placebo apparié conserve l'appariement **mais pas** la distance entre
  instants successifs : un **placebo par blocs** (décalage circulaire) resterait
  à faire pour cela.
- **Trois cellules pré-spécifiées, aucune autre ne sera testée après coup.**

## Antériorité, dite d'avance

Le banc `scripts/banc_esperance_horizon.py` est **partagé** entre tous les
critères de cette série : `or-preinscription` refusera l'antériorité du
**fichier**, alors que ce critère précède bien son **adaptation**. Dit en clair
ici, comme pour le `5min` et le hors échantillon — **la skill ne sera pas
modifiée pour faire passer ce cas.**
