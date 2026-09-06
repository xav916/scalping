#!/bin/bash
# Ping Telegram infra bot chaque fois qu'un signal XAU/EUR approche le seuil Live (conf >=55 <60).
# Cron : */5 * * * * /opt/scalping/scripts/notify-near-live-threshold.sh >> /var/log/scalping/near-live.log 2>&1
set -e

STATE="/var/lib/scalping/last-near-live-id.txt"
DB="/opt/scalping/data/trades.db"
TOKEN="shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg"
URL="https://app.scalping-radar.online/api/admin/notify-infra-telegram?token=${TOKEN}"

mkdir -p /var/lib/scalping

[ -f "$STATE" ] || echo 0 > "$STATE"
LAST=$(cat "$STATE")
LAST=${LAST:-0}

ROWS=$(sqlite3 "$DB" "SELECT id||'|'||pair||'|'||direction||'|'||printf('%.1f',confidence)||'|'||created_at FROM signal_rejections WHERE id > $LAST AND pair IN ('XAU/USD','EUR/USD','WTI/USD') AND reason_code='below_confidence' AND confidence >= 55 AND confidence < 60 ORDER BY id ASC LIMIT 20;")

[ -z "$ROWS" ] && { echo "$(date -Iseconds) no new near-live signals (last id=$LAST)"; exit 0; }

MAX_ID=$LAST
COUNT=0
while IFS='|' read -r id pair dir conf ts; do
  [ -z "$id" ] && continue
  MAX_ID=$id
  COUNT=$((COUNT+1))

  dir_word="ACHAT"
  [ "$dir" = "sell" ] && dir_word="VENTE"
  gap=$(awk -v c="$conf" 'BEGIN { printf "%.1f", 60 - c }')

  TITLE="🔵 Signal proche seuil Live · $pair $dir_word"
  BODY="Un signal $pair $dir_word vient d'être généré à **$conf/100** de confiance.\n\nSeuil Live actuel = 60 → il manque $gap points.\n\nSi la volatilité progresse dans les prochaines minutes, la confiance peut franchir 60 et déclencher un ordre Live automatique sur ton compte IC Markets.\n\nGénéré : $ts"

  curl -sS -m 5 -X POST "$URL" \
    -H "Content-Type: application/json" \
    --data "{\"title\":\"$TITLE\",\"body\":\"$BODY\",\"dedup_key\":\"near_live_${id}\",\"cooldown_seconds\":86400}" \
    > /dev/null || true
done <<< "$ROWS"

echo "$MAX_ID" > "$STATE"
echo "$(date -Iseconds) processed $COUNT signals up to id=$MAX_ID"
