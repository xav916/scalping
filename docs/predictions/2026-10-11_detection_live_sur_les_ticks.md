# La détection de motifs EN LIVE sur les ticks, et non sur des bougies closes

**Déclaré le 2026-10-11, AVANT d'écrire la mesure.** Décision de Xavier,
répétée après que je l'aie contestée : « la détection de pattern doit être
faite en live sur les tics et pas sur les bougies. »

⚠️ **C'est sa décision, prise CONTRE ma mesure**, et elle est consignée comme
telle. Ce que ma mesure dit : 5 zéros indépendants sur la direction, dont
**0 cellule sur 16** obtenue au tick la même journée.

## 🔑 CE QUE « EN LIVE SUR LES TICKS » VEUT DIRE, précisément

Deux lectures très différentes, et je choisis celle qui correspond à sa phrase :

**(a) Des signaux natifs du tick** — vitesse, accélération, tick rate,
déséquilibre. ⛔ **Déjà mesuré le jour même : 0 retenu sur 16.** Ce n'est pas
ce que ce banc refait.

**(b) Les MÊMES 17 détecteurs, mais évalués EN CONTINU** sur des bougies
reconstruites à partir du flux de ticks, au lieu d'attendre la clôture de la
bougie M5. ⇒ **C'est ça.** Et ce n'est pas un détail de forme : aujourd'hui un
motif n'est confirmé qu'à la **clôture** de sa bougie, donc avec **jusqu'à
5 minutes de retard**. En live, il est vu **à l'instant où il se forme**.

🔑 Reformulé : ce banc ne change ni les motifs ni les données. Il change **le
MOMENT où on regarde**. C'est exactement ce que Xavier reproche à l'existant,
et c'est mesurable.

## ⛔ LE PIÈGE QUE CELA INTRODUIT, dit d'avance

Un motif sur une bougie **non close** peut apparaître puis **disparaître** dans
la même bougie — le prix repasse, et la figure se défait. C'est le
**repeignage** (*repainting*), et le dépôt en porte déjà la leçon : « une
bougie en cours ferait changer d'avis à chaque cycle ».

⇒ Je mesure donc **deux variantes** du live :

- **LIVE BRUT** : on entre dès que le motif apparaît, sans condition ;
- **LIVE CONFIRMÉ** : le motif doit **tenir 30 secondes** avant qu'on entre.

Et le témoin est la **détection CLOSE**, celle de la production : le motif
n'est pris qu'à la clôture de la bougie M5.

## Les données et le protocole

**3 298 970 ticks** du courtier, 15 jours (2026-09-21 → 2026-10-09),
horodatage validé sur une ancre d'exécution réelle. Les bougies M5 sont
**reconstruites depuis les ticks** (la dernière est partielle, de sa frontière
de 5 min jusqu'à l'instant courant), et on appelle **la vraie fonction de
production** `detect_patterns` — pas une réimplémentation.

Cadence d'évaluation : **toutes les 5 secondes**, la cadence réelle du cycle de
production. Repos de 5 minutes par motif pour ne pas compter dix fois le même
épisode.

Issue mesurée sous **deux géométries** : la production (départ −13 €, traînage
0,50 €, aucun objectif, protection à 60 s) et des **bornes symétriques ±2 €**
pour que la géométrie ne bâillonne pas le signal.

## Les contrôles

1. **le MAUVAIS sens aux mêmes instants** — apparié, la dérive s'annule ;
2. **le témoin CLOSE** — mêmes motifs, mêmes ticks, seul le moment change ;
3. **l'unité est le JOUR** (15 jours), pas le tick.

## ⛔ LE CRITÈRE, POSÉ AVANT DE REGARDER

Le live est déclaré meilleur que la détection close si, sur au moins une
géométrie : son écart `bon sens − mauvais sens` est **supérieur** à celui du
témoin close, avec un **|t| > 2,5** sur l'écart par jour et un **signe stable
sur les deux moitiés**.

## MA PRÉDICTION, POSÉE MAINTENANT

1. ⛔ **Le live ne battra pas la détection close.** Motif : les détecteurs
   lisent au plus 31 bougies M5, soit 2 h 35 d'histoire — avancer de 0 à 5
   minutes le moment de la décision ne change pas une figure qui s'appuie sur
   2 h 35. Je prédis |t| < 2,5.
