# Spec fonctionnelle — Sources de données et cadences

**Date** : 2026-04-19
**Nature** : spec fonctionnelle rétrospective

---

## Vue d'ensemble

Le radar croise **4 types de données** pour détecter et qualifier les setups :

1. **Prix / bougies** (directions, patterns, cassures) — Twelve Data + WebSocket
2. **Volatilité** (intensité du marché par paire) — Mataf scraping
3. **Événements économiques** (calendrier macro, news rouges) — ForexFactory JSON feed
4. **Contexte macro global** (DXY, SPX, VIX, yields, oil, Nikkei, gold) — Twelve Data (Vague 1)

Plus 1 canal de sortie asynchrone : **Telegram** pour les notifications mobiles.

## Source 1 — Twelve Data (prix, bougies, symboles macro)

**Rôle** : fournit les chandeliers OHLC pour détecter les patterns techniques et le spot pour les indicateurs macro.

**Plan actuel** : gratuit (800 requêtes/jour, max ~8 req/min). WebSocket optionnel (plan Grow, 2 symboles simultanés).

**Configuration** :

| Var env | Défaut | Description |
|---|---|---|
| `TWELVEDATA_API_KEY` | (secret) | Clé d'API |
| `TWELVEDATA_WS_ENABLED` | `true` | WebSocket sur 2 symboles phares (XAU/USD, EUR/USD) |
| `TWELVEDATA_WS_MAX_SYMBOLS` | `2` | Limite du plan Grow |

**Utilisation** :

| Consumer | Fréquence | Budget requêtes/jour |
|---|---|---|
| Cycle d'analyse (10 paires × 2 intervalles 5min+1h) | Toutes les 200s | ~400 req/j |
| Macro context refresh (8 symboles × 1 fois) | Toutes les 900s | ~770 req/j |
| **Total** |  | **~1170 req/j** (au-dessus du free tier — TODO : envisager plan Grow ou réduire la fréquence) |

**Fallback** : 
- Si l'API renvoie une erreur, fallback vers MT5 local (via bridge) pour les paires tradées
- En dernier recours, génération de bougies simulées pour éviter le blocage du cycle

**Paires suivies** (`WATCHED_PAIRS`) :
`XAU/USD, EUR/USD, GBP/USD, USD/JPY, EUR/GBP, USD/CHF, AUD/USD, USD/CAD, EUR/JPY, GBP/JPY`

**Symboles macro** (Vague 1 scoring) :
`DXY, SPX, VIX, TNX (US10Y), DE10Y, WTI, NKY (Nikkei 225), XAU/USD`

## Source 2 — Mataf (volatilité relative)

