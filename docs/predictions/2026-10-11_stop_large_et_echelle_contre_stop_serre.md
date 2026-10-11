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
