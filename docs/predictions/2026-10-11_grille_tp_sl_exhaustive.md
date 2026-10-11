# Existe-t-il un couple TP/SL gagnant sur l'or ? — la grille complète

**Déclaré le 2026-10-11, AVANT de mesurer.** Demande de Xavier : « je veux que
tu trouves le juste couple TP/SL qui soit au max gagnant sur l'or ».

## Ce que je sais déjà, et pourquoi je le mesure quand même

L'arithmétique dit qu'aucun couple ne peut gagner : sur une marche sans dérive,
`P(toucher +a avant −b) = b/(a+b)`, donc l'espérance vaut **exactement zéro**
pour tout `(a,b)`, et **−spread** une fois le coût payé. Vérifié hier sur six
couples, sur une plage de produits `a×b` de **1 à 100** : le taux obtenu collait
au taux requis à chaque fois.

⇒ Mais un argument n'est pas une mesure, et Xavier a droit à la **surface
entière** plutôt qu'à ma démonstration. Sur une fenêtre finie, il y aura
**toujours** un couple qui paraît le meilleur — c'est précisément ce que le
hors échantillon existe pour tuer.

## La grille

    TP (EUR) : 1   1,5   2   3   4   5   7   10   15   20
    SL (EUR) : 1   1,5   2   3   4   5   7   10   15   20   30   40

⇒ **120 couples.** Plafond du hasard du laboratoire à 120 cellules :
**|t| > 2,80** (interpolé entre 96 → 2,730 et 128 → 2,829).

## Les données

Magasin **du courtier** bâti hier (`candles_courtier.db`) : **99 750 bougies
M5**, du **2025-05-14** au **2026-10-09** — 17 mois, vérifié à 97/97 ancres
d'exécution et dont la coupure hebdomadaire reproduit l'horaire réel du marché.

⚠️ **Limite déclarée** : granularité **M5**. Une bougie de 5 minutes peut
contenir l'objectif ET le stop ; dans ce cas **on prend le stop**. Cela
**sous-estime** la fréquence des touches pour les petites bornes, et je le dis
plutôt que de le découvrir après.

## Les entrées : systématiques et SANS direction supposée

🔑 Pour mesurer **le couple** et non une entrée, les entrées doivent être
aveugles : **une toutes les 12 bougies M5** (donc une par heure), **dans les
deux sens**.

Et je publie **deux panneaux**, parce qu'ils ne répondent pas à la même
question :

1. **PANNEAU NEUTRE** — achat **et** vente au même instant. L'exposition
   directionnelle est nulle, donc la dérive s'annule : ce panneau montre le
   **coût pur** de chaque couple. C'est l'arithmétique rendue visible.
2. **PANNEAU DIRECTIONNEL** — tous les achats d'un côté, toutes les ventes de
   l'autre. C'est là qu'un « meilleur couple » apparaîtra, parce qu'il
   **récolte la dérive** de la période.

## ⛔ LE CRITÈRE, POSÉ AVANT DE REGARDER

Un couple est retenu s'il réunit **les quatre** :

1. P&L par trade **> 0** sur la **seconde moitié** de la période
   (hors échantillon — la première moitié sert à le désigner) ;
2. **|t| > 2,80** hors échantillon, l'unité étant **le JOUR** ;
3. **n ≥ 500** trades hors échantillon ;
4. le **signe** du P&L identique en échantillon **et** hors échantillon.

⇒ Et une condition de méthode : **le couple est désigné sur la première
moitié, puis jugé sur la seconde.** Je ne choisirai pas le meilleur de la
période entière — ce serait exactement l'erreur que ce document existe pour
éviter.

## MA PRÉDICTION, POSÉE MAINTENANT

1. ✅ Le **panneau neutre** donnera **−spread** partout, à la marge
   d'échantillonnage près, sur les 120 couples.
2. ⚠️ Le **panneau directionnel** fera apparaître un « meilleur couple » en
   échantillon, avec des chiffres qui auront l'air bons.
3. ⛔ Et **ce couple ne se répliquera pas** hors échantillon : **0 couple
   retenu sur 120**.

⇒ Si un couple passe les quatre critères, ma prédiction est **réfutée** et
c'est la première chose exploitable de tout ce chantier.

## Ce que cette mesure ne tranche PAS

- Rien sur une **entrée informée** : les entrées sont volontairement aveugles.
  Un couple optimal pour un signal donné dépendrait de l'horizon de ce signal.
- Rien en dessous de **5 minutes** de granularité.
- Rien sur le **réemploi de la marge** ni sur le nombre de positions.

---

# VERDICT — 2026-10-11

`scripts/banc_grille_tp_sl.py`, sur `candles_courtier.db` (99 750 bougies M5,
2025-05-14 → 2026-10-09). **8 313 entrées** aveugles (une toutes les 12
bougies), **dans les deux sens**, coupure d'échantillon au **2026-01-27**,
**218 jours** hors échantillon.

