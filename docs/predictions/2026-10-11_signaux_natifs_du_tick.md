# Les signaux NATIFS DU TICK portent-ils une direction ?

**Déclaré le 2026-10-11, AVANT d'écrire la mesure.** Demande de Xavier :
« pourquoi ne m'as-tu pas conseillé d'identifier les patterns au tick et pas
aux bougies, vu que la reconnaissance de patterns sur les bougies ne veut rien
dire ? »

## ⛔ MON ERREUR, ACTÉE

Je ne l'avais pas proposé. J'avais répondu quatre fois « pas de direction » sur
des **bougies** (M5 49,13 % contre une base de 49,10 % · M1 **0 retenu sur 28**
· 0/22 motifs · 49,83 % à bornes symétriques), et j'ai traité **l'échelle de
détection comme réglée**. Un détecteur sur bougies qui rend zéro ne prouve rien
sur un signal né du tick. C'était une clôture prématurée.

## La distinction qui structure ce banc

**(a) Redétecter les mêmes motifs plus finement** — engulfing, pin bar, FVG,
cassure d'un range : ce sont des **énoncés sur des bougies**. Les porter « au
tick » revient à faire des bougies plus courtes, et cette direction a déjà
échoué deux fois (M5 → 2 motifs sur 30, tous deux ANTI-prédictifs ; M1 → 0 sur
28). ⇒ **Ce banc ne fait pas ça.**

**(b) Des signaux que la bougie DÉTRUIT** — et c'est l'idée de Xavier :

| signal | formule | PDF |
|---|---|---|
| **vitesse** | `(mid_t − mid_{t−N}) / N`, en $/s | n° 26 |
| **accélération** | `vitesse(t) − vitesse(t−N)` | n° 27 |
| **tick rate** | nombre de ticks dans les N dernières secondes | n° 28 |
| **déséquilibre bid** | `(hausses − baisses) / (hausses + baisses)` sur N s | n° 29, adapté |

⛔ **Pourquoi « adapté » pour le n° 29** : le Tick Imbalance du PDF compte des
**transactions** acheteur/vendeur. Mesuré le 10/10 : `buy = 0, sell = 0` sur
893 ticks — **ce CFD n'a pas de sens de transaction**. On utilise donc le
déséquilibre des **variations de bid**, le seul substitut que la donnée permette.

## Les données

Magasin de **ticks du courtier** bâti le jour même : 2026-09-21 → 2026-10-09,
~4,9 ticks/s, horodatage corrigé par le champ de chaque réponse et **validé sur
une ancre d'exécution réelle** (le fill du 09/10 à 08:20:21 à 4 200,22 tombe
dans la plage des bids de cette minute).

⚠️ Et la route **tronque à 20 000 ticks par appel** — défaut trouvé et traité
avant la collecte : sans suivre `suite_from`, le magasin aurait perdu des ticks
**en silence** sur les tranches chargées.

## Ce que je mesure

Deux fenêtres : **N = 10 s** et **N = 60 s**. Pour chaque signal, les seuils
sont le **p90 et le p10 de sa propre distribution** — pris dans la donnée,
jamais choisis à la main, et surtout jamais réglés sur le résultat.

Quand un signal franchit son seuil, on entre dans **le sens qu'il annonce** et
on mesure l'issue sous **deux géométries** :

1. **la production** : départ −13 €, traînage 0,50 €, aucun objectif,
   protection à 60 s ⇒ ce que ça vaudrait vraiment ;
2. **bornes symétriques ±2 €** ⇒ pour que la géométrie ne **bâillonne** pas le
   signal, la leçon du 10/10 (où la géométrie 2/20 rendait un signal réel
   inaudible).

⇒ **4 signaux × 2 fenêtres × 2 géométries = 16 cellules.**

## Les contrôles, et il y en a trois

1. **le MAUVAIS sens aux mêmes instants** — comparaison appariée, la dérive du
   marché s'annule exactement ;
2. **un placebo par permutation** : 200 tirages de faux instants **appariés sur
   l'heure UTC**, pour que le profil horaire soit le même ;
3. **l'unité est le JOUR**, pas le tick : deux ticks voisins décrivent le même
   mouvement.

## ⛔ LE CRITÈRE, POSÉ AVANT DE REGARDER

Une cellule est retenue si son |t| dépasse le **95ᵉ centile du max|t| des 200
permutations**, avec **n ≥ 200** entrées et un **signe stable sur les deux
moitiés** de la période.

## MA PRÉDICTION, POSÉE MAINTENANT

1. ⛔ **0 cellule retenue sur 16.** Motif : quatre zéros indépendants sur la
   direction, et la leçon du taux de base — les détecteurs reproduisaient
   *exactement* le comportement inconditionnel du marché (49,13 % contre
   49,10 %).
