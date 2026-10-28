# Pré-inscription — l'artefact de prix d'entrée explique-t-il AUSSI le `1d` et le `4h` ?

**Date** : 2026-10-28 · **Écrit AVANT la mesure.** · **Fichier NEUF, commité une fois.**
**Origine** : verdict `644fded`. J'y ai annoncé une échelle
`décalage / risk_pct` **monotone**, sans la tester. Ce banc la teste.

## ⛔ ET ELLE EST DÉJÀ EN DIFFICULTÉ

En rassemblant les chiffres publiés **avant** d'écrire ce critère :

| | `risk_pct` médian | écart publié |
|---|---|---|
| `1d` | 9,3260 % | **−0,1054** |
| `4h` | **0,3722 %** | **−0,0221** |
| `5min` en éch. | **0,5058 %** | **+0,0557** |
| `5min` hors éch. | 0,2106 % | **+0,0874** |

🔴 **Le `4h` a un stop PLUS SERRÉ que le `5min` en échantillon et un écart PLUS
NÉGATIF.** Un classement par `1/risk_pct` prédirait l'inverse. ⇒ **L'échelle
que j'ai annoncée en `644fded` est fausse comme je l'ai écrite** : `risk_pct`
n'était qu'un **substitut** du décalage, et il ne suffit pas.

⇒ Ce banc mesure donc le **décalage réel** par horizon, et pas son substitut.

## 🔑 LA QUANTITÉ DÉCISIVE NE CONTIENT PAS DE PLACEBO

```
artefact = ecart(STOCKE) - ecart(FILL)
         = [esp_reel_STOCKE - esp_placebo] - [esp_reel_FILL - esp_placebo]
         = esp_reel_STOCKE - esp_reel_FILL
```

Le placebo **se simplifie**. Vérifié sur le `5min` hors échantillon :
`−0,059336 − (−0,197829) = +0,138493` contre
`+0,091961 − (−0,046533) = +0,138494`. ✅

