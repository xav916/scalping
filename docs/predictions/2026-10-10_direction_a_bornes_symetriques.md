# Les motifs portent-ils une DIRECTION, quand la borne cesse de l'écraser ?

**Déclaré le 2026-10-10, AVANT d'écrire la mesure.** Décision de Xavier : « Go »
sur la première des deux pistes proposées.

## La question, et pourquoi elle se pose maintenant

Le gros test M1 (29 jours, 1 343 trades séquentiels) donne une réussite de
**90,39 %** contre **91,11 %** requis. Or la probabilité d'atteindre +2 € avant
−20 € dans une marche sans dérive vaut `20/22 = 90,91 %`.

🔑 **Les motifs font donc légèrement PIRE qu'une pièce de monnaie** — et
l'écart à mesurer est de **0,72 point**.

Combien de trades pour distinguer 90,39 % de 91,11 % à 2 σ ?

    n > 4 x p(1-p) / Δ²  =  4 x 0,0865 / 0,0072²  ≈  6 700 trades
    (j'en ai 1 343)

À bornes symétriques, détecter un avantage de 55/45 demande **~400 trades**.
⇒ **facteur 17.**

🔑 La géométrie 2 €/20 € ne rend pas les motifs muets : elle les rend
**inaudibles**. Cette mesure retire le bâillon avant de conclure.

## Ce que je mesure

Sur les **mêmes détections M1** que le gros test (1<sup>er</sup> septembre →
9 octobre 2026, bougies M1 du courtier, un appel `/rates` par jour, fenêtre
`−1/+2 j`, index minute plancher), pour chaque détection je rejoue **deux
fois** :

- **BON SENS** — celui que le nom du motif annonce ;
- **MAUVAIS SENS** — l'opposé, **aux mêmes instants**.

⇒ C'est une comparaison **APPARIÉE** : la dérive du marché s'annule
exactement, puisque les deux jambes partent de la même minute. C'est la leçon
du « +8,60 contre le hasard » retiré le 01/10.

Et je le fais à **six géométries** :

| TP / SL (€) | ce que ça teste |
|---|---|
| 2 / 20 | la production |
| 2 / 2 | symétrique serré |
| 5 / 5 | symétrique moyen |
| 10 / 10 | symétrique large |
| 20 / 20 | symétrique très large |
| 20 / 2 | l'asymétrie **inversée**, pour contrôle |

## ⚠️ LA NORMALISATION, et elle est indispensable

Un écart en euros **grandit mécaniquement** avec la borne : à 20/20 on capture
dix fois plus de mouvement qu'à 2/2. Comparer des euros entre géométries
produirait le faux résultat « plus la borne est grande, plus la direction est
forte ».

Je publie donc trois colonnes :

1. l'écart en **euros** ;
2. l'écart en **R** (divisé par la distance de stop) ;
3. le **taux de réussite implicite**, qui est comparable entre toutes les
   géométries symétriques : à `TP = SL = X`, une pièce donne un écart nul, et
   un avantage `p` donne `écart ≈ (2p − 1) × 2X`, donc

       p = écart / (4X) + 0,5

## ⛔ LE CRITÈRE, POSÉ AVANT DE REGARDER

Les motifs portent une direction si, **à au moins une géométrie symétrique**,
ils réunissent **les quatre** :

1. écart bon − mauvais **> 0** ;
2. **|t| > 2**, l'unité étant **LE JOUR** (des minutes voisines partagent le
   même mouvement : un `t` par trade serait gonflé) ;
3. **n ≥ 1 000** détections et **≥ 20 jours** ;
4. signe stable sur les **deux moitiés** de la période.

⇒ Un seul qui manque, et la direction reste déclarée muette.

## MA PRÉDICTION, POSÉE MAINTENANT

Je prédis que **la direction est muette même à bornes symétriques** : écart
compris entre **−0,10 € et +0,10 €** à 2/2 et à 5/5, et **|t| < 2**.

Motif : le verdict du 2026-10-10 déjà au dossier — « la direction du radar est
indiscernable du hasard », 5 jours, n = 59, horizons 1 → 60 min, **aucune p
sous 0,27** — et les 90,39 % du gros test, qui sont le taux d'une pièce.

⇒ Si l'écart dépasse **+0,10 €** avec les quatre critères, ma prédiction est
**réfutée** et il y a quelque chose à construire.

## Ce que cette mesure ne tranche PAS

- Elle ne dit pas qu'une géométrie symétrique serait **rentable** : elle dit
  seulement si le **sens** porte de l'information. La rentabilité devra
  ensuite payer le spread à chaque trade.
- Elle prend les détections comme données : ni porte d'admission, ni score de
  confiance, ni plafond de marge.
- Elle ne teste **aucune source de direction nouvelle** (calendrier, order
  flow réel, dollar, heure). C'est la piste suivante, pas celle-ci.
