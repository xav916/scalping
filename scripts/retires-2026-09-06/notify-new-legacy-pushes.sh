#!/bin/bash
# Ping Telegram sales bot on every new admin_legacy push (MT5 Demo Pepperstone).
# Ajouté 2026-08-03 après audit couverture pour compléter la matrice.
# Note : Demo = argent fictif, sert de baseline comparaison vs Live.
set -e
STATE="/var/lib/scalping/last-legacy-push-id.txt"
DB="/opt/scalping/data/trades.db"
TOKEN="shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg"
URL="https://app.scalping-radar.online/api/admin/notify-infra-telegram?token=${TOKEN}&channel=sales"
HELPER="/opt/scalping/scripts/lib_calc_risk_eur.py"

# EUR/USD rate depuis bridge Live (Demo bridge n'expose peut-être pas /tick/EUR/USD)
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

ROWS=$(sqlite3 "$DB" "SELECT id||'|'||pair||'|'||direction||'|'||ok||'|'||substr(coalesce(bridge_response,''),1,400)||'|'||pushed_at FROM mt5_pushes WHERE id > $LAST AND destination_id='admin_legacy' ORDER BY id ASC LIMIT 10;")

[ -z "$ROWS" ] && exit 0

MAX_ID=$LAST
while IFS='|' read -r id pair dir okval resp ts; do
  [ -z "$id" ] && continue
  ticket=$(echo "$resp" | grep -oE '"ticket":[ ]*[0-9]+' | head -1 | grep -oE '[0-9]+')
  price=$(echo "$resp" | grep -oE '"(price|avg_price)":[ ]*[0-9.]+' | head -1 | grep -oE '[0-9.]+$')
  volume=$(echo "$resp" | grep -oE '"volume":[ ]*[0-9.]+' | head -1 | grep -oE '[0-9.]+')
  sl=$(echo "$resp" | grep -oE '"sl":[ ]*[0-9.]+' | head -1 | grep -oE '[0-9.]+')
  tp=$(echo "$resp" | grep -oE '"tp":[ ]*[0-9.]+' | head -1 | grep -oE '[0-9.]+')

  dir_word="ACHAT"
  [ "$dir" = "sell" ] && dir_word="VENTE"

  pair_upper=$(echo "$pair" | tr '[:lower:]' '[:upper:]')
  case "$pair_upper" in
    XAU*|XAG*) plat="MT5 Demo Pepperstone · CFD Métal (fictif)" ;;
    WTI*|BRENT*|XTI*|XBR*|NGAS*) plat="MT5 Demo Pepperstone · CFD Énergie (fictif)" ;;
    SPX|NDX|DAX|CAC40|FTSE|US30|US500|NAS100) plat="MT5 Demo Pepperstone · CFD Indice (fictif)" ;;
    BTC*|ETH*|LTC*|XRP*|SOL*|ADA*|DOGE*|BCH*|DOT*) plat="MT5 Demo Pepperstone · CFD Crypto (fictif)" ;;
    *) plat="MT5 Demo Pepperstone · CFD Forex (fictif)" ;;
  esac

  RR_LINE=""
  if [ -n "$price" ] && [ -n "$sl" ] && [ -n "$tp" ] && [ -n "$volume" ]; then
    RR_JSON=$(python3 "$HELPER" --pair "$pair" --entry "$price" --sl "$sl" --tp "$tp" --volume "$volume" --bridge-type mt5 --eur-usd "$EUR_USD" 2>/dev/null || echo '{}')
    RISK_EUR=$(echo "$RR_JSON" | python3 -c "import json,sys;print(json.load(sys.stdin).get('risk_eur',''))" 2>/dev/null)
    REWARD_EUR=$(echo "$RR_JSON" | python3 -c "import json,sys;print(json.load(sys.stdin).get('reward_eur',''))" 2>/dev/null)
    RR=$(echo "$RR_JSON" | python3 -c "import json,sys;print(json.load(sys.stdin).get('rr',''))" 2>/dev/null)
    if [ -n "$RISK_EUR" ] && [ "$RISK_EUR" != "0" ]; then
      RR_LINE="\n🛡️ Stop Loss : ${sl}  →  -€${RISK_EUR} (fictif)\n🎯 Take Profit : ${tp}  →  +€${REWARD_EUR} (fictif)\n📊 Ratio R:R : 1:${RR}"
    fi
  fi

  # Dashboard SaaS = même page positions, filtrable Demo vs Live
  DASHBOARD_URL="https://app.scalping-radar.online/v2/positions"

  if [ "$okval" = "1" ]; then
    TITLE="🟡 $plat · $pair $dir_word"
    BODY="Plateforme : ${plat}\nCompte : Pepperstone Demo (argent fictif, baseline test)\n\n📋 Détail\nTicket : #${ticket:-n/a}\nPrix entrée : ${price:-?}\nVolume : ${volume:-?}${RR_LINE}\n\nEnvoyé : ${ts}\n\n📱 Ouvrir MT5 mobile : metatrader5://\n🔗 Dashboard positions : ${DASHBOARD_URL}\nℹ️ Position Demo — utile pour observer sans risque monétaire."
  else
    TITLE="❌ $plat REFUSÉ · $pair $dir_word"
    BODY="Plateforme : ${plat}\n\n📋 Détail\nVolume tenté : ${volume:-?}\nTenté : ${ts}\n\nℹ️ Voir logs bridge Demo (port 8787)."
  fi

  curl -sS -m 5 -X POST "$URL" -H "Content-Type: application/json" --data "{\"title\":\"$TITLE\",\"body\":\"$BODY\",\"dedup_key\":\"legacy_push_${id}\",\"cooldown_seconds\":86400}" > /dev/null || true
  MAX_ID=$id
done <<< "$ROWS"

echo $MAX_ID > "$STATE"
echo "$(date -Iseconds) processed up to id=$MAX_ID (eur_usd=$EUR_USD)"
