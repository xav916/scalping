# Risque engagé à l'instant t — étendre la mesure à Kraken et IBKR

**Date** : 2026-08-25
**Objectif** : que la commande Telegram `risque` couvre les cinq destinations
(MT5 démo, MT5 réel, Kraken Futures, Kraken Spot, IBKR) au lieu des deux
comptes MT5, en euros, sans jamais publier un chiffre qui n'a pas été mesuré.

---

## 1. Le besoin

La commande `risque` (commit `d60ca2b`) rend le risque engagé cumulé des deux
comptes MT5. Les trois autres destinations n'y figurent pas — ni mesurées, ni
mentionnées. **Leur absence est aujourd'hui invisible**, ce qui est le défaut
qu'on répare : une destination qui ne dit rien se lit comme une destination
qui n'a rien.

## 2. Ce que chaque bridge expose réellement

Vérifié endpoint par endpoint le 2026-08-25, pas déduit de la documentation.

| destination | entrée | prix courant | profit | **stop** | plafond de risque |
|---|---|---|---|---|---|
| `admin_legacy` / `admin_live` (MT5) | `price_open` | `price_current` | `profit` | `sl` dans la position | `garde_fous.max_risque_engage_pct` |
| `admin_kraken` (Futures) | `price` | ✗ | ✗ | ✅ **`/openorders` → `stopPrice`** | ✗ |
| `admin_kraken_spot` | ✗ | `price_usd` | ✗ | ⚠️ **`/positions.active_watchers.sl`** — stop LOGICIEL, pas un ordre du carnet | ✗ |
| `admin_ibkr_us` | `avg_cost` | ✗ | ✗ | ✗ — **pas d'endpoint d'ordres** | ✗ |

Deux conclusions structurent tout le reste :

1. **La dérivation MT5 ne se transporte pas.** Elle repose sur
   `k = profit / (courant − entrée)`, puis `risque = (entrée − stop) × k`.
   Ni Kraken ni IBKR ne rendent `profit` ou `price_current`. Il faut une
   **autre formule**, pas une adaptation.
2. **Kraken Futures est déjà mesurable, sans toucher au bridge.**
   `/openorders` rend `stopPrice`, `reduceOnly` et `orderType` par ordre.
   `_protection_par_symbole` (`kraken-bridge/bridge.py`) réduit ça
   à un booléen pour son propre usage, mais la charge brute porte le prix.

## 3. La forme unique du calcul

```
risque = |entrée − stop| × taille
```

Aucun tick value, aucun multiplicateur de contrat : les tailles Kraken `PF_*`
sont **en actif de base direct** (`kraken_bridge_client.py:36`), les quantités
spot en devise de base, les quantités IBKR en nombre d'actions.

C'est **exactement l'inverse de la formule qui dimensionne l'ordre**
(`qty = risk_money / |entry − sl|`, identique dans les trois clients). Cette
symétrie est le contrôle : recalculer doit restituer le `risk_money` d'origine.

⛔ **Entrée ET stop se lisent chez le COURTIER, jamais dans nos tables.**
Kraken rend l'entrée moyenne réellement obtenue, IBKR rend `avg_cost`, les
stops viennent des ordres vivants. C'est la leçon des 44 % de SL/TP stockés
qui différaient de ceux du courtier, et des `entry_price=0` d'IC Markets : nos
enregistrements ne sont pas la vérité.

## 4. ✅ RÉSOLU — l'écart venait de ma référence, pas du dimensionnement

> **Statut : clos le 2026-08-25.** La section originale est conservée
> ci-dessous ; sa conclusion est corrigée ici.

**Cause racine : `base` n'est pas `risk_money`.** Le système ne vise pas
`capital × risk_pct`, il vise (`sizing.py:203-208`) :

```python
final_mult = conf_mult * pnl_mult * session_mult * macro_mult
risk_money = round(base * final_mult, 2)
```

Les 2,16 USD pris comme référence étaient le `base`. Facteurs mesurés en
production le 25/08 sur `admin_kraken` :

| facteur | valeur mesurée | pourquoi |
|---|---|---|
| `pnl_mult` | **0,5** | PnL 7 jours négatif — **frein de perte, actif en ce moment** |
| `session_mult` | **1,0** | crypto 24/7, grille de séance neutralisée |
| `conf_mult` | 0,5 – 1,5 | selon le score du setup |
| `macro_mult` | plancher 0,3 | selon l'alignement |

