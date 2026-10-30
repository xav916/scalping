# VERDICT — le coût réel de l'or

**Protocole pré-inscrit `b8d01be`, figé avant la mesure. Code `82af40e`.**

## La mesure

| | |
|---|---|
| source | `ticks_courtier.db`, **11 987 039 ticks** `bid`/`ask` |
| couverture | `XAU/USD`, 2026-09-21 → 2026-10-30 |
| exclusions | **0 tick sur 12 M** (aucune cotation croisée, nulle ou aberrante) |
| prix moyen | 4 129,01 $ |

| statistique | magasin | **réel** (markup +10 pts) | relatif | vs `0,0002` |
|---|---|---|---|---|
| médiane | 0,0859 $ | **0,1859 $** | 0,00004502 | **4,44×** |
| moyenne | 0,0844 $ | 0,1844 $ | 0,00004466 | 4,48× |
| p75 | 0,1028 $ | 0,2028 $ | 0,00004912 | 4,07× |
| p95 | 0,1202 $ | 0,2202 $ | 0,00005333 | 3,75× |
| p99 | 0,1239 $ | 0,2239 $ | 0,00005423 | 3,69× |

Taille du point **dérivée** du pgcd de 870 valeurs de spread distinctes :
**0,01 $**, plancher observé 0,05 $ (5 points). Elle n'est pas supposée.

## Une troisième route, jamais testée

Ma fiche du 12/10 avait tranché `/tick` contre `/ticks`. `laboratoire_or`
lit une **troisième** route, `/rates`, dont personne n'avait vérifié si elle
porte le markup. Mesure appariée sur **3 312 bougies** :

```
/rates MOINS /ticks : mediane -2,4 pts | 0,0 % des bougies a +10
niveaux : /rates 5,0 pts | /ticks 8,2 pts | REEL 18,2 pts
```

⇒ **`/rates` ne porte pas le markup non plus**, et il est même plus bas de
2,4 points (`spread_pts` est un entier tronqué, relevé à l'instant de la
bougie).

⚠️ L'instrument a d'abord rendu **4 appariements sur 1 200**. Ce n'était pas
une absence : les bougies portent `+00:00` et `datetime()` rend un espace là
où les ticks ont un `T`, donc la comparaison de chaînes était fausse. Un
témoin balayant sept décalages l'a montré — et a aussi montré qu'il n'y a
**aucun** décalage de fuseau (maximum d'appariements à 0 min).

## Ce que la correction NE change pas

🔑 **Les verdicts d'horizon survivent, et c'est démontré.** Le placebo de
`banc_esperance_horizon` appelle le **même `pnl_pct()`**, donc la même
constante, sur le **même multiensemble de risques** (`d["risk_pct"]` est
réutilisé tirage par tirage). La soustraction du coût porte alors sur
`mean(1/risque)`, identique dans les deux bras ⇒ la différence réel−placebo
est **exactement invariante**.

⇒ `1d` **reste rejeté**, `4h` **reste indiscernable**. Corriger le coût ne
ressuscite aucun verdict. Trois tests gardent cette propriété, dont un
**témoin** (le coût déplace bien les niveaux absolus) et un qui rend la
**précondition explicite** : si le placebo tirait un jour ses propres
risques, l'invariance tomberait et les verdicts devraient être rejoués.

La constante est donc **conservée telle quelle** : la changer casserait la
reproductibilité des verdicts publiés sans déplacer un seul `t`.

## Ce que la correction change — et c'est dans le MAUVAIS sens

La géométrie de production facturait **0,045 €**, lue sur `/rates`. Le coût
réel est **~0,169 €**, soit **3,64×** plus.

| | facturé (`/rates`) | **réel** |
|---|---|---|
| spread par trade | 0,046 € | **0,169 €** |
| réussite **requise** | 91,12 % | **91,68 %** |
| réussite obtenue | 90,39 % | 90,39 % |
| **manque** | 0,72 pt | **1,29 pt** (×1,78) |
| P&L sur 1 343 trades | −380,64 € | **−539,65 €** |
| part du spread dans la perte | 16,3 % | **41,9 %** |

✅ **Témoin de l'instrument** : au coût facturé, mon modèle rend **91,12 %**
et **−380,64 €** contre **91,11 %** et **−378,96 €** publiés — soit 0,4 %
d'écart. C'est cette reproduction qui autorise à appliquer le modèle au coût
réel.

## `spread_cost` : d'« inconnu par construction » à mesuré

Le ledger écrivait `None` et son commentaire disait vrai pour l'époque — *« le
courtier intègre le spread au prix d'exécution… le connaître demanderait
d'enregistrer le bid ET le ask à l'instant du push »*. `ticks_courtier.db` le
fait depuis le 21/09.

```
410 trades or dans la fenetre  ->  410 resolus au TICK DE L'INSTANT (100 %)
cout median 0,176 EUR | moyenne 0,180 | min 0,139 | max 0,926
TOTAL 73,91 EUR   contre un P&L de -55,70 EUR   =>  132,7 % de la perte
```

`_spread()` passe par le **risque en euros** (`risk_amount × spread_prix /
distance_au_stop`) pour ne pas recalculer volume, taille de contrat et
change — trois grandeurs dont chacune a déjà produit une erreur (l'argent
sous-estimé ×10, XLU annoncé à 343 800 €). La chaîne échoue fermée : risque
`NULL` ⇒ coût `NULL`. Et deux refus sont gardés par des tests : **une
hypothèse de classe n'entre pas dans un registre**, et `tick_moyen` non plus
— c'est une mesure, mais pas celle de ce trade.

## ⛔ CORRECTION DU VERDICT DU 28/10 (`09c31e2`)

Le 28/10 j'avais conclu : *« `SPREAD_PCT = 0,0002` était JUSTE à 10 % près »*,
sur une mesure donnant l'or à **0,0251 % du prix**. Aujourd'hui je mesure
**0,0045 %** — un facteur **5,6**. Les deux ne peuvent pas être vrais.

**La mesure du 28/10 était fausse, et voici pourquoi.** Elle passait par
`slippage_pips`, qui est une grandeur **signée** : le glissement peut être
favorable. Or elle en prenait la **médiane de la valeur absolue**.

```
slippage SIGNE, or, n=350 :
   moyenne  -4,85 pips  (-0,0485 $)   t = -0,282   => INDISCERNABLE DE ZERO
   favorables 171 (48,9 %) | defavorables 179 (51,1 %)
   mediane |x| = 1,0750 $   <-- le chiffre du 28/10
```

🔑 **Prendre `|x|` d'une variable de moyenne nulle produit un grand nombre
positif qui ressemble à un coût sans en être un.** Ce qu'on mesure alors est
la **dispersion**, pas l'espérance. Le glissement n'est donc **pas un coût**
sur ce compte : il est symétrique à 49/51.

⇒ Le coût d'exécution déterministe de l'or est le **spread**, et il vaut bien
`0,0000450`. La constante est bien **4,44× trop haute**.

⚠️ **Mais le glissement n'est pas inoffensif** — il apporte de la
**variance** : σ = **3,21 $** (p5 −4,80 $, p95 +4,00 $). Rapporté aux
distances réellement utilisées sur l'or depuis le 21/09 (stop médian
**14,62 $**, objectif **26,04 $**) :

