# La règle de Xavier : départ à −9 €, plancher à −2 €, échelle qui traîne de 0,50 €

**Déclaré le 2026-10-11, AVANT de mesurer.** Sa question : « est-ce que c'est
plus viable comme méthode ? »

## Sa règle, telle que je la comprends

**Départ** : SL **−9 €** (au lieu de −20 €), TP **+2 €**.

**Côté perte** — la formule du point milieu, comme aujourd'hui :

    nouveau stop = (stop + perte) / 2       … mais jamais plus serré que **−2 €**

**Côté gain** — son échelle, qui traîne de **0,50 €** derrière le profit :

    profit ≥ 0,50 €  →  stop à **0** (point mort)
    profit ≥ 1,00 €  →  stop à **+0,50**
    profit ≥ 1,50 €  →  stop à **+1,00**
    profit ≥ 2,00 €  →  stop à +1,50, mais le TP à 2 € a déjà fermé le trade

⚠️ **Deux points d'interprétation, dits avant de mesurer** — si je me trompe,
c'est ici qu'il faut me corriger :

1. « lorsqu'on sera à −2 €, on arrêtera les réductions » : je le lis comme un
   **plancher sur le STOP** (le stop ne devient jamais plus serré que −2 €), pas
   comme un seuil sur la perte. L'autre lecture serait « ne pas resserrer tant
   que la perte est sous 2 € », ce qui donnerait un dispositif très différent.
2. Il ne parle pas d'**objectif mobile**. Or la production, elle, relève le TP
   à `seuil + 2 €` à chaque palier. Je mesure donc **les deux** : sa règle avec
   un TP **fixe** à 2 € (ce qu'il décrit) et la même avec le TP **mobile** (ce
   que fait le code aujourd'hui).

⛔ **Et une contrainte physique qui s'ajoute à son plancher** : un stop ne peut
jamais être posé du mauvais côté du cours — sinon il ferme la position
immédiatement. Le plancher effectif est donc `max(2 €, perte + 0,10 €)`, le
0,10 étant la marge que la production utilise déjà.

## Les six stratégies, sur les MÊMES trades

6 668 entrées aveugles (une toutes les 30 min, deux sens), **99 999 bougies M1
du courtier** (2026-07-01 → 2026-10-09 20h55), palier armé sur la **clôture**
(la version défendable établie au verdict précédent).

| | SL départ | TP | échelle de gains | protection des pertes |
|---|---|---|---|---|
| **X** sa règle | **−9 €** | 2 € fixe | 0,5:0 / 1:0,5 / 1,5:1 | point milieu, plancher −2 € |
| **X+** sa règle, TP mobile | −9 € | `seuil + 2 €` | idem | idem |
| **A1** la production | −20 € | 2 € puis mobile | 1:0,75 / 1,5:1,25 / 1,75:1,5 / 2:1,75 | **désarmée** |
| **A2** production + protection | −20 € | mobile | idem A1 | plancher `perte + 2 €` |
| **B2** stop serré | −2 € | 2 € | non | non |
| **T** témoin | −20 € | 2 € | non | non |

## ⛔ LE CRITÈRE, POSÉ AVANT DE REGARDER

Sa règle est déclarée **meilleure** qu'une autre si : P&L par trade supérieur,
**|t| > 2,5** sur l'écart par **JOUR**, et **signe stable sur les deux
moitiés** de la période.

⚠️ Et la limite déjà déclarée vaut toujours : les entrées sont **fixes**, donc
ce banc ne fait pas payer à un stop serré les trades supplémentaires qu'il
permettrait. Je publie la **durée** pour que ce coût caché soit visible.

## MA PRÉDICTION, POSÉE MAINTENANT

1. ⛔ **Sa règle ne battra personne en espérance** : aucun |t| > 2,5 contre A1,
   A2 ou B2. Motif : l'arrêt optionnel — déplacer un stop ne change pas
   l'espérance d'une marche, et c'est déjà pourquoi 0 couple sur 120 et 0 délai
   sur 5 ont été retenus aujourd'hui.
2. ✅ **Mais elle sera nettement meilleure que la production (A1) sur la
   queue** : je prédis une pire journée entre **−0,3 et −1,2 €** contre
   **−4,03 €**, et un écart-type autour de **2** contre 5,84.
3. 🔑 Je prédis que **sa règle finira très proche de B2 (stop −2 €)** : son
   plancher à −2 € fait que tout trade resté négatif plus de 5 minutes se
   retrouve avec un stop à −2 €. Son −9 € de départ ne sert qu'aux cinq
   premières minutes.
4. ⚠️ Et je prédis que son **TP fixe** fera **moins bien** que le TP mobile sur
   la moyenne (il plafonne les gains à 2 €) mais **mieux** sur la régularité.

⇒ Donc ma réponse attendue à « est-ce plus viable ? » est : **oui sur le
risque, non sur le rendement** — et je le dirai avec les deux chiffres.
