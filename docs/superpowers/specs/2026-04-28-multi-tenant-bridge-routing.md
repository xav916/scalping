# Multi-tenant bridge routing — design

**Date** : 2026-04-28
**Status** : draft, à valider avant code
**Driver** : ouvrir le tier Premium auto-exec à un premier testeur (Cédric Chaussis, c.chaussis@icloud.com)

## Contexte

Le SaaS multi-tenant a été déployé en prod le 2026-04-24. Tier Premium = "auto-exec MT5" comme différenciateur (cf. `project_saas_signal_only_pivot.md`). Côté UI/API, les hooks existent :

- `users.broker_config` (JSON column) stocke `bridge_url`, `bridge_api_key`, `broker_name` per user
- `GET /api/me/broker_config` lit la config (sans api_key)
- `POST /api/me/broker_config` la persiste (validation min 16 chars)
- `POST /api/broker/test` ping un bridge arbitraire pour valider

**Mais** le module qui exécute les ordres `backend/services/mt5_bridge.py` lit `MT5_BRIDGE_URL` et `MT5_BRIDGE_API_KEY` depuis l'env global (`config/settings.py`). Tous les ordres partent vers **un seul bridge** = celui de l'admin (compte Pepperstone démo 62119130). Conséquence : si Cédric configure son bridge dans Settings, ses ordres partent quand même chez l'admin. Le multi-tenant est moitié-fait.

## Pourquoi maintenant

1. Premier testeur Premium prêt à on-board (Cédric, Mac niveau 0 — il aura un VPS Windows dédié pour son MT5)
2. Faire le chantier sous pression d'un user concret évite les abstractions vides
3. Sans ce refactor, impossible d'ouvrir le tier Premium même à des users payants
4. Le coût de découvrir le bug en prod avec un user payant >> coût du fix maintenant

## Scope

**In scope**
- Router les pushes d'ordres vers le bridge per-user (Premium tier + auto_exec activé + bridge config valide)
- Garder l'admin legacy (env-based AUTH_USERS) en route via le bridge global comme aujourd'hui — pas de régression sur le compte 62119130
- Dedup partagé en DB (sinon `_sent_setups_today` in-process casse avec plusieurs users)
- Filtres `_check_rejection` adaptés per-user (confidence threshold, market hours, asset class) avec fallback aux valeurs globales si pas overridé
- Rejection logging per-user (qui a vu sa rejection)
- Kill switch global (admin coupe tout) — kill switch per-user reporté
- Tests unitaires + 1 test d'intégration

