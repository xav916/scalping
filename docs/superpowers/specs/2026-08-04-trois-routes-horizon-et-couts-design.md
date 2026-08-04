# Trois routes de trading — horizon et coûts

**Date** : 2026-08-04
**Objectif** : rendre MT5, Kraken et IBKR simultanément opérationnelles, à capital constant.

---

## 1. Le besoin

Couvrir trois classes d'actifs, chacune par la route qui y donne accès :

| classe | route | état au 2026-08-04 |
|---|---|---|
| forex, métaux, CFD actions | MT5 IC Markets | actif, €297,30, 0 position |
| crypto | Kraken | désactivé le soir même (frais 2,6× l'edge) |
| vraies actions US en DMA | IBKR | bridge codé, non déployé, compte Cash |

**Contrainte** : ~500 € au total, aucun apport prévu.

Cette contrainte est structurante et non négociable dans ce design. Elle ferme le compte
Margin IBKR (2 000 $ minimum) et impose de travailler en compte Cash — sans levier,
règlement à J+1.

## 2. Le constat qui structure la solution

Les trois ponts techniques existent et ont été prouvés en réel. Aucun blocage
d'ingénierie. Ce qui bloque est économique, et de deux natures :

- **Kraken** — coût *proportionnel* (0,10 % aller-retour taker contre un SL médian de
  0,347 % du prix). Un ratio ne s'améliore pas avec le capital.
- **IBKR** — coût *fixe* (~2 USD l'aller-retour). Il s'améliore mécaniquement avec la
  taille, mais 500 € ne suffisent pas.

**Le blocage réel n'est donc ni le capital ni le broker : c'est l'horizon.** Un TP de
scalping est trop petit pour survivre à un coût qui ne soit pas un simple spread.
Allonger l'horizon est la seule variable disponible sans argent frais, et elle agit sur
les deux routes bloquées à la fois.

Deux découvertes faites pendant la conception confirment la direction :

**Aucun modèle de coût n'existe dans le code.** `commission` n'apparaît que dans le
programme de parrainage ; `maker`/`taker` seulement comme features de scoring. Le
dispatch décide sans jamais consulter un prix de revient. C'est la cause commune de
trois incidents de la semaine : 876 trades crypto perdants, xStocks construite puis
mesurée, Voie C forex codée entièrement avant de découvrir 383 % de coût.

**L'horizon long tourne déjà, mais n'est pas branché.** `shadow_setups.timeframe`
contient `1h` (20 748), `4h` (244) et `1d` (50), alimentés par des systèmes V2 actifs
en production (`V2_CORE_LONG_XAUUSD_4H`, `V2_WTI_OPTIMAL_WTIUSD_4H`,
`V2_CORE_LONG_ETHUSD_1D`), frais du jour même. Ils détectent, enregistrent et
réconcilient — ils n'atteignent jamais le dispatch. Même motif que les paires equity
découvertes le matin : un flux analysé en continu, jamais routé, invisible faute de
refus explicite.

Le chantier n'est donc pas « construire un radar day-trading » mais **brancher un
générateur existant, en interposant une porte de coût**.

## 3. Architecture

### 3.1 Modèle de coût par destination, consulté au dispatch

Chaque destination déclare sa structure de coût réelle :

```
admin_live   (MT5)    spread seul, absorbé dans le prix        ~0,022 R mesuré
admin_kraken          proportionnel, 0,05 % par jambe          0,10 % A/R
voie_c       (IBKR)   fixe, ~1 USD par ordre avec minimum      ~2 USD A/R
```

Au dispatch, avant tout envoi, le coût attendu du trade est comparé à son edge brut
attendu — distance au TP × probabilité de l'atteindre. La règle déjà posée devient du
code :

> **frais > 30 % de l'edge brut ⇒ le signal n'est pas envoyé**

**D'où vient cette probabilité.** Pour le scalping, elle est mesurée sur `trades`
(analyser `trades`, pas `shadow_setups`). Pour 4h et 1d, **aucune mesure fiable
n'existe encore** : l'historique shadow antérieur au 2026-08-04 est à écarter. Tant
qu'un échantillon propre n'est pas constitué, ces routes restent en état `TELEGRAM`,
sans argent — la porte de coût n'a donc rien à arbitrer. Elle ne devient décisive qu'au
passage en `AUTO_EXEC`, et ce passage exige justement cet échantillon. Aucune valeur
par défaut n'est inventée : une probabilité inconnue vaut `None`, jamais `0`, et une
destination sans probabilité connue ne peut pas passer en argent réel.

Conséquences :

- **L'arrêt de la crypto devient automatique.** Il ne dépend plus de
  `KRAKEN_BRIDGE_ENABLED`, un drapeau remis à la main le 2026-08-04 après avoir été
  rallumé sans que la décision d'arrêt soit revenue dessus.
- **IBKR devient sûr à ouvrir à 500 €.** La route refuse d'elle-même toute position
  trop petite pour payer sa commission.
- **Le prochain broker se mesure avant de se construire** : une ligne de déclaration
  avant la première ligne de bridge.

Fondations réutilisées : `risk_eur.py` (calcul sur notionnel, validé contre le P&L
réellement encaissé) et `signal_rejections` (traçabilité des refus).

### 3.2 Le portage, coût que le scalping ne payait pas

À 4h ou 1d, une position paie aussi sa détention. Ce coût n'existe nulle part
aujourd'hui :

- **Kraken perpétuels** → funding prélevé périodiquement
- **MT5 CFD** → swap overnight
- **IBKR cash** → aucun, faute de levier : avantage réel de la contrainte Cash

Le funding Kraken est déjà collecté comme feature de scoring ; il doit être réutilisé
comme **coût**. Sans lui, le modèle sous-estimerait Kraken précisément là où il doit
être sévère.

### 3.3 L'horizon comme dimension de premier ordre

**Prérequis, à traiter en premier.** La production analyse des bougies de 5 minutes
(`CANDLE_INTERVAL=5min`) alors que le shadow V1 et le moteur de backtest étiquettent
en `1H`. L'horizon est donc aujourd'hui mal enregistré sur le flux principal.
Construire un routage sur une étiquette fausse reproduirait l'erreur du
`bar_timestamp` corrigée la veille. Corriger d'abord, brancher ensuite.

`BridgeConfig` reçoit deux champs, de même nature que ses filtres existants
(`allowed_asset_classes`, `allowed_patterns`, `excluded_pairs`) :

```
allowed_horizons : frozenset[str]     MT5 {5min} · Kraken {4h, 1d} · IBKR {4h, 1d}
cost_model       : CostModel          proportionnel + fixe + minimum par ordre
```

Deux refus traçables au dispatch : `horizon_not_allowed`, `fees_exceed_edge`.

**Aucun code de refus ne commence par un souligné.** Les codes privés `_xxx` sont
supprimés silencieusement — c'est ce qui a rendu AAPL invisible deux jours durant.

### 3.4 Routage cible

| route | horizon | source | à compléter |
|---|---|---|---|
| MT5 | scalping | V1 | rien, actif |
| Kraken | 4h et 1d | V2 crypto | BTC — seul ETH est couvert aujourd'hui, et en 1d |
| IBKR | 4h et 1d | V2 actions | titres individuels — seuls les ETF XLK et XLI sont couverts |

Kraken accepte les deux horizons parce que sa seule source crypto existante
(`V2_CORE_LONG_ETHUSD_1D`) est en 1d : le restreindre à 4h ne routerait rien.

### 3.5 Garde-fous

La chaîne existante s'applique sans modification : kill switch global, pause
automatique par paire à 3 SL/h, plafond de notionnel (2× Kraken, 5× global), délai
minimum entre ordres, garde-fou de corrélation, perte quotidienne max 3 %, positions
maximum, whitelists.

Ce qu'elle ne couvre pas, et qui naît de l'horizon long : une position tenue plusieurs
heures ou jours traverse des événements qu'une position de scalping ne rencontrait
jamais.

| risque | réponse |
|---|---|
| gap de week-end | généraliser le gel énergie du vendredi à toute position dont l'horizon dépasse la clôture |
| earnings | le veto earnings (×0,60) devient **bloquant dès l'horizon 4h**, atténuant en deçà |
| gap overnight actions | accepté, intégré au dimensionnement — non éliminable en compte Cash |

Principe : **à horizon long, un veto qui réduit la taille ne suffit plus.** Un
événement connu à l'avance et tombant pendant la détention doit empêcher l'ouverture,
puisqu'on ne peut plus sortir avant.

### 3.6 Mise en route

Aucune route nouvelle ne reçoit d'argent avant un échantillon propre postérieur au
2026-08-04. Les outcomes 4h existants (28 TP1 / 124 SL / 68 TIMEOUT) sont
**inexploitables** : le bug de déduplication faussait les comptes jusqu'à ×960 et toute
mesure shadow antérieure est à écarter. Ils ne disent rien, ni en bien ni en mal.

Ordre appliqué, celui qui a fonctionné le matin même sur les actions :

1. état `TELEGRAM` — les setups sont visibles, jugés, aucun argent engagé
2. mesure sur échantillon propre, route par route
3. `AUTO_EXEC` seulement si la mesure tient

## 4. Hors périmètre

- Pas de nouveau générateur de signaux : les systèmes V2 existent.
- Pas de passage en compte Margin IBKR : hors budget, et le design doit tenir à 500 €.
- Pas de refonte du scoring : le barème v2 du jour reste tel quel.
- Ordres **maker** sur Kraken : levier réel (division possible des frais par deux) mais
  à mesurer séparément, après le modèle de coût. Ne pas mélanger deux changements.

## 5. Vérification

Le design est tenu quand :

1. un signal dont les frais dépassent 30 % de l'edge produit une ligne dans
   `signal_rejections` avec `fees_exceed_edge`, et rien n'est envoyé ;
2. `KRAKEN_BRIDGE_ENABLED=true` ne suffit plus à faire trader la crypto à perte ;
3. les setups 4h atteignent l'état `TELEGRAM` et sont visibles sur Telegram ;
4. l'horizon enregistré correspond à l'intervalle de bougies réellement analysé ;
5. la suite de tests passe entièrement — 1485 verts au moment de la rédaction.

## 6. Pièges connus à ne pas rejouer

- Sonder la bonne table : `signal_rejections.details`, pas `personal_trades`.
- Vérifier les seuils par `resolve_destinations`, jamais par les attributs de settings.
- Quatorze couches multiplicatives s'appliquent après le barème de base.
- Un correctif de portée peut ressusciter des décisions passées inertes : auditer avant
  de déployer.
- Tester les deux sens : l'admission bloque en amont de la whitelist, et un seul sens
  testé ne prouve rien.
