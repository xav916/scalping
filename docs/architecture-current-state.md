# Architecture — État actuel (source de vérité)

**Dernière mise à jour :** 2026-04-30
**Mainteneur :** mettre à jour à chaque transition (activation/désactivation d'une couche)

> Ce document décrit ce qui **tourne réellement en prod aujourd'hui**, pas ce qui
> existe dans le code. Si tu te demandes "on est sur quel système ?", la réponse
> est ici.

## TL;DR en une phrase

**Aujourd'hui, les trades qui se déclenchent en démo Pepperstone sont produits par
le système V1 (legacy scoring), exécutés via le bridge Python sur VPS Lightsail.**
L'EA MQL5 et Track A V2_CORE_LONG existent en parallèle mais ne tradent pas encore.

## Carte des 3 couches

```mermaid
flowchart TB
    subgraph SIGNAL["🧠 SIGNAL — qui décide les trades"]
        V1["✅ V1 scoring (legacy)<br/>ACTIF en prod<br/>verdict 'pas d'edge structurel'<br/>actif depuis ~6 semaines"]
        TRACKA["📊 Track A V2_CORE_LONG XAU H4<br/>SHADOW LOG (observe seulement)<br/>actif depuis 2026-04-25<br/>Sharpe 1.59 backtest, gate S6 = 2026-06-06"]
    end

    subgraph EXEC["📡 EXECUTION — qui pousse au broker"]
        BRIDGE["✅ Bridge Python (VPS Lightsail Windows)<br/>ACTIF pour user admin<br/>VPS 100.74.160.72 / 13.51.157.9<br/>actif depuis 2026-04-20"]
        EAQUEUE["🆕 EA MQL5 queue (mt5_pending_orders)<br/>DEPLOYÉ mais idle<br/>endpoints /api/ea/* live<br/>aucun user routé encore"]
    end

    subgraph BROKER["🏦 BROKER — où atterrissent les ordres"]
        PEPPER["✅ Pepperstone démo (compte 62119130)<br/>ACTIF<br/>PaperStone-Demo, paper money"]
    end

    V1 ==>|"setups générés<br/>par cycle radar"| BRIDGE
    BRIDGE ==>|"POST /order"| PEPPER
    TRACKA -.->|"observe sans<br/>exécuter"| TRACKA

    EAQUEUE -.->|"polls=1<br/>exec=0<br/>(idle)"| BRIDGE_EA["MT5 admin Desktop<br/>(EA attaché XAUUSD M30<br/>depuis 2026-04-30 13h23)"]

    style V1 fill:#90EE90
    style BRIDGE fill:#90EE90
    style PEPPER fill:#90EE90
    style TRACKA fill:#FFD700
    style EAQUEUE fill:#FFA07A
    style BRIDGE_EA fill:#FFA07A
```

**Légende :**
- 🟢 vert = actif, produit du trade en démo
- 🟡 jaune = actif, produit de la donnée mais pas de trade (observation)
- 🟠 orange = déployé mais idle (pas de routing vers cette couche)

## Détail couche par couche

### Couche 1 — Signal (qui décide les trades)

| Système | Statut | Depuis | Direction trades | Edge backtest |
|---|---|---|---|---|
| **V1 scoring legacy** | ✅ actif prod | ~6 semaines | Multi-pattern, multi-direction, multi-asset | ❌ pas d'edge structurel (verdict 2026-04-25) |
| **Track A V2_CORE_LONG XAU H4** | 📊 shadow log | 2026-04-25 | LONG only sur XAU + extensions XAG/WTI/ETH | ✅ Sharpe 1.59, maxDD 20% (24m backtest) |
| ML modèle | ❌ jamais activé | — | — | AUC 0.526 (pas d'edge ML) |

**Ce qui se passe concrètement** : à chaque cycle radar (toutes les ~2 min), V1 calcule
les setups, les insère en DB. Si `MT5_BRIDGE_ENABLED=true` et le setup match les filtres
(asset class, confidence ≥ seuil), il est pushé au bridge.

### Couche 2 — Execution (qui pousse les ordres au broker)

| Système | Statut | Depuis | Users routés |
|---|---|---|---|
| **Bridge Python (VPS Lightsail)** | ✅ actif | 2026-04-20 | admin (toi) |
| **EA MQL5 queue** | 🟠 déployé idle | 2026-04-29 deploy + 2026-04-30 attach | aucun (smoke seulement) |

**Pourquoi 2 chemins coexistent** : on est en transition bridge → EA. Le bridge marche,
on le garde tant que l'EA n'a pas été validé en réel. Une fois Cédric onboardé via EA
et stabilisé 3-4 jours, on pourra basculer admin sur EA aussi (et déprécier le bridge).

**Routage actuel** :
- `users.tier = 'premium'` AND `users.api_key_set = true` → EA queue (futur Cédric)
- Sinon → bridge Python (admin actuellement)

### Couche 3 — Broker (où atterrissent les ordres)

| Broker | Statut | Compte | Mode |
|---|---|---|---|
| **Pepperstone UK Demo** | ✅ actif | 62119130 / PepperstoneUK-Demo | Paper money |
| Pepperstone Réel | ❌ pas activé | — | Bloqué jusqu'à V2 macro ou Track A live |

**Mode démo intentionnel** : V1 a été validé sans edge → on n'investit pas en réel.
Le passage à argent réel est explicitement gaté sur l'activation Track A (gate S6
= 2026-06-06) ou un pivot V2 macro.

## Ce qui change dans les 6 prochaines semaines (planning)

| Date | Événement | Impact archi |
|---|---|---|
| 2026-04-30 (auj.) | Smoke EA admin sur XAUUSD M30 | EA attaché, idle |
| 2026-04-30 (auj.) | Mail Cédric envoyé | — |
| ~2026-05-02 | Cédric onboardé sur EA | EA queue passe ACTIVE pour Cédric |
| 2026-05-03 | Routine W1 shadow log | Premier rapport hebdo Track A |
| ~2026-05-10 | Décision admin → EA (si Cédric stable) | Bridge Python deprecated |
| 2026-06-06 | **Gate S6** Track A | GO Phase 5 (auto-exec démo Track A) ou continuation observation |
| 2026-06+ | Si gate S6 passé | Track A devient signal principal en démo, V1 désactivé |

## Comment vérifier ce qui tourne en live (commandes)

```bash
# 1. Quel système signal pousse les trades ?
curl -u admin:PASS https://app.scalping-radar.online/api/trades?limit=5
# → champ `signal_pattern` = source V1 (range_bounce_down, momentum_up, etc.)

# 2. Quelle couche execution est routée ?
# → champ `notes` du trade contient "Auto-exec via bridge MT5" = Bridge Python
# → si "Auto-exec via EA queue" = EA MQL5

# 3. État du shadow log Track A
curl https://app.scalping-radar.online/api/shadow/v2_core_long/public-summary?token=shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg

# 4. État santé EA admin (sur PC local MT5)
# Onglet Experts dans MT5 → ligne "[ScalpingRadarEA] alive — polls=N exec=N fail=N"
```

## Pourquoi cet empilement (rationale)

On a **trois ères qui coexistent** parce qu'on est dans une transition :

1. **Ère V1 (legacy, ~mars 2026 → aujourd'hui)** : système initial, signaux multi-pattern.
   Backtest a invalidé son edge le 2026-04-25 mais on continue à le faire tourner en
   démo car (a) il alimente les analytics, (b) il sert de baseline observable, (c)
   l'arrêter avant Track A live = trou dans la timeline.

2. **Ère recherche Track A (2026-04-25 → maintenant)** : pivot vers un système
   risk-adjusted validé. En shadow log seulement jusqu'à gate S6.

3. **Ère pivot infra MQL5 (2026-04-29 → maintenant)** : changement d'architecture
   d'exécution (bridge Python → EA). Indépendant du signal, c'est juste pour
   simplifier l'onboarding des futurs users premium (Cédric en premier).

L'archi finale visée (~2026-06-15+) : **Track A signal → EA queue → Pepperstone démo**.
Trois couches simplifiées, V1 et bridge Python tous deux deprecated.

## Circuit breaker — auto-pause/auto-resume sur rafale SL

**Activé depuis 2026-04-30** (env `RAFALE_AUTO_PAUSE_ENABLED=true`, default).

Le watchdog `stop_loss_alerts` tourne toutes les 5 min et :

1. **Détecte les rafales** :
   - Globale : ≥ 5 SL auto-exec en 1h → Telegram + **auto-pause**
   - Par pattern : ≥ 3 SL même pattern en 1h → Telegram seul (pas de pause)
2. **Auto-pause** (rafale globale uniquement) : appelle `kill_switch.set_rafale_pause()`
   qui bloque l'envoi de nouveaux ordres au bridge MT5 pendant
   `RAFALE_PAUSE_DURATION_MIN` minutes (default 120 = 2h).
3. **Auto-resume** : à chaque cycle 5 min, `consume_expired_rafale_pause()`
   vérifie si la pause a expiré ; si oui, clear automatique + Telegram
   "Auto-resume" envoyé.

**Effet sur les couches** :
- Couche 1 (signal) : continue de générer (analytics non affectées)
- Couche 2 (exec) : nouveaux ordres bloqués, **trades ouverts continuent**
  jusqu'à leur SL/TP naturel (pas de fermeture forcée)
- Couche 3 (broker) : aucun changement

**Désactivation** : `RAFALE_AUTO_PAUSE_ENABLED=false` dans `.env` puis
restart. Ou clear manuel : `kill_switch.clear_rafale_pause()` via shell
Python dans le container (rare cas).

## Liens utiles

- Verdict V1 : [`docs/superpowers/specs/2026-04-22-backtest-v1-findings.md`](superpowers/specs/2026-04-22-backtest-v1-findings.md)
- Synthèse recherche : [`docs/superpowers/specs/2026-04-26-research-project-synthesis.md`](superpowers/specs/2026-04-26-research-project-synthesis.md)
- Spec EA pivot : [`docs/superpowers/specs/2026-04-29-mql5-ea-pivot-spec.md`](superpowers/specs/2026-04-29-mql5-ea-pivot-spec.md)
- Multi-tenant routing : [`docs/superpowers/specs/2026-04-28-multi-tenant-bridge-routing.md`](superpowers/specs/2026-04-28-multi-tenant-bridge-routing.md)
- Journal observation drawdown : [`docs/superpowers/journal/2026-04-30-v1-drawdown-observation.md`](superpowers/journal/2026-04-30-v1-drawdown-observation.md)
