# Pré-inscription — le signal `5min` tient-il HORS ÉCHANTILLON ?

**Date** : 2026-10-27 · **Écrit AVANT toute mesure hors échantillon.**
**Origine** : `78375ca`. En échantillon, le `5min` bat le placebo de
**+0,0557 R** avec `t = +6,28` et **200 tirages sur 200** — le premier signal
positif de ce mur. Mais c'est **un seul régime de 68 jours, en donnée
rattrapée**, et c'est exactement le profil des deux trouvailles du 08/10 qui se
sont évaporées (`t +2,28 → +0,52`, `+2,09 → +0,16`).

## La population hors échantillon — mesurée avant d'écrire

```
donnee VECUE (resolved_backfill = 0), 7 memes paires Binance,
barres STRICTEMENT avant 2026-08-20

n = 4 280     periode 2026-08-05 -> 2026-08-19  (15 jours)
sens : 2 142 achats / 2 138 ventes            <- equilibre, comme en echantillon
risk_pct median : 0,2106 %                    <- CONTRE 0,5059 % en echantillon
=> cout = 0,0951 R                            <- CONTRE 0,0395 R, soit 2,4x
chevauchement temporel avec l echantillon : 54 lignes, EXCLUES
```

🔴 **Le `risk_pct` est deux fois plus serré hors échantillon.** Marché plus
calme début août ⇒ `recent_low − ATR×k` sur 5 bougies donne des stops plus
courts ⇒ **le coût relatif double**.

⇒ **Conséquence décisive sur le choix de la statistique** : comparer les
**espérances nettes** entre les deux échantillons serait **confondu par le
coût**. On teste donc l'**écart réel − placebo**, qui est **invariant au coût**
puisque les deux bras le paient à l'identique.

## Critère

**La statistique** : `ecart_signal = esperance_R_reel − esperance_R_placebo`,
convention **A**, contre le même placebo de 200 tirages (mêmes paires, même
nombre par paire, même période, même `risk_pct`, même sens, même fenêtre de
96 h ; seul l'instant d'entrée est tiré).

**Référence en échantillon** : `ecart_signal = +0,0557 R`, `t = +6,28`,
200/200 tirages battus.

<!-- CRITERE-MACHINE
statistique: ecart_signal_reel_moins_placebo
convention: A
horizon: 5min
fenetre_heures: 96
population: resolved_backfill=0 AND timeframe=5min AND pair IN 7_BINANCE AND bar_timestamp < 2026-08-20
fin_chargement: 2026-10-27T18:00:00+00:00
tirages_placebo: 200
cellules: 1
correction_multiplicite: PLAFOND_PAR_PERMUTATION_200_TIRAGES
reference_en_echantillon_ecart: 0.0557
reference_en_echantillon_t: 6.28
validite: n_reel >= 3500 ET couverture_bougies_pct > 99 ET abs(risk_pct_median_placebo - risk_pct_median_reel) < 0.01 ET tirages_aboutis >= 190
admission: ecart_signal > 0 ET t_contre_placebo > 2.00 ET tirages_battus_pct >= 95.0
rejet: abs(t_contre_placebo) < 2.00
inverse: ecart_signal < 0 ET t_contre_placebo < -2.00
P1_ecart_signal_min: 0.0
P2_t_contre_placebo_min: 2.00
P3_esperance_R_reel_attendue_max: 0.0
P4_esperance_R_placebo_attendue_max: -0.05
P5_t_hors_echantillon_max: 6.28
-->

⚠️ **Les clés gardent les noms que l'outillage lit** (`admission`, `rejet`),
mais **leur SENS ici est différent** et il faut le lire comme tel :

| clé engagée | ce qu'elle signifie dans CE banc |
|---|---|
| `admission` | le signal est **CONFIRMÉ** hors échantillon |
| `rejet` | le signal est **ÉVAPORÉ** — il ne se distingue plus du hasard |
| `inverse` | le signal **se retourne** : pire que le hasard |

⛔ La question n'est **pas** « faut-il admettre cette règle » : on sait déjà
qu'à +0,0014 R net elle ne paie pas. La question est **le signal se
reproduit-il**. J'ai d'abord nommé les clés `confirme` / `evapore`, et
`or-preinscription` l'a refusé — à juste titre : sans `rejet`, `or-verdict`
refuserait ce verdict **à perpétuité**. Les noms de l'outillage l'emportent sur
mes préférences de vocabulaire.

