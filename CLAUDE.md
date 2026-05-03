# Scalping — Notes projet

## Contexte

Système de scalping automatisé actuellement **en démo** (MetaQuotes-Demo via bridge MT5).
Objectif final : passage en live avec élargissement progressif des instruments tradés.

## Feuille de route — Intégration de tous les supports

### Phase 1 : Démo restreinte (semaines 1-4, en cours)

- Conserver les **16 paires actuelles** (forex majeurs + XAU/XAG + BTC/ETH + SPX/NDX + WTI)
- Aucun ajout d'instrument
- Objectif : collecter 200-500 trades par classe d'actif
- Mettre en place le **logging ML-ready** en parallèle (table `signals`, `signal_id`, `fill_price`, `close_reason`, `skipped_setups`)
- Identifier les instruments gagnants vs perdants statistiquement

### Phase 2 : Élargissement contrôlé (semaines 4-8)

Ajouter par **lots de 5-10 instruments**, 2 semaines de démo par lot avant validation :
- Lot A : indices européens (DAX, CAC40, FTSE)
- Lot B : indices US (US30, NAS100)
- Lot C : énergie (Brent, NatGas)
- Lot D : forex exotiques (USD/NOK, USD/SEK, USD/MXN)
- Lot E : crypto élargies (SOL, ADA, XRP)

Méthode : éditer `WATCHED_PAIRS` dans `.env`. Classification automatique via `asset_class_for()`.

### Phase 3 : Migration multi-broker (semaines 8-12)

Le broker actuel (MetaQuotes-Demo / OANDA) ne couvre pas tout.
- Choisir un broker multi-asset : **Pepperstone, IC Markets, Admiral Markets ou Darwinex**
- Mettre à jour `MT5_SYMBOL_MAP` avec les nouveaux symboles broker
- Étendre `MT5_BRIDGE_ALLOWED_ASSET_CLASSES="forex,metal,index,energy,crypto"`
- Tester d'abord sur compte démo du nouveau broker

#### 3b. Sortir de l'écosystème MT5 pour les vraies bourses (à étudier)

**Constat** : tous les brokers MT5 (Pepperstone & co) ne donnent que des **CFDs synthétiques**. Pas d'accès direct aux bourses (NYSE, NASDAQ, Euronext, Xetra, TSE, LSE…), pas d'actions individuelles, pas d'obligations, pas de DMA. Le broker est ta contrepartie qui hedge, jamais le market.

**Question à trancher en Phase 3** : faut-il rester en CFD MT5, ou réécrire le bridge pour un broker stocks ?

| Option | Couvre | Coût chantier |
|---|---|---|
| **MT5 multi-asset** (Pepperstone, etc.) | + indices, + énergie, + crypto altcoins. **Toujours CFD.** | Faible (juste config) |
| **Interactive Brokers (IBKR)** | NYSE/NASDAQ/Euronext/TSE/LSE en DMA, actions, options, futures, bonds | **Réécrire le bridge** (TWS API ≠ MT5). ~2-3 semaines |
| **Saxo Bank / Trading 212 / DEGIRO** | Stocks Europe/US en exécution simple, pas DMA | Réécriture bridge selon API du broker |

Décision dépendra de :
- Validation V2 / Track A — si edge confirmé sur instruments existants, prioriser breadth (MT5 multi-asset) avant de complexifier le bridge
- Ambition produit — Scalping Radar reste-t-il sur métaux/énergie/crypto, ou ouvre vers actions individuelles (autre modèle, autres horizons) ?
- Budget temps : 2-3 semaines de réécriture bridge IBKR vs valeur ajoutée produit

À l'ouverture de Phase 3, **réviser cette section** : valider si on étend juste le CFD ou si on bascule vers DMA/stocks.

### Phase 4 : Scaling infra (si > 30 instruments simultanés)

- Twelve Data : passer du plan Grow (5 000 req/j) au plan Pro (75 000 req/j, ~75 €/mois)
- Ou basculer sur MT5 direct comme source de données (illimité)
- Paralléliser l'analyse par classe d'actif (actuellement séquentielle)

### Phase 5 : Passage en live

Prérequis avant activation :
- Kill switch global (pause auto si perte journalière > seuil)
- Sizing dynamique (vs 0.01 lot fixe actuel)
- Remonter `MT5_BRIDGE_MIN_CONFIDENCE` à 95 au démarrage
- Phase shadow 1-2 semaines sur démo du broker live
- Stats validées : win rate, drawdown max, profit factor, exposition simultanée

Changements techniques minimes :
- `.env` : `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`
- Bridge (PC Windows) : `PAPER_MODE` → `LIVE_MODE`
- Aucun changement code backend

## Principes directeurs

- **Ne jamais élargir avant d'avoir validé** la classe d'actif précédente
- Chaque instrument a sa personnalité (volatilité, heures actives) → probable besoin de sous-modèles par classe
- Un scalping efficace = 5-8 instruments maîtrisés, pas 50 survolés
- Garder l'humain dans la boucle pour valider chaque passage de phase

## Architecture actuelle (rappel)

- Backend : FastAPI (EC2 + Nginx + Let's Encrypt)
- Frontend : en cours de refonte React (coté utilisateur, via CLI)
- Data : Twelve Data (plan Grow)
- Broker : MetaQuotes-Demo (OANDA TMS) via bridge MT5 sur PC Windows
- Auth : cookies HttpOnly session same-origin
- Branche de dev : `claude/demo-to-live-automation-eswt0`

## Instruments actuels (WATCHED_PAIRS)

```
EUR/USD, GBP/USD, USD/JPY, EUR/GBP, USD/CHF, AUD/USD, USD/CAD,
EUR/JPY, GBP/JPY, XAU/USD, XAG/USD, BTC/USD, ETH/USD, SPX, NDX, WTI/USD
```

Auto-exécutables via bridge : forex + métaux uniquement (`MT5_BRIDGE_ALLOWED_ASSET_CLASSES="forex,metal"`).
