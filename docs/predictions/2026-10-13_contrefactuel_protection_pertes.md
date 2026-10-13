# Ce que la protection des pertes a VRAIMENT évité, sur les trades RÉELS

**Déclaré le 2026-10-13, AVANT d'écrire la mesure.**

Xavier voulait « désactiver la protection de perte en positif ». Cette
formulation ne correspond à rien : la protection **refuse** d'agir sur un
trade en profit (`eligible()` → `False — en profit ou à l'équilibre`).
Interrogé, il a répondu **sans préférence**, donc je tranche : **on ne la
désactive pas**, et je remplace le chiffre approximatif que je lui ai donné
par une mesure.

## ⛔ CE QUE JE DOIS CORRIGER

Je lui ai dit : « les 57 stops ont coûté −102 € là où leur largeur initiale
valait −744 €, donc la protection a évité 642 € ». **C'est un majorant, pas un
contrefactuel** — je l'ai signalé, mais un majorant présenté à côté d'une
conclusion se retient comme la conclusion. Sans protection, une partie de ces
trades serait **repartie en gain** au lieu d'aller au stop plein.

## Ce qu'on mesure

🔑 **Sur les ENTRÉES RÉELLES du 12/10**, pas des entrées synthétiques : on
reprend l'instant, le sens et le prix d'exécution de chacun des 165 trades
automatiques, et on rejoue chaque trade **deux fois** sur les ticks réels :

| | |
|---|---|
| **A** | avec la protection des pertes, telle qu'armée (fenêtre 60 s, négativité 30 s consécutives, point milieu, plancher 2 × spread, plafond 9 €) |
| **B** | sans elle — le stop initial ne bouge plus jamais côté perte |

Les deux gardent le traînage côté gain, puisque c'est l'état d'hier. Contrôle
**apparié** : mêmes instants, mêmes ticks, même coût réel (+10 pts de markup).

## ⛔ LE CRITÈRE

Il n'y a rien à « retenir » ici : c'est une **description**. Mais je fixe
d'avance ce qui me ferait changer d'avis sur la recommandation :

- si `B − A` est **positif** avec `t > +2`, alors **la protection coûte** et
  la recommandation de la garder serait fausse ;
- si `B − A` est négatif avec `t < −2`, la protection **gagne** ;
- entre les deux, elle est **indécidable sur un jour** et je le dirai.

## MES PRÉDICTIONS, posées avant de coder

1. 🔑 **Le vrai montant évité sera BEAUCOUP plus petit que 744 €.** Je prédis
   entre **100 et 400 €** sur la journée. C'est la prédiction qui corrige mon
   propre chiffre.
2. ✅ **La protection gagnera quand même**, `t < −2` sur `B − A`. Raison : la
   mesure du 12/10 dit que **tous les perdants sont des stops** et que le
   stop plein vaut 13 € contre une perte médiane de 1,66 € constatée.
3. ⚠️ **Mais la RÉUSSITE sera MEILLEURE sans protection** — je prédis au moins
   **+5 points**. Un stop large laisse des trades revenir. C'est le
   compromis : moins de trades perdants, mais ceux qui perdent coûtent 8× plus.
4. ⛔ **Et un jour ne suffira pas à trancher une politique.** Je l'écris
   d'avance : 165 trades sur une seule journée, avec 91 % de la perte sur
   3 trades, ne fondent pas une décision durable. Si je trouve `t = −3`, ce
   sera un `t` d'une journée.
