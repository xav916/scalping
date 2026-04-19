# Spec fonctionnelle — Intégration MetaTrader 5 et bridge

**Date** : 2026-04-19
**Nature** : spec fonctionnelle rétrospective

---

## Pourquoi un bridge ?

**Contrainte technique** : la librairie Python officielle `MetaTrader5` communique avec le terminal via **mémoire partagée Windows**, pas via réseau. Le terminal MT5 doit donc tourner sur la **même machine** que le processus Python qui l'appelle. Le backend Scalping Radar vit sur AWS EC2 (Linux, cloud) → il ne peut pas parler directement à MT5.

**Solution** : un petit service Python (`bridge.py`) tourne sur le PC Windows de l'utilisateur, expose une API HTTP, et relaie les ordres vers MT5 local. Le backend EC2 appelle cette API via un tunnel **Tailscale**.

## Topologie

```
[EC2 Backend] ──HTTP──> [Tailscale tunnel] ──HTTP──> [PC Bridge :8787] ──SharedMemory──> [MT5 Desktop] ──> [Broker]
   100.103.107.75                                     100.122.188.8                                     MetaQuotes-Demo
```

Tailscale fait du **WireGuard** chiffré entre les deux machines. Le PC n'a pas besoin d'ouvrir un port public, il s'inscrit simplement dans le réseau privé Tailscale.

## Compte de trading actuel

| Propriété | Valeur |
|---|---|
| Broker | MetaQuotes (serveur démo officiel MT5) |
| Serveur | `MetaQuotes-Demo` |
| Login | 10010590722 |
| Type | **Démo** (argent fictif, 100 000 EUR de capital) |
| Objectif | Valider la boucle complète avant de passer en live |

**Le live n'est pas encore activé.** `PAPER_MODE=false` côté bridge signifie "ordres LIVE envoyés au broker", mais comme c'est un compte démo, c'est sans risque financier.

## Le bridge en 10 points

1. **Technologie** : Flask + MetaTrader5 Python lib 5.0.5735, Python 3.14 (venv local `C:\Scalping\mt5-bridge\venv`)
2. **Démarrage auto** : Task Scheduler Windows au logon (script `install_autostart.ps1`)
3. **Ports** : écoute 0.0.0.0:8787 (exposé via Tailscale)
4. **Auth** : header `X-API-Key` vérifié à chaque requête (clé secrète dans `.env` bridge et backend)
5. **Base locale** : SQLite `orders.db` avec table `orders` (audit complet de tous les ordres tentés/filled/closed)
6. **Endpoints** : `/health`, `/account`, `/symbols`, `/positions`, `/tick/<pair>`, `/order`, `/kill`, `/audit`
7. **Monitor thread** : surveille les positions ouvertes toutes les 5s (breakeven, partial close, trailing stop)
8. **Dedup** : refus d'ordres identiques dans les 5 minutes (même pair/direction/entry)
9. **Safety gates** : 6 vérifications avant chaque ordre (voir section dédiée)
10. **Kill switch** : endpoint `/kill` ferme toutes les positions + bloque les nouveaux ordres

## Règles d'auto-exécution

Le backend pousse un setup au bridge uniquement si :

| Filtre | Valeur actuelle |
|---|---|
| `MT5_BRIDGE_ENABLED` | `true` |
| `setup.verdict_action` | `"TAKE"` (pas WAIT, pas SKIP) |
| `setup.confidence_score` | ≥ `MT5_BRIDGE_MIN_CONFIDENCE` (60 actuellement) |

Le bridge lui-même ajoute des filtres :

| Safety gate | Valeur défaut | Rôle |
|---|---|---|
| `MAX_LOT` | `0.1` | Taille maximum d'un ordre (en lots) |
| `MAX_OPEN_POSITIONS` | `3` | Refus si déjà 3 positions ouvertes |
| `MAX_DAILY_LOSS_PCT` | `3.0` | Refus si la perte du jour dépasse 3% du capital |
| `DEDUP_WINDOW_SEC` | `300` | Refus d'un ordre identique dans les 5 min |
| `TRADING_HOURS_UTC` | vide | Si défini, refus hors de cette plage (ex `07-21`) |
| Filling mode | IOC avec fallback FOK | Gère les brokers qui n'acceptent qu'un seul type |

## Sizing (taille de position risk-based)

Le backend envoie un **risk_money** (euros/dollars à risquer), **pas un nombre de lots fixe**. Le bridge calcule les lots en connaissant le symbole broker :

```
risk_money = TRADING_CAPITAL × RISK_PER_TRADE_PCT / 100
# Ex: 10 000 × 1% = 100$

lots = risk_money / (|entry - sl| × tick_value × tick_count)
```

Le `tick_value` et le `tick_size` viennent de `mt5.symbol_info(symbol)` en temps réel — adapté au broker et au symbole.

**Garde-fous** :
- `lots` est arrondi au step du symbole (ex : 0.01)
- Clampé entre `volume_min` et `MAX_LOT`
- Si `|entry - sl|` est trop petit → ordre refusé

## Post-execution monitor

Une fois la position ouverte, un **thread de monitoring** la suit :

| Événement | Déclencheur | Action |
|---|---|---|
| **Breakeven auto** | Prix atteint `BREAKEVEN_TRIGGER_PCT` (50%) de la distance TP | Déplace SL à l'entry (0 risque) |
| **Partial close** | Après breakeven, prix atteint 70% du TP | Ferme `PARTIAL_CLOSE_PCT` (50%) des lots, sécurise un gain |
| **Trailing stop** | Après partial close | SL suit le prix à distance `TRAIL_DISTANCE_POINTS` (150) |
| **Fermeture auto** | TP atteint ou SL touché | MT5 clôture, bridge logue |

