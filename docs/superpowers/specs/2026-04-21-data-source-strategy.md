# Data source strategy — Twelve Data vs MT5 direct

**Date :** 2026-04-21
**Contexte :** Décision pour la Phase 2 d'élargissement des supports et au-delà.

## Problème

Le radar source actuellement ses bougies via **Twelve Data plan Grow** (55 req/min, 6 000 req/jour, ~16 paires suivies). Deux contraintes remontent :

1. **Élargir à > 30 instruments** (Phase 2 + 3 de la roadmap CLAUDE.md) saturera le plan Grow. Deux options : upgrade Twelve Data Pro (75 €/mois) ou basculer sur une source de données directe via le bridge MT5.
2. **Risque de divergence source/exec** : le 2026-04-20, un bug dans `_generate_simulated_candles` a produit des prix fantômes (2650) sur des paires à 1.08, provoquant 56% de rejection MT5 (rc=10016 INVALID_STOPS). C'est la manifestation exacte du problème "la source de prix n'est pas celle de l'exécution".

## Décision

**MT5 direct** devient la source primaire à terme. **Pas maintenant.**

### Plan progressif en 3 étapes

#### Étape 1 : Status quo (maintenant → ouverture de la Phase 2)

- Rester sur **Twelve Data Grow**.
- Pas de changement de code.
- TD Grow (55 req/min) suffit amplement pour les 16 paires actuelles.
- On est en phase d'observation (objectif : 200-500 trades par classe d'actif). On ne veut pas refactorer la plomberie data pendant qu'on collecte les stats.

#### Étape 2 : Chantier MT5 direct (au moment d'ajouter le premier lot Phase 2)

Déclencheur : l'user ajoute un lot d'instruments qui n'est pas couvert par TD Grow (ex : DAX, FTSE, forex exotiques NOK/SEK/MXN, crypto SOL/ADA/XRP).

Livrables :

1. **Endpoint `/candles` sur le bridge VPS** (Flask, `C:/Scalping/mt5-bridge/bridge.py`) :
   - `GET /candles?symbol=EUR/USD&interval=5m&n=50`
   - Source : `MT5.copy_rates_from_pos(symbol, timeframe, 0, n)`
   - Mapping symboles interne → broker via `MT5_SYMBOL_MAP` (déjà existant)
   - Response JSON : `[{ts, open, high, low, close, volume}, ...]`
   - Cache côté bridge (30s TTL par (symbol, interval)) pour limiter les calls MT5

2. **Endpoint `/ticks` sur le bridge** :
   - `GET /ticks?symbols=EUR/USD,GBP/USD` (batch)
   - Source : `MT5.symbol_info_tick(symbol)`
   - Response JSON : `{EUR/USD: {bid, ask, ts}, ...}`

3. **Refactor `backend/services/price_service.py`** :
   - Nouvelle fonction `_fetch_from_bridge(pair, interval, n)` qui appelle le bridge
   - Wrapper `get_candles_for_pair` avec priorité : bridge primary → Twelve Data fallback
   - Env var `PRICE_SOURCE=mt5_primary|twelvedata_primary` (default `mt5_primary` après switch)
   - Cache + semaphore existants réutilisés tels quels