⇒ **L'artefact est immune à la dérive du placebo**, ce qui compte ici : les
critères `1d` et `4h` **n'ont pas de `fin_chargement`**, donc leurs placebos
dérivent avec les bougies qui s'ajoutent (mesuré à **1,2 × 10⁻⁵ R** en 25 min
sur le `4h`). Je **pose** une borne pour que ma passe soit reproductible, et
j'accepte en échange une tolérance de reproduction de **2 %** — très au-dessus
de la dérive attendue (~10⁻⁴ R, soit 0,1 % de l'écart du `1d`).

## Ce qui est mesuré, par horizon

Pour `1d` et `4h`, sur **leur propre population et leur propre fenêtre** :

- `esperance_reel_STOCKE` — géométrie d'août, **contrôle de reproduction** ;
- `esperance_reel_FILL` — entrée à l'**ouverture** de sa bougie d'entrée ;
- **`artefact`** = la différence, **sans placebo** ;
- `mediane_decalage_sur_risque` — **la cause**, mesurée et non plus supposée ;
- `part_entree_hors_bougie_pct` — la part de fills inatteignables ;
- les taux `SL` / `TP1` **dès la première bougie**, pour les trois bras ;
- et, avec placebo (200 tirages, schéma `UNIFORME` comme les bancs publiés),
  `ecart_fill` et `t_fill`.

## 🔑 Contrôle d'amplitude, fait AVANT d'engager

- **L'artefact** est une différence d'espérances, non bornée. Mesuré à
  **+0,1385 R** sur le `5min`. Les seuils **0,02** et **−0,02** encadrent zéro
  et sont **tous deux franchissables**.
- **`mediane_decalage_sur_risque`** : mesurée à **0,341** sur le `5min`, elle
  vit dans [0 ; ∞). Le seuil **0,05** pour le `1d` est intérieur, et un
  dépassement est parfaitement possible si mon raisonnement sur `risk_pct` est
  faux — ce que le tableau ci-dessus rend déjà plausible.
- **`t_fill`** n'est pas plafonné.

<!-- CRITERE-MACHINE
statistique: artefact_de_prix_d_entree_par_horizon
convention: A
forme: placebo
cellules_horizon: 1d,4h
placebo_schema: UNIFORME
horizon_1d: 1d
population_1d: resolved_backfill=1 AND timeframe=1d
fenetre_heures_1d: 240
reference_esperance_reel_1d: -0.064062
reference_ecart_1d: -0.105410
horizon_4h: 4h
population_4h: resolved_backfill=1 AND timeframe=4h
fenetre_heures_4h: 96
reference_esperance_reel_4h: -0.266410
reference_ecart_4h: -0.022076
artefact_5min_mesure: 0.138494
decalage_sur_risque_5min_mesure: 0.341
fin_chargement: 2026-10-28T21:00:00+00:00
tirages_placebo: 200
graine: 20261027
cellules: 2
tolerance_reproduction_pct: 2.0
validite: n_reel_1d >= 1000 ET n_reel_4h >= 1500 ET couverture_min_pct > 99 ET ecart_reproduction_max_pct < 2.0 ET part_entree_hors_bougie_fill_max_pct < 0.5 ET tirages_aboutis_min >= 190
admission: artefact_1d < 0.02 ET artefact_4h < 0.138494
rejet: artefact_1d >= 0.02
P1_artefact_1d_max: 0.02
P2_artefact_4h_max: 0.138494
P3_artefact_4h_plancher: 0.0
P4_decalage_sur_risque_1d_max: 0.05
P5_artefact_1d_plancher: -0.02
-->

⚠️ **Correspondance des noms** : `admission` = **l'échelle tient** — l'artefact
est négligeable sur le `1d` et inférieur à celui du `5min` sur le `4h`.
`rejet` = **elle ne tient pas** : le `1d` porte lui aussi un artefact
matériel, et mon explication de la série s'effondre.

## Prédictions, dites d'avance

1. **`artefact(1d) < 0,02 R`** — négligeable : à `risk_pct` 9,33 %, un décalage
   de l'ordre de 0,07 % du prix ne déplace presque aucune barrière.
2. **`artefact(4h) < 0,1385 R`** — inférieur à celui du `5min`.
3. **`artefact(4h) > 0`** — mais **positif** : la spécification stockée
   **favorise** le bras réel, à tous les horizons.
4. **`médiane(|décalage| / risque)(1d) < 0,05`** — 🔑 **la cause, mesurée
   directement**, contre **0,341** au `5min`.
5. **`artefact(1d) > −0,02 R`** — et pas négatif.

⚠️ **Ce que ces prédictions NE couvrent pas** : l'**ordre** `1d < 4h < 5min`
n'est testé qu'en partie (`P1`+`P2`+`P3` l'impliquent, mais sans seuil sur
l'écart `4h`–`5min`). Je ne revendiquerai donc pas « l'échelle est monotone »
sur la seule base de ce banc.

## Ce que chaque issue implique

- **Admission** ⇒ l'artefact est bien **concentré là où le stop est serré
  devant le décalage**, et le retrait du `5min` s'inscrit dans une explication
  **cohérente de toute la série**. ⛔ Sans pour autant rendre le `1d` ou le `4h`
  exploitables : leurs écarts corrigés resteraient **négatifs**.
- **Rejet** (`artefact(1d) ≥ 0,02`) ⇒ ⛔ **l'artefact touche TOUS les horizons**,
  y compris celui dont le stop est 44 fois plus large. Alors ce n'est pas une
  question d'échelle mais un **défaut général de spécification**, et **les trois
  verdicts d'espérance** (`1d`, `4h`, `5min`) devraient être relus, pas
  seulement celui du `5min`.
- ⚠️ **Si `P3` échoue** (artefact `4h` **négatif**), la spécification stockée
  **défavoriserait** le réel sur cet horizon. Je n'ai pas d'explication prête,
  et je le dirais comme tel.
- ⚠️ **Si `P4` échoue** alors que `P1` tient, le décalage relatif du `1d` est
  grand **sans** produire d'artefact — et c'est alors mon modèle de la cause
  qui est faux, pas l'échelle.

## ⚠️ Limites

- **Deux horizons, deux cellules.** Le `5min` **en échantillon** (18 668 lignes,
  `risk_pct` 0,5058 %) n'est **pas** couvert ici, alors que c'est lui qui
  contredit le classement par `1/risk`. ⛔ Lacune assumée : il demanderait une
  troisième cellule et sa propre reproduction.
- `fin_chargement` **posée ici, absente des critères publiés** ⇒ reproduction à
  **2 %**, pas à 0,001 % comme pour le `5min`.
- Les populations `1d` et `4h` sont **rattrapées** (`resolved_backfill=1`), donc
  distinctes de celle du `5min` hors échantillon.
- Antériorité du banc partagé : refus pré-annoncé, skill **non modifiée**.
