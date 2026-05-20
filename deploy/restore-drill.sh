#!/bin/bash
# Smoke test du backup S3 : download dernier backup + PRAGMA integrity_check sur chaque DB.
# Usage manuel : sudo bash /opt/scalping/scalping/deploy/restore-drill.sh
# Sortie : 0 si toutes les DBs sont OK, 1 sinon.

set -euo pipefail

S3_BUCKET="${S3_BUCKET:-scalping-backups-xav}"
TMP_DIR="$(mktemp -d /tmp/scalping-restore-drill.XXXXXX)"
trap 'rm -rf "$TMP_DIR"' EXIT

echo "[$(date -u +'%F %T UTC')] Restore drill on s3://$S3_BUCKET/"

LATEST_PREFIX="$(aws s3 ls "s3://$S3_BUCKET/" | grep 'PRE ' | awk '{print $2}' | sort | tail -1 | tr -d '/')"
if [ -z "$LATEST_PREFIX" ]; then
    echo "FAIL: no backup found in s3://$S3_BUCKET/"
    exit 1
fi
echo "  latest prefix: $LATEST_PREFIX"

aws s3 sync "s3://$S3_BUCKET/$LATEST_PREFIX/" "$TMP_DIR/" --quiet

RESULT=0
for db in "$TMP_DIR"/*.db; do
    [ -f "$db" ] || continue
    name="$(basename "$db")"
    size="$(stat -c%s "$db" 2>/dev/null || stat -f%z "$db")"
    integrity="$(sqlite3 "$db" "PRAGMA integrity_check;" 2>&1 | head -1)"
    if [ "$integrity" = "ok" ]; then
        echo "  OK   $name (${size} bytes, integrity=ok)"
    else
        echo "  FAIL $name (${size} bytes, integrity=$integrity)"
        RESULT=1
    fi
done

if [ "$RESULT" -eq 0 ]; then
    echo "[$(date -u +'%F %T UTC')] Drill PASSED for $LATEST_PREFIX"
else
    echo "[$(date -u +'%F %T UTC')] Drill FAILED for $LATEST_PREFIX"
fi
exit "$RESULT"
