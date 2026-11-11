---
name: trader-meanrev
description: >-
  Mean Reversion FX Trader. Détecte les pics de volatilité sur les paires forex
  surveillées et prend des positions contre-trend avec cible VWAP du jour.
  Pipeline totalement automatique : filtre régime (BBW 1h + ATR 1h) → trigger
  temporel (bougie 15min + reversal) → exécution MT5 bridge sur IC Markets.
  Sizing dynamique 0.5% du balance, time stop 4h, gates indépendants. OFF par
  défaut (MEANREV_ENABLED=false). Utiliser si l'utilisateur dit "activer la
  mean reversion", "trader le retour à la moyenne", "après un pic de vol",
  "contre-trend forex", ou après une /trader-analyst qui identifie un pic.
argument-hint: "[enable|status|pause|resume]"
---

# trader-meanrev

Stratégie de **mean reversion** sur paires forex après pic de volatilité.
Signal composite 1h (régime) + 15min (trigger), cible VWAP du jour, time
stop 4h. Exécution live via bridge MT5 sur Lightsail Windows (IC Markets).

## Rationale

Les paires forex, surtout les majors, exhibent une **autocorrélation
négative à court terme après un choc de vol** : un pic exagéré tend à se
corriger partiellement vers une moyenne locale dans les heures qui
suivent. Capturer cette correction demande trois conditions simultanées :

1. **Régime haute volatilité confirmé** — sinon on confond un coup de
   bruit normal avec un vrai pic exploitable.
2. **Événement déclencheur daté** — une bougie exceptionnelle avec un
   début de reversal, pas juste "l'ATR est élevé".
3. **Cible réaliste** — un retour partiel vers le VWAP du jour, pas
   une inversion complète du trend.

## Signal composite

### Filtre régime (1h, 100 bougies)

- **BBW percentile > 80** : `(BB_up - BB_down) / SMA20` au-dessus du
  80e percentile de ses 100 dernières valeurs. Confirme qu'on est en
  régime de vol atypique.
- **ATR(14) 1h > 2× moyenne(ATR, 50)** : l'ATR courant est au moins le
  double de sa moyenne sur 50 bougies. Confirmation indépendante.

Les deux sont requis. L'intersection ≈ 5-10% des bougies, soit 1 à 2
fenêtres de régime par jour par paire.

### Trigger temporel (15min, 50 bougies)

- **Amplitude bougie > 2.5× ATR(14) 15min** : la dernière bougie est
  exceptionnellement grande par rapport à son ATR local.
- **Reversal pattern** : la bougie suivante (ou la queue de la trigger)
  montre un début de correction (close du côté opposé à la direction
  du mouvement).

### Direction

**Contre la bougie trigger** :
- Trigger baissière (close < open avec grande amplitude) → **BUY**
- Trigger haussière (close > open avec grande amplitude) → **SELL**

## Exécution

- **Entry** : au market dès que le setup est valide.
- **SL** : au-delà du pic extrême de la bougie trigger + **buffer 0.1× ATR**
  (pour éviter les stop-hunt sur mèches). Pour BUY : SL = low_trigger - 0.1×ATR.
  Pour SELL : SL = high_trigger + 0.1×ATR.
- **TP = VWAP du jour** : fetch dynamique sur les bougies 15min du jour UTC
  en cours. `VWAP = sum(typical × volume) / sum(volume)` avec typical =
  (H+L+C)/3.
- **Time stop 4h** : si la position est encore ouverte 4h après l'entrée,
  elle est fermée au market (évite les positions qui coincent sur un
  régime qui ne corrige plus).

## Sizing

**Risque fixe 0.5% du balance MT5**, fetché dynamiquement à chaque cycle
via `GET /account` sur le bridge.

```
risk_money_eur = balance_eur × 0.005
distance_sl    = abs(entry - sl)
lot_value_eur  = valeur_1_lot_dans_paire(pair, entry)
lots           = (risk_money_eur / distance_sl) / lot_value_eur
```

Lot minimum broker (0.01 MT5 standard = 1000 unités). Si le capital ne
permet pas 0.01 lot avec le risque autorisé → setup skip, pas d'ouverture
avec risque sur-dimensionné.

## Univers (16 paires watched)

Hérité de `WATCHED_PAIRS` du .env par défaut. Peut être surchargé par
`MEANREV_UNIVERSE`.

**Fiabilité MR par asset class** :