ⓘ Paramètre que la pré-inscription ne fixait pas, déclaré avant de mesurer :
une borne jamais touchée en **24 h** fait une sortie **au prix du marché** —
plutôt que d'écarter ces trades, ce qui aurait sélectionné l'issue. Part
concernée : **0,0 % à 13,8 %** selon le couple.

## ⇒ AUCUN COUPLE RETENU SUR 120. Ma prédiction 3 tient.

    couple designe (meilleur en echantillon)   TP 20 / SL 4 EUR
    en echantillon    +0,3125 $/trade   t +1,61
    hors echantillon  **-0,0769 $/trade   t -0,47**   n 8 312, 218 jours

    ⛔ critere 1 (P&L hors > 0)        ECHOUE
    ⛔ critere 2 (|t| hors > 2,80)     ECHOUE
    ✅ critere 3 (n >= 500)            n = 8 312
    ⛔ critere 4 (meme signe)          +0,3125 dedans, -0,0769 dehors

✅ **Et la prédiction 2 tient aussi** : un « meilleur couple » est bien
apparu en échantillon avec des chiffres d'allure correcte (+0,31 $/trade), et
il s'est **évaporé** hors échantillon.

## ⛔ MAIS MA PRÉDICTION 1 EST RÉFUTÉE — et c'est le vrai résultat du banc

Je prédisais que le panneau neutre donnerait **−spread partout** (≈ −5
centimes). Mesuré, sous la convention pré-inscrite (une bougie qui contient
les deux bornes compte comme un **stop**) :

    mediane des 120 : **-25,36 centimes**   min -130,87   max +16,57
    18 couples sur 120 sont POSITIFS
    diagonale TP=SL : -49,10 (1/1) ... -9,87 (20/20), jamais -5

Alors j'ai **encadré la convention** : même banc, seule la règle d'égalité
changée (la bougie qui contient les deux compte comme un **objectif**) :

    mediane des 120 : **+2,20 centimes**   max +54,91
    63 couples sur 120 positifs
    la case TP1/SL1 passe de **-49,10 a +36,77**  ⇒ **86 centimes d'ecart**

🔑 **Le panneau neutre ne mesure donc PAS le coût : il mesure ma propre
convention.** Deux raisons, et je les avais toutes les deux ratées :

1. **la granularité M5 domine** — plus les bornes sont petites, plus souvent
   une seule bougie de 5 min contient les deux, et c'est la règle d'égalité
   qui décide alors du résultat, pas le marché ;
2. **le panneau n'est symétrique que sur la diagonale** — un achat et une
   vente au même instant avec le même couple n'ont pas des bornes en miroir
   dès que `TP ≠ SL` (l'achat vise `+TP/−SL`, la vente `−TP/+SL`). Mon
   « l'exposition est nulle donc il ne reste que le coût » est faux hors
   diagonale.

## ⛔ ET LA ROUTE INTERDITE LE PROUVE

Tester les 120 et garder ce qui passe — ce que la pré-inscription interdit
**pour conclure** — donne :

    convention "stop"     **0** couple sur 120
    convention "objectif" **29** couples sur 120, t jusqu'a **+25,19**
                          tous a bornes minuscules (TP 1-3, SL 1-1,5)

⇒ Les 29 « gagnants » sont **entièrement fabriqués par la règle d'égalité**.
C'est précisément ce que la pré-inscription existait pour empêcher, et ça
montre à quel point une surface de 120 cellules peut produire du t à 25.

## 🔑 CE QU'IL FAUT RETENIR, et qui dépasse ce banc

**Sur des bougies M5, tout verdict de TP/SL à bornes petites vit à
l'intérieur de l'incertitude de la granularité elle-même.** Largeur de
l'encadrement mesurée :

    TP 1 / SL 1      **0,86 $/trade**
    TP 2 / SL 2      0,64 $/trade
    TP 2 / SL 20 (la production)  **0,107 $/trade**

⚠️ À comparer aux effets que je mesure d'ordinaire : −0,0627 $ pour la fenêtre
des publications, −0,0833 $ pour le 2/20, 0,06 à 0,70 € pour les bancs de
sortie. **Plusieurs de ces verdicts sont plus petits que l'encadrement de la
convention sur leur propre géométrie.**

⇒ Pour trancher des bornes serrées il faut descendre sous la bougie : le
magasin **M1** bâti le même jour (juste à ±1 minute, ordre parfait) réduit
l'encadrement, et les **ticks** — route `/ticks` déployée le 10/10, ~3 ticks
par seconde sur l'or — le fermeraient.

## Réponse à la demande de Xavier, en une phrase

Il n'existe **pas** de « juste couple TP/SL gagnant » sur l'or : sur 120
couples et 17 mois de bougies du courtier, celui qui gagne le mieux en
échantillon perd hors échantillon, et les seuls couples qui « gagnent » sont
ceux que ma propre règle d'arrondi paie.
