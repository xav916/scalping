# VERDICT — ce que la protection des pertes a vraiment fait le 12/10

**Pré-inscrit le 2026-10-13 (`6bcc600`), AVANT le code. Mesuré le 2026-10-25.**

Rejeu apparié des **165 trades automatiques réels** du 12/10 sur les
**180 041 ticks** de la journée, avec les modules de production **importés**
(`protection_perte_or`, `echelle_stop_or`) et non réimplémentés.

| | |
|---|---|
| **A** | la protection telle qu'armée : fenêtre 60 s, négativité 30 s, point milieu, plancher `k=2 × spread`, plafond 9 € |
| **B** | sans elle — le stop initial ne bouge plus jamais côté perte |

Les deux gardent le traînage côté gain (0,50 € fixe, l'état du 12/10 :
`59a93b3` livrait l'indexation au spread **désarmée**).

## ✅ LE REJEU EST VALIDÉ — il reproduit la journée sur TROIS cibles

```
              total A    SL/TRAILING   reussite
reel           -38,05      57 / 108      65,5 %
rejeu          -38,26      57 / 108      65,5 %
```

⚠️ **Au prix d'un paramètre calibré** : il faut un coût aller-retour de
**30 points** (0,30 USD) pour y arriver, là où le markup mesuré le 12/10
valait **10 points**. Lecture la plus simple : les 10 points sont un écart
**par côté** sur le spread, donc 20 à l'aller-retour, plus le reste.
🔑 Un seul paramètre libre qui aligne **simultanément** le total, le mix de
sorties et la réussite : c'est trois contraintes pour un degré de liberté.

## ⇒ LE VERDICT, selon le critère pré-inscrit

```
B - A  =  +23,03 EUR sur la journee
apparie : moyenne +0,1396 EUR/trade, ecart-type 2,7438, t = +0,65
=> |t| <= 2  ->  INDECIDABLE SUR UN JOUR
```

**Et la branche « indécidable » était pré-inscrite comme telle.** Le critère
disait : `t > +2` ⇒ la protection coûte ; `t < −2` ⇒ elle gagne ; entre les
deux ⇒ indécidable, « et je le dirai ».

🔑 **Mais le SIGNE est stable sur toute la plage de coût testée** :

```
markup   B - A      t      reussite B - A
0,10    +11,74    +0,34        +17,6 pt
0,20    +22,16    +0,63        +18,8 pt
0,30    +23,03    +0,65        +17,0 pt
```

⇒ **La conclusion ne dépend pas de la calibration** : sur cette journée, la
protection **a coûté** de l'argent plutôt que d'en sauver, sans que l'écart
soit significatif.

## ⛔ CE QUE JE DOIS CORRIGER, ET C'ÉTAIT L'OBJET DE LA PRÉ-INSCRIPTION

Le 13/10 j'ai dit à Xavier : « les 57 stops ont coûté −102 € là où leur largeur
initiale valait −744 €, donc la protection a évité 642 € ». Je l'avais signalé
comme un **majorant**.

🔴 **Il était pire qu'un majorant : il avait le mauvais SIGNE.** Sans
protection, la journée faisait **−15,24 €** au lieu de **−38,26 €**.

La raison tient en une phrase : un stop resserré au point milieu se retrouve
**collé au cours**, et le bruit le déclenche. Le majorant comptait les pertes
évitées sans compter **les trades qui seraient repartis en gain**.

## ✅ ET UNE MESURE DESCRIPTIVE, SANS AUCUN REJEU

Lue directement dans `personal_trades` :

```
164 des 165 stops ont ete DEPLACES en realite (dont les 57 qui ont fini sur SL)
les 57 sorties SL : -1,791 EUR/trade  pour une largeur initiale de 13,07 EUR
les 108 TRAILING_SL : +0,593 EUR/trade
```

La protection resserrait donc bel et bien, sur quasiment chaque trade. Ce n'est
pas son action qui manquait — c'est son **effet net** qui est négatif ici.

## MES PRÉDICTIONS : 2 SUR 4

1. ⛔ **FAUSSE** — « entre 100 et 400 € évités ». Elle a **coûté ~23 €**.
   C'était la prédiction censée corriger mon propre chiffre : elle le corrige
   dans le mauvais sens.
2. ⛔ **FAUSSE** — « la protection gagnera, `t < −2` ». Signe opposé, sur les
   trois niveaux de coût.
3. ✅ **JUSTE, et largement** — « la réussite sera meilleure sans protection,
   au moins +5 points » : **+17,0 points** (65,5 % contre 82,4 %).
4. ✅ **JUSTE** — « un jour ne suffira pas à trancher une politique » :
   `t = +0,65`.

## ⚠️ LES RÉSERVES, et elles sont sérieuses

- **Un seul jour, 165 trades, et 91 % de la perte sur 3 trades.** Pré-inscrit
  comme insuffisant pour une politique, et ça n'a pas changé.
- **Le coût aller-retour est calibré**, pas mesuré indépendamment. Le markup
  de 10 points mérite d'être re-mesuré **par côté**.
- **Les paliers du traînage** sont ceux d'aujourd'hui ; je n'ai pas retrouvé
  leur valeur du 12/10.
- ⛔ **Aucune recommandation de désarmement.** `t = +0,65` ne justifie pas de
  toucher à un garde-fou. Ce verdict dit que mon chiffre de 642 € était faux,
  pas que la protection doit tomber.

## ⇒ CE QUI DEVRAIT SUIVRE

Rejouer **plusieurs jours**. Le banc est paramétrique (`BANC_MARKUP_USD`, la
date en constante) et tourne en ~2 minutes par journée — mais le magasin de
ticks est **gelé au 16/10** depuis la panne du pont, donc la fenêtre
disponible va du **21/09 au 16/10**.

Cf. [[project_pont_mt5_mort_9_jours_2026_10_25]].
