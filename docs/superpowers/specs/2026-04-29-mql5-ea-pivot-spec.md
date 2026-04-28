# Pivot MQL5 EA — éliminer le bridge Python pour Premium auto-exec

**Date** : 2026-04-29
**Status** : draft, à valider avant code
**Driver** : friction onboarding Premium. Le bridge Python actuel exige par user
~2h de pair-RDP + ~22€/mois VPS Windows + Tailscale. Bloque la croissance
Premium au-delà de 1-2 cobayes (Cédric).

## Contexte

Architecture actuelle (déployée 2026-04-28) :

```
EC2 (radar Linux)
  │ POST /order
  ▼
Bridge Flask Python (Windows VPS du user, ~22€/mois)
  │ MetaTrader5 package local
  ▼
MT5 Desktop (Windows, du user)
  │ broker connection
  ▼
Compte broker du user
```

Forcing du bridge Python : MT5 ne peut être piloté que localement via le
package `MetaTrader5`. Donc Python doit tourner sur la même machine que MT5.
D'où le VPS Windows par user.

**Problème UX** : l'onboarding Cédric, c'est 11 étapes (cf.
`docs/onboarding-cedric-bridge.md`), 1-2h de pair-RDP, 22€/mois récurrent,
niveau tech ≥ 1 effectif.

## Architecture cible — EA MQL5

Pivot vers un Expert Advisor MQL5 qui tourne **dans** MT5 et fait du polling
HTTP vers le SaaS pour récupérer les ordres en attente.

```
EC2 (radar Linux)
  │ INSERT INTO mt5_pending_orders
  ▼
SQLite mt5_pending_orders queue
  │ GET /api/ea/pending (l'EA poll toutes les 30s)
  ▼
ScalpingRadarEA.ex5 (compilé MQL5, dans Experts/ de MT5)
  │ OrderSend() natif MQL5
  ▼
MT5 Desktop (Windows OU Mac via Parallels OU VPS quelconque)
  │ broker connection
  ▼
Compte broker du user
```

### Onboarding cible pour le user (~5 min)

1. Télécharge `ScalpingRadarEA.ex5` depuis Settings → Auto-exec
2. Met le fichier dans `<MT5 Data Folder>/MQL5/Experts/`
3. Restart MT5
4. Drag l'EA sur n'importe quel chart
5. Saisit son `api_key` dans les inputs EA
6. Click "OK" + Tools → Options → Expert Advisors → "Allow WebRequest for
   listed URL" + ajoute `https://app.scalping-radar.online`
