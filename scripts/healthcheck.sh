#!/usr/bin/env bash
# Scalping Radar — Healthcheck multi-comptes
# Usage : ./healthcheck.sh [--verbose]
# Cron : */15 * * * * /opt/scalping/scripts/healthcheck.sh > /var/log/scalping/healthcheck.log 2>&1
set -u
VERBOSE="${1:-}"
ALERTS=()
ENVFILE=/opt/scalping/.env
DEMO_KEY=$(sudo grep "^MT5_BRIDGE_API_KEY=" "$ENVFILE" | cut -d= -f2)
LIVE_KEY=$(sudo grep "^MT5_BRIDGE_LIVE_API_KEY=" "$ENVFILE" | cut -d= -f2)
DEMO_URL=$(sudo grep "^MT5_BRIDGE_URL=" "$ENVFILE" | cut -d= -f2)
LIVE_URL=$(sudo grep "^MT5_BRIDGE_LIVE_URL=" "$ENVFILE" | cut -d= -f2)
SALES_BOT=$(sudo grep "^SALES_TELEGRAM_BOT_TOKEN=" "$ENVFILE" | cut -d= -f2)
SALES_CHAT=$(sudo grep "^SALES_TELEGRAM_CHAT_ID=" "$ENVFILE" | cut -d= -f2)
INFRA_BOT=$(sudo grep "^INFRA_TELEGRAM_BOT_TOKEN=" "$ENVFILE" | cut -d= -f2)
INFRA_CHAT=$(sudo grep "^INFRA_TELEGRAM_CHAT_ID=" "$ENVFILE" | cut -d= -f2)

log() { [[ -n "$VERBOSE" ]] && echo "$@"; }
fail() { ALERTS+=("$1"); echo "[FAIL] $1"; }

# 1) /health Demo
log "=== 1) Bridge Demo /health ==="
DH=$(curl -s -m 5 "$DEMO_URL/health")
echo "$DH" | grep -q "62119130" && log "  OK Pepperstone Demo login 62119130" || fail "Bridge Demo /health KO ou login != 62119130 (got: ${DH:0:120})"
echo "$DH" | grep -q "PepperstoneUK-Demo" || fail "Bridge Demo server != PepperstoneUK-Demo"

# 2) /health Live
log "=== 2) Bridge Live /health ==="
LH=$(curl -s -m 5 "$LIVE_URL/health")
echo "$LH" | grep -q "13137475" && log "  OK IC Markets Live login 13137475" || fail "Bridge Live /health KO ou login != 13137475 (got: ${LH:0:120})"
echo "$LH" | grep -q "ICMarketsEU-MT5-5" || fail "Bridge Live server != ICMarketsEU-MT5-5"

# 3) Bridges isolés (les 2 logins doivent etre differents)
log "=== 3) Isolation bridges ==="
[[ "$DH" != "$LH" ]] || fail "/health Demo == /health Live — bridges encore mélangés !"

# 4) Compte Live balance (alerte si < 250 = drawdown important)
log "=== 4) Live account balance ==="
LA=$(curl -s -m 5 -H "X-API-Key: $LIVE_KEY" "$LIVE_URL/account")
LB=$(echo "$LA" | python3 -c "import sys,json; print(json.load(sys.stdin).get('balance', 0))")
log "  balance=$LB EUR"
python3 -c "import sys; sys.exit(0 if float()>=250 else 1)" || fail "Live balance €$LB < 250 (drawdown 17%+)"

