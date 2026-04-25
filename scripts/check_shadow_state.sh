#!/usr/bin/env bash
# Diag rapide état Phase 4 shadow log post-deploy.
# Usage : bash scripts/check_shadow_state.sh

set -u
KEY="C:/Users/xav91/Scalping/scalping/scalping-key.pem"
HOST="ec2-user@100.103.107.75"

echo "=== git revision EC2 ==="
ssh -o StrictHostKeyChecking=no -i "$KEY" "$HOST" "cd /home/ec2-user/scalping && git log --oneline -3"

echo
echo "=== container ==="
ssh -i "$KEY" "$HOST" "sudo docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}'"

echo
echo "=== shadow_setups DB ==="
ssh -i "$KEY" "$HOST" "sudo docker exec scalping-radar python -c \"
import sqlite3
c = sqlite3.connect('/app/data/trades.db')
print('total:', c.execute('SELECT COUNT(*) FROM shadow_setups').fetchone()[0])
print('by_system:', c.execute('SELECT system_id, COUNT(*) FROM shadow_setups GROUP BY system_id').fetchall())
rows = list(c.execute('SELECT system_id, bar_timestamp, outcome FROM shadow_setups ORDER BY bar_timestamp DESC LIMIT 5'))
print('latest_5:')
for r in rows: print(' ', r)
\""

echo
echo "=== scheduler logs (15 min, shadow/wti only) ==="
ssh -i "$KEY" "$HOST" "sudo journalctl -u scalping --since '15 minutes ago' --no-pager | grep -iE 'shadow|wti|v2_core|v2_wti' | tail -30"

echo
echo "=== scheduler logs (15 min, errors) ==="
ssh -i "$KEY" "$HOST" "sudo journalctl -u scalping --since '15 minutes ago' --no-pager | grep -iE 'error|exception|traceback' | tail -20"
