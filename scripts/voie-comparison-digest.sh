#!/bin/bash
# Digest horaire : lit voie-comparison.jsonl sur la dernière heure et pousse
# un résumé Telegram infra via api.telegram.org (indépendant du domaine SaaS)

set -uo pipefail

LOG=/var/log/scalping/voie-comparison.jsonl
BOT_TOKEN=$(sudo grep -E '^INFRA_TELEGRAM_BOT_TOKEN=' /opt/scalping/.env | cut -d= -f2-)
CHAT_ID=$(sudo grep -E '^INFRA_TELEGRAM_CHAT_ID=' /opt/scalping/.env | cut -d= -f2-)

if [ -z "$BOT_TOKEN" ] || [ -z "$CHAT_ID" ]; then
  echo "INFRA_TELEGRAM_BOT_TOKEN or INFRA_TELEGRAM_CHAT_ID missing" >&2
  exit 1
fi

if [ ! -s "$LOG" ]; then
  echo "log empty" >&2
  exit 0
fi

BODY=$(LOG="$LOG" python3 <<'PY'
import json, os
from collections import defaultdict
from datetime import datetime, timedelta, timezone

path = os.environ['LOG']
cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
by_sym = defaultdict(list)

with open(path) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        try:
            ts = datetime.fromisoformat(r['ts'].replace('Z', '+00:00'))
        except Exception:
            continue
        if ts < cutoff:
            continue
        if r.get('spread_pct') is None:
            continue
        by_sym[r['symbol']].append(r['spread_pct'])

if not by_sym:
    print("Voie A vs B — pas de tick comparable sur la derniere heure")
    raise SystemExit(0)

lines = ["Voie A (Kraken xStock) vs Voie B (IC Markets CFD) — 1h"]
for sym in sorted(by_sym):
    vals = by_sym[sym]
    n = len(vals)
    avg = sum(vals) / n
    mn = min(vals)
    mx = max(vals)
    lines.append(f"{sym}: n={n} avg={avg:+.3f}% min={mn:+.3f}% max={mx:+.3f}%")
print("\n".join(lines))
PY
)

if [ -z "$BODY" ]; then
  exit 0
fi

MESSAGE=$(printf "<b>Voie A (Kraken xStock) vs Voie B (CFD IC Markets)</b>\n<pre>%s</pre>" "$BODY")

curl -sS --max-time 10 -X POST \
  "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
  -d "chat_id=${CHAT_ID}" \
  --data-urlencode "text=${MESSAGE}" \
  -d "parse_mode=HTML" \
  -d "disable_web_page_preview=true" > /dev/null
