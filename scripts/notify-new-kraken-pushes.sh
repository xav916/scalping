#!/bin/bash
# Ping Telegram sales bot on new admin_kraken + admin_kraken_stocks pushes.
# Unifié 2026-08-03 : gère les 2 destinations (crypto + xStocks equity) qui partagent le bridge Kraken Futures port 8790.
# Ajout SL/TP EUR + R:R + plateforme précisée.
set -e
STATE="/var/lib/scalping/last-kraken-push-id.txt"
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

ROWS=$(sqlite3 "$DB" "SELECT id||'|'||pair||'|'||direction||'|'||ok||'|'||substr(coalesce(bridge_response,''),1,500)||'|'||pushed_at||'|'||destination_id FROM mt5_pushes WHERE id > $LAST AND destination_id IN ('admin_kraken','admin_kraken_stocks') ORDER BY id ASC LIMIT 10;")

[ -z "$ROWS" ] && exit 0

MAX_ID=$LAST
while IFS='|' read -r id pair dir okval resp ts dest_id; do
  [ -z "$id" ] && continue
  order_id=$(echo "$resp" | grep -oE '"market_order_id":[ ]*"[a-f0-9-]+"' | head -1 | grep -oE '"[a-f0-9-]+"$' | tr -d '"')
  avg_price=$(echo "$resp" | grep -oE '"avg_price":[ ]*[0-9.]+' | head -1 | grep -oE '[0-9.]+')
  volume=$(echo "$resp" | grep -oE '"volume":[ ]*[0-9.]+' | head -1 | grep -oE '[0-9.]+')
  sl=$(echo "$resp" | grep -oE '"sl":[ ]*[0-9.]+' | head -1 | grep -oE '[0-9.]+')
  tp=$(echo "$resp" | grep -oE '"tp":[ ]*[0-9.]+' | head -1 | grep -oE '[0-9.]+')
  sl_err=$(echo "$resp" | grep -oE '"sl_error":[ ]*"[^"]+"' | head -1)
  tp_err=$(echo "$resp" | grep -oE '"tp_error":[ ]*"[^"]+"' | head -1)

  dir_word="ACHAT"
  [ "$dir" = "sell" ] && dir_word="VENTE"

  # Label plateforme dynamique selon destination_id
  if [ "$dest_id" = "admin_kraken_stocks" ]; then
    plat="Kraken Futures · xStock (equity tokenisée USD)"
  else
    plat="Kraken Futures · Perpetuel Crypto USD"
  fi

  RR_LINE=""
  if [ -n "$avg_price" ] && [ -n "$sl" ] && [ -n "$tp" ] && [ -n "$volume" ]; then
    RR_JSON=$(python3 "$HELPER" --pair "$pair" --entry "$avg_price" --sl "$sl" --tp "$tp" --volume "$volume" --bridge-type kraken --eur-usd "$EUR_USD" 2>/dev/null || echo '{}')
    RISK_EUR=$(echo "$RR_JSON" | python3 -c "import json,sys;print(json.load(sys.stdin).get('risk_eur',''))" 2>/dev/null)
    REWARD_EUR=$(echo "$RR_JSON" | python3 -c "import json,sys;print(json.load(sys.stdin).get('reward_eur',''))" 2>/dev/null)
    RR=$(echo "$RR_JSON" | python3 -c "import json,sys;print(json.load(sys.stdin).get('rr',''))" 2>/dev/null)
    if [ -n "$RISK_EUR" ] && [ "$RISK_EUR" != "0" ]; then
      RR_LINE="\n🛡️ Stop Loss : ${sl}  →  -€${RISK_EUR}\n🎯 Take Profit : ${tp}  →  +€${REWARD_EUR}\n📊 Ratio R:R : 1:${RR}"
    fi
  fi

  if [ "$okval" = "1" ]; then
    prot="✅ SL + TP protégés"
    [ -n "$sl_err" ] && prot="⚠️ SL NON placé ($sl_err)"
    [ -n "$tp_err" ] && prot="$prot | ⚠️ TP NON placé"
    TITLE="🟢 $plat · $pair $dir_word"
    BODY="Plateforme : ${plat}\nCompte : Kraken Futures LIVE (argent réel USD)\n\n📋 Détail\nOrder ID : ${order_id:-n/a}\nPrix moyen : ${avg_price:-?}\nVolume : ${volume:-?} contracts${RR_LINE}\n\nEnvoyé : ${ts}\n$prot"
  else
    TITLE="❌ $plat REFUSÉ · $pair $dir_word"
    BODY="Plateforme : ${plat}\n\n📋 Détail\nVolume tenté : ${volume:-?}\nTenté : ${ts}\n\nℹ️ Logs : sudo journalctl -u kraken-bridge -f"
  fi

  curl -sS -m 5 -X POST "$URL" -H "Content-Type: application/json" --data "{\"title\":\"$TITLE\",\"body\":\"$BODY\",\"dedup_key\":\"kraken_push_${id}\",\"cooldown_seconds\":86400}" > /dev/null || true
  MAX_ID=$id
done <<< "$ROWS"

echo $MAX_ID > "$STATE"
echo "$(date -Iseconds) processed up to id=$MAX_ID (eur_usd=$EUR_USD)"
