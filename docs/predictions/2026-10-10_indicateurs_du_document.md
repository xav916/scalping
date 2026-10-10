# Les indicateurs de GOLD MICROTRADER V1 portent-ils de l'information sur M1 ?

**Déclaré le 2026-10-10, AVANT d'écrire la mesure.** Demande de Xavier :
« construis EMA/VWAP/Z/imbalance d'abord ».

## Pourquoi cette mesure

Le 2026-10-10 j'ai mesuré les **22 familles de motifs du radar** sur 17 505
bougies M1 : **0 retenu sur 22**, avec un `p_hasard` jusqu'à 0,985.

⛔ Mais ce refus ne dit **rien** du document. Ses « patterns » ne sont pas des
motifs de bougies : ce sont des **indicateurs**, et j'ai vérifié qu'**aucun des
quatre n'existe dans le dépôt** (0 occurrence de `vwap`, 0 d'`ema` comme
indicateur, 0 d'`imbalance`). C'est donc de l'information **neuve**.

## Ce que je construis

Quatre indicateurs, tels que le document les définit :

| § | indicateur | définition du document |
|---|------------|------------------------|
| 19 | EMA | EMA 9, EMA 20, EMA 50 sur M1 ; EMA20/EMA50 sur M5 |
| 19 | VWAP | VWAP de session (ancrée à l'ouverture de session) |
| 6 | Z | `Z = (Prix - VWAP) / sigma` |
| 9 | TickImbalance | `(UpTicks - DownTicks) / (UpTicks + DownTicks)` |

Puis ses **deux setups de V1** (§15, « la V1 commence volontairement avec
seulement deux setups ») :

- **SETUP A — Trend Pullback Momentum** (§5) : sur M5 `EMA20 > EMA50`, pente
  EMA20 positive, prix > VWAP ; sur M1 `EMA9 > EMA20` ; le prix retrace vers
  EMA20 ou VWAP puis repart au-dessus de EMA9. Symétrique en vente.
- **SETUP B — Compression → Breakout** (§7) : compression du range, puis
  cassure du plus haut des 10 dernières M1, confirmée par le tick imbalance.

## ⚠️ LA LIMITE, DÉCLARÉE D'AVANCE

**Le tick imbalance de son §9 n'est PAS calculable ici.** Il compte des
*ticks* montants et descendants ; je n'ai que de l'**OHLC M1** chez le
courtier. J'utilise donc un **substitut déclaré** : la position de la clôture
dans le range de la bougie, agrégée sur k bougies —

    imb = moyenne sur k bougies de  ((C - L) - (H - C)) / (H - L)

⇒ Si un setup qui dépend de ce substitut échoue, **je ne pourrai pas conclure
que son tick imbalance échoue** : seulement que mon substitut n'informe pas.
Je le dirai explicitement dans le verdict. Les setups qui ne dépendent que de
EMA/VWAP/Z, eux, sont testés **tels qu'il les écrit**.

## ⛔ LE CRITÈRE, POSÉ AVANT DE REGARDER

Identique à celui des 22 motifs, pour que la comparaison soit à armes égales.
Spread déduit (0,060 $ médian mesuré), bornes **réelles de la production**
(objectif 2 EUR / stop 20 EUR, rejouées bougie par bougie, et en cas
d'ambiguïté dans la même bougie **on prend le stop**).

Pour qu'un signal soit retenu, il doit battre **les trois** :

1. **zéro** — sinon il ne paie pas ses frais ;
2. **la permutation des signes** (2 000 tirages, graine fixe) — sinon le sens
   ne porte rien ;
3. **le même signal tiré à des INSTANTS AU HASARD** — sinon c'est le marché
   qui bouge, pas l'indicateur qui informe.

Et **n ≥ 100** détections pour que la cellule compte.

⇒ Un seul des trois qui manque, et **on ne construit rien**.

## MA PRÉDICTION, POSÉE MAINTENANT

Je prédis **0 retenu**, pour la même raison arithmétique qui a tué les 22
motifs : à objectif 2 EUR contre stop 20 EUR il faut **90,9 %** de réussite, et
aucun signal d'une minute ne tient ça. Je prédis aussi que les setups
**directionnels** (A) feront **moins bien que le hasard**, comme `momentum_up`
(−0,94 $, `p_hasard` 0,877).

⇒ Si un indicateur est retenu, ma prédiction est **réfutée** et c'est une
trouvaille. Si aucun ne l'est, le document est clos sur ses propres termes.

## Ce que cette mesure ne tranche PAS

- Elle ne dit rien d'un **autre couple objectif/stop**. L'asymétrie
  production (0,10 R) est hostile à tout signal court ; c'est mesuré à part.
- Elle ne dit rien des **ticks réels** (cf. la limite déclarée).
- Elle ne dit rien d'un horizon **autre que M1**.

---

# VERDICT, le 2026-10-10

## ⛔ MA PREDICTION EST PARTIELLEMENT REFUTEE

J'avais predit **0 retenu**. Sur la fenetre de 21 jours, **7 cellules** passent
le critere — **toutes** de la meme famille : le **retour a la moyenne sur Z**,
c'est-a-dire son **§6**, celui que le document decide de remettre a plus tard
(« la mean reversion/VWAP viendra ensuite »).

⇒ Les deux setups qu'il choisit de construire d'abord (**A** Trend Pullback
Momentum, **B** Compression -> Breakout) echouent sur **24 cellules sur 24**.
Le seul qui respire est celui qu'il differe.

## CE QUE LES CONTROLES ONT SURVECU, ET CE QU'ILS ONT TUE

| controle | resultat |
|----------|----------|
| zero, permutation, instants au hasard | ✅ passes sur 6 cellules (3 ancrages x 2 sens) |
| **apparie** (base de SON sens) | ✅ passe : achat +1,04 / vente +0,83, t +6,6 / +5,8 |
| effectifs equilibres | ✅ 505 achats contre 441 ventes |
| mon hypothese « |Z|>2 choisit des moments CALMES » | ⛔ **REFUTEE** : l'ATR y est PLUS HAUT (2,11 contre 1,82) et le range des 60 min a venir est identique (14,0 contre 14,9) |
| **mauvais sens aux memes instants** | ✅ 4 cellules sur 6 : seul le bon sens gagne |
| **120 jours, 56 exploitables** | ⚖️ l'effet TOMBE SOUS LA BARRE |

## ⚖️ LE HORS ECHANTILLON : INDECIDABLE

Unite = **le JOUR**, pas la minute (des minutes voisines partagent le meme
mouvement : un t « par minute » est gonfle).

    REGARDE   (15 jours)   ecart moyen +1,6022 $   t = +2,21   11/15 positifs
    JAMAIS VU (41 jours)   ecart moyen +1,0784 $   t = +1,88   26/41 positifs
    ENSEMBLE  (56 jours)   ecart moyen +1,2187 $   t = +2,64   37/56 (66 %)

⇒ L'effet **retrecit de 33 %** hors echantillon et **passe sous |t| = 2**.
Ce n'est ni une confirmation ni une refutation : c'est **INDECIDABLE**, la
meme signature que le banc des surprises economiques.

✅ Mais il n'est **pas** qu'une derive de marche : `r = -0,173` entre l'ecart et
la derive du jour, et l'effet est positif **des deux cotes** — +1,7574 $ les
jours ou l'achat etait favorise, +0,7517 $ les jours ou la vente l'etait.

## ⛔ ET LE POINT QUI DECIDE POUR LA PRODUCTION

Sur les 56 jours, le meme signal rejoue a plusieurs bornes :

    bornes TP/SL ($)    n      BON sens   MAUVAIS    ECART      t
      2,24 / 22,40    4754     +0,0024    -0,3034   +0,3058   +2,46   <- PRODUCTION
      2,24 /  2,24    4754     -0,0886    -0,1433   +0,0547   +1,19
      5,00 /  5,00    4754     +0,0673    -0,1800   +0,2473   +2,43
     10,00 / 10,00    4754     +0,5794    -0,6794   +1,2589   +6,97

🔑 **Aux bornes REELLES de la production, le bon sens rend +0,0024 $ par
trade — zero.** L'information existe (le mauvais sens perd −0,30), mais
l'objectif a 2 EUR **la rend avant qu'elle se materialise** : elle vit dans la
derive a l'heure, qui demande une cible de l'ordre de **10 $ (~9 EUR)**.

⚠️ Et mon premier chiffre etait gonfle par la fenetre : +0,96 $ par trade sur
21 jours, **+0,0024 $ sur 56**. Un facteur 400. Je le dis parce que j'ai failli
l'annoncer comme une trouvaille.

## CE QU'ON NE CONSTRUIT PAS, ET CE QUI RESTE

⛔ **On n'arme rien.** Un signal indecidable hors echantillon et nul aux bornes
de production ne justifie aucune ligne de code en production.

🔬 La seule question que la mesure rend legitime : **le couple objectif/stop**.
C'est la troisieme fois qu'une mesure independante y revient (les chemins de la
semaine, l'asymetrie du document, et maintenant Z). Elle est deja posee et
attend une decision de Xavier.

⚠️ Multiplicite : 37 cellules en partie 1. Les 6 cellules de |Z|>2 sont
fortement correlees (memes instants, 3 ancrages) — c'est **une** hypothese
mesuree 6 fois, pas 6 hypotheses. Et son seuil |Z|>2 vient de **son §6**, pas
de mon ajustement : rien n'a ete calibre sur les donnees.
