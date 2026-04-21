# Scalping — Notes projet

> **Convention de maintenance** : ce fichier est la mémoire projet partagée entre toutes les
> sessions Claude Code. **Mets-le à jour quand tu commites un changement architectural**
> (nouveau service, nouvelle table, refonte majeure, décision de design non évidente). Un
> hook pre-commit (`.githooks/pre-commit`) te rappelle à l'ordre quand tu commites des
> fichiers sensibles sans toucher à ce fichier. Actualiser cette page en 5 min évite à la
> session suivante de redécouvrir l'architecture à chaque fois.

## Contexte

Système de scalping automatisé actuellement **en démo** (MetaQuotes-Demo via bridge MT5).
Objectif final : passage en live avec élargissement progressif des instruments tradés.

## Feuille de route — Intégration de tous les supports

### Phase 1 : Démo restreinte (semaines 1-4, en cours)

- Conserver les **16 paires actuelles** (forex majeurs + XAU/XAG + BTC/ETH + SPX/NDX + WTI)
- Aucun ajout d'instrument
- Objectif : collecter 200-500 trades par classe d'actif
- Logging ML-ready **livré** (table `signals`, `signal_id` sur `personal_trades`, `fill_price`, `slippage_pips`, `close_reason`)
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

### Phase 4 : Scaling infra (si > 30 instruments simultanés)

- Twelve Data : passer du plan Grow (5 000 req/j) au plan Pro (75 000 req/j, ~75 €/mois)
- Ou basculer sur MT5 direct comme source de données (illimité)
- Paralléliser l'analyse par classe d'actif (actuellement séquentielle)

### Phase 5 : Passage en live

Prérequis avant activation :
- Kill switch global (**livré**, voir `backend/services/kill_switch.py`)
- Sizing dynamique (**livré**, voir `backend/services/sizing.py`)
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
- **Aucun trade manuel** : l'exécution est 100% déléguée au bridge MT5. Le dashboard n'offre **pas** de bouton "J'ai pris ce signal" — c'est voulu pour avoir un feedback loop propre (signal = mesure du modèle, personal_trade = mesure de l'exécution, pas de biais psycho humain au milieu)
- **Pas de feature sans data** : on n'ajoute pas de règle de scoring sans ≥200 trades pour valider empiriquement. Les multiplicateurs actuels (session, macro, confiance...) sont des priors raisonnables à calibrer plus tard

## Architecture actuelle

### Stack

- **Backend** : FastAPI (Python 3.11), déployé sur EC2 + Nginx + Let's Encrypt + DuckDNS
- **Frontend** : React 18 + Vite + TypeScript + Tailwind + SWR + react-router (voir `frontend-react/`). L'ancien vanilla HTML reste comme **fallback** (activation auto selon la présence de `frontend-react/dist/`)
- **Data** : Twelve Data (plan Grow, 5000 req/j, ~10 paires à 180s cycle)
- **Broker** : MetaQuotes-Demo (OANDA TMS) via bridge MT5 sur PC Windows (Tailscale)
- **Auth** : cookies HttpOnly session same-origin (pas de JWT, pas de CORS)
- **Branche de dev** : `claude/demo-to-live-automation-eswt0`

### Services backend (`backend/services/`)

| Service | Rôle |
|---|---|
| `scheduler.py` | Cycle d'analyse 180-300s + jobs périodiques (backtest check, sync bridge, macro, COT hebdo, Fear&Greed quotidien, cockpit push 5s) |
| `analysis_engine.py` | Détection volatilité / tendance / patterns / setups |
| `price_service.py` | Fetch Twelve Data avec cache et semaphore anti-rate-limit |
| `twelvedata_ws.py` | WebSocket Twelve Data pour ticks <1s |
| `forexfactory_service.py` | Calendrier éco (JSON feed primaire + scraping HTML fallback) |
| `macro_context_service.py` | Snapshot 8 indicateurs macro (DXY, SPX, VIX, US10Y, Oil, Nikkei, Gold, DE10Y) |
| `mt5_bridge.py` | Push setups HTTP → bridge Windows (auto-exec selon seuil confiance) |
| `mt5_sync.py` | Pull `/audit` bridge → remontée dans `personal_trades` avec matching `signal_id` |
| `trade_log_service.py` | Table `personal_trades` (trades réels + contexte macro + fill/slippage/close_reason) |
| `backtest_service.py` | Tables `signals` (archive ML-ready) + `trades` (outcome théorique) |
| `cockpit_service.py` | Agrégateur cockpit (build payload unique pour homepage + push WS 5s) |
| `notification_service.py` | WebSocket `/ws` : broadcast signals/ticks/cockpit, auth par user |
| `analytics_service.py` | Breakdowns win rate (pair, hour, pattern, confidence, asset_class, regime, exec quality) |
| `drift_detection.py` | Drift 7j vs baseline sur pair et pattern |
| `kill_switch.py` | Coupure auto (daily loss ≥ seuil) ou manuelle ; gate dans `mt5_bridge._should_push` |
| `sizing.py` | `risk_money = capital × risk_pct × conf × pnl × session × macro` |
| `session_service.py` | Classification session UTC (london_ny_overlap, asian, weekend...) + multiplicateur |
| `event_blackout.py` | Blocage auto-exec ±15min autour d'un event HIGH-impact sur la devise |
| `macro_alignment.py` | Multiplicateur cross-asset (DXY/VIX/yields/regime) |
| `cot_service.py` | Ingestion CFTC hebdo + z-score 52 semaines + flag extrêmes (affichage seulement) |
| `fear_greed_service.py` | CNN Fear & Greed quotidien (affichage seulement) |