2. ⚠️ Je prédis que **la vitesse paraîtra prédictive en apparence** sur la
   géométrie de production, par pure **auto-corrélation** : entrer dans le sens
   d'un mouvement en cours capture la fin de ce mouvement. Le contrôle apparié
   (mauvais sens) devrait l'absorber ; s'il ne l'absorbe pas, c'est le résultat.
3. ✅ Je prédis que le **tick rate** sera le plus informatif des quatre — non
   sur la direction, mais sur la **durée** : un flux dense résout les trades
   plus vite, comme la grappe de publications l'a montré (÷1,3 à ÷2,4).
4. ⚠️ Et je prédis que les bornes symétriques donneront des |t| **plus grands**
   que la production, parce qu'un objectif à 0,50 € de traînage coupe
   l'information avant qu'elle se matérialise.

⇒ Si une cellule passe, c'est **la première information directionnelle établie
de tout ce projet**, et Xavier aura eu raison contre moi sur l'échelle de
détection.


---

# VERDICT — 2026-10-11

`scripts/banc_signaux_du_tick.py`. **3 298 970 ticks** du courtier,
**15 jours** de cotation (2026-09-21 → 2026-10-09 23:56 UTC).

## ⇒ 0 CELLULE RETENUE SUR 16. Ma prédiction 1 tient.

Plafond par permutation (200 tirages appariés sur l'heure) : **2,260**.

    signal        N s  geometrie      n      bon sens   mauvais    ecart      t
    tick_rate      10  symetrique   1392     -0,1868    +0,0230   -0,2861  **-2,24**
    tick_rate      10  production   1392     -0,0316    +0,1308   -0,2070   -2,03
    vitesse        60  production   2819     +0,0765    +0,0065   +0,0696   +1,39
    tick_rate      60  production    543     +0,1014    +0,1763   -0,1597   -1,26
    vitesse        10  symetrique   3556     -0,1014    -0,0520   -0,0504   -1,06
    acceleration   60  production   2969     +0,0311    -0,0010   +0,0306   +0,77
    ... les dix autres : |t| <= 0,77

## 🔑 LA SEULE CELLULE QUI APPROCHE LA BARRE DIT L'INVERSE DE L'INTUITION

`tick_rate` à 10 s, bornes symétriques : **|t| = 2,24 contre un plafond de
2,260** — elle manque de **0,02**. Et son signe est **NÉGATIF** : quand le flux
est dense, entrer **dans le sens** du mouvement **perd** (−0,1868 contre
+0,0230 pour le mauvais sens).

⚠️ Je n'en fais pas une trouvaille : c'est le **maximum de 16 cellules**, et le
plafond est construit exactement pour ça. Manquer la barre de 0,02 n'est pas
la franchir. Mais la **direction** du résultat est intéressante — une rafale de
ticks ressemble à un **épuisement**, pas à une impulsion.

## MES QUATRE PRÉDICTIONS

1. ✅ « 0 cellule retenue sur 16 » : **juste**.
2. ⚠️ « la vitesse paraîtra prédictive par auto-corrélation, le contrôle apparié
   devrait l'absorber » : à moitié. `vitesse 60 s` est bien le meilleur positif
   (bon sens **+0,0765** contre **+0,0065**), donc le contrôle ne l'absorbe
   **pas** entièrement — mais `t = +1,39` reste loin sous la barre. À 10 s elle
   est plate (t −0,24).
3. ⚠️ « le tick rate sera le plus informatif, sur la DURÉE et non la
   direction » : **à moitié faux**. Il est bien le plus informatif — mais **sur
   la direction**, et **à l'envers**. ⛔ Et je n'ai pas mesuré la durée dans ce
   banc : la prédiction reste donc **non vérifiée** sur sa seconde moitié.
4. ⚠️ « les bornes symétriques donneront des |t| plus grands » : **mitigé**.
   Vrai pour le tick rate (2,24 contre 2,03), **faux** pour la vitesse à 60 s
   (0,68 contre 1,39).

## ⇒ CE QUE ÇA FERME, ET CE QUE ÇA N'INTERDIT PAS

C'est le **cinquième zéro indépendant** sur la direction, et le premier obtenu
**au tick** — donc la question de l'échelle de détection est traitée, et Xavier
avait raison d'exiger qu'elle le soit.

⛔ Ce banc **n'épuise pas** les signaux de tick : il en teste quatre, sur deux
fenêtres. Il ne dit rien d'un signal composé (par exemple tick rate **plus**
accélération), ni d'une fenêtre très courte (1 s), ni du carnet — qui n'existe
pas sur ce CFD.
🔑 Et la piste que ce banc **ouvre malgré lui** est le **retour à la moyenne sur
rafale de ticks**, puisque c'est le signe qui est ressorti. Ce serait une
question neuve, à pré-inscrire à part.