**Rôle** : récupère le ranking volatilité des 10 paires majeures sur une URL publique (https://www.mataf.net/en/forex/tools/volatility).

**Méthode** : scraping HTML (BeautifulSoup) + fallback si la page est JS-rendered.

**Configuration** :

| Var env | Défaut | Description |
|---|---|---|
| `MATAF_POLL_INTERVAL` | `300` (5 min) | Fréquence fetch |

**Ce que ça donne** : un score volatilité par paire classé `LOW / MEDIUM / HIGH` (seuils `VOLATILITY_THRESHOLD_MEDIUM=1.2`, `VOLATILITY_THRESHOLD_HIGH=1.5`).

**Utilisation** : l'un des 5 facteurs du scoring (poids 0-20 pts). `HIGH → 20 pts`, `MEDIUM → 12 pts`, `LOW → 3 pts`.

**Fallback** : dictionnaire de volatilités approximatives par paire (codé en dur) — permet au cycle de ne pas bloquer mais prive le scoring de fraîcheur.

## Source 3 — ForexFactory (calendrier économique)

**Rôle** : liste des événements économiques à venir (NFP, FOMC, CPI, GDP, etc.) avec leur impact (LOW/MEDIUM/HIGH).

**Méthode** : JSON feed gratuit `https://nfs.faireconomy.media/ff_calendar_thisweek.json` (source primaire, fiable). Fallback HTML scraping. Fallback ultime : données échantillon codées en dur.

**Configuration** :

| Var env | Défaut | Description |
|---|---|---|
| `FOREXFACTORY_POLL_INTERVAL` | `600` (10 min) | Fréquence fetch |

**Ce que ça donne** : liste d'événements avec timestamp UTC, devise impactée, impact level, titre.

**Utilisation** :
- Facteur 5 du scoring (0-10 pts) : si un événement rouge est à < 30 min sur une devise du setup → malus
- Veto macro (Vague 1) : bloque les setups dans les 30 min avant une news rouge
- Alertes pré-session + aperçu du calendrier dans l'UI

## Source 4 — Contexte macro global (Vague 1)

**Rôle** : filtrer les setups qui vont à contre-courant du régime de marché global.

**Détails complets** : voir `2026-04-19-macro-context-scoring-design.md`.

**Résumé** :
- 8 symboles fetch via Twelve Data toutes les 15 min (DXY, SPX, VIX, US10Y, DE10Y, Oil, Nikkei, Gold)
- Dérivation du régime `risk_on / neutral / risk_off`
- Application d'un multiplicateur 0.75 → 1.2 sur la confidence du setup
- Veto optionnel dans les cas extrêmes (VIX > 30, DXY > 2σ intraday)

**État actuel** : `MACRO_SCORING_ENABLED=true`, `MACRO_VETO_ENABLED=false` (phase shadow multiplier).

## Canal de sortie — Telegram

**Rôle** : notifications mobiles pour que l'utilisateur ne rate pas un setup ou une alerte.

**Contenu des push** :

| Type | Déclencheur | Destinataire |
|---|---|---|
| Setup de trade | Verdict = TAKE ou WAIT, confidence ≥ `TELEGRAM_SETUP_MIN_CONFIDENCE` (50 actuellement) | `TELEGRAM_CHATS[user]` ou fallback `TELEGRAM_CHAT_ID` |
| Ouverture de session | 5 min avant London / NY / Tokyo, skip weekends | `TELEGRAM_CHAT_ID` (global) |
| Health alert | Cycle arrêté > 10 min | Global |
| Kill switch | Daily loss limit atteint | Par user |

**Dedup** : 
- Setup : clé `(date, pair, direction, entry_5dp)` en mémoire → évite les doublons dans la journée
- Session alert : clé `(date, session_name)` en mémoire → 1 push max par session par jour

**Configuration** :

| Var env | Rôle |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token du bot (via @BotFather) |
| `TELEGRAM_CHATS` | Mapping `user:chat_id` séparé par virgules |
| `TELEGRAM_CHAT_ID` | Fallback global si `TELEGRAM_CHATS` vide |
| `TELEGRAM_MIN_STRENGTH` | Niveau min des signaux classiques (weak/moderate/strong) |
| `TELEGRAM_SETUP_MIN_CONFIDENCE` | 50 actuellement (abaissé pour la phase observation) |
| `TELEGRAM_SETUP_VERDICTS` | `TAKE,WAIT` par défaut (les SKIP ne sont pas pushés) |

## Matrice fraîcheur vs tolerance

| Source | Fréquence fetch | Tolerance avant "stale" | Comportement si stale |
|---|---|---|---|
| Twelve Data prix 5min | 200s | N/A (toujours le dernier reçu) | Utilise la dernière bougie dispo |
| Twelve Data 1h | 200s | N/A | Idem |
| Mataf | 300s | 1h | Fallback statique |
| ForexFactory | 600s | 24h | Fallback échantillon codé en dur |
| Macro (Twelve Data 1d) | 900s | 7200s (2h) | Mode neutre (mult=1.0, veto off) |

## Budget API et limites connues

**Twelve Data free** : 800 req/j. **Consommation estimée : ~1170 req/j** (au-dessus).

Actions possibles si on dépasse :
1. **Upgrade plan** (Grow = $29/mois, 6000 req/j)
2. **Réduire la fréquence** du cycle d'analyse (200s → 300s = -33%)
3. **Désactiver le refresh macro** en dehors des heures de marché (économise ~50% sur les 770 req/j macro)
4. **Cache plus agressif** sur les bougies 1h (elles changent lentement)

**Mataf** : pas de rate-limit officiel, mais scraping agressif pourrait faire bloquer. 5 min est conservateur.

**ForexFactory JSON feed** : open, pas de rate-limit documenté.

## Ce qui n'est PAS branché (différé)

- **Sentiment retail** (Myfxbook / OANDA order book) — Vague 2, non commencé
- **News sentiment IA** (Finnhub / Alpha Vantage) — Vague 3, non commencé
- **COT report CFTC** — pas prévu (trop lent pour le scalping)
- **Options flow** — pas prévu (coût)
- **Twitter / Reddit sentiment** — pas prévu (bruyant)

## Références

- Service prix : `backend/services/price_service.py`
- Service Mataf : `backend/services/mataf_service.py`
- Service ForexFactory : `backend/services/forexfactory_service.py`
- Service macro : `backend/services/macro_context_service.py`
- Service Telegram : `backend/services/telegram_service.py`
- Settings : `config/settings.py`
