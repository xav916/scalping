#!/bin/bash
# Rapport quotidien des candidats à promotion sur destinations sans auto-promote
# (admin_kraken, admin_kraken_spot, admin_kraken_stocks).
# Base : nombre de signaux reçus par user:2 (Cédric EA bypass verdicts) sur 7j/30j
# comme proxy de la qualité/volume signal, puisque les destinations Kraken sont
# actuellement DEMOTED donc pas de flux réel pour mesurer WR/PnL.
# Push notif @xav_scalping_sales_bot chaque jour à 18h UTC = 20h Paris.
set -uo pipefail

DB=/opt/scalping/data/trades.db
BOT_TOKEN=$(sudo grep -E '^SALES_TELEGRAM_BOT_TOKEN=' /opt/scalping/.env | cut -d= -f2-)
CHAT_ID=$(sudo grep -E '^SALES_TELEGRAM_CHAT_ID=' /opt/scalping/.env | cut -d= -f2-)

if [ -z "$BOT_TOKEN" ] || [ -z "$CHAT_ID" ]; then
  echo "missing sales creds" >&2
  exit 1
fi

# Seuils empiriques (calqués sur gates 1-2 du promotion_engine)
MIN_SIGNALS_7D=5     # au moins 5 signaux dans les 7j = flux actif
MIN_SIGNALS_30D=20   # au moins 20 signaux dans les 30j = volume statistique

# Query volume signaux par pair × direction sur user:2 (proxy)
STATS_JSON=$(sudo sqlite3 $DB "
SELECT json_group_array(json_object(
  'pair', pair,
  'direction', direction,
  'n_7d', n_7d,
  'n_30d', n_30d
))
FROM (
  SELECT
    pair,
    direction,
    SUM(CASE WHEN pushed_at > datetime('now','-7 days') THEN 1 ELSE 0 END) as n_7d,
    COUNT(*) as n_30d
  FROM mt5_pushes
  WHERE destination_id='user:2'
    AND pair IN ('BTC/USD','ETH/USD','AAPL','TSLA','NVDA','MSFT','MSTR','HOOD','SPY','QQQ')
    AND pushed_at > datetime('now','-30 days')
  GROUP BY pair, direction
  HAVING n_30d >= 1
);
")

# État actuel pair_admission_state pour ces pairs sur destinations Kraken
CURRENT_STATE_JSON=$(sudo sqlite3 $DB "
SELECT json_group_array(json_object(
  'pair', pair,
  'direction', direction,
  'destination', destination,
  'state', state
))
FROM (
  SELECT pair, direction, COALESCE(destination,'GLOBAL') as destination, state
  FROM pair_admission_state pas1
  WHERE pair IN ('BTC/USD','ETH/USD','AAPL','TSLA','NVDA','MSFT','MSTR','HOOD','SPY','QQQ')
    AND id = (
      SELECT MAX(id) FROM pair_admission_state pas2
      WHERE pas2.pair=pas1.pair
        AND (pas2.direction IS pas1.direction OR (pas2.direction IS NULL AND pas1.direction IS NULL))
        AND (pas2.destination IS pas1.destination OR (pas2.destination IS NULL AND pas1.destination IS NULL))
    )
);
")

# Compose rapport via Python
BODY=$(STATS_JSON="$STATS_JSON" STATES_JSON="$CURRENT_STATE_JSON" \
  MIN_7D="$MIN_SIGNALS_7D" MIN_30D="$MIN_SIGNALS_30D" python3 <<'PY'
import json, os
stats = json.loads(os.environ.get('STATS_JSON') or '[]')
states = json.loads(os.environ.get('STATES_JSON') or '[]')
min_7d = int(os.environ.get('MIN_7D', 5))
min_30d = int(os.environ.get('MIN_30D', 20))

# Indexe l'état actuel : (pair, direction, destination_or_None) -> state
state_idx = {}
for s in states:
    dest = s['destination'] if s['destination'] != 'GLOBAL' else None
    state_idx[(s['pair'], s['direction'], dest)] = s['state']

# Résout état pour un (pair, direction, dest) : direct → fallback global
def resolve_state(pair, direction, dest):
    if (pair, direction, dest) in state_idx:
        return state_idx[(pair, direction, dest)]
    if (pair, direction, None) in state_idx:
        return state_idx[(pair, direction, None)]
    if (pair, None, None) in state_idx:
        return state_idx[(pair, None, None)]
    return 'UNKNOWN'

# Cible : destinations sans auto-promote (Kraken)
CRYPTO_DESTS = ['admin_kraken', 'admin_kraken_spot']
STOCKS_DESTS = ['admin_kraken_stocks']

def is_crypto(p): return p in ('BTC/USD','ETH/USD')
def is_stock(p): return p in ('AAPL','TSLA','NVDA','MSFT','MSTR','HOOD','SPY','QQQ')

candidates_promote = []
to_watch = []
missing_data = []

for s in stats:
    pair, direction, n7, n30 = s['pair'], s['direction'], s['n_7d'], s['n_30d']
    dests = CRYPTO_DESTS if is_crypto(pair) else (STOCKS_DESTS if is_stock(pair) else [])
    # Kraken Spot = long-only, skip sell direction
    if direction == 'sell':
        dests = [d for d in dests if d != 'admin_kraken_spot']

    for dest in dests:
        cur_state = resolve_state(pair, direction, dest)
        if cur_state == 'AUTO_EXEC':
            continue  # déjà tradable, skip

        row = f"{pair} {direction.upper()} → {dest} [{cur_state}] · 7j={n7} 30j={n30}"
        if n7 >= min_7d and n30 >= min_30d:
            candidates_promote.append(row)
        elif n30 >= min_30d // 2 or n7 >= max(min_7d // 2, 1):
            to_watch.append(row)
        else:
            missing_data.append(row)

lines = []
if candidates_promote:
    lines.append("🟢 <b>Candidats promotion (critères remplis)</b>")
    lines.extend(f"  • {r}" for r in candidates_promote[:10])
    lines.append("")
if to_watch:
    lines.append("🟡 <b>À surveiller (proche seuils)</b>")
    lines.extend(f"  • {r}" for r in to_watch[:10])
    lines.append("")
if missing_data:
    lines.append("🔵 <b>Données insuffisantes (volume trop faible)</b>")
    lines.extend(f"  • {r}" for r in missing_data[:10])
    lines.append("")

if not lines:
    lines.append("Aucune destination Kraken sans admission à évaluer aujourd'hui.")

lines.append(f"\n<i>Seuils : n_7d ≥ {min_7d} + n_30d ≥ {min_30d} (proxy user:2 EA)</i>")
lines.append("<i>Rapport quotidien 20h Paris. Reply au bot pour promouvoir manuellement.</i>")

print("\n".join(lines))
PY
)

if [ -z "$BODY" ]; then
  echo "empty body" >&2
  exit 0
fi

MESSAGE=$(printf "<b>Candidats promotion Kraken · %s</b>\n\n%s" "$(date -u '+%Y-%m-%d')" "$BODY")

curl -sS --max-time 10 -X POST \
  "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
  -d "chat_id=${CHAT_ID}" \
  --data-urlencode "text=${MESSAGE}" \
  -d "parse_mode=HTML" \
  -d "disable_web_page_preview=true" > /dev/null

echo "$(date -Iseconds) sent promotion candidates report"
