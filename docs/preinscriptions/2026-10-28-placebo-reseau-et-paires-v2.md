# Pré-inscription v2 — placebo RÉSEAU et PAIRES : **un seul instrument de validité corrigé**

**Date** : 2026-10-28 · **Écrit AVANT toute mesure.** · **Fichier NEUF, commité une fois.**
**Remplace** : `2fb952b` (`2026-10-28-placebo-reseau-et-paires.md`), qui **reste
au dépôt** et dont **tout le reste est repris à l'identique** : les trois
schémas, la population, la graine, les seuils, les cinq prédictions, les limites
et le refus d'antériorité.

## ⛔ Pourquoi une v2 : une clause de VALIDITÉ impossible par construction

La v1 engageait, pour vérifier que le regroupement avait bien agi :

```
abs(instants_distincts_placebo_apparie - instants_distincts_reel) < 1
```

**Elle ne peut pas être tenue.** Le placebo apparié tire **une heure pleine par
groupe `(paire, barre)`**, parmi ≈ 351 heures disponibles, pour ≈ 343 groupes par
paire. Les **collisions** sont inévitables — problème des anniversaires :

```
instants distincts attendus = 351 x (1 - exp(-343/351)) x 7  ~  1 533
instants distincts du reel                                   =  2 403
ecart attendu ~ 870,  la clause exige < 1
```

🔴 **Conséquence si je l'avais lancée** : `or-verdict` aurait **ARRÊTÉ** le banc
sur une clause de validité violée — comportement correct de l'outil, sur **un
défaut de ma pré-inscription**, pas de la donnée.

🔑 **Et le fond du défaut** : « autant d'instants distincts » ne mesure pas ce
que je voulais vérifier. Deux setups d'un même groupe peuvent partager leur
instant (ce que je veux) sans que le **nombre** d'instants distincts soit
conservé (ce que les collisions interdisent). **J'ai confondu la propriété avec
une de ses conséquences — qui n'en est pas une.**

✅ **Attrapé avant toute exécution**, par le contrôle d'arithmétique désormais
systématique. C'est la **deuxième fois dans la journée** qu'il sauve une mesure,
et la **cinquième** de la série.

## L'instrument corrigé

```
groupes_respectes_pct > 99
```

**`groupes_respectes_pct`** = part des groupes `(paire, barre)` dont **tous** les
setups ont reçu **le même** instant tiré, dans le schéma décisif.

- Vaut **100 %** si et seulement si le regroupement a agi — c'est **exactement**
  la propriété voulue, et non une conséquence supposée.
- Vaut ≈ **0 %** sur `UNIFORME` et `RESEAU` pour les 1 877 groupes à deux
  setups : l'instrument **discrimine**, il n'est pas décoratif.
- **Amplitude** : [0 ; 100], le seuil de 99 est strictement intérieur, et les
  deux issues sont atteignables.

⚠️ `instants_distincts_reel` et `instants_distincts_placebo_apparie` restent
**mesurés et publiés** — ils documentent les collisions, qui sont un fait de
structure intéressant. Ils ne sont simplement **plus une condition de validité**.

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
remplace: 2026-10-28-placebo-reseau-et-paires.md
validite: n_reel >= 3500 ET couverture_bougies_pct > 99 ET part_entrees_reseau_pct > 99 ET part_placebo_reseau_pct > 99 ET groupes_respectes_pct > 99 ET tirages_aboutis >= 190
admission: ecart_signal_reseau_et_paires > 0 ET t_contre_placebo_reseau_et_paires > 2.00 ET tirages_battus_pct_reseau_et_paires >= 95.0
rejet: abs(t_contre_placebo_reseau_et_paires) < 2.00
P1_ecart_reseau_max: 0.0874
P2_ecart_reseau_et_paires_max: 0.0874
P3_ecart_reseau_et_paires_min: 0.0
P4_t_reseau_et_paires_min: 2.00
P5_ecart_reseau_et_paires_plancher: 0.029
-->

## Ce qui est repris sans changement de la v1

- **Les trois asymétries** qui motivent le banc : réseau horaire dur (**100 %**
  des barres à `:00`), appariement vérifié (**1 877 duos de sens opposés sur
  1 877**, 2 403 instants pour 4 280 setups), et donc `n` réel = **2 403
  instants**.
- **L'échelle** : `UNIFORME` (témoin **rejoué**, pas recopié) → `RESEAU`
  (conserve la position dans l'heure) → `RESEAU_ET_PAIRES` (+ l'appariement),
  les trois dans **la même passe**, sur **les mêmes bougies**.
- **Le tirage parmi TOUTES les heures pleines** de l'étendue, jamais parmi les
  heures où le détecteur a tiré — sinon l'écart serait ≈ 0 par construction.
- **Les cinq prédictions**, estimation ponctuelle **≈ +0,040 R**, `P5` nommée
  comme la plus fragile.
- **Les conséquences de chaque issue**, dont : un `rejet` me fait **RETIRER la
  réplication du `5min`**, et aucun horizon n'aurait alors d'information
  démontrée à l'entrée. **Rétractation, pas nuance.**
- **Les limites** : hors échantillon seulement, asymétrie résiduelle des prix
  d'époque, pas de placebo par blocs, trois cellules et aucune autre.
- **Le refus d'antériorité** du banc partagé, dit en clair, skill non modifiée.
