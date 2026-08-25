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
| `admin_kraken_spot` | ✗ | `price_usd` | ✗ | ✗ — **pas d'endpoint d'ordres** | ✗ |
| `admin_ibkr_us` | `avg_cost` | ✗ | ✗ | ✗ — **pas d'endpoint d'ordres** | ✗ |

Deux conclusions structurent tout le reste :

1. **La dérivation MT5 ne se transporte pas.** Elle repose sur
   `k = profit / (courant − entrée)`, puis `risque = (entrée − stop) × k`.
   Ni Kraken ni IBKR ne rendent `profit` ou `price_current`. Il faut une
   **autre formule**, pas une adaptation.
2. **Kraken Futures est déjà mesurable, sans toucher au bridge.**
   `/openorders` rend `stopPrice`, `reduceOnly` et `orderType` par ordre.
   `_protection_par_symbole` (`kraken-futures-bridge/bridge.py:513`) réduit ça
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

## 4. ⛔ Le contrôle de réciprocité NE TOMBE PAS JUSTE — premier livrable

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

⇒ **Aucun chiffre n'est publié avant que cet écart soit expliqué.** Deux
hypothèses, exclusives, et il faut trancher :

- **(a) la mesure est juste et le dimensionnement sous-délivre** — alors la
  commande vient de révéler un défaut de sizing sur le réel Kraken, et c'est
  le résultat le plus important de tout ce chantier ;
- **(b) la formule manque quelque chose** — stop déplacé depuis l'ouverture,
  position partiellement fermée, ou taille plancher du courtier.

Publier avant de savoir laquelle, c'est publier un chiffre dont on ignore le
sens. Le distinguer se fait en rejouant l'ordre d'origine : `bridge_audit.db`
et `journalctl -u scalping` portent le `risk=` demandé au dispatch.

## 5. Ce qui change côté bridges

| bridge | changement | déploiement |
|---|---|---|
| Kraken Futures | **aucun** | — |
| Kraken Spot | ajouter `GET /openorders` (stops vivants + `reduceOnly`) | `kraken-spot-bridge`, EC2 |
| IBKR | ajouter `GET /openorders` (ordres enfants du bracket, rattachés au `conId`) | VPS `100.74.160.72:8792` |

Le geste est le même trois fois : **exposer le prix du stop vivant, pas un
booléen de protection.** Un booléen dit qu'une position est bornée, jamais où.

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

1. **Réciprocité** — `|entrée − stop| × taille` restitue le `risk_money` du
   dispatch, sur les positions Kraken réelles. C'est le test qui a déjà
   détecté quelque chose (§4) ; il doit conclure avant la publication.
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
