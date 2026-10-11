# Stop large + échelle, ou stop serré d'office ? — la question de Xavier

**Déclaré le 2026-10-11, AVANT de mesurer.** Question de Xavier, dans ses
mots : « est-ce qu'il vaut mieux laisser vivre le trade de −20 € et resserrer
par automatisme le stop, comme c'est le cas maintenant, ou est-ce qu'il faut de
base mettre le stop loss à −2 € ou −1 € ? »

## ⓘ CE QUE FAIT LA PRODUCTION AUJOURD'HUI, lu dans le code et dans l'env

Trois dispositifs, et il faut les distinguer :

1. **bornes de départ** : SL **−20 €**, TP **+2 €** ;
2. **échelle de GAINS** (`ECHELLE_STOP_OR=1`, donc **ARMÉE**), paliers lus dans
   l'environnement `1.0:0.75, 1.5:1.25, 1.75:1.5, 2.0:1.75` — au premier
   palier franchi, le stop passe **au-dessus de l'entrée** et l'objectif
   devient **`seuil + 2 €`** (donc 3,00 € à partir de 1,00 € de profit, jusqu'à
   4,00 €). **Cliquet** : jamais de desserrage ;
3. **protection des PERTES** (`protection_perte_or`) : à partir de 5 min
   d'âge, si le trade est négatif depuis au moins 2 min 30, le stop est ramené
   au **point milieu** `(stop + perte)/2`, avec un plancher à `perte + 2 €`.
   ⛔ **Elle est DÉSARMÉE** : `PROTECTION_PERTE_OR` est absent de
   l'environnement, donc il vaut `0`. Je le mesure quand même, pour chiffrer ce
   que l'armer ferait.

## Les six stratégies comparées, sur les MÊMES trades

Mêmes **6 668 entrées aveugles** (une toutes les 30 minutes, deux sens),
**99 999 bougies M1 du courtier** (2026-07-01 → 2026-10-09 20h55), un seul
parcours par trade où les six stratégies avancent **en parallèle** avec leur
propre état.

| | SL de départ | TP | échelle de gains | protection des pertes |
|---|---|---|---|---|
| **T** témoin | −20 € | 2 € | non | non |
| **A1** la production | −20 € | 2 € | **oui** | non |
| **A2** | −20 € | 2 € | **oui** | **oui** |
| **B1** | **−1 €** | 2 € | non | non |
| **B2** | **−2 €** | 2 € | non | non |
| **B3** | **−2 €** | 2 € | **oui** | non |

Je publie pour chacune : **P&L par trade**, **écart-type**, **pire journée**,
**taux de réussite**, **durée moyenne** jusqu'à la sortie, et le détail des
issues (TP, SL, échelle, temps).

## ⚠️ LA LIMITE QUI COMPTE, DITE D'AVANCE

Les entrées sont **fixes** : une toutes les 30 minutes, identiques pour les six.
Donc ce banc **ne fait pas payer** à un stop serré les trades
**supplémentaires** qu'il permettrait en libérant la place plus vite. Or un
stop serré se résout beaucoup plus vite.

🔑 Le spread est payé **une fois par trade** : à nombre de trades égal, les six
paient pareil ; **à durée égale**, un stop serré en paie davantage. C'est
pourquoi je publie la **durée** — c'est elle qui porte ce coût caché, et elle
joue **en faveur** du stop serré dans mon tableau.

## ⛔ LE CRITÈRE, POSÉ AVANT DE REGARDER

Une stratégie est déclarée **meilleure** qu'une autre si :

1. son P&L par trade est supérieur **hors échantillon** (2ᵉ moitié de la
   période, la 1ʳᵉ servant à désigner) ;
2. l'écart par **JOUR** a un **|t| > 2,5** (6 stratégies, ~15 paires
   comparées) ;
3. le signe de l'écart est **stable sur les deux moitiés**.

## MA PRÉDICTION, POSÉE MAINTENANT

1. ⛔ **Aucune paire ne franchira le critère en espérance.** Toutes les
   géométries valent zéro avant coût et `−spread` après : c'est l'arrêt
   optionnel, et c'est déjà pourquoi 0 couple sur 120 a été retenu ce matin.