**Out of scope (chantiers séparés)**
- Sizing per-user (chacun aura le `RISK_PER_TRADE_PCT` global pour V1, override per-user en V2)
- Settings UI étendu pour configurer `confidence_threshold` per-user
- Multi-broker (chaque user peut avoir son broker, mais on assume Pepperstone-like comme l'admin pour V1)
- Rate limiting per-user (V2 si abus)
- Telegram alerts per-user déjà géré séparément, hors scope ici
- Reconciliation `mt5_sync` per-user (le module `_reconcile_open_trades` lit le bridge admin — chantier suivant après celui-ci)

## État actuel à connaître

Module `backend/services/mt5_bridge.py` :
- `send_setup(setup)` est appelé **une fois par setup** depuis le scheduler (`backend/scheduler.py` probablement)
- Lit `MT5_BRIDGE_URL`, `MT5_BRIDGE_API_KEY`, `MT5_BRIDGE_MIN_CONFIDENCE`, `MT5_BRIDGE_LOTS`, `MT5_BRIDGE_ALLOWED_ASSET_CLASSES`, `MT5_BRIDGE_MIN_SL_DISTANCE_PCT_PER_CLASS`, `MT5_BRIDGE_MAX_POSITIONS_PER_PAIR`, `MT5_BRIDGE_BLOCKED_DIRECTIONS`, `MT5_BRIDGE_AVOID_HOURS_UTC` depuis l'env
- `_sent_setups_today: set[tuple[str, str, str, str]]` = dedup process-local (clé : date, pair, direction, entry)
- `_count_open_trades_for_pair(pair)` lit la table `trades` côté DB sans filtre user
- `record_rejection(...)` écrit table `signal_rejections` sans dimension user
- Erreurs bridge (429, 10016 INVALID_STOPS, timeouts) gèrent un retry implicite via discard de la dedup key

Schéma DB existant (à confirmer) :
- `users` : `id`, `email`, `tier`, `broker_config` (JSON), `watched_pairs` (JSON list)
- `trades` : table partagée, à confirmer si `user_id` column présente
- `signal_rejections` : table partagée, à confirmer si `user_id` column présente

## Design

### Architecture cible

Au lieu d'un appel `send_setup(setup)` qui pousse vers UN bridge :

```
send_setup(setup):
  1. Pour chaque destination (admin legacy + users Premium éligibles) :
     a. resolve_destination(user_id) → BridgeConfig | None
     b. check_per_destination_filters(setup, dest) → reason | None
     c. push_to_bridge(setup, dest)
```

Une **destination** est soit :
- `admin_legacy` : config depuis env (`MT5_BRIDGE_URL` + clé), comme aujourd'hui — on garde pour zéro régression sur le compte 62119130
- `user:{id}` : config depuis `users.broker_config` (Premium tier + auto_exec_enabled + watched_pairs contient setup.pair)

### Contrat `BridgeConfig`

Simple dataclass :
```python
@dataclass
class BridgeConfig:
    destination_id: str  # "admin_legacy" ou "user:42"
    user_id: int | None  # None pour admin_legacy
    bridge_url: str
    bridge_api_key: str
    min_confidence: int  # default = MT5_BRIDGE_MIN_CONFIDENCE global
    allowed_asset_classes: set[str]  # default = MT5_BRIDGE_ALLOWED_ASSET_CLASSES global
    auto_exec_enabled: bool  # short-circuit si False
```

### Étapes par destination

Pour chaque destination, dans cet ordre :

1. **Watchlist match** : `setup.pair in watched_pairs(user_id)` (admin_legacy = WATCHED_PAIRS env)
2. **Auto-exec enabled** : booléen explicite dans `users.broker_config.auto_exec_enabled` (default false pour les users — opt-in)
3. **Bridge config valide** : `bridge_url` + `bridge_api_key` set, `len(api_key) >= 16`
4. **Filtres `_check_rejection`** : confidence ≥ min_confidence, asset class allowed, market hours, kill switch GLOBAL, max positions per pair (compté **per-bridge**, pas global)
5. **Dedup** : clé étendue `(date, destination_id, pair, direction, entry)` au lieu de `(date, pair, direction, entry)`
6. **Push** : POST `bridge_url/order` avec `bridge_api_key`, payload identique à aujourd'hui
7. **Rejection logging** : `record_rejection(user_id=user_id, ...)` pour traçabilité per-user

### Dedup en DB

Migration : table `mt5_pushes`
```sql
CREATE TABLE mt5_pushes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  destination_id TEXT NOT NULL,        -- "admin_legacy" ou "user:42"
  date TEXT NOT NULL,                   -- YYYY-MM-DD
  pair TEXT NOT NULL,
  direction TEXT NOT NULL,
  entry_price_5dp TEXT NOT NULL,        -- str pour stable hashing
  pushed_at TEXT NOT NULL,              -- ISO8601 UTC
  ok INTEGER NOT NULL,                  -- 1 si bridge a accepté, 0 si rejected
  bridge_response TEXT,                 -- JSON tronqué 500 chars
  UNIQUE(destination_id, date, pair, direction, entry_price_5dp)
);
CREATE INDEX idx_mt5_pushes_lookup ON mt5_pushes(destination_id, date, pair);
```

`UNIQUE` constraint = dedup atomique : `INSERT OR IGNORE` → si déjà pushé aujourd'hui pour cette destination, skip.
La table sert aussi de log d'audit (qui a reçu quoi quand). Purge périodique (J-30) en cron.

### Filtres per-bridge

`_count_open_trades_for_pair` actuel lit `trades` sans filtre. Refactor : filtre par `bridge_destination_id` (ou `user_id`) si la column existe en DB. **Question ouverte** : `trades` a-t-elle déjà un user_id ? À vérifier avant de coder. Si non, migration nécessaire (column add + backfill admin_legacy).

`MT5_BRIDGE_MAX_POSITIONS_PER_PAIR` reste global pour V1 (override per-user en V2).

### Concurrency

Un push synchrone pour 1 user prend ~5s (timeout httpx). Avec 5 users Premium → 25s par setup → bloque le scheduler. Solution :
- `asyncio.gather` sur les destinations dans `send_setup`
- Limit concurrence avec `asyncio.Semaphore(8)` (cohérent avec le rate limit Twelve Data déjà en place)

### Migration progressive

1. **Phase A — code** : refactor `mt5_bridge.py` pour la liste de destinations. Admin legacy reste l'unique destination dans la liste. Tests passent. **Aucune régression observable** pour l'admin.
2. **Phase B — DB** : migration `mt5_pushes` + extension de la dedup. Tests intégration.
3. **Phase C — multi-user** : enrichir la liste de destinations avec les users Premium. Tests E2E avec un user fictif.
4. **Phase D — onboarding Cédric** : VPS Windows + bridge MT5 chez lui + signup + Premium DB + Settings → Auto-exec.

Phase A + B peuvent se faire sans ouvrir aucun user (zéro changement comportemental).

## Plan d'implémentation

| Phase | Effort | Livrable |
|---|---|---|
| **A. Refactor send_setup** | 2h | `mt5_bridge.py` accepte une liste de destinations (V1 = juste admin_legacy), tests unitaires existants verts |
| **B. DB dedup** | 1h | Migration `mt5_pushes`, refactor dedup, test_mt5_bridge_dedup_db.py |
| **C. Multi-user enable** | 2h | `users_service.list_premium_auto_exec_users()`, enrichir liste destinations, test_mt5_bridge_multi_user.py |
| **D. UI auto_exec_enabled** | 30min | Settings frontend exposant le toggle (déjà partiellement présent ?), API `/api/me/broker_config` étendu |
| **E. Onboarding Cédric** | 2-3h | VPS, MT5, bridge.py, Tailscale (ou tunnel public), validation E2E |
| **Total** | **7-9h** sur 2-3 sessions | |

## Tests

### Unitaires
- `test_mt5_bridge_destinations.py` : `resolve_destinations()` retourne admin + Premium users selon tier/watchlist/auto_exec
- `test_mt5_bridge_filters.py` : `_check_rejection_per_destination` applique les filtres avec fallback global
- `test_mt5_bridge_dedup_db.py` : dedup par destination_id, INSERT OR IGNORE atomique
- `test_mt5_bridge_concurrency.py` : 5 destinations en parallèle ne bloquent pas le scheduler

### Intégration
- `test_mt5_bridge_e2e_admin_only.py` : admin_legacy seul → comportement identique à V1 (aucune régression)
- `test_mt5_bridge_e2e_multi_user.py` : 1 admin + 1 user mock → 2 pushes vers 2 bridges distincts (mock httpx)

### Smoke prod
- Avant onboarding Cédric : un dry-run avec son bridge mock-up depuis un VPS test pour vérifier le routing
- Pendant onboarding Cédric : validation que SES ordres tombent bien sur SON compte Pepperstone démo, pas le compte 62119130 admin

## Risques + mitigations

| Risque | Probabilité | Mitigation |
|---|---|---|
| Régression compte admin (ordres ratés sur 62119130) | moyenne | Phase A garde admin_legacy seule destination, fully tested avant Phase C |
| Dedup race condition multi-user | faible | UNIQUE constraint DB |
| Bridge user down → bloque le scheduler | faible | Timeout httpx 5s + semaphore 8 |
| User mal-configure son bridge → erreurs récurrentes en log | moyenne | Limiter à 3 erreurs consécutives → désactive auto_exec_enabled auto + alerte UI |
| Cédric set un mauvais broker (compte réel au lieu de démo) | élevée | Settings UI : forcer un toggle "compte démo confirmé" obligatoire avant activation auto_exec |

## Rollback

Si la Phase A introduit une régression admin :
- Revert le merge depuis main
- Restart `scalping.service`
- Le bridge VPS continue à recevoir les ordres legacy comme avant

Si Phase C dérape (un user Premium pousse en boucle) :
- Désactiver `auto_exec_enabled=false` pour ce user en DB direct
- Garder l'admin operationnel

## Open questions à régler avant code

1. **`trades` a-t-elle déjà un `user_id` ?** Vérifier le schéma. Si non, migration séparée.
2. **`auto_exec_enabled` est-il déjà dans `broker_config` JSON ?** Sinon, ajouter le champ + endpoint UI pour le toggle.
3. **Les `users` legacy env (admin) ont quel `id` en DB ?** Probablement `None` (pas insérés en DB). Confirme que la résolution destination admin_legacy ne nécessite pas un user_id DB.
4. **Sizing per-user maintenant ou en V2 ?** V2 (cf. out of scope), mais à confirmer.
5. **Telegram alerts per-user routées comment aujourd'hui ?** Cohérence avec ce chantier — vérifier qu'on n'introduit pas une divergence.
6. **Reconciliation `_reconcile_open_trades` (mt5_sync.py) à étendre ou pas ?** Hors scope mais doit suivre dans la foulée — sinon les positions ouvertes côté users Premium ne sont pas trackées en DB.

## Décision finale

Avant de commencer Phase A, valider avec l'user :
- Scope ci-dessus est OK
- Open questions (1) et (2) ont une réponse claire (lecture du schéma DB + grep code)
- Cédric est OK pour attendre Phase A+B+C complets avant son onboarding (plutôt que d'être on-boardé direct sur du code half-baked)
