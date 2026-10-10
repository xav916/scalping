# « Laisser courir » tient-il hors échantillon ?

**Déclaré le 2026-10-10, AVANT d'écrire la mesure.** Décision de Xavier :
« Lancé la vérification » — avant d'armer quoi que ce soit.

## D'où vient l'hypothèse

Sur les **92 chemins reconstruits de la semaine du 05 au 09/10**, laisser
chaque trade d'or courir jusqu'à son objectif 2 € ou son stop 20 € donnait
**+44,04 €** (75 TP, 0 SL) contre **−6,05 €** réellement obtenus.

⇒ Avantage en échantillon : **+50,09 € sur 92 trades = +0,544 € par trade.**

⛔ Cette semaine est **celle qui a formé l'hypothèse**. Elle ne peut pas la
tester.

## Pourquoi je refuse d'armer sans ce test

Il y a deux heures, le signal `|Z| > 2` donnait **+0,96 $ par trade** sur
21 jours. Élargi à 56 jours : **+0,0024 $**. Un facteur **400**. Et mon
« +8,60 contre le hasard » du 01/10 avait été retiré pour la même raison.

🔑 Une mesure sur une fenêtre courte n'est pas un résultat, c'est une
hypothèse.

## Ce que je mesure

Sur **tous les trades d'or réels** de `personal_trades` (destination
`admin_live`) des **120 derniers jours**, chemin reconstruit minute par minute
depuis les bougies **M1 DU COURTIER**, je rejoue sur **les mêmes entrées** :

| politique | règle |
|-----------|-------|
| **A — laisser courir** | premier contact de l'objectif 2 € ou du stop 20 €, rien d'autre ne touche le stop |
| **B — la machinerie** | l'échelle de gains (`1,0:0,75 / 1,5:1,25 / 1,75:1,5 / 2,0:1,75`) **et** la protection de perte (fenêtre 300 s, moitié 150 s, stop ÷2, plancher perte + 2 €), telles qu'elles tournent en production |

⇒ Comparaison **APPARIÉE** : mêmes entrées, mêmes chemins, mêmes bornes
initiales. Le P&L réel sert de troisième colonne, pour référence seulement.

## ⛔ LE CRITÈRE, POSÉ AVANT DE REGARDER

« Laisser courir » est **retenu** s'il réunit **les quatre** :

1. avantage `A − B` **> 0** ;
2. **|t| > 2**, l'unité étant **LE JOUR** et non le trade — des trades du même
   jour partagent le même chemin, un `t` par trade serait gonflé ;
3. **n ≥ 100 trades** et **≥ 20 jours** ;
4. le signe de l'avantage **tient sur les DEUX moitiés** de la période.

⇒ Un seul qui manque, et **on n'arme pas**.

## MA PRÉDICTION, POSÉE MAINTENANT

Je prédis que l'avantage **rétrécit fortement** : je prédis `A − B` **sous
+0,20 € par trade** hors échantillon, contre +0,544 € en échantillon.

⇒ S'il reste **au-dessus de +0,20 €** avec les quatre critères, ma prédiction
est réfutée et l'expérience est justifiée.

## Garde-fous du rejeu

- ⛔ **Alignement MESURÉ par jour**, jamais supposé : les horodatages du pont
  dérivent (décalage vu de +10 796 à −64 209 s). On cherche le décalage qui
  place le plus de prix d'exécution réels dans la bougie correspondante, et un
  jour qui n'atteint pas **95 % d'ancres** est **ÉCARTÉ**.
- ⛔ Dans une bougie qui contient l'objectif **ET** le stop, on prend le
  **STOP**. Supposer l'objectif fabriquerait le résultat.
- ⛔ Le **spread est facturé** sur les deux politiques.
- ⚠️ Les trades ouverts **dans le terminal MT5** (`notes` = `MANUEL-TERM`) sont
  comptés **à part** : l'échelle et la protection ne les adoptent que depuis le
  09/10.

## Ce que cette mesure ne tranche PAS

- Elle ne dit rien d'un **autre couple** objectif/stop que 2 €/20 €.
- Elle ne dit rien de la **direction** des entrées : elle prend les entrées
  réelles comme données et ne compare que la **gestion de sortie**.
- Elle ne simule pas le **réemploi de la marge** : un trade qui se ferme tôt
  libère une place. Si « laisser courir » gagne, ce gain est **surestimé** de
  ce que les trades suivants auraient rapporté.
