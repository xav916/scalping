#!/bin/bash
set -euo pipefail

# MT5 Bridges Health Monitoring — runs hourly (xx:37 UTC)
# Détecte si les 2 bridges (legacy Pepperstone Demo + live IC Markets) sont DOWN
# et alerte le bot infra Telegram via dedup + cooldown 3h

HEALTH_TOKEN="shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg"
HEALTH_URL="https://app.scalping-radar.online/api/admin/mt5-bridges-health"
NOTIFY_URL="https://app.scalping-radar.online/api/admin/notify-infra-telegram"

TMP_DIR="/tmp/scalping-mt5-monitor-$$"
mkdir -p "$TMP_DIR"
trap "rm -rf $TMP_DIR" EXIT

HEALTH_JSON="$TMP_DIR/bridges.json"
ISSUES_JSON="$TMP_DIR/issues.json"

echo "=== MT5 Bridges Health Check — $(date -u +'%Y-%m-%d %H:%M:%S UTC') ==="

# --- Step 1: Fetch health endpoint ---
echo "1. Fetching MT5 bridges health endpoint..."
HTTP_CODE=$(curl -sk --max-time 10 \
  "${HEALTH_URL}?token=${HEALTH_TOKEN}" \
  -o "$HEALTH_JSON" \
  -w '%{http_code}')

if [ "$HTTP_CODE" != "200" ]; then
  echo "❌ Health endpoint DOWN (HTTP $HTTP_CODE)"
  HEAD=$(head -3 "$HEALTH_JSON" 2>/dev/null || echo "(empty)")
  PAYLOAD=$(python3 -c "import json; print(json.dumps({'title': '🚨 Bridge monitor — health endpoint DOWN', 'body': f'HTTP $HTTP_CODE : {\"$HEAD\"}'}))")
  curl -sk -X POST "${NOTIFY_URL}?token=${HEALTH_TOKEN}" \
    -H 'Content-Type: application/json' \
    -d "$PAYLOAD" -w '\nHTTP %{http_code}\n'
  exit 1
fi

# Validate JSON
if ! python3 -c "import json; json.load(open('$HEALTH_JSON'))" 2>/dev/null; then
  echo "❌ Invalid JSON from health endpoint"
  PAYLOAD=$(python3 -c "import json; print(json.dumps({'title': '🚨 Bridge monitor — invalid JSON', 'body': 'mt5-bridges-health returned malformed JSON'}))")
  curl -sk -X POST "${NOTIFY_URL}?token=${HEALTH_TOKEN}" \
    -H 'Content-Type: application/json' \
    -d "$PAYLOAD" -w '\nHTTP %{http_code}\n'
  exit 1
fi

echo "✓ Health endpoint OK (HTTP 200)"

# --- Step 2: Parse + detect anomalies ---
echo "2. Analyzing bridge health data..."
python3 - <<PY > "$ISSUES_JSON"
import json
import sys

HEALTH_FILE = "$HEALTH_JSON"

try:
    with open(HEALTH_FILE) as f:
        d = json.load(f)
except Exception as e:
    print(f"Error reading health file: {e}", file=sys.stderr)
    sys.exit(1)

issues = []
for key in ('legacy', 'live'):
    b = d.get(key) or {}
    label = {
        'legacy': 'Pepperstone Demo (legacy/8787)',
        'live': 'IC Markets Live (live/8788)'
    }[key]

    # Skip if not configured
    if not b.get('configured'):
        continue

    # Check if unreachable
    if not b.get('reachable'):
        err = b.get('error') or b.get('status') or 'unknown'
        issues.append({
            'key': key,
            'label': label,
            'url': b.get('url'),
            'detail': f"UNREACHABLE ({err})",
        })
        continue

    # Check if ok=false
    if not b.get('ok'):
        issues.append({
            'key': key,
            'label': label,
            'url': b.get('url'),
            'detail': f"reachable but ok=false (login={b.get('login')}, server={b.get('server')})",
        })

out = {'count': len(issues), 'issues': issues, 'snapshot': d}
print(json.dumps(out, indent=2, ensure_ascii=False))
PY

COUNT=$(python3 -c "import json; print(json.load(open('$ISSUES_JSON'))['count'])")
echo "✓ Analyzed bridges, found $COUNT anomalie(s)"

# --- Step 3: Notify if issues (with dedup + cooldown) ---
if [ "$COUNT" -gt 0 ]; then
  echo "3. Sending Telegram alerts..."

  # Process each issue separately with dedup_key
  for KEY in $(python3 -c "import json; [print(i['key']) for i in json.load(open('$ISSUES_JSON'))['issues']]"); do
    PAYLOAD=$(python3 - <<PY
import json

d = json.load(open('$ISSUES_JSON'))
iss = next(i for i in d['issues'] if i['key'] == '$KEY')

title = f"🚨 Bridge {iss['label']} DOWN"
body = f"{iss['detail']}\nURL : {iss['url']}\nAction : RDP au VPS cedric-mt5-bridge, relancer mt5-bridge-{iss['key']} via .\\\\venv\\\\Scripts\\\\python.exe .\\\\bridge.py"

print(json.dumps({
    'title': title,
    'body': body,
    'dedup_key': f"bridge_{iss['key']}_down",
    'cooldown_seconds': 10800
}))
PY
)

    echo "=== POST infra-telegram pour $KEY ==="
    NOTIFY_CODE=$(curl -sk -X POST "${NOTIFY_URL}?token=${HEALTH_TOKEN}" \
      -H 'Content-Type: application/json' \
      -d "$PAYLOAD" \
      -w '%{http_code}' -o /dev/null)

    if [ "$NOTIFY_CODE" = "200" ]; then
      echo "✓ Telegram alert sent for $KEY (HTTP 200)"
    elif [ "$NOTIFY_CODE" = "503" ]; then
      echo "⚠ Telegram endpoint not configured (HTTP 503) — non-blocking"
    else
      echo "❌ Telegram POST failed for $KEY (HTTP $NOTIFY_CODE)"
    fi
  done
else
  echo "3. No anomalies detected — all bridges UP"
fi

# --- Step 4: Final report ---
echo ""
echo "=== Final Report ==="
python3 - <<PY
import json
from datetime import datetime

d = json.load(open('$ISSUES_JSON'))
snapshot = d['snapshot']

print(f"Timestamp: {snapshot.get('now', '?')}")
print(f"Anomalies detected: {d['count']}")
print()

for key in ('legacy', 'live'):
    b = snapshot.get(key) or {}
    label = {
        'legacy': 'Pepperstone Demo (legacy/8787)',
        'live': 'IC Markets Live (live/8788)'
    }[key]

    if not b.get('configured'):
        print(f"{label}: NOT CONFIGURED")
        continue

    reachable = b.get('reachable', False)
    ok = b.get('ok', False)
    status = "✓ UP" if (reachable and ok) else "❌ DOWN"

    print(f"{label}:")
    print(f"  Status: {status}")
    print(f"  URL: {b.get('url', '?')}")
    print(f"  Reachable: {reachable}")
    print(f"  OK: {ok}")
    if reachable:
        print(f"  Login: {b.get('login', '?')}")
        print(f"  Server: {b.get('server', '?')}")
    if not reachable:
        print(f"  Error: {b.get('error', '?')}")

if d['issues']:
    print()
    print("Issues:")
    for iss in d['issues']:
        print(f"  - {iss['label']}: {iss['detail']}")
else:
    print()
    print("Status: All bridges healthy ✓")

PY

echo "=== Check complete ==="
