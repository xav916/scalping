#!/bin/bash
# Compare xStock Kraken Futures (Voie A) vs CFD IC Markets .NAS/.NYSE (Voie B)
# Log JSONL vers /var/log/scalping/voie-comparison.jsonl (une ligne par paire par run)

set -uo pipefail

BK=$(sudo grep -E '^KRAKEN_BRIDGE_API_KEY=' /opt/kraken-bridge/.env | cut -d= -f2-)
LU=$(sudo grep -E '^MT5_BRIDGE_LIVE_URL=' /opt/scalping/.env | cut -d= -f2-)
LK=$(sudo grep -E '^MT5_BRIDGE_LIVE_API_KEY=' /opt/scalping/.env | cut -d= -f2-)

LOG_DIR=/var/log/scalping
LOG=$LOG_DIR/voie-comparison.jsonl
sudo mkdir -p "$LOG_DIR"
sudo touch "$LOG"
sudo chmod 664 "$LOG"

TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# pair:kraken_pair_alias:mt5_symbol
PAIRS=(
  "AAPL:AAPL:AAPL.NAS"
  "TSLA:TSLA:TSLA.NAS"
  "NVDA:NVDA:NVDA.NAS"
  "MSTR:MSTR:MSTR.NAS"
  "HOOD:HOOD:HOOD.NAS"
  "SPY:SPY:SPY.NYSE"
  "QQQ:QQQ:QQQ.NAS"
)

for entry in "${PAIRS[@]}"; do
  IFS=':' read -r label ka_pair mt_sym <<< "$entry"

  KA=$(curl -s --max-time 4 -H "X-Bridge-Key: $BK" "http://127.0.0.1:8790/tick/$ka_pair" 2>/dev/null || echo '{}')
  MT=$(curl -s --max-time 6 -H "X-API-Key: $LK" "$LU/tick/$mt_sym" 2>/dev/null || echo '{}')

  KA_JSON="$KA" MT_JSON="$MT" TS="$TS" LABEL="$label" MT_SYM="$mt_sym" \
  python3 -c "
import json, os
ka = json.loads(os.environ.get('KA_JSON') or '{}')
mt = json.loads(os.environ.get('MT_JSON') or '{}')
out = {'ts': os.environ['TS'], 'symbol': os.environ['LABEL'], 'mt_sym': os.environ['MT_SYM']}

if ka.get('ok'):
    kb, ks = ka.get('bid') or 0, ka.get('ask') or 0
    out['a_bid'] = kb
    out['a_ask'] = ks
    out['a_mid'] = round((kb + ks) / 2, 4) if kb and ks else None
    out['a_mark'] = ka.get('markPrice')
    out['a_index'] = ka.get('indexPrice')
    out['a_funding'] = ka.get('fundingRate')
else:
    out['a_error'] = ka.get('error') or 'no_data'

mb, ms = mt.get('bid') or 0, mt.get('ask') or 0
mtime = mt.get('time', '')
if mb and ms and not mtime.startswith('1970'):
    out['b_bid'] = mb
    out['b_ask'] = ms
    out['b_mid'] = round((mb + ms) / 2, 4)
    out['b_time'] = mtime
else:
    out['b_error'] = 'market_watch_not_activated' if mtime.startswith('1970') else (mt.get('error') or 'no_data')

if out.get('a_mid') and out.get('b_mid'):
    delta = out['a_mid'] - out['b_mid']
    out['spread_abs'] = round(delta, 4)
    out['spread_pct'] = round(delta / out['b_mid'] * 100, 4)

print(json.dumps(out, separators=(',', ':')))
" | sudo tee -a "$LOG" > /dev/null
done
