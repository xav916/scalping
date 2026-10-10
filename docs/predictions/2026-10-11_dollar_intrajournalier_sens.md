# Le dollar donne-t-il le SENS de l'or à l'échelle de la MINUTE ?

**Déclaré le 2026-10-11, AVANT de mesurer.** Demande de Xavier : « ce que je
veux, c'est pouvoir déterminer le sens du trade — buy ou sell ».

## Pourquoi cette piste, et pourquoi c'est la dernière sérieuse

Tout ce qui a été atteint hier dit « pièce de monnaie » :

    22 motifs sur M1                          0 retenu    (p_hasard  0,985)
    498 cellules de labo (M1/M3/M5/…/M60)     0 retenue   (plafond 3,03)
    direction a 6 geometries, 64 062 obs      49,83 %     une piece
    dollar/taux/VIX/SPX en DECALE             0/12        tous |t| <= 1,23
    surprise economique                       0/363       (plafond 3,153)
    order flow reel                           buy=0, sell=0 -> INEXISTANT

🔑 **Mais un seul chiffre de la journée était fort** : l'or contre le dollar
**le même jour** donne `r = −0,4229`, **t = −8,78** sur 356 jours.

Ce n'est pas un motif, c'est un **mécanisme** : l'or est coté **en** dollars,
donc un mouvement du dollar déplace mécaniquement son prix. Et je ne l'ai
testé qu'**au jour** et qu'**en décalé** — les deux morts. Mon test ne pouvait
pas **voir dedans** : `macro_daily` est quotidien.

⇒ La question n'a jamais été posée à l'horizon où Xavier trade.

## ✅ Ce que j'ai vérifié avant de pré-inscrire

Le pont sert du **M1** sur les cinq paires qui font le dollar, du **même
courtier** et de la **même horloge** que l'or :

    XAU/USD  EUR/USD  USD/JPY  GBP/USD  USD/CHF  AUD/USD
    (USD/CAD rend 502 — non utilisé)

🔑 Et la synchronisation est **résolue** : chaque réponse porte son
`decalage_serveur_sec`, et la correction déterministe
`−decalage_serveur_sec/60 + 180` (vérifiée hier sur 21 jours / 154 ancres) les
ramène toutes en **UTC vrai**. Sans elle, cette mesure serait impossible.

## L'indice dollar, défini explicitement

Rendement du dollar à la minute = **moyenne équipondérée** des rendements de
l'USD contre les cinq devises :

    +r(USD/JPY)  +r(USD/CHF)  −r(EUR/USD)  −r(GBP/USD)  −r(AUD/USD)

⚠️ Ce n'est **pas** le DXY officiel (il pondère EUR à 57,6 % et inclut CAD et
SEK). C'est un **facteur dollar** équipondéré, et je le dis plutôt que de
prétendre reproduire un indice que je n'ai pas.

## ⛔ LA PORTE DE VALIDITÉ

La corrélation au **décalage ZÉRO** entre le facteur dollar et l'or doit être
**négative et forte**, cohérente avec le `−0,42` journalier.

⇒ **Porte : `r(décalage 0)` doit être < −0,20.** Sinon ma synchronisation est
fausse — et **aucun verdict n'est rendu**.

⚠️ Et le corrélogramme doit montrer un **pic au décalage 0**. Un pic ailleurs,
ou pas de pic du tout, dirait que l'alignement est faux.

## CE QUE JE MESURE

Corrélation croisée entre le rendement du dollar à `t − k` et le rendement de
l'or à `t`, pour **k de −30 à +30 minutes**, à trois largeurs de fenêtre
**w = 1, 5 et 15 minutes**.

- `k > 0` : le **dollar MÈNE** — c'est le seul cas exploitable ;
- `k = 0` : simultané, non exploitable, c'est la porte ;
- `k < 0` : l'or mènerait le dollar — contrôle de symétrie.

## ⛔ LE CRITÈRE, POSÉ AVANT DE REGARDER

Le dollar donne le sens si, à un décalage **k ≥ 1 minute**, il réunit **les
cinq** :

1. corrélation **non nulle** et de **signe négatif** (cohérent avec le
   mécanisme) ;
2. **|t| > 2,730** — le plafond du laboratoire pour ~96 cellules
   (30 décalages positifs × 3 fenêtres = 90) ;
3. **n ≥ 10 000** minutes appariées ;
4. signe **stable sur les deux moitiés** de la période ;
5. et l'avantage implicite doit **dépasser le spread** : converti en euros sur
   0,01 lot, le gain espéré par trade doit excéder **0,045 €**.

⇒ Un seul qui manque, et le dollar ne donne pas le sens à cet horizon.

## MA PRÉDICTION, POSÉE MAINTENANT

✅ Je prédis que **la porte PASSE** : `r(0)` sera entre **−0,25 et −0,60**.

⛔ Et je prédis **0 décalage retenu pour k ≥ 1** : l'information est consommée
**à l'intérieur de la première minute**. Motif : le couple or/dollar est l'une
des relations les plus arbitrées du marché, et le test journalier a déjà montré
qu'il ne reste rien à J+1.

⇒ Si un décalage `k ≥ 1` est retenu, ma prédiction est **réfutée**, et c'est
alors la première source de direction de tout ce chantier.

## Ce que cette mesure ne tranche PAS

- Elle ne dit rien d'une **rentabilité** : une corrélation n'est pas un P&L.
  Il faudrait ensuite la rejouer avec des bornes et le spread.
- Elle ne teste pas l'**or menant le dollar** comme piste (le `k < 0` n'est là
  que comme contrôle de symétrie).
- Elle ne dit rien des **autres métaux**.