7. Auto-trading ON (bouton dans la barre d'outils MT5)

Done. Pas de Python. Pas de VPS. Pas de Tailscale. **Marche sur Mac aussi**
(MT5 a une version Mac via Wine officielle Pepperstone).

## Ce qui change côté SaaS

### Garder du chantier multi-tenant (Phases A-D)

- ✅ `BridgeConfig` dataclass → renommer `EAConfig`, garder la structure
- ✅ `resolve_destinations(setup)` → garder, c'est le point d'entrée multi-tenant
- ✅ `users.broker_config.auto_exec_enabled` → garder, même UI Settings
- ✅ `mt5_pushes` table dedup → garder, devient queue de pending orders
- ✅ Endpoint `POST /api/user/broker/auto-exec` → garder
- ✅ UI Settings React toggle → garder, change juste les inputs (au lieu de
  bridge_url + api_key, on lui donne juste l'api_key + le download EA)

### Changer

- ❌ `_push_to_destination(setup, dest)` HTTP POST → ✅
  `_enqueue_for_destination(setup, dest)` INSERT en DB
- ❌ Endpoint `/api/user/broker/test` (test bridge alive) → ✅ Endpoint
  `/api/ea/heartbeat` (l'EA poll régulièrement, on track la dernière vue)
- ❌ Section UI "URL bridge" → ✅ Section UI "Télécharger l'EA + ton api_key"

### Ajouter

- Nouvelle table `mt5_pending_orders` :
  ```sql
  CREATE TABLE mt5_pending_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    api_key_hash TEXT NOT NULL,         -- pour query rapide par EA
    payload TEXT NOT NULL,              -- JSON ordre complet
    status TEXT NOT NULL,               -- PENDING / SENT / EXECUTED / FAILED / EXPIRED
    created_at TEXT NOT NULL,
    fetched_at TEXT,                    -- quand l'EA a poll cet ordre
    executed_at TEXT,                   -- quand l'EA a confirmé OrderSend
    mt5_ticket INTEGER,                 -- ticket MT5 retourné par OrderSend
    mt5_error TEXT,                     -- retcode + message si OrderSend a foiré
    expires_at TEXT NOT NULL            -- TTL 5 min — au-delà l'EA skip
  );
  CREATE INDEX idx_pending_user_status ON mt5_pending_orders(user_id, status);
  CREATE INDEX idx_pending_apikey ON mt5_pending_orders(api_key_hash, status);
  ```

- Endpoints EA :
  - `GET /api/ea/pending?api_key=<key>` → JSON list d'ordres PENDING
    pour ce user, max 5, expires_at > now. Marque comme SENT à la lecture.
  - `POST /api/ea/result` body `{order_id, mt5_ticket, ok, error?}` →
    update la ligne, status=EXECUTED ou FAILED.
  - `POST /api/ea/heartbeat?api_key=<key>` → met à jour
    `users.broker_config.last_ea_heartbeat`. Permet à l'admin de voir
    quels users ont leur EA actif.

- Job cron de cleanup : DELETE FROM mt5_pending_orders WHERE expires_at <
  now AND status IN ('PENDING', 'SENT'). Toutes les heures.

## Ce qui change côté user (Cédric et autres)

### Avant (bridge Python)

- VPS Windows 22€/mois
- Install Python 3.11
- Clone bridge.py + venv + pip install
- Configure .env avec login MT5 + password + server + api_key
- Tâches planifiées au logon
- Tailscale ou tunnel HTTPS public
- Saisit URL + api_key dans Settings

### Après (EA MQL5)

- MT5 sur Mac/Windows/whatever (déjà installé probablement)
- Télécharge `ScalpingRadarEA.ex5` (~50 KB)
- Drop dans `Experts/`
- Restart MT5
- Drag sur chart, saisit api_key
- Allow WebRequest URL `https://app.scalping-radar.online`
- AutoTrading ON

**Différentiel** :
- Setup time : 1-2h → 5 min
- Coût récurrent : 22€/mois → 0€
- Compétences requises : Python + Tailscale + RDP → savoir glisser un fichier

## Plan d'implémentation

| Phase | Effort | Livrable |
|---|---|---|
| **MQL.A.** Spec finalisée | 1 h | ce doc, à itérer |
| **MQL.B.** Migration DB + endpoints EA | 3-4 h | `mt5_pending_orders` table, 3 endpoints, tests unit |
| **MQL.C.** Refactor SaaS push → enqueue | 1-2 h | `_enqueue_for_destination` remplace `_push_to_destination` pour les users (admin_legacy garde le HTTP push pour rétro-compat) |
| **MQL.D.** Code MQL5 EA | 4-6 h | `ScalpingRadarEA.mq5` source, compile `.ex5`, test manuel sur MT5 admin |
| **MQL.E.** UI Settings + endpoint download | 1-2 h | Settings → Auto-exec affiche bouton "Télécharger l'EA" + instructions au lieu du formulaire bridge_url, endpoint `/static/scalping-radar-ea.ex5` |
| **MQL.F.** Tests E2E + migration Cédric | 2-3 h | Cédric switch du bridge Python à l'EA, validation ordres |
| **MQL.G.** Cleanup bridge Python (optionnel, après stabilisation) | 2 h | Mark `mt5-bridge/` comme legacy dans le repo, doc updated |
| **Total** | **14-20 h** sur 4-5 sessions | |

## Risques & mitigations

| Risque | Probabilité | Mitigation |
|---|---|---|
| MQL5 langage que je ne maîtrise pas | élevée | Pair-prog avec Claude, tests step-by-step, mode debug verbose dans l'EA |
| WebRequest bloquante dans MT5 → si SaaS down, MT5 freeze | moyenne | `WebRequest()` a un timeout param. Set 5s. + l'EA tourne sur OnTimer pas OnTick (tick = chaque mouvement de prix, lourd) |
| Race condition multi-EA polling le même order | faible | UPDATE atomique status PENDING → SENT avec WHERE status='PENDING' (UPDATE OR IGNORE) |
| EA exécute un order obsolète (latence > setup décay) | moyenne | TTL `expires_at` 5 min, l'EA skip si expired |
| User désactive AutoTrading sans nous prévenir | élevée | Heartbeat tracking + alerte admin si pas de heartbeat depuis 1h |
| Pepperstone démo n'accepte pas les EAs | très faible | Pepperstone supporte les EAs natifs depuis 15 ans, vérifié sur leur doc |
| Multi-account MT5 (un user a plusieurs comptes) | moyenne | L'EA est attaché à UN chart d'UN compte. Pour multi-account, plusieurs instances EA. À documenter |

## Open questions

1. **Sécurité de l'api_key** : actuellement stockée en clair dans `users.broker_config`. L'EA va l'envoyer en query param par défaut. Faire un hash en DB + vérifier hash côté SaaS = standard. À spécifier en MQL.B.
2. **Polling interval** : 30s par défaut côté EA = jusqu'à 30s de latence entre setup généré et ordre passé. Sur du scalping H4 c'est OK, sur du M5 ça l'est moins. Tradeoff : plus court = plus de load SaaS. Solution V2 : WebSocket si polling trop limitant.
3. **Distribution de l'EA** : compilé `.ex5` ne marche que sur la version MT5 où il a été compilé. Soit on dist source `.mq5` (user le compile lui-même, 1 clic mais besoin du MetaEditor), soit on compile pour les 2-3 builds majeurs et on les dispose tous côté SaaS.
4. **Admin reste sur bridge Python ou migre aussi ?** Garde-t-on les 2 mécanismes en // pour permettre rollback admin si bug EA ? Reco : garder les 2 jusqu'à 2 semaines stables sur Cédric.
5. **Statistiques de couverture** : si l'EA est offline 1h (user a éteint son MT5), les setups générés pendant cette heure sont marqués EXPIRED. Affiche-t-on ce coverage gap dans le dashboard user ?

## Pourquoi ça vaut le coup

| Métrique | Bridge Python (actuel) | EA MQL5 |
|---|---|---|
| Onboarding time per user | 1-2 h | 5 min |
| Coût mensuel per user | 22 € (VPS) | 0 € |
| Compétences user requises | tech intermédiaire | sait glisser un fichier |
| Plateformes supportées | Windows uniquement | Windows + Mac |
| Latence ordre | < 1s (HTTP push) | ≤ 30s (polling, ajustable) |
| Friction Premium funnel | bloquante au-delà 2-3 users | scale infiniment |

À 5 users Premium, on économise 5 × 22 = **110 €/mois** sur les VPS, et
l'onboarding à 5 min permet d'envisager un funnel auto-service (l'user
fait tout seul depuis le SaaS sans pair-RDP).

## Décision

À valider avec le user avant code :
- ✅ Faire le pivot ?
- ✅ Quand ? Après Phase E avec Cédric (validation que multi-tenant marche
  end-to-end sur l'archi push), OU avant (skip Phase E, on-board Cédric
  directement sur l'EA) ?

Si ✅ + après E : ce chantier devient le suivant. ~14-20 h sur 4-5 sessions.

Si ✅ + avant E : on saute la session pair-RDP avec Cédric côté bridge
Python. Cédric sera la première démo de l'EA. Risk : si l'EA a un bug,
Cédric attend pendant qu'on debug. Recommandé seulement si l'EA est
bien testé d'abord côté admin (toi sur ton compte démo).
