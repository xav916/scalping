# Pré-inscription — hors échantillon `5min`, **bras réel RECALCULÉ**

**Date** : 2026-10-27 · **Écrit AVANT la mesure symétrique.**
**Origine** : `49a3810`. Le premier hors échantillon est **inutilisable** :
le bras réel portait les issues **calculées en août par la production**, le
placebo des bougies **du jour** — **24,5 % de désaccord**, dont **+229 TP1
excédentaires** côté réel, soit ≈ **+0,15 R d'artefact**.

## Ce qui change, et ce qui ne change pas

**Change** : le bras réel est **RECALCULÉ** sur les bougies du jour, avec le
même moteur, la même règle de sortie et le même coût que le placebo. Les deux
bras partagent alors **le même instantané de donnée**.

**Ne change pas** : la population (les mêmes 4 280 lignes vécues, 7 paires
Binance, barres avant le 20/08), la géométrie de chaque setup (son `entry`, son
`sl`, son `tp` et son sens, **tels qu'ils ont été décidés en août**), le
placebo, la fenêtre de 96 h, la graine.

⛔ **RIEN N'EST ÉCRIT EN BASE.** Les issues d'août restent la trace de ce que la
production a calculé à l'époque ; les écraser détruirait cette trace sans
bénéfice pour la mesure. Le recalcul vit **en mémoire**.

⚠️ **Ce banc cesse donc de tester le « chemin de résolution »** et devient un
test de **PÉRIODE SEULE** : les décisions d'entrée viennent bien d'août, leurs
issues sont jugées avec la donnée d'aujourd'hui. C'est moins que ce que visait
le banc précédent, et c'est propre.

## ⚠️ DIVULGATION : je peux estimer la réponse avant de mesurer

Le contrôle de provenance me donne de quoi la dériver :

```
reel STOCKE  = +0,0902 R
artefact     = 229 / 4 280 x (1,8 + 1) = +0,1498 R
=> reel RECALCULE attendu  ~  0,0902 - 0,1498 = -0,0596 R
placebo (inchange)         =  -0,1467 R
=> ecart attendu           ~  +0,0871 R
t attendu : 0,0871 / 0,0202 ~ +4,3     (SE deduit du t = 11,71 pour 0,2369)
```

🔑 **L'écart attendu (+0,087 R) reste SUPÉRIEUR à celui en échantillon
(+0,0557 R)**, d'un facteur 1,6 et non 4,3. Un effet mesuré sur 4 280
observations n'a aucune raison d'égaler celui mesuré sur 18 668 : seul le `t`
rétrécit en `√n`, pas la taille de l'effet. **1,6× est dans le plausible ;
4,3× ne l'était pas.**

<!-- CRITERE-MACHINE
statistique: ecart_signal_reel_moins_placebo
convention: A
horizon: 5min
fenetre_heures: 96
source_bras_reel: RECALCULE
population: resolved_backfill=0 AND timeframe=5min AND pair IN 7_BINANCE AND bar_timestamp < 2026-08-20
fin_chargement: 2026-10-27T18:00:00+00:00
tirages_placebo: 200
cellules: 1
correction_multiplicite: PLAFOND_PAR_PERMUTATION_200_TIRAGES
reference_en_echantillon_ecart: 0.0557
reference_stocke_ecart: 0.2369
validite: n_reel >= 3500 ET couverture_bougies_pct > 99 ET abs(risk_pct_median_placebo - risk_pct_median_reel) < 0.01 ET tirages_aboutis >= 190
admission: ecart_signal > 0 ET t_contre_placebo > 2.00 ET tirages_battus_pct >= 95.0
rejet: abs(t_contre_placebo) < 2.00
P1_ecart_signal_min: 0.0
P2_t_contre_placebo_min: 2.00
P3_esperance_R_reel_attendue_max: 0.0
P4_ecart_signal_max: 0.15
P5_desaccord_avec_stocke_pct_min: 20.0
-->

⚠️ Même correspondance que la fois précédente : `admission` **= signal
CONFIRMÉ**, `rejet` **= signal ÉVAPORÉ**. Les noms sont ceux que l'outillage
lit.

🔑 **`P4_ecart_signal_max: 0.15` est le garde-fou de ce banc** : si l'écart
recalculé **dépasse encore 0,15 R**, l'artefact n'a pas été éliminé et il reste
une asymétrie que je n'ai pas trouvée. **Ce n'est pas une prédiction de
confort : c'est la condition qui me ferait dire « je ne comprends toujours
pas ».**

## Prédictions, dites d'avance

1. **L'écart restera POSITIF** : `> 0`.
2. **Il restera significatif** : `t > +2,00`, attendu ≈ **+4,3**.
3. **L'espérance réelle RECALCULÉE sera NÉGATIVE** (`< 0`), attendue
   ≈ **−0,060 R** : le coût hors échantillon (0,0950 R) dépasse le signal.
   🔑 **Le signal peut tenir pendant que la stratégie perd**, et le recalcul
   doit le montrer plus franchement que la version stockée.
4. **L'écart ne dépassera PAS 0,15 R** — sinon l'artefact subsiste et je le
   dirai.
5. **Le désaccord avec les issues stockées sera ≥ 20 %** : c'est la mesure de
   provenance déjà faite (24,5 %), que le banc doit reproduire. ⛔ S'il tombe
   bien plus bas, c'est que je ne recalcule pas ce que je crois recalculer.

## Critère de décision

**VALIDITÉ** — inchangée, plus une exigence nouvelle implicite : les deux bras
sont calculés **dans la même passe**, sur les **mêmes séries**.

**CONFIRMÉ** (`admission`) : `ecart_signal > 0 ET t > +2,00 ET battus >= 95 %`
**ÉVAPORÉ** (`rejet`) : `abs(t) < 2,00`

### Ce que chaque issue implique

- **CONFIRMÉ avec P4 tenu** ⇒ le signal du `5min` existe sur **deux périodes
  disjointes**, mesuré proprement. Ce serait **la première réplication de ce
  mur**. ⛔ Et toujours **pas exploitable** : à −0,06 R net hors échantillon,
  la stratégie **perd** — le signal ne paie ni ici ni en échantillon.
- **CONFIRMÉ mais P4 violé** ⇒ **je ne conclus rien** : un écart encore
  supérieur à 0,15 R signifierait une asymétrie résiduelle non identifiée.
- **ÉVAPORÉ** ⇒ le signal était un artefact de période, et le `5min` rejoint
  le `1d` et le `4h`. **Aucun horizon n'aurait d'information établie.**

## ⚠️ Limites, posées d'avance

- **Période contiguë** : 05 → 19/08, immédiatement avant l'échantillon. Ce
  n'est pas un régime lointain, et le **prospectif du 13 novembre** reste le
  test décisif.
- **Les décisions d'entrée datent d'août, les issues du jour.** Un setup dont
  les bornes ont été calculées sur des prix d'époque est jugé sur des bougies
  re-téléchargées : si la source a changé de contrat ou de convention, le
  recalcul le propagera. C'est précisément ce que `P5` surveille.
- Une seule cellule pré-spécifiée ; **aucune autre ne sera testée après coup.**
