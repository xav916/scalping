---
name: trader-scalp
description: Stratégie scalping intraday RSI/ATR sur candles 1min, visant ~15-30 setups/jour sur IC Markets demo. Tourne en parallèle de meanrev momentum.
---

# trader-scalp

Scalping intraday agressif pour générer un volume élevé de trades (**15-30
TAKE / jour** attendus sur 4 paires FX), en complément de `meanrev momentum`
qui est très sélectif (1-3 trades / semaine).

## Design en 2 phrases

À chaque minute, sur `SCALP_UNIVERSE`, calculer RSI(14) + ATR(14) sur les
dernières bougies 1min. Si `RSI < 30` + bougie haussière → BUY ; si
`RSI > 70` + bougie baissière → SELL. SL/TP calés sur ATR avec R:R 1.5.

## Gates (fail-closed, ordre identique à meanrev)

| Gate | Env var | Baseline |
|---|---|---|
| Feature flag | `SCALP_ENABLED` | `false` |
| Mode | `SCALP_MODE` | `dry_run` |
| Forex hours | — | dim 22h UTC → ven 22h UTC |
| Blackout vendredi | `SCALP_FRIDAY_LATE_BLOCK_UTC` | `19:30` |
| Kill switch global | `kill_switch.status()` | — |
| Balance fetch | bridge `/account` | — |
| Daily loss | `SCALP_MAX_DAILY_LOSS_EUR` | `15.0` |
| Max positions | `SCALP_MAX_POSITIONS` | `10` |

## Sizing

Risque = `SCALP_RISK_PCT` (défaut 0.25%) × balance par trade. Convertit en
lots via `distance_SL × contract_size` (métal = 100 oz, forex = 100000
unités, crypto = 1 unit — réutilise `_contract_size` de `meanrev_trader`).

## Routing Telegram

- `dry_run` → canal demo 🟦
- `live` + `SCALP_ACCOUNT_IS_DEMO=true` → canal demo 🟦 (defaut)
- `live` + `SCALP_ACCOUNT_IS_DEMO=false` → canal `ic_markets` 🟩

Chaque TAKE envoie une **carte riche OPEN** (`send_trade_opened`). Chaque
close (SL/TP/time_stop/Friday) envoie une **carte riche CLOSE**
(`send_close`). Format identique aux cartes meanrev.

## État persisté

`SCALP_STATE_PATH` (défaut `/app/data/scalp_state.json`) :

```json
{
  "opening_date_utc": "2026-11-13",
  "opening_balance_eur": 1000.0,
  "disabled_until_tomorrow": false,
  "bridge_alert_sent_today": false,
  "open_positions": [
    {"pair": "EUR/USD", "direction": "buy", "lots": 0.01,
     "entry": 1.0820, "sl": 1.0815, "tp": 1.08275,
     "entry_time_utc": "2026-11-13T18:30:00+00:00",
     "mt5_ticket": 2088732092, "last_seen_price": 1.0821,
     "status": "open"}
  ],
  "closed_history": [
    {"pair": "EUR/USD", "direction": "buy", "lots": 0.01,
     "entry": 1.0820, "sl": 1.0815, "tp": 1.08275,
     "exit_price": 1.08275, "exit_time_utc": "...",
     "pnl_usd": 7.50, "close_reason": "tp", "status": "closed_tp"}
  ]
}
```

## Config complète

```bash
SCALP_ENABLED=false
SCALP_MODE=dry_run
SCALP_BRIDGE_URL=http://100.74.160.72:8787
SCALP_BRIDGE_API_KEY=            # fallback MT5_BRIDGE_API_KEY si vide
SCALP_ACCOUNT_IS_DEMO=true
SCALP_UNIVERSE=XAU/USD,EUR/USD,GBP/USD,USD/JPY
SCALP_MAX_DAILY_LOSS_EUR=15.0
SCALP_MAX_POSITIONS=10
SCALP_RISK_PCT=0.25              # % du balance par trade
SCALP_RSI_PERIOD=14
SCALP_RSI_LONG_THR=30            # RSI below → entrée LONG
SCALP_RSI_SHORT_THR=70           # RSI above → entrée SHORT
SCALP_SL_ATR_MULT=1.0            # SL distance = 1 × ATR
SCALP_TP_R_MULT=1.5              # TP = 1.5 × distance SL (R:R 1.5)
SCALP_ATR_PERIOD=14
SCALP_TIME_STOP_MINUTES=60       # ferme si position > 60 min
SCALP_FRIDAY_LATE_BLOCK_UTC=19:30
SCALP_SCAN_INTERVAL_SEC=60       # cycle toutes les 60s
SCALP_STATE_PATH=/app/data/scalp_state.json
```

## Scheduler jobs (ajoutés par PR #34)

| Job | Interval / cron | Rôle |
|---|---|---|
| `scalp_cycle` | 60s (configurable) | Détection + exécution |
| `scalp_check_exits` | 30s | SL/TP + time stop |
| `scalp_friday_close` | `fri 19:30 UTC` | Force-close weekend |
| `scalp_daily_recap` | `mon-fri 22:05 UTC` | Récap Telegram |

## Activation

```bash
# /opt/scalping/.env
SCALP_ENABLED=true
SCALP_MODE=dry_run  # commencer en dry_run pour 1-2 jours d'observation
```

Puis `sudo systemctl restart scalping.service`.

Observer pendant 1-2 jours : vérifier fréquence des TAKE, winrate,
drawdown. Si viable → passer `SCALP_MODE=live`.

## Garde-fous spécifiques scalping

- **Spread et commissions sur tant de trades peuvent manger le PnL** :
  avec 30 trades/jour × 1 USD de spread × 5 jours = 150 USD/semaine.
  Garder en tête que cette strat n'est viable que si le profit factor
  dépasse 1.1 **après commissions**.
- **Time stop 60 min** évite les positions qui coincent. Les scalps qui
  "deviennent des swings" sont le symptôme d'un signal faux.
- **Max 10 positions simultanées** limite l'exposition totale.

## Reste à faire avant go live

1. Observer dry_run 1-2 jours → stats
2. Vérifier Twelve Data peut servir des candles 1min pour les 4 paires
   (plan Grow = 2 symbols en WS temps réel, le reste en polling)
3. Valider fréquence réelle vs cible 15-30/jour
4. Si viable : switch `SCALP_MODE=live`