2. ⚠️ **Le LIVE BRUT produira BEAUCOUP plus d'entrées** que le close (je dirais
   5 à 20 fois), et c'est le repeignage : la plupart seront des figures qui se
   défont. Le LIVE CONFIRMÉ devrait en retirer la majorité.
3. ⚠️ Et je prédis que **le LIVE BRUT sera le PIRE des trois** en euros par
   trade, précisément à cause de ces figures qui se défont.
4. ✅ Je prédis en revanche que **le live verra des motifs que le close rate
   entièrement** — des figures formées et défaites à l'intérieur d'une bougie,
   invisibles à la clôture. C'est le seul point où Xavier a mécaniquement
   raison, quoi qu'en dise le P&L.

⇒ Si le live bat le close avec les trois conditions, j'ai tort sur le moment de
la décision, et l'entrée doit passer aux ticks.


---

# VERDICT — 2026-10-11

`scripts/banc_detection_live_ticks.py`. **3 298 970 ticks**, 15 jours,
**4 116 bougies M5 reconstruites depuis les ticks**, **228 413 instants
d'évaluation** (toutes les 5 s).

| vue | n | bon sens | mauvais | écart | t |
|---|---|---|---|---|---|
| **CLOSE** production (la prod) | 6 909 | **+0,0550** | +0,0297 | **+0,0300** | +0,59 |
| CLOSE symétrique | 6 909 | −0,0767 | −0,0779 | +0,0089 | +0,13 |
| **LIVE BRUT** production | **14 739** | +0,0276 | +0,0249 | +0,0079 | +0,26 |
| LIVE BRUT symétrique | 14 739 | −0,0698 | −0,0986 | +0,0357 | +0,71 |
| **LIVE CONFIRMÉ** production | 10 324 | +0,0163 | +0,0014 | +0,0185 | +0,36 |
| LIVE CONFIRMÉ symétrique | 10 324 | −0,0864 | −0,0800 | +0,0035 | +0,05 |

## ⇒ 0 VUE RETENUE SUR 4. Tous les |t| ≤ 0,71.

## ✅ CE QUE XAVIER AVAIT RAISON DE DIRE

**Le live voit 2,13 fois plus de motifs** : 14 739 contre 6 909. Il y a donc
bien **7 830 détections que la clôture rate entièrement** — des figures formées
et défaites à l'intérieur d'une bougie. Sa critique de l'existant était
**mécaniquement juste**.

## ⛔ ET CE QUE LA MESURE AJOUTE

**Aucune de ces détections supplémentaires ne porte de direction.** L'écart
`bon sens − mauvais sens` ne bouge pas : **+0,0079** en live brut contre
**+0,0300** à la clôture, et les deux sont indistinguables de zéro (t +0,26 et
+0,59).

🔑 **La latence de la bougie n'est donc pas le problème.** Le problème est
qu'il n'y a pas de direction à capturer — **ni tôt, ni tard**. Voir le motif
cinq minutes plus tôt ne sert à rien quand le motif ne dit rien.

⚠️ Et sur ces 15 jours, **la clôture a le MEILLEUR écart** (+0,0300) : attendre
n'est pas un handicap mesurable, c'est même légèrement mieux. Mais t = +0,59,
donc ce n'est pas établi non plus — je ne le présente pas comme un argument
pour la clôture.

## MES QUATRE PRÉDICTIONS

1. ✅ « le live ne battra pas le close » : **juste** (0 sur 4).
2. ⛔ « le LIVE BRUT produira 5 à 20 fois plus d'entrées » : **FAUX**. C'est
   **×2,13**, et le confirmé ×1,49. Le repeignage est réel mais **bien plus
   faible** que je l'annonçais.
3. ⛔ « le LIVE BRUT sera le pire en euros » : **faux** aussi. L'ordre est
   CLOSE (+0,0550) > LIVE BRUT (+0,0276) > **LIVE CONFIRMÉ (+0,0163)** — c'est
   la version *confirmée* qui est la plus basse, pas la brute.
4. ✅ « le live verra des motifs que le close rate » : **juste**, 7 830 de plus.

⇒ **Sixième zéro indépendant sur la direction**, et le premier qui porte sur le
**MOMENT de la décision** plutôt que sur l'échelle ou la géométrie. La question
est close : ni les motifs, ni l'échelle, ni l'instant ne portent de direction.
