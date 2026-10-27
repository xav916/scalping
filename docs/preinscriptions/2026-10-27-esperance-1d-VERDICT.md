# Verdict — l'espérance de l'horizon `1d` : REJET

**Pré-inscription** : `d3cd3fe` · **Banc** : `b2ed1f6`
(antériorité **prouvée** par `or-preinscription`, code 0)
**5 prédictions sur 5 passent.** Verdict : **`REJET_horizon_1d_ECARTE`**.

## Le résultat

```
n = 1362 sur 1362   couverture 100,00 %
contrôle du moteur vectorisé : 1362 / 1362 en accord avec la production

VALIDITÉ                                                        valide
  n >= 1000 .............................. 1362
  couverture > 99 % ...................... 100,00 %
  risk médian réel / placebo ............. 9,326 % / 9,326 %
  tirages aboutis >= 190 ................. 200 / 200

ESPÉRANCES (en R par setup)
  réel (convention A) ....................  −0,0641
  placebo (200 tirages) ..................  +0,0413
  convention B (résolus seuls) ...........  −0,1677
  TIMEOUT seuls ..........................  +0,0549
  coût médian ............................  +0,0021

P1  espérance réelle < 0 ...  −0,0641              PASSE
P2  |placebo| < 0,05 .......  +0,0413              PASSE
P3  tirages battus < 95 % ..   0,0 %               PASSE
P4  |TIMEOUT| < 0,20 .......  +0,0549              PASSE
P5  B − A <= −0,05 .........  −0,1036              PASSE

t contre placebo : −4,2262      tirages battus : 0,0 %
```

## Ce que ça dit

**L'horizon `1d` est écarté, et cette fois sur la bonne base.** Le banc
précédent rendait ADMISSION avec un seuil de taux qui ne s'appliquait pas ;
celui-ci mesure une **espérance**, contre un placebo.

🔑 **Le réel ne bat AUCUN des 200 tirages au hasard.** `t = −4,23`. Il ne s'agit
donc pas seulement d'une espérance négative : **l'instant d'entrée du `1d` fait
MOINS BIEN que le hasard**, sur la même géométrie, les mêmes paires, la même
période et le même sens.

✅ **Et mon objection à l'addendum est confirmée, chiffres en main** : les
`TIMEOUT` ont une espérance de **+0,0549 R** (P4) — une bribe, très loin des
1,8 R qu'un « gagnant » vaut. Les compter comme des réussites de même poids,
ce que faisait le test de taux, était bien faux. P5 le confirme par l'autre
bout : l'espérance sur les seuls résolus est **0,1036 R plus négative**, parce
que les `TIMEOUT`, proches de zéro, diluent.

## ⚠️ Les réserves, et elles comptent

- **Le placebo n'est pas nul : +0,0413 R.** Il passe sa barre (0,05) mais de
  peu. Des entrées au hasard sur cette géométrie rapportent donc légèrement —
  dérive haussière de la période, très probablement. ⇒ La comparaison
  réel/placebo reste valide (c'est un écart apparié), mais **le niveau du
  placebo n'est pas une référence neutre**, et une période baissière aurait
  donné un placebo négatif.
- **Un seul régime de marché** : 1 362 setups sur ~68 jours. Rien ici ne dit ce
  que ferait le `1d` ailleurs.
- **Donnée rattrapée** (`resolved_backfill = 1`). Le placebo utilise exactement
  les mêmes bougies, ce qui annule ce biais dans la comparaison mais pas dans
  les niveaux.
- **Aucune mesure hors échantillon.** C'est précisément là que les deux
  trouvailles du 08/10 s'étaient évaporées. Un rejet est moins fragile qu'une
  admission à ce stade, mais la réserve tient.

## `or-verdict` refuse, pour la même raison légitime qu'au banc précédent

```
=== NE PAS PUBLIER
  - [ecart_par_trade] est null
```

Cette skill juge des **rejeux** et mesure leur fidélité à la réalité vécue. Ce
banc ne rejoue rien : il compare une population réelle à un placebo. La
quantité n'existe pas, et **émettre `0.0` aurait fait croire à un rejeu
parfait**. C'est la deuxième fois aujourd'hui : `or-verdict` ne sait juger
qu'une forme de banc, et c'est une limite du pack à documenter ou à étendre —
**jamais à contourner en fabriquant un champ**.

## Le contrôle qui rendait ce banc crédible

**1 362 / 1 362** : le moteur vectorisé rend exactement les mêmes issues que
`simulate_trade_forward`, y compris sur la règle « SL et TP dans la même bougie
⇒ SL ». Sans ce contrôle, les 272 400 simulations du placebo auraient reposé
sur une réimplémentation non vérifiée de la règle de sortie — et un écart de
quelques points de pourcentage sur cette règle aurait suffi à inverser le
signe.

## Ce que ce verdict ne dit pas

- Rien sur le `4h`, ni sur les autres classes d'actifs. Il porte sur le `1d`.
- Rien sur la cause : le `1d` fait moins bien que le hasard, et ce banc ne dit
  pas **pourquoi**. Une cellule de plus sur cette donnée est exclue par la
  pré-inscription.
