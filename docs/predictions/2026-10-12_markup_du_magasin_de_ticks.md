# ⛔ RETRACTATION : il n'y a pas eu de « changement de régime » du spread

**Mesuré le 2026-10-12, et ça annule ma conclusion du matin.**

## Ce que j'avais affirmé, et qui était FAUX

Ce matin, en armant le plancher au spread, j'ai écrit dans `12fe165` :

> « 22 points dépasse le p95 de 3,3 millions de ticks. (…) le **régime de
> spread a changé** entre la mesure et l'armement. »

⛔ **C'est faux.** Le magasin de ticks n'a jamais eu le même spread que la
route d'exécution — pas parce que le marché a changé, mais parce que **les deux
routes du pont ne rendent pas la même donnée**.

## La mesure qui tranche

Deux routes du **même pont**, même symbole, **mêmes secondes** :

```
40 relevés live sur 2 min, appariés au magasin à +/- 2 s, 0 manquant
   ecart live - magasin :  median +10,0 pts   moyenne +10,2   ecart-type 1,2
   p05 +9,0   p25 +10,0   p75 +10,0   p95 +13,0
   26 des 40 valent EXACTEMENT +10
```

🔑 Et une **seconde preuve, indépendante** : les prix d'exécution réels
dévient du bid/ask du magasin de **+3,5 pts (achats)** et **+5,0 pts
(ventes)** — soit **la MOITIÉ** de l'écart, ce qui est exactement ce que
prédit un spread réel égal à `magasin + 10` (un achat est rempli à
`mid + s_reel/2 = ask_magasin + 5`). Si le magasin disait vrai, la déviation
serait nulle.

⇒ **La route `/tick` est celle de l'exécution. Le magasin `/ticks` rend un flux
SANS les 10 points de marge du courtier.**

## Les conséquences, dans l'ordre d'importance

1. 🔴 **Tout banc sur `ticks_courtier.db` sous-estime le coût de 10 points**,
   soit **0,089 €** par trade. C'est énorme au regard de l'ordre de grandeur
   du problème de l'or, dont la géométrie échoue de **0,72 point**.
2. ✅ **Les comparaisons APPARIÉES survivent** : les deux cellules paient le
   même coût manquant, donc l'écart `B − A` reste valide. Ce sont les
   **niveaux absolus** de P&L qui sont optimistes.
3. ✅ **Les deux décisions du jour tiennent**, et l'une est renforcée :
   - le **plancher au spread** (`dd19141`) : 2 × 8 = 16 pts mesurés contre
     2 × 18 = 36 pts réels, les deux très loin des 2,00 € (224 pts) qu'il
     remplace ⇒ conclusion inchangée ;
   - le **déclencheur du traînage** (`dbfb6f4`) : la version mesurée était
     donc **encore plus radicale** que ce que la production aurait fait ⇒ ma
     conclusion (« nette à zéro, et l'effet réel serait plus doux ») est
     **renforcée**, pas affaiblie.
4. ⛔ **Et je retire aussi « le spread est FIXE à 22 points »** : sur 40
   relevés en 2 minutes il varie de **15 à 22 points**.

## La correction posée

La constante est inscrite dans la table `provenance` du magasin lui-même
(`markup_live_points = 10`, avec sa preuve et sa conséquence), pour qu'un banc
futur la trouve **sans relire ce document**. Et le magasin est désormais
entretenu **toutes les heures** par `/opt/scalping/jobs/magasin_ticks.sh`.

🔑 La leçon : **deux routes d'un même pont ne sont pas deux vues de la même
donnée.** Je l'ai supposé pendant trois semaines de bancs. Avant de mesurer un
coût, il faut vérifier que la source porte le coût que l'exécution paie.
