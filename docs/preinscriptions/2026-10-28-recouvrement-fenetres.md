# Pré-inscription — le RECOUVREMENT des fenêtres, et ce qu'il fait au `t`

**Date** : 2026-10-28 · **Écrit AVANT la mesure.**
**Origine** : limite nommée dans `c5c68dc`. Fenêtres de **96 h** sur des barres
de **5 min** ⇒ deux setups consécutifs se recouvrent presque entièrement. J'ai
écrit que « le `t` surestime la certitude » **sans l'avoir mesuré**.

## ⚠️ Ce que j'ai dit de travers, et que cette mesure doit trancher

J'ai présenté le recouvrement comme une menace directe sur le `t`. **C'est au
mieux imprécis.** Le `t` de ces bancs n'est pas un `t` de Student sur `n`
observations indépendantes : c'est
`t = (réel − moyenne(200 tirages)) / écart-type(200 tirages)`.
Chaque tirage est une moyenne sur **les mêmes** `n` setups, avec **les mêmes**
fenêtres qui se recouvrent. ⇒ **La dispersion entre tirages absorbe déjà la
corrélation induite par le recouvrement**, du moins celle que le schéma de
tirage préserve.

🔑 **La vraie menace est donc ailleurs** : le placebo tire `uniform(min, max)`
par paire (lu dans `scripts/banc_esperance_horizon.py`). Il conserve les paires,
leur nombre, la période, le `risk_pct`, le sens et la fenêtre — mais **il
détruit le REGROUPEMENT TEMPOREL** des entrées réelles. Si le réel est plus
aggloméré que l'uniforme, sa variabilité propre est **plus grande** que celle du
placebo, et **là** le `t` est optimiste.

⛔ **Le recouvrement MOYEN ne peut pas trancher** : la concurrence moyenne vaut
`n × fenêtre / étendue` **quelle que soit la disposition** des instants. Il faut
une statistique de **paires**, pas de moyenne — d'où le choix ci-dessous.

## Ce qui est mesuré

Pour chaque population, par paire, sur les seuls instants (aucune bougie) :

- **`recouvrement_moyen`** — pour chaque setup, le nombre d'**autres** setups de
  la même paire dont la fenêtre croise la sienne (`|tᵢ − tⱼ| < 96 h`), moyenné.
  C'est la mesure de dépendance **de chaque observation**, et elle **monte**
  quand les instants s'agglomèrent.
- **`ratio_somme_sur_union`** — `n × 96 h` divisé par l'union réelle des
  fenêtres : le facteur de redondance brut.
- **`n_eff_naif`** — `union / 96 h` : le nombre de créneaux de fenêtre
  réellement distincts. ⛔ **À ne pas lire comme un `n` effectif statistique** :
  c'est une borne géométrique, pas un calcul de variance.
- **`blocs_effectifs`** — le nombre **effectif** de blocs de 96 h occupés
  (Herfindahl, moyenné sur 4 origines de découpage) : **la variable de
  décision**, voir la correction ci-dessous.
- **`ecart_median_s`** — l'écart médian entre entrées consécutives.
- **Les mêmes statistiques sur le placebo** : 20 tirages avec **exactement** le
  schéma du banc (`random.Random(20261027)`, `uniform(min, max)` par paire),
  d'où `ratio_reel_sur_placebo` et un `t` de structure.

## ⚠️ DIVULGATION : je peux estimer l'essentiel avant de mesurer

Hors échantillon : 4 280 setups, 7 paires ⇒ ≈ 611 par paire, étendue ≈ 336 h.

```
recouvrement_moyen  ~  611 x (2 x 96) / 336  ~  350   (moins les bords)
somme               =  4 280 x 96  =  410 880 h
union               <= 7 x (336 + 96)  =  3 024 h   =>  ratio >= 136
n_eff_naif          =  3 024 / 96  ~  31
```

