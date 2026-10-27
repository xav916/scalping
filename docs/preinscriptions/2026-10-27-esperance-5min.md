# Pré-inscription — l'espérance de l'horizon `5min`, avec placebo

**Date** : 2026-10-27 · **Écrit AVANT toute mesure d'espérance.**
**Origine** : le `1d` fait **pire** que le hasard (`0b8106b`, `t = −4,23`) et le
`4h` en est **indiscernable** (`bc6c2be`, `t = −0,98`). Le `5min` est le
**dernier horizon non mesuré** — et celui qui porte le volume : **18 668
setups**, dix fois le `4h`.

## Ce que la forme de la population impose — mesuré avant d'écrire

```
n = 18 668, periode 2026-08-20 -> 2026-10-26, fenetre 96 h
SENS EQUILIBRE : 9 360 ventes / 9 308 achats
7 paires a ~2 650 (BTC, XRP, DOT, ETH, LTC, SOL, ADA) + AVAX 15 + SUI 13
TIMEOUT : 112 sur 18 668, soit 0,67 %
risk_pct median 0,5058 %  =>  cout = 0,0395 R
issues : SL 11 563 · TP1 6 993 · TIMEOUT 112
99,85 % des setups sont sur Binance (gratuit, sans quota)
```

Trois conséquences, et chacune **change une prédiction** par rapport aux deux
bancs précédents :

1. ✅ **Le sens est ÉQUILIBRÉ** (50,1 % / 49,9 %), là où le `4h` était à 100 %
   acheteur. La dérive de la période s'annule donc largement ⇒ **je peux de
   nouveau prédire un placebo proche de zéro**, et cette prédiction redevient
   un **test du banc** (comme pour le `1d`), pas une tolérance large.
2. ⛔ **`TIMEOUT` à 0,67 %** contre 46,5 % pour le `1d` ⇒ les conventions A et
   B sont presque identiques. **Je ne reprends donc PAS la prédiction « B plus
   négative que A d'au moins 0,05 R »** : ici il n'y a quasiment rien à diluer,
   et la recopier fabriquerait un faux échec.
3. 🔑 **Le coût est intermédiaire** : 0,0395 R, entre les 0,0021 R du `1d` et
   les 0,0537 R du `4h`.

## ⚠️ DIVULGATION : ce que j'ai déjà vu avant d'écrire

J'ai vu la distribution des issues, donc le **taux de réussite parmi les
résolus : 6 993 / 18 556 = 37,69 %** — **au-dessus** des **35,71 %** qu'exige
un R:R de 1,8.

L'arithmétique donne alors, brut :
`0,3769 × 1,8 − 0,6231 × 1 = +0,055 R`, moins le coût de 0,0395 R, soit
**≈ +0,016 R net**.

⇒ **Je ne peux donc pas prédire une espérance négative**, comme je l'ai fait
pour le `1d` et le `4h`. Je prédis une espérance **petite et positive**, et
**inférieure au coût**, ce qui ferait échouer l'admission sur le coût seul.
Mais l'espérance réelle dépend des **prix de sortie effectifs** et du P&L des
`TIMEOUT`, que je n'ai **pas** mesurés : la prédiction reste falsifiable.

<!-- CRITERE-MACHINE
statistique: esperance_R_par_setup
convention: A
horizon: 5min
fenetre_heures: 96
fin_chargement: 2026-10-27T13:00:00+00:00
tirages_placebo: 200
cellules: 1
correction_multiplicite: PLAFOND_PAR_PERMUTATION_200_TIRAGES
population: resolved_backfill=1 AND timeframe=5min
validite: n_reel >= 15000 ET couverture_bougies_pct > 99 ET abs(risk_pct_median_placebo - risk_pct_median_reel) < 0.05 ET tirages_aboutis >= 190
admission: esperance_R_reel > cout_R_median ET t_contre_placebo > 2.00 ET tirages_battus_pct >= 95.0
rejet: esperance_R_reel <= 0 ET t_contre_placebo < 2.00
indecidable: abs(t_contre_placebo) < 2.00 ET tirages_battus_pct < 95.0
P1_esperance_R_reel_attendue_min: -0.05
P2_esperance_R_placebo_abs_max: 0.05
P3_tirages_battus_pct_attendu_max: 95.0
P4_ecart_conventions_A_B_abs_max: 0.02
P5_cout_R_median_min: 0.03
-->

