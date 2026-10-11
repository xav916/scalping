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


---

# VERDICT — 2026-10-11

`scripts/banc_regle_xavier_9eur.py`. 6 668 trades aveugles, 99 999 bougies M1
du courtier, six strategies en parallele, palier arme sur la cloture.

| | EUR/trade | ecart-type | pire journee | reussite | duree |
|---|---|---|---|---|---|
| **X sa regle (TP fixe)** | −0,0844 | 2,44 | **−1,43** | 55,74 % | 5,7 min |
| **X+ sa regle, TP MOBILE** | **−0,0287** | 2,54 | −1,30 | 55,58 % | 6,1 min |
| A1 la production | −0,0677 | 5,84 | −4,03 | 92,19 % | 28,9 min |
| A2 production + protection | −0,0247 | 2,99 | −2,15 | 72,89 % | 8,5 min |
| B2 stop −2 | −0,0714 | 2,00 | **−0,12** | 49,75 % | 5,3 min |
| T temoin | −0,1479 | 6,44 | −3,56 | 90,45 % | 36,4 min |

Issues de sa regle : TP 2 660, PROTECTION 1 617, POINT MORT 1 261, ECHELLE
1 057, **SL de depart 72** (contre 516 pour la production).
🔑 Son stop de depart a −9 € n'est touche que **1,1 % du temps** : la
protection le ramene avant.

## ⇒ EST-CE PLUS VIABLE ? OUI SUR LE RISQUE, NON SUR LE RENDEMENT

    contre la production (A1)   ecart -0,1023 EUR/jour   t **-1,06**   signe INVERSE
    contre A2                   ecart -0,0386            t **-1,00**   stable
    contre B2 (stop -2)         ecart -0,0210            t **-0,60**   signe INVERSE
    contre le temoin            ecart -0,0431            t **-0,44**   stable

⇒ **Aucun ecart de rendement n'est etabli** : ma prediction 1 tient.
✅ Mais sur la queue, c'est net : **ecart-type 5,84 → 2,44 (÷2,4)** et **pire
journee −4,03 → −1,43 €** contre la production.

## 🔑 LE SEUL RESULTAT SIGNIFICATIF DE LA JOURNEE : GARDEZ L'OBJECTIF MOBILE

    sa regle a TP FIXE  contre  la meme a TP MOBILE
    ecart **-0,0563 EUR/trade**   **t = -8,18**   signe STABLE   ***

Sa description ne mentionnait pas d'objectif mobile ; le code, lui, releve le
TP a `palier + 2 €`. **Le garder vaut 0,0563 € par trade**, et c'est le `t` le
plus franc de tous les bancs du jour.

⇒ Avec l'objectif mobile, sa regle passe de **−0,0844 a −0,0287 EUR/trade** —
soit la **meilleure des six**, a egalite avec A2 (−0,0247).

## MES PREDICTIONS

1. ✅ « aucun |t| > 2,5 contre A1, A2 ou B2 » : **juste** (−1,06 / −1,00 / −0,60).
2. ⚠️ « pire journee entre −0,3 et −1,2 € » : **presque** — mesuree **−1,43 €**,
   donc hors de ma bande, et je le dis plutot que d'arrondir.
3. ⚠️ « tres proche de B2 » : juste sur l'ecart-type (2,44 contre 2,00),
   **faux sur la queue** — la pire journee de B2 est **12 fois** meilleure
   (−0,12 contre −1,43).
4. ✅ « son TP fixe fera moins bien que le TP mobile » : **juste, et c'est le
   resultat le plus solide du banc**.

## ⚠️ LA LIMITE, inchangee

Duree **5,7 min contre 28,9** pour la production ⇒ **5 fois plus de rotation**,
donc 5 fois plus de spread **si on recycle la place liberee**. Ce banc ne le lui
fait pas payer : les entrees sont fixes.
