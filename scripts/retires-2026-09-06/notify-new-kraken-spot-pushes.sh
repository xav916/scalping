#!/bin/bash
# Ping Telegram sales bot on every new admin_kraken_spot push (BTC/ETH réels).
# Enrichi 2026-08-03 : SL/TP EUR + R:R + plateforme dans titre.
set -e
STATE="/var/lib/scalping/last-kraken-spot-push-id.txt"
DB="/opt/scalping/data/trades.db"
TOKEN="shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg"
URL="https://app.scalping-radar.online/api/admin/notify-infra-telegram?token=${TOKEN}&channel=sales"
HELPER="/opt/scalping/scripts/lib_calc_risk_eur.py"

LU=$(sudo grep -E '^MT5_BRIDGE_LIVE_URL=' /opt/scalping/.env | cut -d= -f2-)
LK=$(sudo grep -E '^MT5_BRIDGE_LIVE_API_KEY=' /opt/scalping/.env | cut -d= -f2-)
EUR_USD=$(curl -sS -m 3 -H "X-API-Key: $LK" "$LU/tick/EUR/USD" 2>/dev/null | python3 -c "import json,sys
try:
    d=json.load(sys.stdin); print(round((d.get('bid',0)+d.get('ask',0))/2, 4))
except Exception: print('')" 2>/dev/null)
EUR_USD=${EUR_USD:-1.155}
[ "$EUR_USD" = "0" ] || [ "$EUR_USD" = "0.0" ] && EUR_USD=1.155

[ -f "$STATE" ] || echo 0 > "$STATE"
LAST=$(cat "$STATE")
LAST=${LAST:-0}

ROWS=$(sqlite3 "$DB" "SELECT id||'|'||pair||'|'||direction||'|'||ok||'|'||substr(coalesce(bridge_response,''),1,500)||'|'||pushed_at FROM mt5_pushes WHERE id > $LAST AND destination_id='admin_kraken_spot' ORDER BY id ASC LIMIT 10;")

[ -z "$ROWS" ] && exit 0

plat="Kraken Spot · BTC/ETH réels (long-only, sans levier)"

MAX_ID=$LAST
while IFS='|' read -r id pair dir okval resp ts; do
  [ -z "$id" ] && continue
  txid=$(echo "$resp" | grep -oE '"txid":[ ]*"[A-Z0-9-]+"' | head -1 | grep -oE '"[A-Z0-9-]+"$' | tr -d '"')
  volume=$(echo "$resp" | grep -oE '"volume":[ ]*[0-9.]+' | head -1 | grep -oE '[0-9.]+')
  avg_price=$(echo "$resp" | grep -oE '"(avg_price|price)":[ ]*[0-9.]+' | head -1 | grep -oE '[0-9.]+$')
  sl=$(echo "$resp" | grep -oE '"sl":[ ]*[0-9.]+' | head -1 | grep -oE '[0-9.]+')
  tp=$(echo "$resp" | grep -oE '"tp":[ ]*[0-9.]+' | head -1 | grep -oE '[0-9.]+')
  watcher=$(echo "$resp" | grep -oE '"watcher_started":[ ]*(true|false)' | head -1 | grep -oE '(true|false)')

  RR_LINE=""
  if [ -n "$avg_price" ] && [ -n "$sl" ] && [ -n "$tp" ] && [ -n "$volume" ]; then
    RR_JSON=$(python3 "$HELPER" --pair "$pair" --entry "$avg_price" --sl "$sl" --tp "$tp" --volume "$volume" --bridge-type kraken_spot --eur-usd "$EUR_USD" 2>/dev/null || echo '{}')
    RISK_EUR=$(echo "$RR_JSON" | python3 -c "import json,sys;print(json.load(sys.stdin).get('risk_eur',''))" 2>/dev/null)
    REWARD_EUR=$(echo "$RR_JSON" | python3 -c "import json,sys;print(json.load(sys.stdin).get('reward_eur',''))" 2>/dev/null)
    RR=$(echo "$RR_JSON" | python3 -c "import json,sys;print(json.load(sys.stdin).get('rr',''))" 2>/dev/null)
    if [ -n "$RISK_EUR" ] && [ "$RISK_EUR" != "0" ]; then
      RR_LINE="\n🛡️ Stop Loss : ${sl}  →  -€${RISK_EUR}\n🎯 Take Profit : ${tp}  →  +€${REWARD_EUR}\n📊 Ratio R:R : 1:${RR}"
    fi
  fi

  # Lien primaire : ordres ouverts (SL/TP watchers émulés visibles)
  ORDERS_URL="https://pro.kraken.com/app/orders?type=open"
  # Lien secondaire : vue trade du symbol (format BTC-USD dash)
  KRAKEN_PAIR=$(echo "$pair" | tr '/' '-' | tr '[:lower:]' '[:upper:]')
  KRAKEN_URL="https://pro.kraken.com/app/trade/${KRAKEN_PAIR}"
  PORTFOLIO_URL="https://pro.kraken.com/app/portfolio"

  if [ "$okval" = "1" ]; then
    watch_line="✅ Watcher SL/TP émulé actif"
    [ "$watcher" = "false" ] && watch_line="⚠️ Watcher NON démarré — position sans protection"
    TITLE="🟢 $plat · $pair"
    BODY="Plateforme : ${plat}\nCompte : Kraken Spot LIVE (crypto vraiment détenue)\n\n📋 Détail\nTxID : ${txid:-n/a}\nPrix : ${avg_price:-?}\nVolume : ${volume:-?} unités${RR_LINE}\n\nEnvoyé : ${ts}\n$watch_line\n\n📱 Suivi ordres ouverts (app Kraken Pro si installée) : ${ORDERS_URL}\n🔗 Portefeuille (holdings) : ${PORTFOLIO_URL}\n🔗 Graphique symbole : ${KRAKEN_URL}"
  else
    TITLE="❌ $plat REFUSÉ · $pair"
    BODY="Plateforme : ${plat}\n\n📋 Détail\nVolume tenté : ${volume:-?}\nTenté : ${ts}\n\nℹ️ Logs : sudo journalctl -u kraken-spot-bridge -f"
  fi

  curl -sS -m 5 -X POST "$URL" -H "Content-Type: application/json" --data "{\"title\":\"$TITLE\",\"body\":\"$BODY\",\"dedup_key\":\"kraken_spot_push_${id}\",\"cooldown_seconds\":86400}" > /dev/null || true
  MAX_ID=$id
done <<< "$ROWS"

echo $MAX_ID > "$STATE"
echo "$(date -Iseconds) processed up to id=$MAX_ID (eur_usd=$EUR_USD)"