2. ⚠️ **L'échelle de gains (A1) sera légèrement PIRE que le témoin (T)** : elle
   resserre dès **1,00 €** de profit sur un objectif à 2 €, donc elle coupe à
   **+0,75 €** des trades qui auraient atteint +2 €. Ce que son objectif mobile
   récupère (jusqu'à 4 €) ne compensera pas.
3. ✅ **B1 et B2 gagneront massivement sur la VARIANCE** — facteur ~4 sur
   l'écart-type et ~7 sur la pire journée — pour un prix **indistinguable de
   zéro** (déjà mesuré : t = +0,04 à −1 €).
4. 🔑 Donc ma réponse attendue à Xavier est : **ni l'une ni l'autre ne rapporte
   plus**, et le choix est un choix de **variance**, pas de rendement — avec un
   avertissement sur la durée, qui fera payer plus de spread au stop serré dès
   qu'on recyclera la place.

⇒ Si une paire franchit les trois critères, j'ai tort et c'est la première
différence de rendement établie entre deux géométries de ce projet.


---

# VERDICT — 2026-10-11

`scripts/banc_stop_large_contre_serre.py`. 6 668 trades aveugles, 99 999
bougies M1 du courtier, les six strategies avancant en parallele sur un seul
parcours.

## 🔑 LE RESULTAT PRINCIPAL EST UN ENCADREMENT, PAS UN CLASSEMENT

Mon premier passage armait un palier sur **l'extreme** de la bougie. Defaut :
si le prix touche +1,00 EUR puis retombe a +0,50, le stop etait pose a +0,75,
donc **AU-DESSUS du cours**, et je creditais +0,75 pour une sortie qui aurait
eu lieu plus bas. La production refuse exactement cela (« poser un stop du
mauvais cote du cours FERME la position »).

J'ai donc refait le banc avec le palier arme sur la **cloture** de la minute,
et je publie **les deux**, parce que la realite est entre les deux : la boucle
de production interroge les prix toutes les quelques secondes, donc elle
attrape une partie des extremes, pas tous.

    A1 (la production)      optimiste **+0,1570 EUR/trade**
                            pessimiste **-0,0677 EUR/trade**
    ⇒ encadrement **0,225 EUR/trade**, plus GRAND que tout effet mesure ce jour

⛔ **Tout l'avantage apparent de l'echelle vient donc de l'hypothese sur la
vitesse de pose du stop, pas de la strategie.** C'est la meme lecon que
l'encadrement de convention du matin, cette fois sur un dispositif **ARME EN
PRODUCTION**.

## LE TABLEAU, version PESSIMISTE (palier arme sur la cloture)

| | EUR/trade | ecart-type | pire journee | reussite | duree |
|---|---|---|---|---|---|
| **T** temoin SL−20/TP2 | −0,1479 | 6,44 | −3,56 | 90,45 % | 36,4 min |
| **A1** la production | −0,0677 | 5,84 | −4,03 | 92,19 % | 28,9 min |
| **A2** + protection | −0,0247 | 2,99 | −2,15 | 72,89 % | 8,5 min |
| **B1** stop −1 | −0,0424 | **1,42** | −0,46 | 33,97 % | 3,2 min |
| **B2** stop −2 | −0,0714 | 2,00 | **−0,12** | 49,75 % | 5,3 min |
| **B3** stop −2 + echelle | −0,0285 | 1,91 | −0,36 | 55,43 % | 4,6 min |

⇒ **Une seule paire sur quinze** franchit le critere pre-inscrit :
**B3 contre B2**, `+0,0476 EUR/trade, t −3,07`, signe stable.
🔑 Autrement dit : **si on met un stop serre, il faut garder l'echelle.**

En version optimiste, 6 paires franchissent et A1 bat le temoin a t +3,80.
⚠️ Je ne retiens pas ce classement : il repose sur le defaut corrige ci-dessus.

## CE QUI EST ROBUSTE DANS LES DEUX VERSIONS

1. **Aucune strategie ne RAPPORTE.** Les six sont entre −0,15 et −0,02
   EUR/trade. Le choix n'est pas un choix de rendement.
2. **La queue**, elle, change enormement :

       pire journee   T **−3,56 EUR**  ->  B2 **−0,12 EUR**   (÷30)
       ecart-type     T **6,44**       ->  B1 **1,42**        (÷4,5)

3. **La protection des PERTES (A2), aujourd'hui DESARMEE**, ramene le nombre de
   stops touches de 631 (temoin) a **1 sur 6 668**, pour un cout non
   significatif. C'est le dispositif le plus efficace du lot sur la queue.
4. **La duree** : B2 se resout en 5,3 min contre 36,4 min pour le temoin.

## ⚠️ LE PIEGE DU RECYCLAGE, deja declare avant la mesure

Les entrees sont **fixes** dans ce banc. Or un stop serre libere la place
**7 fois plus vite** ⇒ a nombre d'heures egal il permet 7 fois plus de trades,
donc **7 fois plus de spread**. Ce banc ne le lui fait pas payer.

⇒ Donc : **a rythme d'entrees inchange**, le stop serre est strictement
meilleur sur le risque pour un rendement equivalent. **Si on recycle la place
liberee**, il devient nettement pire. La reponse depend de ce reglage-la, pas
du stop.

## MES PREDICTIONS

1. ⛔ « aucune paire ne franchira le critere » : **refutee** en version
   optimiste (6 paires), tenue en version pessimiste (1 paire).
2. ⛔ « l'echelle sera legerement PIRE que le temoin » : **refutee dans les
   deux versions** — elle est legerement meilleure (+0,059 EUR/trade en
   pessimiste, non significatif ; +0,305 en optimiste).
3. ✅ « B1/B2 gagneront massivement sur la variance » : **juste**, facteur 4,5
   sur l'ecart-type et 30 sur la pire journee.
4. ✅ « le choix est un choix de variance, pas de rendement » : **juste**.


---

# ANNEXE — 2026-10-11 : a quelle DISTANCE resserrer ? (question de Xavier)

Question : « si on commence a −20 € et qu'au bout d'une minute le cours est a
−5, qu'est-ce qui se passe si la regle resserre le stop a −1 ? Est-ce que le
trade est cloture ? Ou peut-on mettre une regle a l'entier inferieur ? »

## LA REPONSE MECANIQUE : oui, ça fermerait — et la production le refuse deja

A −5 € de perte, le niveau « −1 € » est **du mauvais cote du cours** (pour un
achat, c'est un prix PLUS HAUT que le prix courant). MT5 refuse un tel ordre,
et s'il passait il se declencherait **immediatement** : on encaisserait les
**−5 €**, pas les −1 €. Fermer n'est pas proteger.

Deux gardes existent deja dans le code :

    equiper_trades_main   MARGE_FRANCHIE_EUR = 0,10 : une borne deja franchie
                          est SIGNALEE, jamais posee
    protection_perte_or   plancher `perte + 2 €` : le stop n'est jamais pose a
                          moins de 2 € du cours

⇒ Et a −5 € avec un stop a −20 €, la regle d'aujourd'hui ne va PAS a −1 € :
elle calcule le **point milieu** `(20 + 5) / 2` et pose le stop a **−12,50 €**,
en laissant 7,50 € de respiration.

## SA PROPOSITION, MESUREE — `scripts/banc_marge_protection.py`

« Entier inferieur » = stop a `−(floor(perte) + 1)`, donc −6 € a −5,3 € de
perte. Memes 6 668 trades, depart SL −20 / TP 2, echelle armee sur la cloture.

| variante | EUR/trade | ecart-type | pire journee | reussite | resserrages |
|---|---|---|---|---|---|
| **P2 marge 2 € (aujourd'hui)** | −0,0247 | 2,99 | −2,15 | 72,89 % | 12 275 |
| P1 marge 1 € | −0,0337 | 2,85 | −1,67 | 69,30 % | 12 450 |
| **PENT entier inferieur** | −0,0289 | 2,81 | **−1,61** | 68,33 % | 12 538 |
| P05 marge 0,50 € | −0,0317 | 2,81 | −1,63 | 68,15 % | 12 633 |
| **SANS protection** | −0,0677 | **5,84** | **−4,03** | 92,19 % | 0 |

Chaque variante contre la regle d'aujourd'hui :

    P1    -0,0162 EUR/jour   t -0,89   signe INVERSE entre les moities
    PENT  -0,0148            t -0,63   signe INVERSE
    P05   -0,0232            t -0,86   signe INVERSE

⇒ **Sa proposition est INDISTINGUABLE de la regle actuelle** en esperance, avec
une pire journee legerement meilleure (−1,61 contre −2,15). Resserrer la marge
de 2 € a moins d'un euro ne casse donc **pas** les trades par le bruit — mais
ne rapporte rien non plus.

## 🔑 LE VRAI ECART EST AILLEURS

    stop de depart touche :  **1 fois sur 6 668** avec protection
                             **516 fois** sans
    ecart-type :   5,84  ->  2,81 a 2,99   (÷ 2)
    pire journee : -4,03 ->  -1,61 a -2,15

Pour un cout de **0,064 €/trade, non significatif** (t +0,65).

⇒ La question n'est pas « quelle marge », c'est **« armer ou non la protection
des pertes »** — et elle est **DESARMEE** aujourd'hui.
