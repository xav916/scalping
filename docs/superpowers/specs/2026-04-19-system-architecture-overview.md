# Spec fonctionnelle — Architecture globale du système Scalping Radar

**Date** : 2026-04-19
**Nature** : spec fonctionnelle rétrospective (décrit l'état du système en prod)
**Audience** : futur mainteneur, user qui veut comprendre les dépendances

---

## Vue d'ensemble

Scalping Radar est un **système d'aide à la décision pour le trading forex/or intraday** qui :

1. **Collecte en continu** des données de marché (prix, volatilité, événements économiques, contexte macro global)
2. **Détecte automatiquement** des setups de trading à haute probabilité (patterns techniques + filtres multi-facteurs)
3. **Notifie** l'utilisateur via Telegram + UI temps réel
4. **Exécute automatiquement** les setups à haute conviction sur un compte MetaTrader 5 (démo puis live)
5. **Log tout** en SQLite pour analyse post-mortem et futur apprentissage ML

## Acteurs

| Acteur | Rôle |
|---|---|
| **Utilisateur** (2 comptes) | Consulte le dashboard, reçoit les push Telegram, valide/ignore les setups manuels, supervise l'auto-exec |
| **Scalping Radar backend** | Collecte, analyse, notifie, ordonnance (tourne sur EC2) |
| **Bridge MT5** | Passerelle locale entre le backend cloud et MetaTrader 5 desktop (tourne sur le PC de l'utilisateur) |
| **MetaTrader 5 Desktop** | Le terminal officiel du broker qui exécute réellement les ordres |
| **Sources de données externes** | Twelve Data, Mataf, ForexFactory (voir spec `data-sources.md`) |
| **Telegram Bot API** | Canal de notification mobile |
| **Broker MetaQuotes** | Fournit le compte de trading démo (compte 10010590722) |

## Diagramme des composants

```
┌──────────────────────────────────────────────────────────┐
│                    SOURCES EXTERNES                       │
│  Twelve Data │ Mataf │ ForexFactory │ Telegram │ Broker   │
└────────┬──────────┬────────┬────────────┬──────────┬─────┘
         │ REST/WS  │ Scrape │ JSON feed  │ Bot API  │ MT5
         │          │        │            │          │ Network
         ▼          ▼        ▼            ▼          ▼
┌──────────────────────────────────────────────────────────┐
│                 SCALPING RADAR BACKEND                    │
│                 (EC2 — Docker — FastAPI)                  │
│                                                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐           │
│  │ Fetchers │→ │ Analysis │→ │ Notification │           │
│  │ (poll)   │  │ Engine   │  │ (WS, TG, MT5)│           │
│  └──────────┘  └──────────┘  └──────┬───────┘           │
│         │            │               │                   │
│         └────────────┴───────────────┼───> SQLite        │
│                                       │   (trades.db)    │
│                  ┌────────────────────┘                   │
│                  │ push setup si conf >= 60              │
│                  ▼                                        │
│         /api/... + WebSocket                              │
└──────────────────┬───────────────────────────────────────┘
                   │                     
                   │ Tailscale tunnel    
                   │ (EC2 → PC)          
                   ▼                     
┌──────────────────────────────────────────────────────────┐
│           PC WINDOWS DE L'UTILISATEUR                     │
│                                                           │
│   ┌────────────────┐    MetaTrader5      ┌──────────┐    │
│   │  BRIDGE MT5    │────────Python───────│   MT5    │    │
│   │  (Flask local) │       library       │ Desktop  │    │
│   │  port 8787     │                     │          │    │
│   └────────────────┘                     └─────┬────┘    │
│                                                │         │
└────────────────────────────────────────────────┼─────────┘
                                                 │
                                      MT5 broker protocol
                                                 │
                                                 ▼
                                       ┌────────────────┐
                                       │  Broker Cloud  │
                                       │ MetaQuotes-Demo│
                                       └────────────────┘
```

## Flux type d'un trade (happy path)

1. **T=0** — Scheduler lance un cycle d'analyse (toutes les 200s)
2. **T+0.5s** — Fetchers collectent prix 5min + 1h sur 10 paires (Twelve Data), volatilité (Mataf), événements (ForexFactory)
3. **T+1s** — Pattern detector trouve un setup potentiel (ex : breakout_up sur EUR/USD avec confluence)
4. **T+1.2s** — Trade setup builder calcule entry/SL/TP + score de confiance (5 facteurs : pattern 30 + R/R 25 + vol 20 + trend 15 + eco 10)
5. **T+1.3s** — Macro scoring (Vague 1) applique le multiplicateur (×0.75 à ×1.2) selon le contexte DXY/SPX/VIX + veto éventuel
6. **T+1.5s** — Coaching génère le verdict (TAKE / WAIT / SKIP) et les warnings/blockers
7. **T+1.6s** — Si verdict=TAKE et confidence ≥ 80 → **push Telegram**
8. **T+1.7s** — Si confidence ≥ `MT5_BRIDGE_MIN_CONFIDENCE` (60 actuellement) → **push au bridge**
9. **T+2s** — Le bridge calcule la taille de position (risk-based), valide les safety gates, envoie `mt5.order_send()`
10. **T+2.5s** — MT5 exécute, retourne un ticket → bridge logue dans `orders.db`
11. **T+3s** — Dashboard user affiche la nouvelle carte setup en animation stagger
12. **T+60s** — `mt5_sync` pull les ordres du bridge et les insère dans `personal_trades` avec `is_auto=1`
13. **T+N min** — Monitor du bridge surveille la position (BE auto à 50% du TP, partial close, trailing stop)
14. **T+close** — Position fermée, le sync met à jour `personal_trades` (pnl, exit_price, status='CLOSED')
15. **T+close+snapshot** — Le `context_macro` du moment du trade est sauvegardé (pour analyse post-mortem / ML futur)

## Déploiement actuel

| Élément | Hébergement | URL / Accès |
|---|---|---|
| Backend Scalping Radar | AWS EC2 (Amazon Linux 2023), Docker | https://scalping-radar.duckdns.org |
| Domaine | DuckDNS (gratuit) | scalping-radar.duckdns.org |
| HTTPS | Let's Encrypt + certbot auto-renew | — |
| Reverse proxy | Nginx (gzip, CSP, Cache-Control) | Port 443 → 127.0.0.1:8000 |
| Base de données | SQLite (bind mount `/opt/scalping/data/`) | trades.db, backtest.db |
| Scheduler | APScheduler en process Docker | 8 jobs (voir ci-dessous) |
| Tailscale | Service Windows côté PC, daemon côté EC2 | IPs 100.103.107.75 ↔ 100.122.188.8 |
| Bridge MT5 | Flask sur PC Windows user | http://100.122.188.8:8787 (via Tailscale) |
| MT5 Desktop | Application Windows sur PC user | Compte MetaQuotes-Demo 10010590722 |

## Jobs scheduler backend (APScheduler)

| Job | Fréquence | Fonction |
|---|---|---|
| Cycle d'analyse marché | 200s (3min20) | Fetch + detect + notify |
| Check trades backtest | 60s | Vérifie les signaux historiques (hit SL/TP) |
| Alertes pré-session | 60s (action à :55 d'une ouverture) | Push Telegram 5min avant London / NY / Tokyo (skip weekends) |
| Health check radar | 120s | Alerte si cycle arrêté > 10min |
| Email summary | 22h UTC quotidien | Résumé jour par email |
| Sync bridge MT5 | 60s | Pull /audit du bridge, insère dans personal_trades |
| Refresh macro context | 900s (15min) | Fetch DXY/SPX/VIX et met à jour le cache macro |

## Authentification et multi-user

- **Session auth** HTTP-only cookie, secrets.token_urlsafe
- **2 users** configurés dans `AUTH_USERS` env : couderc.xavier@gmail.com, c.chaussis@icloud.com
- **Affichage** : mapping `AUTH_DISPLAY_NAMES` permet d'afficher des prénoms dans l'UI
- **Telegram** : mapping `TELEGRAM_CHATS` — chaque user reçoit ses propres push sur son chat
- **Silent mode** : par user, activable manuellement (UI) — désactive push personnels
- **Auto-trade** : attribué à un user unique défini par `AUTO_TRADE_USER` (actuellement couderc.xavier@gmail.com) — toutes les positions auto apparaissent dans ses "Mes trades"

## Safety, observability, rollback

- **Toutes les variables sensibles** (seuils, flags, secrets) sont en `.env`, aucune hard-codée
- **Feature flags** pour les modules optionnels (MT5_BRIDGE_ENABLED, MT5_SYNC_ENABLED, MACRO_SCORING_ENABLED, TWELVEDATA_WS_ENABLED)
- **Kill switches** : passer un flag à `false` + `systemctl restart scalping` désactive le module en < 5s
- **Health checks** : endpoint `/health` public + alerte Telegram auto si cycle arrêté
- **Logs structurés** : stdout du conteneur Docker, accessibles via `docker logs`
- **Backups** : SQLite `trades.db` est dans un bind mount persistant, peut être synchronisé vers S3 (script `deploy/backup-s3.sh`)
- **PWA offline** : service worker v15 cache le shell — l'UI fonctionne même sans réseau (mais pas d'updates live)

## Ce qui n'est PAS fait (connu)

- Pas de CI/CD automatique (deploy manuel via `git pull` + `docker build` sur EC2)
- Pas de tests end-to-end (49 unit tests backend, 0 test frontend)
- Pas de monitoring externe (Grafana, Datadog, etc.) — juste les logs Docker
- Pas de redondance réseau côté PC (si Tailscale tombe, plus d'auto-exec, alerte via Telegram)
- Pas de basculement live vers un autre broker (mono-broker MetaQuotes)

## Références

- Specs détaillées : `docs/superpowers/specs/`
- Plan d'implémentation macro : `docs/superpowers/plans/2026-04-19-macro-context-scoring.md`
- Guide rollout macro : `docs/macro-rollout.md`
- Deploy EC2 : `DEPLOY.md`
