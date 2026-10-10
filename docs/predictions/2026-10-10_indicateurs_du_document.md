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
