# La négativité persistante prédit-elle le stop ? — PRÉDICTION INSCRITE AVANT

**Affirmation de Xavier le 2026-10-10** : *« pour un trade qui est 75 % du
temps négatif, on a bien plus de chances de tomber sur le SL que sur le TP.
Donc c'est peut-être judicieux d'arrêter les trades négatifs 80 % du temps. »*

⛔ **Ce fichier est écrit et commité AVANT la mesure hors échantillon.**

## Ce qui a été observé EN ÉCHANTILLON (vendredi 09/10 seul)

À la minute 10, négativité mesurée **sur les 10 premières minutes seulement** —
jamais sur la vie entière, qui contiendrait le résultat :

```
negatif >= 75 %   n=16   SL 9 / TP 1   31,2 % gagnants   -4,91 EUR
negatif <  75 %   n= 8   SL 2 / TP 4   75,0 % gagnants   +0,17 EUR
                               ecart -5,08 EUR   t = -2,29
```

Gradient monotone à la minute 10 : `<50 % → +1,82` · `50-75 % → −0,82` ·
`75-90 % → +1,45` (n=1) · `90 %+ → −5,34`. Idem à la minute 15.

## ⚠️ POURQUOI JE N'ARME RIEN SUR CE CHIFFRE

1. **n = 16 contre 8.** Minuscule.
2. **Une journée, choisie après coup**, et 12 cellules examinées (4 bandes ×
   3 minutes). Prendre « minute 10, ≥ 75 % » est un choix fait APRÈS avoir vu
   la grille.
3. ⚠️ **Circularité partielle** : un trade encore ouvert à la minute 10 et
   négatif 90 % du temps est *déjà* en train de perdre. « Il finit au stop »
   est en partie mécanique — même si le stop est à 20 €, donc loin.
4. 🔑 **Le précédent** : le filtre de tendance de l'or passait à **t +2,28 en
   échantillon** et tombait à **+0,52 hors échantillon**. Même forme, même
   piège.

## LE CRITÈRE, FIXÉ MAINTENANT

Mesure sur **tous les jours de marché depuis le 01/10 SAUF le 09/10** (le jour
qui a servi à former l'hypothèse), alignement mesuré par jour, seuil à 95 %
d'ancres ou le jour est écarté.

- ✅ **CONFIRMÉE** si, à la minute 10, l'écart `(négatif ≥ 75 %) − (négatif
  < 75 %)` reste **négatif avec |t| > 2** et **n ≥ 15 de chaque côté**.
- ⛔ **RÉFUTÉE** si l'écart change de signe, ou si |t| < 1.
- ⚖️ **INDÉCIDABLE** entre les deux, ou si n < 15 d'un côté.

⇒ **Et même confirmée, elle ne sera pas armée telle quelle** : fermer un trade
à −2 ou −3 € sur ce signal a déjà été mesuré **perdant** (27 cellules, 24 ≤ 0,
car 64 % des trades commencent négatifs et beaucoup remontent). Confirmée, elle
justifierait au mieux de **ne pas RENOUVELER** un trade, ou de libérer la place
— pas de couper à perte fixe.

## Le contexte qui motive la question

Xavier veut libérer la marge pour d'autres trades. Mesuré vendredi : le plafond
de 5 positions n'a **jamais** été atteint (max 4), mais **161 refus réels**
pour place ou marge ont eu lieu, dont **23 pendant la vie** du trade
`#1360840476` (−9,63 €, 126 min). Et l'espérance d'un trade de plus est
**+0,993 €** depuis le 01/10 (n=63) contre **−0,797 €** sur 30 jours (n=91) —
elle a **changé de signe**.