### Pipeline d'exécution d'un setup

```
cycle analyse → generate setups → record_signals() archive TOUS
                                ↓
                       filter_high_confidence_setups (verdict TAKE/WAIT/SKIP)
                                ↓
                  record_setups() pour le backtest outcome
                                ↓
                       mt5_bridge.send_setup(setup)
                                ↓
                     _should_push() gate hierarchique :
                  1. is_configured ?
                  2. kill_switch.is_active() ?
                  3. event_blackout.is_blackout_for(pair) ?
                  4. setup.is_simulated ?
                  5. verdict_blockers ?
                  6. confidence >= MT5_BRIDGE_MIN_CONFIDENCE ?
                  7. asset_class in MT5_BRIDGE_ALLOWED_ASSET_CLASSES ?
                  8. dedup journalier
                                ↓
              sizing.compute_risk_money(setup) :
              base × conf_mult × pnl_mult × session_mult × macro_mult
                                ↓
                  POST /order vers le bridge MT5 (Windows PC)
                                ↓
                  bridge calcule les lots depuis risk_money + specs broker
                                ↓
                          MT5 place l'ordre
                                ↓
                  mt5_sync.sync_from_bridge() pull /audit :
                  match signal_id + store fill_price + slippage + close_reason
                                ↓
                       personal_trades table updated
```

### Tables SQLite

Deux fichiers :
- `backtest.db` : `trades` (outcomes théoriques), `signals` (archive ML-ready)
- `trades.db` : `personal_trades` (trades réels), `user_prefs` (silent mode),
  `cot_snapshots` (hebdo CFTC), `fear_greed_snapshots` (quotidien CNN)

Backup S3 via `deploy/backup-s3.sh`. **Vérifier** que le cron tourne et qu'il embarque les deux fichiers.

### Endpoints REST (résumé non exhaustif)

- **Cockpit** : `GET /api/cockpit` (one-shot complet pour homepage)
- **Analytics / drift** : `GET /api/analytics`, `GET /api/drift`
- **Kill switch** : `GET|POST /api/kill-switch`
- **COT / Fear&Greed** : `GET /api/cot`, `GET /api/fear-greed` (+ `/refresh` manuels)
- **Données marché** : `/api/overview`, `/api/signals`, `/api/trade-setups`, `/api/volatility`, `/api/macro`, `/api/events`, `/api/candles`, `/api/indicators`, `/api/ticks`
- **Trades** : `GET /api/trades` (lecture seule, plus de POST/PATCH manuel), `/api/trades.csv`, `/api/daily-status`, `/api/risk`, `/api/equity`, `/api/stats/*`
- **Telegram silent mode** : `POST /api/silent-mode`
- **Ops** : `/api/health`, `/api/refresh` (force cycle)
- **WebSocket** : `/ws` (messages type `cockpit`, `signal`, `tick`, `update`, `pong`)

### Frontend React (`frontend-react/`)

Structure :
- `src/api/` : types miroirs des payloads backend + client HTTP
- `src/hooks/` : `useAuth` (SWR `/api/me`), `useCockpit` (REST initial + WS live, reconnect exponential backoff)
- `src/components/cockpit/` : panels tour de contrôle (MacroBanner, ActiveTradesPanel, PendingSetupsPanel, TodayStatsBar, SystemHealthFooter, AlertsStack, KillSwitchToggle)
- `src/pages/` : Cockpit (home), Analytics, Trades, Login

Le backend sert automatiquement le build si `frontend-react/dist/` existe (détection au boot dans `backend/app.py`), sinon retombe sur le vanilla HTML. Rollback trivial : supprimer le dist du container.

## Instruments actuels (WATCHED_PAIRS)

```
EUR/USD, GBP/USD, USD/JPY, EUR/GBP, USD/CHF, AUD/USD, USD/CAD,
EUR/JPY, GBP/JPY, XAU/USD, XAG/USD, BTC/USD, ETH/USD, SPX, NDX, WTI/USD
```

Auto-exécutables via bridge : forex + métaux uniquement (`MT5_BRIDGE_ALLOWED_ASSET_CLASSES="forex,metal"`).

## Ce qui reste à faire (hors démo/data)

- **Alertes Telegram des alerts critical** du cockpit (kill switch, near_sl)
- **Endpoint `/api/live-readiness`** : check-list automatique avant bascule live
- **Backup S3** : vérifier que le cron tourne et embarque `signals.db` + `trades.db` + `backtest.db`
- **Rotation des logs** uvicorn / nginx (disque qui se remplit sinon)
- **Déploiement React sur EC2** (nécessite rebuild Docker : Node pour le stage Vite)

## Ce qui est intentionnellement NON fait

- LLM news sentiment (coût, fragile, ROI incertain sans dataset)
- Fine-tuning d'un modèle maison (trop tôt, < 200 trades réels)
- Mobile app native (PWA du navigateur suffit)
- Trade manuel (supprimé volontairement, voir principes directeurs)