Six des huit ordres retombent directement dans la plage légitime de
`conf × macro` (0,5 – 1,5). Les deux qui sortent de ~3 % sont expliqués par
**l'arrondi vers le bas de la quantité** — le risque mesuré est un
**minorant** du risque visé. Vérifié au centième sur DOT :

```
risk_money visé = 2,1586 × 0,5 × 0,5 = 0,5397 USD
qty théorique   = 0,5397 / 0,2371    = 2,2760
pas de 0,1, arrondi bas               → 2,2      (observé : 2,2)
risque réel     = 2,2 × 0,2371        = 0,5216 USD (mesuré : 0,5216)
```

⇒ **Ni le dimensionnement ni la formule `|entrée − stop| × taille` ne sont en
cause.** Le contrôle de réciprocité était mal spécifié.

### Ce que l'enquête a produit d'utile

1. ⛔ **Le contrôle doit viser `risk_money`, pas `base`**, et accepter
   `mesuré ≤ risk_money` puisque la quantité s'arrondit vers le bas. Un
   contrôle qui vise `base` crie au loup à chaque fois que le frein de perte
   ou un score médiocre réduit la taille — c'est-à-dire en permanence.
2. ⛔ **`risk_money` n'est persisté nulle part.** `journalctl` ne tient qu'un
   jour, et `mt5_pushes.bridge_response` ne le porte pas. Il a fallu le
   reconstruire par l'arithmétique inverse. ⇒ **Le persister avec le push**
   est le prérequis pour que ce contrôle tourne en routine plutôt qu'à la
   main. C'est aussi ce qui manquait pour détecter les positions placebo.
3. ⚠️ **Fait d'exploitation, silencieux** : `pnl_mult = 0,5` en ce moment.
   **Chaque ordre Kraken part à demi-taille**, par conception, et rien ne
   l'annonce.

---

## 4-bis. La section originale — ce qui avait alerté

Mesuré sur les deux positions Kraken vivantes le 2026-08-25 :

```
portfolio_value_usd = 107,93     risk_per_trade_pct = 2,0
⇒ risk_money attendu par trade  = 2,16 USD

PF_DOTUSD    entrée 0,9507   stop 0,7136   size 2,2     → 0,5216 USD   (24 % du voulu)
PF_PAXGUSD   entrée 4608,0   stop 4312,2   size 0,003   → 0,8874 USD   (41 % du voulu)
                                                  TOTAL  1,4090 USD   (1,31 % du portefeuille)
```

Les deux positions risquent **moins de la moitié** de ce qui était prévu.
C'est le motif exact des positions placebo du démo, où 455 trades sur 610
risquaient un millième du voulu sans qu'aucun contrôle ne le détecte
(`project_sizing_crypto_placebo_2026_08_11`).

Le garde-fou posé alors, `_risque_realise()` + `RISK_RATIO_MIN=0.5`, **refuse**
une position qui risque moins de la moitié du voulu — mais il vit dans
`bridge.py` (MT5). **Il faut établir s'il est armé sur la route Kraken.**

Deux hypothèses avaient été posées : **(a)** le dimensionnement sous-délivre,
**(b)** la formule manque quelque chose. **Les deux sont réfutées** — voir §4.
L'ordre d'origine de PAXG, retrouvé dans `mt5_pushes` (`id=14187`), montre
entrée, stop et volume **identiques à aujourd'hui** : ni stop déplacé, ni
fermeture partielle. La position est née avec ce risque.

Ce qui manquait était une troisième hypothèse, celle qui s'est vérifiée : la
**référence** était fausse.

## 5. Ce qui change côté bridges

> **Révisé le 2026-08-25 après lecture du bridge spot** — la première version
> de cette section prévoyait un `GET /openorders` sur le spot. C'est faux, et
> pour une raison qui compte (voir ci-dessous).

| bridge | changement | déploiement |
|---|---|---|
| Kraken Futures | **aucun** — `/openorders` expose déjà `stopPrice` | — |
| Kraken Spot | **ajouter `entry` au registre des watchers** (2 lignes) | `kraken-spot-bridge`, EC2 |
| IBKR | ajouter `GET /openorders` (ordres enfants du bracket) | VPS `100.74.160.72:8792` |

### ⛔ Le spot n'a pas de stop chez le courtier

