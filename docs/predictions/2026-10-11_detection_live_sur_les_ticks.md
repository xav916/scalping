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
