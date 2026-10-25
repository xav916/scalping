# La protection des pertes, HORS ÉCHANTILLON — 13 journées, 99 trades

**Déclaré le 2026-10-25, AVANT d'écrire la mesure.**

Le verdict du jour (`ffb150e`) a mesuré le 12/10 : `B − A = +23,03 €`,
`t = +0,65`, **indécidable**. Le rejeu reproduisait la journée sur trois cibles,
mais **au prix d'un paramètre calibré** : un coût aller-retour de 30 points là
où le markup mesuré valait 10.

## ⛔ CE QUI REND CETTE MESURE POSSIBLE, ET CE QU'ELLE N'EST PAS

Le magasin de ticks couvre **14 journées** avec des trades automatiques :

```
12/10 seul        165 trades   =  62,5 % de TOUT l echantillon
13 autres jours    99 trades   =  37,5 %   (1 a 32 trades par jour)
```

⛔ **Ce n'est donc PAS une extension multi-jours** : la population resterait
dominée par la journée déjà mesurée, et un total agrégé ne serait qu'un 12/10
légèrement bruité. Je refuse de présenter ça comme un test indépendant.

✅ **Ce que c'est** : le coût de 30 points a été **calibré sur le 12/10 et sur
lui seul**. Les 99 trades des 13 autres journées n'ont participé à **aucun**
réglage. Ils constituent donc un **hors échantillon pur, à zéro paramètre
libre** — le coût est **gelé à 0,30 USD**, la cadence de sonde à 1 minute, le
traînage à 0,50 € fixe.

## Ce qu'on mesure

Le **même banc**, inchangé (`scripts/banc_contrefactuel_protection.py`), sur
les 13 journées du **21/09 au 11/10**, trades automatiques XAU/USD clôturés.

| | |
|---|---|
| **A** | la protection telle qu'armée |
| **B** | sans elle — le stop initial ne bouge plus jamais côté perte |

Écart apparié `B − A`, par trade, sur les 99 trades agrégés.

## ⛔ LE CRITÈRE, posé d'avance

- `B − A` positif avec `t > +2` ⇒ **la protection coûte**, confirmé hors
  échantillon ;
- `B − A` négatif avec `t < −2` ⇒ **elle gagne**, et le résultat du 12/10 était
  un accident de journée ;
- entre les deux ⇒ **indécidable**, et je le dirai sans l'habiller.

⛔ **ET UNE CONDITION DE VALIDITÉ, séparée du critère** : si le rejeu ne
reproduit pas le P&L réel de ces journées à **mieux que 0,50 €/trade** en
valeur absolue agrégée, je déclare la mesure **non concluante pour cause de
rejeu invalide** — comme je l'ai fait cet après-midi avant de corriger les
trois défauts. Un rejeu qui rate la réalité ne mesure pas un contrefactuel.

⛔ **Aucun réglage ne sera touché après coup.** Si le coût de 0,30 ne reproduit
pas ces journées, c'est un résultat, pas une invitation à le recalibrer.

## MES PRÉDICTIONS, posées avant de coder

1. 🔑 **`B − A` restera POSITIF** (la protection coûte). Raison : le mécanisme
   mesuré est structurel, pas propre à une journée — un stop resserré au point
   milieu finit collé au cours, et le bruit le déclenche.
2. ⚠️ **Mais `|t|` ne dépassera pas 2**, donc **encore indécidable**. À
   `+0,14 €/trade` sur n=99 avec un écart-type de ~2,7, `t` vaut ~0,5. Je
   l'écris pour qu'on ne lise pas un `t` de confort comme une confirmation.
3. ✅ **L'écart de RÉUSSITE se maintiendra à au moins +5 points** en faveur de
   `B`. C'est la trouvaille la plus robuste du 12/10 (+17,0 points) et la seule
   de mes quatre prédictions d'hier à être passée largement.
4. ⛔ **Le rejeu reproduira ces journées MOINS BIEN que le 12/10.** Le coût de
   0,30 y était ajusté ; ailleurs il ne l'est pas. Je prédis une erreur
   agrégée **supérieure à 0,10 €/trade** en valeur absolue — tout en restant
   sous la barre de 0,50 € de la condition de validité.
5. 🔑 **Le 12/10 est une journée ABERRANTE.** Je prédis que le P&L réel par
   trade des 13 autres journées sera **meilleur** que les −0,231 €/trade du
   12/10. S'il l'est, alors mesurer la protection sur le 12/10 seul la jugeait
   sur son pire jour.

## ⚠️ Ce que cette mesure ne pourra pas dire

Même un `t > +2` ne justifierait pas de désarmer : 99 trades répartis sur
13 journées à 1-32 trades chacune, ce n'est pas une politique. Au mieux, ça
dira si le résultat du 12/10 **se reproduit ailleurs**.
