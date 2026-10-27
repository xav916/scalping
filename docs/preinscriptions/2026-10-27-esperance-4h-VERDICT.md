# Verdict — l'espérance de l'horizon `4h` : REJET, mais pour une autre raison que le `1d`

**Pré-inscription** : `5978135` · **Banc** : `b9aa6f7`
(antériorité **prouvée** par `or-preinscription`, code 0)
**5 prédictions sur 5 passent.** Verdict mécanique :
**`REJET_horizon_4h_ECARTE`**.

## Le résultat

```
n = 1775 sur 1775   couverture 100,00 %
controle du moteur vectorise : 1775 / 1775 en accord avec la production

VALIDITE                                                        valide
  n >= 1500 .............................. 1775
  couverture > 99 % ...................... 100,00 %
  risk median reel / placebo ............. 0,3722 % / 0,3722 %
  tirages aboutis >= 190 ................. 200 / 200

ESPERANCES (en R par setup)
  reel (convention A) ....................  −0,2664
  placebo (200 tirages) ..................  −0,2443
  convention B (resolus seuls) ...........  −0,4695
  TIMEOUT seuls ..........................  +0,1730
  cout median ............................  +0,0537

P1  esperance reelle sous le seuil ...  seuil  +0,000   PASSE
P2  |placebo| sous le seuil ..........  seuil  +0,300   PASSE
P3  tirages battus sous le seuil .....  seuil +95,000   PASSE
P4  cout median AU-DESSUS du seuil ...  seuil  +0,040   PASSE
P5  B − A sous le seuil ..............  seuil  −0,050   PASSE

t contre placebo : −0,9840      tirages battus : 13,0 %
```

## 🔑 Ce que ça dit, et c'est DIFFÉRENT du `1d`

| | `1d` (`0b8106b`) | `4h` |
|---|---|---|
| réel | −0,0641 R | **−0,2664 R** |
| placebo | +0,0413 R | **−0,2443 R** |
| écart | −0,105 R | **−0,022 R** |
| `t` | **−4,23** | **−0,98** |
| tirages battus | **0 %** | **13 %** |

⇒ **Le `1d` faisait PIRE que le hasard. Le `4h` est INDISCERNABLE du hasard.**

Les deux sont négatifs, mais la cause diffère : sur le `4h`, le réel et le
placebo perdent **la même chose** (≈ −0,25 R), et cette perte est la **dérive**
d'une population exclusivement acheteuse sur ces 68 jours — exactement ce que
la pré-inscription annonçait. ⇒ **L'instant d'entrée du `4h` ne porte aucune
information**, ni bonne ni mauvaise.

## ⛔ Et mon seuil d'indécidabilité était trop serré

J'avais pré-inscrit `indecidable : abs(esperance_reel − esperance_placebo) <
0,01 ET abs(t) < 2,00`. L'écart mesuré vaut **0,022 R** — au-dessus de 0,01 —
donc la branche `rejet` se déclenche, alors que **« aucune information »
décrirait mieux les faits** (`t = −0,98`, 13 % des tirages battus).

🔑 C'est une limite de **mon critère**, pas de la mesure, et je l'inscris ici
plutôt que de la corriger après coup. Le verdict mécanique engagé est `REJET` ;
la lecture honnête est **indiscernable du hasard**. Les deux figurent dans ce
document, et **je ne réécris pas le seuil pour obtenir l'étiquette qui me
plaît**.

⇒ Pour un prochain horizon, le seuil d'indécidabilité devrait porter sur le
`t`, pas sur un écart absolu en R : à `risk_pct` de 0,37 %, 0,01 R est une
quantité minuscule et le seuil était inopérant par construction.

## 🔴 La conséquence, inscrite d'avance

Le `1d` et le `4h` sont **tous deux écartés**. Il ne reste que le **`5min`
crypto**, mesuré à **+0,0089 R** — et **sans placebo**, donc **non établi**.

⚠️ Autrement dit : à ce jour, **aucun horizon de ce système n'a d'information
démontrée à l'entrée**. Le `5min` est le seul candidat restant, et il attend sa
propre mesure avec contrôle aléatoire.

## Ce que le dispositif a bien fait

- **1 775 / 1 775** d'accord entre le moteur vectorisé et
  `simulate_trade_forward`, règle du pire cas incluse. Sans ce contrôle, les
  355 000 simulations du placebo auraient reposé sur une réimplémentation non
  vérifiée.
- `risk_pct` médian **identique à la 4ᵉ décimale** entre réel et placebo :
  la structure est bien reproduite.
- **Le coût est matériel et prédit** : `0,0537 R > 0,040` (P4), soit 26 fois
  celui du `1d`. Il représente ~20 % de la perte, donc il aggrave sans
  expliquer — la dérive fait le reste.

## ⛔ Deux défauts de ma part sur ce banc

1. **Un `KeyError` au moment d'imprimer a détruit une mesure de douze
   minutes**, parce que le JSON était écrit **après** le rapport. Corrigé
   (`18d70b0`) : le JSON part d'abord, et un test statique compare les clés
   lues par le rapport à celles écrites par la mesure.
2. **La première passe a rendu `REJET_horizon_1d_ECARTE` et un titre
   « horizon 1d » alors qu'elle mesurait le `4h`.** Les chiffres étaient justes,
   l'étiquette mentait — et c'est l'étiquette qui survit dans une fiche. Corrigé
   et relancé, chiffres reproduits à l'identique (graine fixe).

## ✅ `or-verdict` : PUBLIABLE

```
=== PUBLIABLE
  - REJET : toutes les clauses tenues          code 0
```

La skill recalcule les **quatre** clauses de validité et les **deux** branches
contre les champs du résultat, et confirme. Le résultat déclare
`forme: "placebo"`, `horizon: "4h"`, `fenetre_heures: 96`, et le fichier de
critère qu'il a lu — tout est traçable sans croire le banc sur parole.

## ⚠️ « Reproductible » demandait une nuance, et je la pose

La relance (étiquettes corrigées) a reproduit **tout** à l'identique, sauf un
point :

```
esperance_R_placebo   −0,24434551  ->  −0,24433440     (écart 1,1e−5 R)
t                        −0,98398  ->     −0,98447
```

Réel, `n`, couverture, contrôle 1 775/1 775, `risk_pct` médian et tirages
battus : **identiques au bit**.

🔑 **Cause** : les tirages piochent dans une fenêtre dont la borne haute est
`max(barre) + 120 h` — **dans le futur**. Vingt-cinq minutes plus tard, quelques
bougies de plus existent sous cette même borne, donc une poignée de tirages
tombent sur un index différent. **La graine fixe les nombres aléatoires ; elle
ne fixe pas la donnée.**

⚠️ L'écart est de **0,004 %** sur la moyenne du placebo et ne déplace aucune
décision. Je le signale parce que « reproductible » doit vouloir dire quelque
chose de précis : ce banc est reproductible **pour un instantané de donnée
donné**, pas à travers le temps. Un prochain banc devrait **borner le
chargement à la date de la pré-inscription** plutôt qu'à une échéance future.

## Ce que ce verdict ne dit pas

- **Population exclusivement ACHETEUSE** : rien sur le sens vendeur.
- Donnée **rattrapée**, un seul régime de marché sur ~68 jours.
- Une seule cellule pré-spécifiée ; **aucune autre ne sera testée après coup
  sur cette donnée.**
- Rien sur le `5min`, le `1d`, ni les paires du pont (XAU, WTI), absentes de
  cette population.
