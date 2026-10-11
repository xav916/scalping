# Négativité CUMULÉE contre négativité CONSÉCUTIVE

**Déclaré le 2026-10-12, AVANT d'écrire la mesure.**

Xavier, après avoir dû bouger un stop à la main la nuit de la réouverture :
*« pourquoi le SL du trade actif ne bouge pas selon les minutes ? »*

## ⛔ LE DÉFAUT MESURÉ EN PRODUCTION, qui motive ce banc

Position `1360877900`, vendeur, ouverte à 22:57:01. En **quatre minutes**, la
protection a refusé **cinq fois** :

```
22:57:05  ouvert depuis 5 s         (age mini 60 s)
22:58:06  EN PROFIT +0,36 EUR       pas son domaine
22:59:04  negatif depuis 28 s       il en faut 30
23:00:28  EN PROFIT +0,13 EUR       pas son domaine
23:01:11  negatif depuis 8 s        il en faut 30
```

🔑 **Chaque retour en positif remet le compteur de négativité à zéro.** Un
trade qui oscille autour de l'équilibre n'accumule donc **jamais** 30 secondes
négatives d'affilée, et garde son stop de départ de 13 € indéfiniment — alors
que c'est précisément le trade qui ne va nulle part.

Xavier a fini par bouger le stop lui-même. L'arithmétique le confirme : le
premier resserrage automatique donne 2,62 € de distance, là où un point milieu
depuis 13 € aurait donné 7,02 €. La protection partait donc de **sa** valeur.

## ⚠️ LE CHOIX DE DONNÉES, et pourquoi il n'est pas neutre

La règle raisonne en **secondes**. Le magasin de bougies M1 (99 999 bougies) ne
donne qu'un OHLC par minute : il ne dit rien du **chemin intra-minute**, donc
il est **incapable** de départager une série de 30 s continues d'un cumul de
30 s. Mesurer dessus serait inventer une réponse.

⇒ On mesure sur le **magasin de ticks du courtier** : `ticks_courtier.db`,
**3 298 970 ticks**, 2026-09-21 → 10-09, horodatés à la milliseconde.
⛔ Sa limite, assumée : il ne couvre que de **01:00 à 20:55 UTC** (le
collecteur ne tournait pas la nuit). La réouverture du dimanche, et les heures
22:00–01:00 où Xavier trade désormais, **ne sont pas dans l'échantillon**.

## Les deux règles comparées

```
A (actuelle)   negatif depuis 30 s CONSECUTIVES
B (proposee)   negatif 30 s CUMULEES sur une fenetre glissante de 120 s
```

Tout le reste est identique et reprend la production : stop de départ 13 €,
âge minimal 60 s, cadence 60 s, point milieu, plafond de largeur 9 €, plancher
absolu 2 €, traînage de 0,50 € sans objectif, pas minimal 0,10 €.

Trois fenêtres de cumul testées : **30 s / 60 s**, **30 s / 120 s**,
**30 s / 180 s**. Plus un témoin **C : aucune condition de négativité**, pour
savoir si la condition sert à quelque chose du tout.

⇒ **4 règles × 1 géométrie = 4 cellules**, sur les mêmes instants d'entrée.

🔑 Le contrôle est **apparié** : les quatre règles rejouent **exactement les
mêmes positions**, aux mêmes instants, sur les mêmes ticks. Leur seul écart est
la condition de déclenchement. Unité statistique = **le JOUR** (15 jours).

## ⛔ LE CRITÈRE, posé maintenant

B remplace A **si et seulement si les trois** sont vrais :

1. la **pire journée** de B est meilleure que celle de A ;
2. l'écart de rendement `B − A` n'est **pas significativement négatif** —
   borne : `t > −2,0` sur l'unité JOUR ;
3. le signe de `B − A` est **stable sur les deux moitiés** de la période.

⚠️ Si B améliore la pire journée mais dégrade le rendement avec `t ≤ −2,0`,
on ne retient pas : on aurait échangé un défaut connu contre une perte
mesurée.

## MES PRÉDICTIONS, posées avant de coder

1. ⚠️ **B déclenche beaucoup plus souvent** — je prédis **au moins 2 fois**
   plus de resserrages que A. C'est mécanique, ce n'est pas un résultat.
2. ✅ **B améliore la pire journée.** Je le prédis parce que la mesure de
   cadence du 11/10 avait déjà montré que resserrer plus tôt réduit la queue
   (pire journée −1,75 → −0,60 € en passant de 5 min à 1 min).
3. ⛔ **Et je prédis que l'écart de rendement sera indistinguable de zéro**,
   `|t| < 2`, exactement comme pour la cadence. Mon raisonnement : les sept
   zéros disent que la direction n'existe pas, donc déplacer le moment de la
   sortie ne peut pas créer de rendement — seulement redistribuer la variance.
4. ⚠️ **Je prédis que la réussite BAISSE** avec B (plus de trades coupés
   petits), de l'ordre de 5 à 10 points. C'est le prix visible du dispositif,
   et il faudra le dire.
5. 🔑 **Et le témoin C me servira à trancher une question que personne n'a
   posée** : si C (aucune condition de négativité) fait aussi bien que B, alors
   la condition elle-même est décorative, et la bonne réponse est de la
   **retirer** plutôt que de la raffiner.

⇒ Si mes prédictions 2, 3 et 5 tiennent ensemble, la recommandation sera de
passer à B — ou de supprimer la condition, ce qui serait plus simple encore.