| Paires | Classe | Fiabilité MR |
|---|---|---|
| EUR/USD, GBP/USD, USD/JPY, USD/CHF, AUD/USD, USD/CAD | FX major | **Reliable** |
| EUR/GBP, EUR/JPY, GBP/JPY | FX cross | **Reliable** |
| XAU/USD | Commodity | *Experimental* (biais trend macro) |
| BTC/USD, ETH/USD | Crypto | *Experimental* (régimes asymétriques) |
| SPX, NDX | Equity index | *Experimental* (drift haussier structurel) |

La skill ne filtre pas automatiquement — on scanne tout, on observe la
stat par paire pendant la semaine d'observation, puis on décide quoi
désactiver.

## Gates fail-closed (ordre identique à auto_trader)

| Check | Env var | Baseline |
|---|---|---|
| Feature flag global | `MEANREV_ENABLED` | false |
| Mode | `MEANREV_MODE` | live |
| Forex hours (dim 22h UTC → ven 22h UTC) | — | — |
| Blackout vendredi | `MEANREV_FRIDAY_LATE_BLOCK_UTC` | 19:30 UTC |
| Kill switch global | `backend.services.kill_switch.status()` | — |
| FOMC/CPI window | `economic_calendar_veto.is_high_impact_window(120)` | — |
| Earnings veto | `earnings_calendar_service.hours_to_next_earnings()` | 48h |
| Perte journalière plafond | `MEANREV_MAX_DAILY_LOSS_EUR` | 10.0 |
| Positions ouvertes max | `MEANREV_MAX_POSITIONS` | 5 |

Un seul False → abort du cycle.

## Bridge MT5 (Lightsail Windows, IC Markets)

- URL : `MEANREV_BRIDGE_URL` (défaut `http://100.74.160.72:8787`)
- Auth : `MEANREV_BRIDGE_API_KEY` (optionnel, header `X-Bridge-Key`)
- Endpoints attendus :
  - `GET /account` → balance, equity
  - `GET /positions` → liste positions ouvertes
  - `POST /order` → open market order (pair, direction, lots, sl, tp)
  - `POST /close` → fermeture position (ticket)

**Fail-closed si bridge down** : si une requête HTTP échoue au cycle
(timeout, 5xx, connection refused), le cycle skip + alerte Telegram.
Pas de retry infini, pas de queue — on reprendra au cycle suivant quand
le bridge sera de nouveau joignable.

## Mode live direct

Contrairement à auto_trader qui démarre en dry_run, meanrev démarre
directement en **live** (`MEANREV_MODE=live`) dès activation. Décision
assumée : les paires forex sont liquides, les spreads courtiers serrés,
et le mécanisme MT5 est déjà éprouvé via `push_to_mt5` existant.

Pour tester sans risque : passer `MEANREV_MODE=dry_run` avant d'activer
`MEANREV_ENABLED=true`.

## Jobs scheduler

| Job | Trigger | Rôle |
|---|---|---|
| `meanrev_cycle` | interval `MEANREV_SCAN_INTERVAL_SEC` (900s) | scan setups |
| `meanrev_check_exits` | interval 60s | time stop 4h + VWAP targets |
| `meanrev_friday_close` | cron `fri 19:30 UTC` | force close positions |
| `meanrev_daily_recap` | cron `mon-fri 22:05 UTC` | recap Telegram |

## État persisté JSON

`MEANREV_STATE_PATH` (défaut `/app/data/meanrev_state.json`) :

```json
{
  "opening_date_utc": "2026-11-11",
  "opening_balance_eur": 500.0,
  "disabled_until_tomorrow": false,
  "open_positions": [
    {
      "pair": "EUR/USD", "direction": "buy", "lots": 0.01,
      "entry": 1.0823, "sl": 1.0810, "tp": 1.0850,
      "vwap_target": 1.0850,
      "entry_time_utc": "2026-11-11T14:30:00+00:00",
      "mt5_ticket": 12345, "status": "open"
    }
  ],
  "closed_history": [
    {
      "pair": "EUR/USD", "entry": 1.0823, "exit": 1.0850,
      "pnl_usd": 2.70, "reason": "vwap_hit",
      "close_date": "2026-11-11T16:45:00+00:00"
    }
  ]
}
```

## Déclencheurs

Activer manuellement après validation du bridge MT5 :

```bash
# .env en prod
MEANREV_ENABLED=true
MEANREV_MODE=live  # ou dry_run pour observer sans ordres
```

Puis `sudo systemctl restart scalping.service` sur l'EC2.
