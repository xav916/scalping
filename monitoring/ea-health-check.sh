#!/bin/bash
set -euo pipefail

# EA Health Monitoring — runs 4×/day (00:23, 06:23, 12:23, 18:23 UTC)
# Détecte anomalies (heartbeat offline, ordres zombies, low exec rate) et alerte Telegram

HEALTH_TOKEN="shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg"
HEALTH_URL="https://app.scalping-radar.online/api/admin/auto-exec/health-token"
NOTIFY_URL="https://app.scalping-radar.online/api/admin/notify-infra-telegram"

TMP_DIR="/tmp/scalping-health-$$"
mkdir -p "$TMP_DIR"
trap "rm -rf $TMP_DIR" EXIT

HEALTH_JSON="$TMP_DIR/health.json"
ISSUES_JSON="$TMP_DIR/issues.json"

echo "=== EA Health Check — $(date -u +'%Y-%m-%d %H:%M:%S UTC') ==="

# --- Step 1: Fetch health-token ---
echo "1. Fetching health endpoint..."
HTTP_CODE=$(curl -sk \
  "${HEALTH_URL}?token=${HEALTH_TOKEN}" \
  -o "$HEALTH_JSON" \
  -w '%{http_code}')

if [ "$HTTP_CODE" != "200" ]; then
  echo "❌ Health endpoint DOWN (HTTP $HTTP_CODE)"
  HEAD=$(head -3 "$HEALTH_JSON" 2>/dev/null || echo "(empty)")
  PAYLOAD=$(python3 -c "import json; print(json.dumps({'title': '🚨 EA monitoring — health endpoint DOWN', 'body': 'HTTP $HTTP_CODE, first lines:\n$HEAD'}))")
  curl -sk -X POST "${NOTIFY_URL}?token=${HEALTH_TOKEN}" \
    -H 'Content-Type: application/json' \
    -d "$PAYLOAD" -w '\nHTTP %{http_code}\n'
  exit 1
fi

# Validate JSON
if ! python3 -c "import json; json.load(open('$HEALTH_JSON'))" 2>/dev/null; then
  echo "❌ Invalid JSON from health endpoint"
  PAYLOAD=$(python3 -c "import json; print(json.dumps({'title': '🚨 EA monitoring — invalid JSON', 'body': 'health-token returned malformed JSON'}))")
  curl -sk -X POST "${NOTIFY_URL}?token=${HEALTH_TOKEN}" \
    -H 'Content-Type: application/json' \
    -d "$PAYLOAD" -w '\nHTTP %{http_code}\n'
  exit 1
fi

echo "✓ Health endpoint OK (HTTP 200)"

# --- Step 2: Parse + detect anomalies ---
echo "2. Analyzing health data..."
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
for u in d.get('users', []):
    uid = u.get('user_id')
    label = u.get('email') or f'user_{uid}'

    # 1) Heartbeat OFFLINE or stale > 30 min
    hb = u.get('heartbeat') or {}
    age = hb.get('age_seconds') or 0
    status = hb.get('status') or 'UNKNOWN'
    if status != 'LIVE' and age > 1800:
        issues.append(f"{label} (id={uid}) heartbeat {status} — last seen {age}s ago")

    # 2) Zombies (sent_stale or pending_overdue)
    z = u.get('zombies') or {}
    ztotal = z.get('total') or 0
    if ztotal > 0:
        issues.append(
            f"{label} (id={uid}) {ztotal} ordres zombies "
            f"(sent_stale={z.get('sent_stale',0)} pending_overdue={z.get('pending_overdue',0)})"
        )

    # 3) Low executed_rate on >=3 resolved orders
    o = u.get('orders_24h') or {}
    total = o.get('total') or 0
    exec_rate = o.get('executed_rate')
    if total >= 3 and exec_rate is not None and exec_rate < 0.5:
        by_status = o.get('by_status') or {}
        failed_by_pair = o.get('failed_by_pair') or {}
        if failed_by_pair:
            worst = max(failed_by_pair.items(), key=lambda x: x[1])
            top = f"{worst[0]}:{worst[1]}"
        else:
            top = '?'
        issues.append(
            f"{label} (id={uid}) exec_rate={int(exec_rate*100)}% sur {total} ordres 24h "
            f"(EXEC={by_status.get('EXECUTED',0)} FAILED={by_status.get('FAILED',0)}, top FAILED pair={top})"
        )

# 4) Global totals
T = d.get('totals') or {}
if (T.get('users_offline') or 0) > 0:
    issues.append(f"GLOBAL: {T['users_offline']} user(s) OFFLINE")

out = {
    'count': len(issues),
    'issues': issues,
    'totals': T,
    'users_count': len(d.get('users', [])),
}
print(json.dumps(out, indent=2, ensure_ascii=False))
PY

COUNT=$(python3 -c "import json; print(json.load(open('$ISSUES_JSON'))['count'])")
echo "✓ Found $COUNT anomalie(s)"

# --- Step 3: Notify if issues ---
if [ "$COUNT" -gt 0 ]; then
  echo "3. Sending Telegram alert..."

  PAYLOAD=$(python3 - <<PY
import json

ISSUES_FILE = "$ISSUES_JSON"
with open(ISSUES_FILE) as f:
    d = json.load(f)

T = d['totals']
body_lines = ['* ' + i for i in d['issues']]
body_lines.append('')
body_lines.append(f"users={d['users_count']} live={T.get('users_live',0)} offline={T.get('users_offline',0)} stale={T.get('users_stale',0)}")
body_lines.append(f"orders_24h={T.get('orders_24h','?')} exec_rate_24h={T.get('executed_rate_24h','?')} zombies={T.get('zombies_total',0)}")

body = '\n'.join(body_lines)
title = f"EA health — {d['count']} anomalie(s)"  # No double bold per Markdown legacy limit

print(json.dumps({'title': title, 'body': body}))
PY
)

  NOTIFY_CODE=$(curl -sk -X POST "${NOTIFY_URL}?token=${HEALTH_TOKEN}" \
    -H 'Content-Type: application/json' \
    -d "$PAYLOAD" -w '%{http_code}' -o /dev/null)

  if [ "$NOTIFY_CODE" = "200" ]; then
    echo "✓ Telegram alert sent (HTTP 200)"
  elif [ "$NOTIFY_CODE" = "503" ]; then
    echo "⚠ Telegram endpoint not configured (HTTP 503) — non-blocking"
  else
    echo "❌ Telegram POST failed (HTTP $NOTIFY_CODE)"
  fi
else
  echo "3. No anomalies detected — no alert sent"
fi

# --- Step 4: Final report ---
echo ""
echo "=== Final Report ==="
python3 - <<PY
import json

ISSUES_FILE = "$ISSUES_JSON"
with open(ISSUES_FILE) as f:
    issues = json.load(f)

T = issues['totals']
print(f"Anomalies: {issues['count']}")
print(f"Users: {issues['users_count']} total | {T.get('users_live',0)} live | {T.get('users_offline',0)} offline | {T.get('users_stale',0)} stale")
print(f"Orders 24h: {T.get('orders_24h','?')} total | exec_rate={T.get('executed_rate_24h','?')} | zombies={T.get('zombies_total',0)}")
if issues['issues']:
    print("\nIssues:")
    for i in issues['issues']:
        print(f"  - {i}")
else:
    print("Status: All healthy ✓")
PY

echo "=== Check complete ==="