`kraken-spot-bridge` ne pose **aucun ordre stop chez Kraken**. Il lance un
**watcher logiciel** (`_start_watcher`, ligne 368) : un thread qui surveille le
prix et vend au marché quand le niveau est touché. Un `/openorders` n'y
trouverait rien.

`/positions` publie déjà `active_watchers` avec `pair`, `qty`, `sl` et `tp` —
**il ne manque que le prix d'entrée**, d'où un changement de deux lignes au
lieu d'un endpoint.

⚠️ **Un stop logiciel et un stop courtier ne sont pas le même objet.**
`_watchers` est un dictionnaire en mémoire, **sans persistance** : un
redémarrage du bridge spot perd ses stops et laisse les positions nues. Le
message doit donc le marquer (`stop_logiciel`) — les compter à l'identique
surestimerait la protection.

⇒ **La non-persistance des watchers est un risque réel, hors périmètre de ce
chantier.** Constatée ici, elle est à traiter séparément.

Là où un stop courtier existe, le geste est le même : **exposer son prix, pas
un booléen de protection.** Un booléen dit qu'une position est bornée, jamais
où.

## 6. Devise — une seule conversion, faillible sans dommage

Kraken et IBKR comptent en USD, MT5 en EUR, et l'utilisateur veut des euros.
Un seul taux EURUSD, lu via le `/tick` d'un bridge MT5 déjà authentifié.

⛔ **Taux indisponible ⇒ on ne convertit pas et on ne somme pas.** Le total
tombe alors sur « impossible », comme pour une destination illisible. Un taux
approximatif produirait un total crédible et faux — le chiffre que le code
refuse déjà d'imprimer.

## 7. Le message

- **MT5** : inchangé — euros, plafond, pourcentage, marge restante.
- **Kraken Futures / Spot / IBKR** : euros convertis, **pas de pourcentage**,
  et une mention explicite qu'aucun plafond de risque n'est armé sur ces
  destinations. Un `—` muet se lirait comme « 0 % ».
- **Total** : ne s'annonce que si **toutes** les destinations sont mesurées
  **et** converties. La règle actuelle ne change pas, elle s'étend.

Les quatre façons de ne pas savoir restent distinctes et nommées : bridge
muet ⇒ `illisible` ; position pile à l'entrée ⇒ `non mesurable` ; position
sans stop ⇒ `indécidable` ; stop à l'équilibre ⇒ un vrai zéro.

## 8. ⚠️ Ce qui ne sera PAS prouvé

**Le bridge IBKR refuse les connexions** — armé et fermé depuis la décision du
2026-08-10 de rester à 100 USD ; il refuse chaque setup en `fees_exceed_edge`.

Son `/openorders` sera écrit et testé sur bouchons, **jamais exercé en
marche**. Aujourd'hui IBKR rendra `illisible`, ce qui est le verdict juste.
Cette limite est déclarée ici pour ne pas être comptée comme faite.

⚠️ Kraken Spot porte **0 position** à ce jour : son chemin sera exercé à vide.

## 9. Tests

1. **Réciprocité** — `|entrée − stop| × taille` doit valoir **`risk_money`, à
   un arrondi de quantité près et par en dessous** — ⛔ jamais `base`
   (`capital × risk_pct`), qui ignore les quatre multiplicateurs et ferait
   crier au loup dès que le frein de perte s'active (§4). Prérequis :
   persister `risk_money` avec le push.
2. **Mutations** — stop absent ⇒ `indécidable` jamais 0 ; taux FX manquant ⇒
   pas de total ; bridge muet ⇒ `illisible` ; une destination oubliée du
   parcours ⇒ un test tombe.
3. **Branchement** — les cinq destinations sont réellement parcourues. Des
   tests de fonctions pures ne diraient rien si le parcours en sautait une.
4. **Concordance croisée** — les chiffres reproduits par un second chemin de
   code, comme pour la sonde de saturation.

## 10. Ce qui reste à trancher

**Faut-il poser un vrai plafond de risque sur Kraken ?** Une fois la mesure en
place, le pourcentage redeviendrait comparable entre destinations. Mais c'est
une **porte de trading** qui refusera des ordres, pas une mesure — donc une
décision distincte de ce chantier, et qui appartient à Xavier.

⚠️ Rappel de méthode : ne jamais desserrer une porte, et poser la mesure avant
la porte — l'ordre inverse laisserait le compte exposé entre les deux.