En échantillon : 18 668 setups sur ≈ 1 632 h ⇒ recouvrement ≈ **310**, et
`n_eff_naif` ≈ 180 pour 10 paires (plus s'il y a plus de paires forex).

## 🔑 L'ARITHMÉTIQUE DU SEUIL, faite AVANT de l'engager

Trois fois j'ai engagé un seuil **impossible par construction**. Donc, cette
fois, le calcul d'abord. Sous un modèle de corrélation échangeable, le facteur
d'inflation de variance vaut `1 + c·ρ` avec `c` le recouvrement moyen. Un excès
de regroupement d'un facteur `k` porte le rapport des écarts-types à
`√((1 + k·c·ρ)/(1 + c·ρ))`, qui tend vers **`√k`** quand `c·ρ` est grand :

| excès `k` | `t` hors éch. 4,32 devient | `t` en éch. 6,28 devient |
|---|---|---|
| 1,2 | 3,94 | 5,73 |
| 2,0 | **3,05** | **4,44** |
| 4,0 | **2,16** | **3,14** |
| 9,0 | **1,44** | **2,09** |

⇒ **Un seuil à 1,20 serait décoratif** : il « échouerait » sans que la
conclusion bouge. Le seuil qui **mord** est à **2,00** — au-delà, la marge
commence à se consommer sérieusement, et à 4,0 le hors échantillon frôle la
barre de 2. **C'est donc 2,00 que j'engage.**

⚠️ Ce calcul suppose une corrélation échangeable et un `c·ρ` grand : c'est une
approximation, pas une identité. Elle fixe l'**ordre de grandeur** du seuil, et
c'est tout ce que je lui demande.

## ⛔ CORRECTION, AVANT TOUTE MESURE : mon seuil était infalsifiable

**Écrit le même jour, après avoir codé le banc et AVANT de l'exécuter.**

J'ai vérifié l'arithmétique du seuil mais **pas l'amplitude de la statistique
sur laquelle je le posais**. Le rapport des recouvrements **SATURE** dans ce
régime :

```
n/paire = 611, etendue = 336 h, fenetre = 96 h
tirage UNIFORME     ~ 299,3 croisements par setup
plafond (tout colle) = 610
=> RATIO MAXIMUM ATTEIGNABLE = 2,038
```

🔴 **Mon seuil engagé valait 2,00 pour un maximum atteignable de 2,038.**
`P5 < 2,00` n'aurait pu être violée que par une agglomération quasi totale :
c'est **le quatrième seuil impossible par construction**, cette fois dans
l'autre sens — non pas impossible à tenir, mais impossible à **enfreindre**.

✅ **Cette fois il a été attrapé AVANT la mesure**, et pas par relecture : par
un test qui sondait le comportement de la statistique sur une agglomération
fabriquée, et qui a rendu `×1,18` là où j'attendais `> 1,5`.

### Ce qui change, et pourquoi c'est légitime

La **décision** passe sur le **nombre effectif de blocs** de 96 h occupés
(Herfindahl `(Σnᵦ)²/Σnᵦ²`, moyenné sur 4 origines de découpage) :

```
ratio_blocs = blocs_effectifs(UNIFORME) / blocs_effectifs(REEL)
```

| | plancher | uniforme | plafond du rapport |
|---|---|---|---|
| hors éch. (7 paires, 3,5 blocs/paire) | 7 | ≈ 24,5 | **≈ 3,5** |
| en éch. (≈ 17 blocs/paire) | n paires | ≈ 17 × n | **≈ 17** |

⇒ **Le seuil de 2,00 vit désormais bien à l'intérieur de l'amplitude**, et son
sens est direct : « le réel occupe-t-il moins de la moitié des unités
indépendantes que l'uniforme occupe ? ». La table de `√k` ci-dessus s'y
applique telle quelle, `k` étant la perte de blocs.

⛔ **Le recouvrement reste mesuré et publié** — c'est la question posée, et
c'est lui qui dit l'ampleur du problème. Il n'est simplement **plus
décisionnel**. Et le banc **publie désormais le MAXIMUM ATTEIGNABLE de chaque
rapport**, pour que ce défaut ne puisse pas se reproduire en silence.

<!-- CRITERE-MACHINE
statistique: recouvrement_temporel_des_fenetres
forme: placebo
horizon: 5min
fenetre_heures: 96
population: resolved_backfill=0 AND timeframe=5min AND pair IN 7_BINANCE AND bar_timestamp < 2026-08-20
population_secondaire: resolved_backfill=1 AND timeframe=5min
tirages_placebo: 20
graine: 20261027
cellules: 1
validite: n >= 4000 ET n_secondaire >= 15000 ET paires >= 5 ET tirages_aboutis >= 20
admission: ratio_blocs_placebo_sur_reel < 2.00 ET ratio_blocs_placebo_sur_reel_secondaire < 2.00
rejet: ratio_blocs_placebo_sur_reel >= 2.00
P1_recouvrement_moyen_min: 150
P2_ratio_somme_sur_union_min: 40
P3_n_eff_naif_max: 400
P4_ratio_blocs_min: 1.00
P5_ratio_blocs_max: 2.00
-->

⚠️ **Correspondance des noms** : `admission` = **le placebo reproduit la
dépendance du réel**, donc les `t` publiés (+6,28 et +4,32) **tiennent comme
statistiques de randomisation**. `rejet` = **la structure diffère trop**, et une
réplication ne peut être revendiquée qu'après un **placebo par BLOCS**.

⛔ **Le `t` de structure n'est PAS la variable de décision**, et c'est délibéré :
sur 20 tirages d'une statistique très concentrée, la significativité est **bon
marché** — un excès de 2 % rendrait un `t` énorme sans rien changer. **La
décision porte sur la MAGNITUDE** (`ratio_reel_sur_placebo`). Le `t` est publié
comme description.

## Prédictions, dites d'avance

1. **`recouvrement_moyen ≥ 150`** sur les **deux** populations, attendu ≈ **350**
   (hors éch.) et ≈ **310** (en éch.). ⇒ chaque observation partage sa fenêtre
   avec **des centaines** d'autres.
2. **`ratio_somme_sur_union ≥ 40`**, attendu ≈ **136** hors échantillon.
3. **`n_eff_naif ≤ 400`**, attendu ≈ **31** hors échantillon.
4. **`ratio_blocs > 1,00`** : le réel occupe **moins** d'unités indépendantes
   que l'uniforme — le détecteur ne tire pas ses instants au hasard. Attendu
   ≈ **1,1** (soit ≈ 22 blocs réels contre ≈ 24,5 uniformes hors échantillon).
5. **`ratio_blocs < 2,00`** : et la perte reste **sous la moitié**, pour un
   plafond atteignable de **≈ 3,5** — le seuil est donc réellement
   enfreignable, contrairement à celui que je viens de retirer.

## Ce que chaque issue implique

- **P4 et P5 tenues** ⇒ le réel est aggloméré, mais **pas assez pour renverser
  les `t`** : la limite que j'ai inscrite dans `c5c68dc` est **mesurée et
  bornée**, et la réplication du `5min` tient. ⚠️ Elle ne devient pas « sans
  objet » : le facteur reste à porter dans toute lecture du `t`.
- **P5 violée** (`≥ 2,00`) ⇒ **je retire la réplication** jusqu'à un placebo par
  **blocs** (décalage circulaire par paire, qui préserve exactement le
  regroupement réel). ⛔ Ce serait une rétractation, pas une nuance.
- **P4 violée** (le réel occupe **PLUS** de blocs que l'uniforme) ⇒ le placebo est
  **conservateur**, les `t` sont si quelque chose **sous-estimés**. ⛔ Et je
  devrais expliquer pourquoi un détecteur produit des instants plus réguliers
  que le hasard, ce que je n'attends pas.

## ⚠️ Limites, posées d'avance

- Mesure **purement géométrique** sur les instants : elle ne dit rien de la
  corrélation **réelle** des issues, seulement de la structure qui la porte.
  Le `ρ` du calcul ci-dessus n'est **pas** mesuré.
- Recouvrement calculé **par paire**. Les 7 paires crypto sont fortement
  corrélées entre elles ⇒ la dépendance **inter-paires** est ignorée, donc le
  recouvrement rapporté est un **plancher**.
- Une seule cellule pré-spécifiée ; aucune autre ne sera testée après coup.