🔑 **`rejet` porte sur `abs(t) < 2,00`**, sans condition de signe : un signal
qui ne se distingue plus du hasard est évaporé **quel que soit** le signe de
l'écart. C'est la correction de l'erreur du `4h`, où un seuil en R était
inopérant par construction.

## Prédictions, dites d'avance

1. **L'écart restera POSITIF** : `ecart_signal > 0`.
2. **Il restera significatif** : `t > +2,00`. Attendu ≈ **+3,0** — l'effet
   divisé par `√(18 668 / 4 280) = √4,36 = 2,09`, soit `6,28 / 2,09`. ⛔ Si le
   `t` tombe sous 2, le signal est évaporé et je le dirai sans chercher
   d'excuse de taille d'échantillon : **la prédiction tient compte de la
   taille**.
3. **L'espérance NETTE réelle sera NÉGATIVE** (`< 0`), malgré un signal
   intact : le coût vaut **0,0951 R** hors échantillon contre un signal de
   ≈ 0,056 R. 🔑 **Le signal peut tenir pendant que la stratégie perd** — et
   c'est le point le plus important de cette pré-inscription.
4. **Le placebo sera proche de −(coût)**, soit `< −0,05 R` et attendu
   ≈ **−0,095 R**. ⛔ **Correction explicite de mon erreur du banc `5min`**, où
   j'avais posé une barre de « placebo proche de zéro » à 0,050 alors que le
   coût seul valait 0,0395 : un placebo paie le coût, il n'est **jamais**
   proche de zéro en net.
5. **Le `t` hors échantillon sera INFÉRIEUR à +6,28**, par simple effet de
   taille.

## Critère de décision

**VALIDITÉ** — si elle échoue, **rien n'est conclu** :

    n_reel >= 3500  ET  couverture > 99 %
    ET  |risk_pct_median_placebo − risk_pct_median_reel| < 0,01 pt
    ET  tirages_aboutis >= 190 sur 200

⚠️ La tolérance de `risk_pct` porte sur **réel contre placebo** à l'intérieur du
hors échantillon, **pas** entre les deux échantillons : ceux-là diffèrent
par construction (0,21 % contre 0,51 %), et c'est un fait, pas un défaut.

**CONFIRMÉ** : `ecart_signal > 0 ET t > +2,00 ET tirages_battus >= 95 %`
**ÉVAPORÉ** : `abs(t) < 2,00`
**INVERSÉ** : `ecart_signal < 0 ET t < −2,00`

### Ce que chaque issue implique

- **CONFIRMÉ** ⇒ le signal du `5min` existe sur **deux régimes disjoints**.
  Ce serait **la première trouvaille de ce mur à survivre hors échantillon**.
  ⛔ Et ça ne la rend toujours **pas** exploitable : à ce coût, elle perd. La
  suite serait alors « réduire le coût ou capter un mouvement plus grand », pas
  « mettre en production ».
- **ÉVAPORÉ** ⇒ le `5min` rejoint le `1d` et le `4h`. **Aucun horizon de ce
  système n'aurait d'information établie**, et la série serait close.
- **INVERSÉ** ⇒ pire : le signal se retourne d'un régime à l'autre, ce qui
  signifierait qu'on mesurait une particularité de période.

## ⚠️ Limites, posées d'avance

- 🔴 **Hors échantillon FAIBLE, et je le dis maintenant** : la période (05 →
  19/08) **précède immédiatement** l'échantillon et n'en est séparée que par un
  jour. Ce n'est pas un régime lointain. Un vrai hors échantillon serait
  **prospectif** — la réconciliation fonctionne depuis le 26/10 et produit
  ~300 setups/jour, donc **~4 000 setups vers le 13 novembre**. Celui-ci est le
  **meilleur disponible aujourd'hui**, pas le meilleur possible.
- ✅ **Mais il change DEUX choses à la fois** : période **et** chemin de
  résolution (vécu au lieu de rattrapé). Un signal qui survit aux deux est plus
  crédible qu'un simple découpage.
- ⚠️ **Le banc devra être adapté** pour lire `resolved_backfill = 0` et
  restreindre l'univers : il code aujourd'hui `= 1` en dur. L'adaptation sera
  **postérieure à ce commit**, et `or-preinscription` refusera de nouveau
  l'antériorité du **fichier** partagé — comme pour le `5min`, ce sera dit en
  clair dans le verdict.
- Une seule cellule pré-spécifiée ; **aucune autre ne sera testée après coup
  sur cette donnée.**