| | en fraction de R |
|---|---|
| **spread** (coût certain) | **0,012 R** par trade |
| **glissement** (bruit, moyenne nulle) | **σ = 0,22 R** |

⇒ Le bruit d'entrée vaut **18× le coût du spread** en écart-type. Il ne fait
pas perdre d'argent en espérance, mais il brouille toute mesure d'avantage —
ce qui est cohérent avec cinq réfutations de la direction.

## ⛔ Ce que je ne conclus PAS

Le brut hors coût vaut **+0,0444 €/trade**, **t = +0,126** sur 410 trades,
intervalle 95 % **[−0,65 ; +0,74]** ⇒ **indiscernable de zéro**.

Je n'écris donc **pas** « sans le spread ce serait rentable ». L'asymétrie
est ailleurs, et elle est plus solide :

🔑 **l'avantage est du bruit autour de zéro ; le coût est une certitude** de
0,176 €/trade (min 0,139, max 0,926). Un signal de moyenne nulle moins un
coût certain donne une perte certaine. L'échantillon de 410 trades est trop
bruité pour le montrer seul (net t = −0,384) ; les 1 343 trades du test de
septembre-octobre le montrent.

## La dette qui n'existait pas

⛔ **`fill_price` n'est pas un défaut.** 350 trades portent `fill_price ==
entry_price` **et** un `slippage_pips` non nul : le glissement est mesuré
contre un troisième prix, `mt5_pushes.entry_price_5dp`, le prix **demandé**.
`entry_price` a été réécrit avec le prix exécuté — comportement voulu, que
`slippage_instrumentation_check` documente explicitement.

Ma liste de dettes en nommait trois ; **une n'existait pas**, et la plus
grave n'y figurait pas (la géométrie de production, pas le banc). Deuxième
fois en une journée qu'une liste de défauts écrite à la main se révèle
périmée.

## Ce qui reste hors de portée

⛔ **Aucun magasin courtier ne contient de bid/ask pour le forex, la crypto
ou l'énergie.** Les valeurs par classe de `cout_execution` sont donc des
**hypothèses déclarées**, marquées comme telles et refusées par
`exiger_mesure()`. Pour les mesurer il faut d'abord **collecter** — c'est une
limite de données, pas de code.

⚖️ Acceptable aujourd'hui parce que l'or est la **seule voie en argent réel**
(`LIVE_WHITELIST_PAIRS == {XAU/USD}`).
