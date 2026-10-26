# Pré-inscription — la géométrie des setups `1d` peut-elle payer ?

**Date** : 2026-10-26 · **Écrit AVANT toute requête de mesure.**
**Origine** : piste laissée ouverte par le verdict `c2dbc62` — les setups `1d`
exigent un TP médian de **21,3 %** (crypto) / **17,3 %** (autres) pour un `mfe`
médian de 6,1 % / 4,9 %, soit **25 fois** la distance du `4h` (0,64 %).

## ⛔ Ce que j'avais dit et que je retire d'avance

J'ai écrit « ressemble à un réglage mal mis à l'échelle pour l'horizon
journalier ». **La lecture du code rend cette formulation probablement
fausse** : le chemin générique de `calculate_trade_setup` est

```python
atr_k = _atr_buffer_mult(atr, entry)
recent_low = min(c.low for c in candles[-5:])     # 5 BOUGIES de l'horizon
stop_loss  = recent_low - atr * atr_k
risk       = entry - stop_loss
take_profit_1 = entry + risk * PATTERN_TP1_RR     # RR = 1,8
```

Sur un horizon `1d`, « les 5 dernières bougies » couvrent **cinq jours** et
l'ATR est journalier. Une distance de 21 % peut donc être la **conséquence
exacte et correcte** de la formule. La question n'est pas « y a-t-il un bug »
mais « cette géométrie peut-elle payer ».

## Critère — les trois questions, dans l'ordre

1. **La formule est-elle appliquée correctement en `1d` ?**
2. **Si oui, le taux de réussite atteint-il ce que le R:R exige ?**
3. Le traitement des `TIMEOUT` change-t-il la réponse ?

<!-- CRITERE-MACHINE
RR_attendu: 1.80
RR_tolerance: 0.05
cellules: 1
correction_multiplicite: AUCUNE_REQUISE
population: resolved_backfill=1 AND timeframe=1d
reussite_requise_pct: 35.71

# VALIDITE DU REJEU -- condition sur la DONNEE, distincte du critere de
# decision. Si elle echoue, le banc ne conclut RIEN, dans aucun sens.
validite: n_resolus_1d >= 300 ET part_mfe_non_nul_pct > 99 ET part_rows_RR_conforme_pct > 95

# ADMISSION -- l horizon 1d est CONSERVE. Formulee en positif et sur un
# seuil chiffre : la geometrie tient son exigence arithmetique.
admission: reussite_1d_resolus_pct >= 35.71 ET z_binomial >= -2.00

# REJET -- l horizon 1d est ECARTE.
rejet: reussite_1d_resolus_pct < 35.71 ET z_binomial < -2.00

# INDECIDABLE si les deux conventions de TIMEOUT divergent.
indecidable: abs(ecart_convention_A_B_pt) >= 5.0

# Controles
P1_part_rows_RR_conforme_pct_min: 95.0
P2_risk_pct_1d_median_min: 9.0
P2_risk_pct_1d_median_max: 15.0
P4_controle_4h_RR_conforme_pct_min: 95.0
placebo: NON_EXECUTE
-->

Le bloc ci-dessus est le critere ENGAGE : c est lui que `or-verdict` hache,
pas la prose. La prose peut etre reecrite sans toucher a l empreinte ; les
seuils, non.
## Prédictions, dites d'avance

1. **La formule est correctement appliquée** : le rapport
   `|TP − entry| / |entry − SL|` vaudra **1,80 ± 0,05** pour **> 95 %** des
   setups `1d`. ⇒ si P1 passe, **je retire publiquement « mal mis à
   l'échelle »** : il n'y a pas de bug d'échelle, seulement une géométrie
   large.
2. Le **risque** en `1d` sera de **9 % à 15 %** du prix (médiane attendue
   ≈ 11,8 %, soit 21,3 / 1,8).
3. **Le taux de réussite des `1d` résolus (TP1 vs SL, `TIMEOUT` exclus) sera
   SOUS les 35,71 % requis**, avec `z < −2,00`. Sur ~594 résolus attendus,
   l'erreur type vaut ≈ 1,97 pt : un déficit de 4 points est détectable.
4. **Contrôle `4h`** : le même rapport y sera aussi conforme à 1,80
   (> 95 %) — autrement dit l'écart entre horizons vient du **stop**, pas du
   R:R.
5. **Les deux conventions de `TIMEOUT` donneront le même sens** :
   - **A** — `TIMEOUT` compté à son P&L réel (dernier prix connu) ;
   - **B** — `TIMEOUT` exclu, réussite sur TP1/(TP1+SL) seuls.
   L'écart de taux de réussite entre A et B restera **sous 5 points**.

## Critère de décision

Les trois conditions sont celles du bloc machine ci-dessus, redites en clair.

**VALIDITÉ DU REJEU** — condition sur la *donnée*, distincte de la décision.
Si elle échoue, **le banc ne conclut rien, dans aucun sens** :

    n_resolus_1d >= 300  ET  part_mfe_non_nul > 99 %  ET  RR conforme > 95 %

**ADMISSION — l'horizon `1d` est CONSERVÉ** :

    reussite_1d_resolus >= 35,71 %   ET   z_binomial >= -2,00

**REJET — l'horizon `1d` est ÉCARTÉ** :

    reussite_1d_resolus < 35,71 %    ET   z_binomial < -2,00

**INDÉCIDABLE** si les deux conventions de `TIMEOUT` divergent de **5 points
ou plus**. La réponse dépendrait alors d'une convention de clôture arbitraire,
et aucune décision ne doit être prise là-dessus.

Et une conséquence qui ne dépend d'aucun seuil : **si P1 passe, je retire
« mal mis à l'échelle »**. Il n'y aurait alors pas de bug d'échelle, seulement
une géométrie large — et l'écarter pour un bug inexistant serait se tromper de
raison même en ayant la bonne conclusion.

### Ce que chaque issue implique

- **Validité ✗** ⇒ rien. On répare la donnée, on ne conclut pas.
- **P1 ✗** ⇒ incohérence de calcul : c'est elle qu'on corrige d'abord, et le
  reste du banc devient sans objet.
- **Rejet** ⇒ la géométrie `1d` est correctement calculée et **structurellement
  perdante** : elle exige 35,7 % et ne les obtient pas.
- **Admission** ⇒ la géométrie large **tient son exigence** et ma piste était
  une fausse alerte. Je le dirai tel quel.

## ⚠️ Limites, posées d'avance

- **Donnée rattrapée** : tout porte sur `resolved_backfill = 1`. Les issues
  ont été produites par le même chemin de calcul que la production, mais sur
  des bougies allées chercher après coup.
- **Aucun placebo n'est exécuté.** Je ne compare pas à des entrées tirées au
  hasard sur les mêmes paires et le même horizon. Ce que ce banc peut dire se
  limite donc à « cette géométrie atteint-elle son propre seuil arithmétique »
  — **pas** « y a-t-il un edge ». Un `z` significatif ici ne prouverait aucune
  information prédictive, seulement un déséquilibre entre le R:R demandé et le
  taux obtenu.
- **n modeste** : ~1 148 setups `1d` rattrapés, dont ~594 résolus. Une seule
  cellule pré-spécifiée, donc aucune correction de multiplicité n'est requise
  — et aucune autre cellule ne sera testée après coup sur cette donnée.
- **Coûts** : `SPREAD_SLIPPAGE_PCT = 0,02 %`, négligeable face à des distances
  de 10-20 %. Contrairement aux bancs courts, le coût n'est **pas** le sujet
  ici.
