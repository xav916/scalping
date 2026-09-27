# Stratégie de copie MQL5 : le sizing décide, pas le trader — 2026-09-27

Question posée : projection au 31/12/2026 avec 500 € sur un compte réel IC Markets,
en suivant [Goldtrade Pro ICM](https://www.mql5.com/en/signals/2084890) puis
[GoldWave](https://www.mql5.com/en/signals/2339082) ; puis quel fournisseur suivre
à 100 € et lequel à 1 000 €.

Troisième volet, après [le crible des quinze fournisseurs](2026-09-27-analyse-fournisseurs-mql5-signals.md)
(`ext-1`) et [la contrepartie théorique](2026-09-27-existe-t-il-un-edge-a-louer.md) (`ext-2`).
Ces deux-là jugeaient les fournisseurs. Celui-ci mesure ce qui se passe **chez
l'abonné**, et le résultat est que le fournisseur n'est pas la variable dominante.

> ⛔ **À 100 €, aucun des deux n'est copiable** : le volume calculé tombe sous le lot
> minimum d'IC Markets. L'abonnement GoldWave sur 3 mois (126 €) **coûte plus cher que
> le compte lui-même**.
> ⛔ **À 1 000 €, Goldtrade Pro ICM** — mais viser **1 100 €**, pas 1 000 (voir §2).
> ⛔ **La copie ne doit pas aller sur le compte du bridge** : R-29 le rend inopérant (§5).

Calcul reproductible : [`scripts/projection_copie_mql5.py`](scripts/projection_copie_mql5.py).

---

## 1. Le mécanisme que personne ne regarde avant de payer

MQL5 calcule le volume de l'abonné comme
`lot_fournisseur × (équité_abonné / équité_fournisseur) × allocation`,
puis **arrondit vers le bas et jamais vers le haut** (modérateur MQL5 ; la page de
règles officielle ne le formule pas — c'est la seule incertitude de mécanique de ce
document). Un volume sous `0.01` ne peut donc pas remonter à `0.01` : **le trade
n'est pas copié du tout.**

Les deux fournisseurs ont des équités opposées, ce qui inverse tout :

| | Équité fournisseur | Son lot | Seuil d'exécution à 100 % | à 95 % |
|---|---|---|---|---|
| **Goldtrade Pro ICM** | 7 360 € | ~0,074 | **1 000 €** | **1 053 €** |
| **GoldWave** | 428,68 $ = 366 € | ~0,010 | **366 €** | **386 €** |

Le seuil de Goldtrade tombe *exactement* à 1 000 € parce que sa fiche divulgue que
l'EA tourne avec `LotsizeStep=1000` — 0,01 lot par 1 000 € d'équité. Ce n'est pas
une coïncidence, c'est le paramètre de l'EA qui se propage à l'abonné.

## 2. Projection au 31/12/2026 (95 jours, 200 000 chemins, net de frais)

**Goldtrade Pro ICM** (39 $/mois, 65 trades attendus) :

| Capital | Volume | P10 | Médiane | P90 | P(perte) | frais / dispersion |
|---|---|---|---|---|---|---|
| 100 € | 0,0010 → **rien** | — | **0 €** | — | 100 % | frais > capital |
| 500 € | 0,0050 → **rien** | — | **400 €** | — | 100 % | — |
| 1 000 € | 0,0100 → 0,01 (1,00×) | 835 € | **1 063 €** | 1 377 € | 37,1 % | 18,4 % |
| 2 000 € | 0,0200 → 0,02 (1,00×) | 1 768 € | 2 226 € | 2 851 € | 27,2 % | 9,2 % |
| 5 000 € | 0,0500 → 0,05 (1,00×) | 4 573 € | 5 723 € | 7 295 € | 21,7 % | 3,7 % |

**GoldWave** (49 $/mois, 68 trades attendus) :

| Capital | Volume | P10 | Médiane | P90 | P(perte) | frais / dispersion |
|---|---|---|---|---|---|---|
| 100 € | 0,0027 → **rien** | — | **−26 €** | — | 100 % | **frais > capital** |
| 500 € | 0,0136 → 0,01 (0,73×) | 410 € | **463 €** | 514 € | **83,6 %** | **120,5 %** |
| 733 € | 0,0200 → 0,02 (1,00×) | 677 € | 789 € | 898 € | 23,1 % | 56,7 % |
| 1 000 € | 0,0273 → 0,02 (0,73×) | 945 € | 1 052 € | 1 153 € | 23,6 % | 60,3 % |
| 5 000 € | 0,1365 → 0,13 (0,95×) | 5 329 € | 6 051 € | 6 751 € | 5,3 % | 8,8 % |

### Trois lectures

**À 500 €, GoldWave perd dans 83,6 % des cas alors qu'il gagne 95,27 % de ses
trades.** Le gain de trading médian du trimestre est de +88 € pour 126 € d'abonnement :
le frais est plus grand que l'edge. Ce n'est pas un défaut du trader.

**La colonne « frais / dispersion » est le vrai verdict.** À 500 €, l'abonnement
GoldWave représente **120,5 % de tout l'écart P10-P90**. L'expérience ne peut donc pas
mesurer le fournisseur : le résultat au 31/12 sera déterminé par ce qui a été payé,
pas par ce qui a été tradé. Ce ratio ne devient exploitable qu'autour de 5 000 €.

**Le sizing est grumeleux, et pas monotone.** 733 € donne une meilleure médiane
(+7,6 %) que 1 000 € (+5,2 %) chez GoldWave : à 733 € le ratio tombe pile sur 0,02 lot
(expo 1,00×), à 1 000 € on perd 27 % de l'exposition dans l'arrondi. **Les paliers
utiles ne sont pas les chiffres ronds.**

> ⚠️ **Piège à 1 000 €.** La documentation MQL5 plafonne l'allocation à 95 % du solde.
> À 95 %, le volume Goldtrade devient 0,0095 → **arrondi à zéro, rien n'est copié**.
> Le seuil réel est **1 053 €**. Viser **1 100 €** pour la marge, et **lire le volume
> calculé dans la fenêtre de souscription MQL5 avant de confirmer le paiement** —
> MQL5 l'affiche, c'est la vérification qui coûte zéro.

## 3. Effet de cliquet : le drawdown s'auto-amplifie au lot minimum

À 1 000 € le lot vaut 0,01, soit le minimum. Quand l'équité baisse, **le lot ne peut
plus baisser** : le risque en pourcentage monte mécaniquement. À 650 € d'équité, le
même 0,01 lot représente **1,54× le risque initialement voulu**.

Conséquence pour le réglage du coupe-circuit : le drawdown maximal historique de
Goldtrade est de 26,68 %. Placer l'arrêt au-dessus garantit d'être sorti par un
drawdown *normal* ; le placer à 35 % (650 € sur 1 000 €) c'est accepter −350 € comme
coût d'un fonctionnement nominal. Il n'y a pas de réglage confortable à cette taille :
c'est une propriété du lot minimum, pas un choix.

## 4. Combien de temps avant de savoir ? Et pourquoi la réponse diffère

Taille d'échantillon pour un t de 2 sur l'espérance par trade :

| | Espérance | Écart-type | N requis | Durée au rythme observé |
|---|---|---|---|---|
| Goldtrade Pro ICM | +0,268 %/trade | 2,43 % | **330 trades** | **1,3 an** |
| GoldWave | +0,324 %/trade | 1,58 % | 94 trades | 0,4 an |

**Le N de GoldWave n'est pas interprétable, et c'est le point le plus important de ce
document.** Sa faible variance vient d'un échantillon de **14 pertes dont aucune n'est
une catastrophe**. Preuve interne : sa pire perte clôturée vaut −5,73 % de l'équité,
mais son **drawdown en équité atteint 17,52 %** — trois fois plus. Ses positions sont
donc allées bien plus profond que ce que n'importe quelle perte enregistrée révèle.
Un test sur la moyenne ne peut pas voir un risque qui vit dans une queue non
échantillonnée ; il le compte comme de la régularité.

Son taux de réussite d'équilibre est de **81,68 %** (gain moyen 1,72 $ contre perte
moyenne 7,67 $, rapport de 1 à 4,5). Il affiche 95,27 %. La marge est réelle mais
établie sur 14 points.

Goldtrade, à l'inverse, **expose** son risque : 741 trades, **312 pertes observées**,
DD équité 12,17 % *inférieur* au DD solde 31,95 % — les perdants sont coupés — et un
taux de réussite de 57,89 %, réaliste. Son edge est mal démontré (0,92 % des jours
font 80 % de la croissance ; c'est 1 signal parmi les **29** que publie Profalgo
Limited), mais son risque, lui, est mesuré. **Préférer le risque mesuré à la
probabilité de perte affichée la plus basse.**

## 5. Contrainte bloquante : pas sur le compte du bridge

**R-29** : `MAGIC_NUMBER` est écrit sur chaque ordre et **jamais lu**. Les conséquences
tracées dans l'audit portent directement sur ce projet de copie :

- `bridge.py:664` — toute position étrangère compte dans le drawdown journalier et le plafond ;
- `bridge.py:784` — elle consomme le budget de `_risque_engage_par_poche`, donc **bloque les ordres du système** ;
- `bridge.py:1868` — elle entre dans la boucle de surveillance : **le bridge déplace le break-even et fait des clôtures partielles sur des trades qui ne sont pas les siens**.

Ce n'est donc pas un défaut de comptabilité, c'est une **interférence active** : le
bridge et le copieur MQL5 se battraient pour la gestion des mêmes positions or.

⛔ **La copie va sur un compte séparé**, dans le second terminal isolé déjà documenté
([`deploy/terminal-copie-isole.md`](../../../deploy/terminal-copie-isole.md)) — ou bien
R-29 est corrigé d'abord, avec le correctif **différencié** que l'audit spécifie
(filtrer sur le magic pour *ce que je gère*, ne pas filtrer pour *le risque de compte*).

## 6. Stratégie étagée

| Palier | Capital | Fournisseur | Objectif | Sortie |
|---|---|---|---|---|
| **0** | < 386 € | **aucun** | accumuler | rien ne s'exécute, ne pas payer |
| **1** | 386 – 1 052 € | **GoldWave**, 1 mois | **instrumentation, pas P&L** | plomberie validée ou non |
| **2** | ≥ 1 100 € | **Goldtrade Pro ICM** | pré-enregistrer, 330 trades | banc rend son verdict |
| **3** | ≥ 5 000 € | idem, si palier 2 passé | frais retombés à 3,7 % | — |

**Palier 1 — ce qu'on mesure, et ce n'est pas l'argent.** À 500 € le frais vaut 120 %
de la dispersion : le P&L est illisible. Les cinq seules choses observables pour
49 $ : (1) la copie part-elle ; (2) latence entre l'ordre du fournisseur et le fill ;
(3) le symbole `XAUUSD` correspond-il sans suffixe ; (4) quel volume MQL5 ouvre-t-il
réellement, comparé au calcul du §1 ; (5) les SL/TP sont-ils répliqués. Ces cinq
réponses ont une valeur réelle avant tout engagement plus gros. Le P&L n'en a aucune.
Optimum de sizing du palier : **733 €** (expo 1,00× au lieu de 0,73×).

**Palier 2 — pré-enregistrement obligatoire, avant de souscrire.** `declare()` dans
`research_bench` : *« Goldtrade Pro ICM rend un R net ≥ 0 sur 330 trades, après frais
et slippage. »* Horizon **1,3 an**. Journaliser chaque trade copié contre le trade du
fournisseur dans la table `signals` (`fill_price`, `close_reason`) : c'est ce qui
mesure le slippage de copie directement, au lieu de l'estimer.

**Critères d'arrêt du palier 2, au-delà du coupe-circuit d'équité :**
1. le DD équité du fournisseur repasse **au-dessus** de son DD solde → la thèse « les perdants sont coupés » est morte ;
2. arrêt de trading > 3 semaines — *déjà observé* : alertes « no trading activity » de juin à septembre 2026, activité 11,64 % ;
3. Profalgo publie un signal de remplacement, ou les statistiques de celui-ci sont remises à zéro ;
4. fidélité de copie < 90 % des trades du fournisseur sur un mois ;
5. 330 trades atteints sans t ≥ 2 → l'edge n'est pas démontré, résilier.

## 7. Ce que la stratégie interdit

- **Ne pas suivre les deux en même temps.** Les deux tradent XAUUSD, comme 11 des 29
  fournisseurs du plus gros catalogue de `ext-1`. Ce n'est pas de la diversification,
  c'est un doublement d'exposition sur l'or — l'instrument où le contrefactuel de ce
  projet donne **−0,689 R** et où XAG affiche **−1 565,98 €** sur 152 trades.
- **Ne pas router la copie par le bridge du système** (§5).
- **Ne pas monter au palier 3 avant que le palier 2 ait rendu son verdict** — c'est le
  principe directeur du projet : ne jamais élargir avant d'avoir validé.

## Hypothèses et limites

- Espérances **constatées** sur chaque fiche, projetées inchangées. Calibration validée :
  l'historique réel de Goldtrade (×7,36 sur 741 trades) tombe entre P25 et P75 du
  modèle (×3,91 – ×9,08, médiane ×5,94).
- Le modèle est **moins accidenté que la réalité** : il concentre 80 % de la croissance
  sur 2,0 % des trades, la fiche en annonce 0,92 %. Le vrai chemin sera plus brutal.
- **Slippage de copie non modélisé** : même broker donc même spread, mais la latence
  coûte ~5-20 pips sur une espérance de ~146 pips (3 à 14 %). Les projections sont
  donc légèrement optimistes.
- **EUR/USD 1,17 supposé**, non vérifié à la source. 3 mensualités supposées ; 4 si le
  prélèvement démarre le 27/09.
- La règle d'arrondi vers le bas vient d'un message de modérateur, pas de la page de
  règles officielle. C'est la seule incertitude de mécanique, et elle est décisive pour
  le palier 0 : à vérifier dans la fenêtre de souscription avant de payer.

## Sources

- [Goldtrade Pro ICM](https://www.mql5.com/en/signals/2084890) · [GoldWave](https://www.mql5.com/en/signals/2339082)
- [Rules for copy trading](https://www.mql5.com/en/signals/rules) — « Signals can only be created based on a real account »
- [Signal Lotsize — forum MQL5](https://www.mql5.com/en/forum/209128) — « the lot size is rounded down and never up »
- Interne : `ext-1`, `ext-2`, R-29 (`docs/audit-externe-2026-09-16.md:1542`), `deploy/terminal-copie-isole.md`