**Fréquence du check** : `MONITOR_INTERVAL_SEC` = 5s.

## Mapping symboles broker

Les brokers utilisent des suffixes différents (`.pro`, `.s`, `.raw`, etc.). Le mapping se configure dans `.env` backend :

```
MT5_SYMBOL_MAP="XAU/USD:GOLD.pro,EUR/USD:EURUSD.pro,GBP/USD:GBPUSD.pro,..."
```

Pour MetaQuotes-Demo, le format est simple : `EURUSD`, `GBPUSD`, `XAUUSD` (sans suffixe).

## Synchronisation bridge → dashboard

Toutes les 60s, le backend fait un `GET /audit?since_id=<last>` sur le bridge :

- Les **fills** (status=filled + mode=live) → INSERT dans `personal_trades` avec `is_auto=1`, `mt5_ticket=<ticket>`
- Les **closed** → UPDATE de la ligne correspondante (pnl, exit_price, closed_at, status='CLOSED')

Conséquence : les ordres auto apparaissent dans les sections **Mes trades / Risque / Equity / Détecteur d'erreurs** du dashboard, exactement comme si l'utilisateur les avait pris manuellement.

**Dedup** : la colonne `mt5_ticket` est unique — un re-pull (crash, restart) ne crée pas de doublons (INSERT OR IGNORE).

## Attribution utilisateur

Les trades auto sont attribués à un user unique (`AUTO_TRADE_USER` = `couderc.xavier@gmail.com`). Ils apparaissent donc dans **son** "Mes trades", sa courbe d'équité, son tableau de risque. L'autre user n'a pas accès aux trades auto.

Rationale : le bridge/MT5 est physiquement le PC d'un seul utilisateur, c'est son compte broker.

## Redémarrage après coupure

Si le PC redémarre :

1. **Tailscale** démarre automatiquement (service Windows)
2. **MT5 Desktop** est lancé par la tâche planifiée (mémorise le login)
3. **Bridge** est lancé par la tâche planifiée (`start_all.ps1`)
4. Au 1er cycle d'analyse (200s), le backend retente le push au bridge
5. Le `mt5_sync` reprend son polling depuis `last_id` persisté sur disque (`mt5_sync_state.json`)

**Caveat** : si un ordre était en cours au moment du crash, le bridge le retrouvera via `mt5.positions_get()` au redémarrage. Le monitor reprend la surveillance (BE, partial, trailing).

## Observabilité

- **Logs bridge** : `C:\Scalping\mt5-bridge\bridge.log` (console + stderr)
- **SQLite bridge** : `C:\Scalping\mt5-bridge\orders.db` (audit complet)
- **Logs backend** : `docker logs scalping-radar` (ligne `mt5_sync: X nouveaux trades auto, Y fermés`)
- **Dashboard** : section "Mes trades" avec flag `is_auto`

## Kill switches

| Niveau | Commande | Effet |
|---|---|---|
| Backend refuse de push | `MT5_BRIDGE_ENABLED=false` + `systemctl restart scalping` | Le radar détecte mais ne pousse plus au bridge |
| Bridge refuse d'exécuter | Ctrl+C dans la fenêtre PowerShell du bridge | Plus aucun ordre ne passe |
| Kill immédiat toutes positions | `curl -X POST /kill -H "X-API-Key: ..."` | Ferme tout + bloque les nouveaux ordres jusqu'au restart |
| MT5 désactive | Bouton "AutoTrading" dans MT5 Desktop (rouge) | MT5 rejette les ordres avec erreur 10027 |
| Tailscale off | `tailscale down` sur le PC | Le bridge devient injoignable depuis EC2 (le système revient en mode "détection seule") |

## Passage du démo au live (checklist future)

Quand l'user voudra passer en live :

1. Ouvrir un compte réel chez son broker (OANDA, IC Markets, Pepperstone, etc.)
2. Remplacer `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER` dans le `.env` du bridge
3. Vérifier le `MT5_SYMBOL_MAP` (les symboles varient entre brokers)
4. Commencer avec `MT5_BRIDGE_LOTS=0.01` (1 micro lot = $1/pip sur EUR/USD)
5. Surveiller 1 semaine avec `MT5_BRIDGE_MIN_CONFIDENCE=90` (plus strict)
6. Si résultats bons → abaisser progressivement à 80, puis 70

**Ne JAMAIS passer live avec `MACRO_VETO_ENABLED=false`**. Le veto est un filet de sécurité essentiel en live.

## Ce qui n'est pas fait

- **Pas de redondance de bridge** (un seul PC — si le PC tombe, pas de trade auto)
- **Pas de VPS MT5** (serait l'étape d'après pour 24/7 sans PC allumé)
- **Pas de multi-broker** (un seul terminal MT5 actif)
- **Pas de couverture options** (pas de hedge automatique)
- **Pas de gestion de news** côté bridge (le backend gère ça avec les événements ForexFactory)

## Références

- Bridge : `C:\Scalping\mt5-bridge\bridge.py`
- Bridge env : `C:\Scalping\mt5-bridge\.env`
- Backend push : `backend/services/mt5_bridge.py`
- Sync : `backend/services/mt5_sync.py`
- Settings : `config/settings.py` (sections MT5_BRIDGE_* et MT5_SYNC_*)
- Autostart Windows : `C:\Scalping\start_all.ps1` + `C:\Scalping\install_autostart.ps1`