# 5) DB checks via container
log "=== 5) DB checks ==="
DB_CHECK=$(sudo docker exec -i scalping-radar python3 << 'PY'
import sqlite3, json
from datetime import datetime, timezone, timedelta
con = sqlite3.connect("/app/data/trades.db")
con.row_factory = sqlite3.Row
out = {}
# 5a Cedric heartbeat <30 min
cfg = json.loads(con.execute("SELECT broker_config FROM users WHERE id=2").fetchone()[0] or "{}")
hb = cfg.get("last_ea_heartbeat")
if hb:
    age_min = (datetime.now(timezone.utc) - datetime.fromisoformat(hb)).total_seconds()/60
    out["cedric_hb_min"] = round(age_min, 1)
else:
    out["cedric_hb_min"] = -1
# 5b Cycle heartbeat <5 min
r = con.execute("SELECT cycle_started_at FROM radar_cycle_heartbeat ORDER BY id DESC LIMIT 1").fetchone()
if r:
    age_min = (datetime.now(timezone.utc) - datetime.fromisoformat(r[0])).total_seconds()/60
    out["cycle_hb_min"] = round(age_min, 1)
# 5c Rafale verdict_blocker dernière heure
n = con.execute("SELECT COUNT(*) FROM signal_rejections WHERE created_at >= datetime('now','-1 hour') AND reason_code='verdict_blocker'").fetchone()[0]
out["verdict_blocker_1h"] = n
# 5d Pushes count dernière heure (info, pas une alerte weekend)
n = con.execute("SELECT COUNT(*) FROM mt5_pushes WHERE pushed_at >= datetime('now','-1 hour')").fetchone()[0]
out["pushes_1h"] = n
# 5e EXTRA_PAIRS_GLOBAL loaded
import os
out["extra_pairs"] = os.environ.get("MT5_BRIDGE_EXTRA_PAIRS_GLOBAL", "")
# 5f Cedric Stripe sub (devrait pas etre obsolete)
print(json.dumps(out))
PY
)
log "  DB: $DB_CHECK"
CEDRIC_HB=$(echo "$DB_CHECK" | python3 -c "import sys,json; print(json.load(sys.stdin)['cedric_hb_min'])")
CYCLE_HB=$(echo "$DB_CHECK" | python3 -c "import sys,json; print(json.load(sys.stdin)['cycle_hb_min'])")
EXTRA=$(echo "$DB_CHECK" | python3 -c "import sys,json; print(json.load(sys.stdin)['extra_pairs'])")

python3 -c "import sys; sys.exit(0 if float()<60 else 1)" || fail "EA Cedric heartbeat = ${CEDRIC_HB} min (>60 min — EA peut être down)"
python3 -c "import sys; sys.exit(0 if float()<10 else 1)" || fail "Radar cycle heartbeat = ${CYCLE_HB} min (>10 min — scheduler bloqué)"
[[ "$EXTRA" == *"BTC/USD"* ]] || fail "MT5_BRIDGE_EXTRA_PAIRS_GLOBAL ne contient pas BTC/USD"

# 6) Telegram bots reachable (juste check token, pas envoi)
log "=== 6) Telegram bots /getMe ==="
for nm in infra sales; do
    case "$nm" in infra) tok="$INFRA_BOT";; sales) tok="$SALES_BOT";; esac
    [[ -n "$tok" ]] || { fail "Token $nm vide"; continue; }
    R=$(curl -s -m 5 "https://api.telegram.org/bot${tok}/getMe")
    echo "$R" | grep -q ok:true && log "  OK bot $nm" || fail "Telegram bot $nm token invalide"
done

# Alertes
if [[ ${#ALERTS[@]} -gt 0 ]]; then
    MSG="🚨 <b>Healthcheck Scalping Radar - ${#ALERTS[@]} erreur(s)</b>%0A%0A"
    for a in "${ALERTS[@]}"; do MSG="$MSG- $a%0A"; done
    MSG="$MSG%0A<i>$(date -u "+%Y-%m-%d %H:%M UTC")</i>"
    curl -s -m 10 -X POST "https://api.telegram.org/bot${INFRA_BOT}/sendMessage" \
        -d "chat_id=${INFRA_CHAT}" \
        -d "text=${MSG}" \
        -d "parse_mode=HTML" > /dev/null
    echo "[ALERT SENT] ${#ALERTS[@]} échecs détectés"
    exit 1
fi
echo "[OK] Tous les checks passent ($(date -u "+%H:%M UTC"))"
exit 0