⛔ **`indecidable` ne porte plus sur un écart absolu en R.** Sur le `4h`, je
l'avais pré-inscrit à `abs(reel − placebo) < 0,01 R` : à `risk_pct` de 0,37 %
c'était **inopérant par construction**, et la branche `rejet` s'est déclenchée
là où « aucune information » décrivait mieux les faits. **Le seuil porte
désormais sur le `t` et la part de tirages battus** — les deux quantités qui
disent réellement si le réel se distingue du hasard.

🔑 **`fin_chargement` est nouveau** : le chargement des bougies est borné à une
date FIXE, et non plus à `max(barre) + 120 h`, qui tombait **dans le futur**.
C'est ce qui a fait bouger l'espérance du placebo de `1,1e−5 R` entre deux
passes du `4h`. **« Reproductible » doit vouloir dire bit pour bit.**

## Prédictions, dites d'avance

1. **L'espérance réelle sera PETITE ET POSITIVE** : `> −0,05 R`, et je table
   sur ≈ **+0,016 R** d'après l'arithmétique du taux de réussite. ⛔ C'est la
   première fois sur ce mur que je ne prédis pas une espérance négative.
2. **Le placebo sera proche de zéro** : `|moyenne| < 0,05 R`, le sens étant
   équilibré. ⛔ **Si le placebo s'en écarte franchement, c'est le BANC qui est
   faux**, pas une découverte.
3. **Le réel ne battra PAS 95 % des 200 tirages.** Autrement dit : même une
   espérance positive ne se distinguera pas du hasard, parce que **+0,016 R est
   sous le coût de 0,0395 R** — et un placebo neutre place la barre à zéro, pas
   en dessous.
4. **L'écart entre conventions A et B sera PETIT** : `|A − B| < 0,02 R`,
   contre **0,20 R** sur le `1d`. Avec 0,67 % de `TIMEOUT`, il n'y a presque
   rien à diluer.
5. **Le coût sera intermédiaire et matériel** : `> 0,03 R`. À ≈ +0,016 R
   d'espérance, **le coût à lui seul interdit l'admission** — et c'est le fait
   le plus décisif de cette pré-inscription.

## Critère de décision

**VALIDITÉ** — si elle échoue, **rien n'est conclu, dans aucun sens** :

    n_reel >= 15000  ET  couverture > 99 %
    ET  |risk_pct_median_placebo − risk_pct_median_reel| < 0,05 pt
    ET  tirages_aboutis >= 190 sur 200

**ADMISSION — l'instant d'entrée du `5min` porte une information exploitable** :

    esperance_R_reel > cout_R_median  ET  t_contre_placebo > +2,00
    ET  tirages_battus >= 95 %

**REJET** : `esperance_R_reel <= 0 ET t_contre_placebo < +2,00`

**INDÉCIDABLE** : `|t_contre_placebo| < 2,00 ET tirages_battus < 95 %` — le
réel ne se distingue pas du hasard, quel que soit le signe de l'espérance.

### Ce que chaque issue implique

- **Admission** ⇒ **la première information retenue sur ce mur**, et elle
  exigerait une mesure **hors échantillon** avant toute production.
- **Indécidable** ⇒ le `5min` rejoint le `4h` : aucune information à l'entrée.
  **Les trois horizons seraient alors épuisés.**
- **Rejet** ⇒ pire encore : il ferait moins bien que le hasard, comme le `1d`.

## ⚠️ Limites, posées d'avance

- Donnée **rattrapée**, un seul régime de marché (~68 jours).
- **Crypto uniquement** en pratique (99,85 %) : rien sur le forex ni les
  métaux.
- Une seule cellule pré-spécifiée ; **aucune autre ne sera testée après coup
  sur cette donnée.**
- ⚠️ **~3,7 M simulations** (18 668 × 200) : le contrôle du moteur vectorisé
  contre la production reste obligatoire, et son échec doit **arrêter** le banc.
