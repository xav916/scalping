# Analyse des fournisseurs MQL5 Signals — 2026-09-27

Question posée : parmi les fournisseurs qui vendent la copie de leurs trades sur
MQL5 Signals, lesquels sont les plus sûrs à suivre, et pourquoi ?

> ⛔ **Aucun ne l'est.** Ce document classe par *marqueurs de risque*, pas par
> sécurité. Il élimine les dangereux ; il ne désigne pas un gagnant.

---

## 1. La méthode, et pourquoi elle inverse le classement de la place de marché

MQL5 trie par croissance et par « fiabilité ». Deux raisons de ne pas s'y fier.

**La croissance affichée est un marqueur de danger, pas de qualité.** Le guide
officiel de MetaQuotes le dit lui-même :

> « January growth was 1176%. This is an indication of intense **deposit
> boosting** » — et « the higher is the expected profit, the higher is the risk ».
> — [Tips for Selecting a Trading Signal](https://www.mql5.com/en/articles/1838)

Sur 29 signaux relevés en page d'accueil, **douze dépassent ce seuil**.

**La « fiabilité » n'est pas définie.** Le guide officiel de sélection de MQL5 ne
l'emploie ni ne la définit. On ne s'appuie pas dessus. (`NoPain MT5` affiche
64 abonnés payants avec 15 % de fiabilité.)

### Le critère qui a fait tout le travail

**Le rapport entre drawdown en ÉQUITÉ et drawdown en SOLDE.**

- `DD équité < DD solde` ⇒ les perdants sont coupés. L'équité ne plonge pas plus
  bas que ce que les clôtures enregistrent.
- `DD équité > DD solde` ⇒ les perdants restent ouverts. Le guide MQL5 nomme ce
  motif : une « *propensity for "sitting out" losses* », qui trahit des stops
  absents ou mal placés.

C'est la même logique que `PLACEBO_PCT` dans `laboratoire_or` : un stop qui ne
coupe pas n'est pas un stop, il est décoratif.

### Les critères secondaires

| Critère | Seuil | Source |
|---|---|---|
| Semaines de trading | ≥ 20-25 (12 minimum) | guide MQL5 |
| Dépôt initial | un compte à 139 $ rend tout pourcentage illisible | mesure |
| Profit factor | < 1,5 = marge trop mince | jugement |
| Charge max du dépôt | plus c'est bas, moins ça empile | mesure |
| Taux de réussite | **un taux très élevé inquiète** — il accompagne l'absence de stop | guide MQL5 |

---

## 2. Les cinq fiches, relevées le 2026-09-27

| | Semaines | Croissance | DD solde | DD équité | PF | Trades | Réussite | Charge max | Abonnés | Dépôt init. |
|---|---|---|---|---|---|---|---|---|---|---|
| **Pure Gold 2000 Vantage** | 29 | 198 % | 11,55 % | **6,84 %** ✅ | 2,32 | 637 | 52,3 % | 12,03 % | 7 | — |
| **Gold Reaper New V2 2** | **100** | 309 % | 16,89 % | **7,18 %** ✅ | 2,34 | 873 | 72,5 % | **4,77 %** | 53 | — |
| Lucky Cat MT5 | 36 | 341 % | 28,61 % | 11,05 % | **1,50** | 699 | 67,4 % | 12,58 % | 5 | 350 $ |
| MegaGold | 73 | 331 % | 30,70 % | 16,34 % | **1,18** | 346 | 68,2 % | 6,17 % | **0** | **200 $** |
| MSC Gold Stable Pro | 127 | **1 470 %** | 15,45 % | **33,70 %** ⛔ | 3,19 | 1 137 | **82,2 %** | 24,82 % | 40 | **139 $** |

⚠️ **Écart relevé** : la liste d'accueil annonçait 2 309 % pour `Gold Reaper`,
sa fiche en annonce 309 %. C'est la fiche qui fait foi. Un chiffre de liste ne
se recopie pas sans vérification.

---

## 3. Lecture

### Le moins alarmant : `Pure Gold 2000 Vantage`

Le seul dont **tous** les marqueurs pointent dans le bon sens. DD équité
(6,84 %) **inférieur** au DD solde (11,55 %). Taux de réussite 52,3 % — crédible,
là où un 82 % doit inquiéter. Charge de dépôt 12 %. 637 trades sur 29 semaines,
compte réel, 45 000 $ sous gestion. Et la croissance la plus basse de la liste,
donc la moins gonflée.

**Sa faiblesse** : 29 semaines, soit le minimum acceptable. Et 7 abonnés.

### Le second : `Gold Reaper New V2 2`

**100 semaines** d'historique et une charge de dépôt de **4,77 %** — le plus
prudent des cinq sur ce point. DD équité très inférieur au DD solde.

**Sa faiblesse, et elle est sérieuse** : les avis d'abonnés rapportent des
**échecs de copie chez plusieurs courtiers**. Une stratégie saine qui ne se copie
pas coûte autant qu'une mauvaise.

### Le vaccin : `MSC Gold Stable Pro`

C'est le plus séduisant — 127 semaines, 1 470 %, 82 % de réussite, PF 3,19,
40 abonnés, **235 000 $ qui le suivent**. Et le plus dangereux :

- **DD équité 33,70 % contre 15,45 % en solde** — plus du double ;
- avis d'abonnés signalant **l'absence de stop-loss** ;
- dépôt initial **139 $**, ce qui rend les 1 470 % illisibles.

Fort taux de réussite + pas de stop + équité qui plonge deux fois plus que le
solde : la courbe est parfaite jusqu'au jour où elle ne l'est plus.

### Les deux pièges d'échelle

`MegaGold` : 331 % de croissance **sur un compte de 200 $**, profit factor 1,18,
zéro abonné. `Lucky Cat` : 350 $ de dépôt, PF 1,50, et des avis signalant des
entrées « au hasard », des lots incohérents et un fournisseur qui ne répond pas.

---

## 4. Ce que cette analyse ne peut pas dire

Qu'un de ces signaux soit sûr. **Aucun ne l'est.**

Le système de ce projet, avec des mois de mesure et un banc d'essai
pré-enregistré, affiche `DSR = 0,017` — aucun edge établi. Et `PBO = 0,579` dit
que sélectionner sur historique affiché fait moins bien que la médiane hors
échantillon **six fois sur dix**. Choisir un fournisseur sur sa courbe, c'est
exactement cette sélection-là.

Ce document élimine les dangereux. Il ne promet rien sur les autres.

---

## 5. Architecture, pour mémoire

⛔ **L'outil de scalping n'intervient pas.** MQL5 Signals copie **dans le
terminal** : le backend n'est jamais sur le chemin, et il ne doit pas l'être —
`R-29` établit que le bridge gérerait ces positions (stops déplacés, clôtures
partielles) et qu'elles consommeraient son budget de risque.

Le montage correct est dans `deploy/terminal-copie-isole.md` : second compte,
second terminal en mode portable, `MT5_TERMINAL_PATH` obligatoire sur le bridge.

---

## 6. Addendum — le regard rapproché élimine les DEUX finalistes

Approfondissement demandé le même jour sur les deux qui ressortaient. Les fiches
détaillées portent des informations que les statistiques de tête ne montrent pas.
**Elles disqualifient les deux**, et pour les mêmes trois raisons.

### Le critère le plus fort, et c'est MQL5 qui le calcule

MQL5 publie lui-même, sur chaque fiche, **la concentration de la croissance** :

| | Concentration publiée |
|---|---|
| `Pure Gold 2000 Vantage` | **80 % de la croissance en 6 jours** |
| `Gold Reaper New V2 2` | **80 % de la croissance en 32 jours sur 695** — 4,6 % des jours |

> ⛔ **Un edge qui tient dans 4,6 % des jours n'est pas un edge : c'est quelques
> fenêtres favorables.** Le guide MQL5 recommande de privilégier « *signals with
> smooth growth of profit* ». Aucun des deux n'y répond.

C'est le critère à placer **en premier**, avant même le rapport équité/solde : il
se lit sur la fiche, il est calculé par la plateforme, et il ne se maquille pas.

### Le fournisseur n'est pas un trader, c'est un catalogue

| | Signaux exploités | Produits vendus |
|---|---|---|
| `Pure Gold 2000 Vantage` | **11** | 5 |
| `Gold Reaper New V2 2` | **29** | 27 |

Quelqu'un qui exploite 29 signaux simultanément ne suit pas 29 stratégies : il
place 29 paris et vend celui qui a survécu. Les autres sont retirés sans bruit.

**C'est exactement le biais de sélection que `PBO = 0,579` mesure**, appliqué à
l'échelle d'un catalogue plutôt qu'à celle d'un backtest. Vous n'achetez pas une
méthode, vous achetez le survivant d'une portée.

### La copie échoue en pratique

Ce n'est pas un risque de stratégie, c'est un risque d'exécution — et il coûte
autant :

- `Gold Reaper` : *« Not a single trade was copied for the entire month »*
  (inadéquation de taille de dépôt), échecs de *mapping* de symboles, slippage,
  support absent ;
- `Pure Gold` : avertissements MQL5 répétés — *« too frequent deals »*, *« no
  trading activity detected »* — tout au long de 2026.

### Deux relevés de plus qui achèvent le dossier

**L'historique n'est pas homogène.** `Pure Gold` a **changé de stratégie le
9 avril** (« switching from UBS to EA Pure Gold »). Ses 29 semaines ne sont donc
pas 29 semaines de ce système. Un historique qu'on croit long est en réalité
plus court que le système qu'on achète.

**Le Sharpe de `Gold Reaper` est de 0,23** sur 100 semaines. À comparer au
`DSR = 0,017` de ce projet : ni l'un ni l'autre n'établit d'edge.

⚠️ Et une incohérence non résolue sur `Pure Gold` : la fiche annonce
**3 trades/semaine**, alors que 637 trades sur 29 semaines en font 22. Les deux
chiffres viennent de la même page. Je ne sais pas lequel est juste.

### Verdict de l'addendum

**Aucun des deux finalistes ne passe.** Et les trois motifs — croissance
concentrée sur quelques jours, fournisseur-catalogue, copie défaillante — ne sont
pas propres à eux : ce sont des propriétés du modèle économique de la place de
marché.

Le crible révisé, dans l'ordre :

1. **concentration de la croissance** — rejeter si 80 % tient dans moins de 15 %
   des jours ;
2. **nombre de signaux du fournisseur** — au-delà de 3, c'est un catalogue ;
3. **historique homogène** — aucun changement de stratégie en cours de route ;
4. **DD équité < DD solde** ;
5. **avis d'abonnés sur la copie effective**, pas sur la performance ;
6. semaines, profit factor, charge de dépôt, dépôt initial.

## Sources

- [Trading Signals MetaTrader 5](https://www.mql5.com/en/signals/mt5)
- [Tips for Selecting a Trading Signal to Subscribe](https://www.mql5.com/en/articles/1838)
- [Rules for copy trading](https://www.mql5.com/en/signals/rules)
- Fiches : [Pure Gold 2000 Vantage](https://www.mql5.com/en/signals/2362868) ·
  [Gold Reaper New V2 2](https://www.mql5.com/en/signals/2265877) ·
  [Lucky Cat MT5](https://www.mql5.com/en/signals/2359404) ·
  [MegaGold](https://www.mql5.com/en/signals/2337490) ·
  [MSC Gold Stable Pro](https://www.mql5.com/en/signals/2231030)