4. **Refactor `backend/services/twelvedata_ws.py`** :
   - Optionnel : remplacer par polling `/ticks` sur bridge (WS MT5 n'existe pas nativement)
   - Ou garder TD WS en secondaire pour les paires couvertes

5. **Tests** :
   - `test_price_service_bridge_primary.py` : mock bridge responses, valider fallback TD quand bridge down
   - Smoke test : `curl /api/candles` retourne des bougies cohérentes avec `/api/setups`

6. **Monitoring** :
   - Ajouter `last_bridge_candles_sync` dans `/api/status`
   - Alerte Telegram si bridge candles fail > 3 cycles consécutifs

#### Étape 3 : Nettoyage Twelve Data

Après 1-2 semaines de stabilité en MT5 primary :

- Downgrade Twelve Data vers plan Free (800 req/jour, gratuit) — garde comme fallback résilience
- Archiver les dépendances TD spécifiques si plus utilisées
- Mettre à jour `CLAUDE.md` phase 4 : "scaling infra" devient obsolete

## Pourquoi ce choix

### MT5 direct gagne sur le fond

| Critère | Twelve Data Pro | MT5 direct |
|---|---|---|
| Coût | 75 €/mois (900 €/an) | Gratuit (broker démo déjà actif) |
| Limite instruments | ~30+ paires | Illimité |
| Exactitude source/exec | Divergence possible | **Identique** — même feed |
| Latence | Externe (TD → EC2 → VPS → broker) | VPS → MT5 local = ms |
| Effort initial | 0 jour | 2-5 jours |
| Historique | Profond (années) | Limité broker (semaines/mois) |
| Résilience | SaaS 99.9% | VPS + connection broker |
| Multi-broker (phase 3) | Fonctionne partout | Un bridge par broker |

**Arguments décisifs :**

1. **Exactitude = sécurité live**. Le bug des prix fantômes du 20/04 est la démonstration pratique que source ≠ exec est dangereux. Pour un système d'exécution automatique qui va passer en live, la source des bougies DOIT être identique à celle du broker qui exécute. MT5 direct rend ce bug physiquement impossible.

2. **Coût long terme**. 900 €/an × 3 ans = 2 700 €. Un investissement de 3-5 jours de dev une bonne fois > location à vie.

3. **Illimité.** Plus de "budget req" à optimiser. Phase 2 (ajout lots A-E) ne nécessite plus aucune action infra. Phase 4 ("scaling infra si > 30 instruments") disparaît de la roadmap.

4. **Infrastructure existante.** Bridge MT5 déjà opérationnel sur VPS Windows, avec Tailscale, monitoring, alertes Telegram. Pas de nouvelle dépendance à créer — juste étendre l'existant.

### Pourquoi pas maintenant

- TD Grow suffit pour les 16 paires actuelles. Pas de contrainte pratique immédiate.
- Phase d'observation en cours : introduire un gros refactor data pendant qu'on collecte des stats = polluer les données et risquer des régressions.
- Le timing idéal du chantier coïncide avec le besoin concret d'élargir (Phase 2) — on teste le nouveau flow avec les nouveaux instruments dans un cadre bornée.

### Ce qu'il ne faut pas faire : upgrader TD Pro

Upgrade TD Pro à 75 €/mois est un **pansement coûteux** qui :

- Règle le problème de rate limit
- Ne règle PAS le problème de cohérence source/exec (potentiel de bugs type prix fantômes inchangé)
- Crée une dépendance externe récurrente de 900 €/an
- Repousse mécaniquement le chantier MT5 direct qu'il faudra de toute façon faire pour Phase 5 (live)

## Risques et mitigations

| Risque | Mitigation |
|---|---|
| VPS down → radar aveugle | Fallback TD Free (800 req/jour, gratuit). Dégradé mais fonctionnel. |
| Broker coupe les données | Monitoring existant (alertes Telegram /status). Possibilité de pivoter sur broker secondaire via second bridge. |
| Historique MT5 insuffisant pour backtests profonds | Garder TD actif en parallèle pour backtesting one-shot. Le cœur live utilise MT5. |
| Mapping symboles complexe en multi-broker | Déjà géré dans `MT5_SYMBOL_MAP`. Extensible par broker. |
| Bug dans le refactor `price_service` | Déploiement progressif : `PRICE_SOURCE=mt5_primary` avec fallback TD pendant 1 sprint avant de retirer TD. |

## Métriques de succès

- Cycle d'analyse < 10s après bascule (vs ~30s actuel avec TD rate limit)
- Zéro rejection rc=10016 liée à des prix fantômes (déjà vrai post-fix du 20/04, objectif : le garantir structurellement)
- Coût data mensuel ≤ 0 € (vs 0 € Grow / 75 € Pro)
- Capacité d'élargir WATCHED_PAIRS sans action infra

## Prochaines actions

Pas de plan d'implémentation détaillé maintenant — sera rédigé comme `docs/superpowers/plans/YYYY-MM-DD-mt5-direct-source.md` au moment du déclenchement (ouverture Phase 2).
