#!/bin/bash
# Backup quotidien des SQLite vers S3 — atomicity SQLite + alert Telegram on fail.
# Usage : ajouter au cron de l'EC2 :
#   0 23 * * * /opt/scalping/scalping/deploy/backup-s3.sh >> /var/log/scalping-backup.log 2>&1
#
# Pre-requis :
#   - aws cli + sqlite3 installes
#   - bucket S3 cree (ex: s3://scalping-backups-xav)
#   - role IAM EC2 avec permission s3:PutObject sur ce bucket
#   - variables INFRA_TELEGRAM_BOT_TOKEN + INFRA_TELEGRAM_CHAT_ID dans /opt/scalping/.env (alerting optionnel)

set -euo pipefail

S3_BUCKET="${S3_BUCKET:-scalping-backups-xav}"
DATA_DIR="/opt/scalping/data"
TMP_DIR="$(mktemp -d /tmp/scalping-backup.XXXXXX)"
TIMESTAMP="$(date -u +%Y%m%d-%H%M%S)"
LOG_PREFIX="[$(date -u +'%Y-%m-%d %H:%M:%S UTC')]"

# Load infra creds for alerting (best-effort, no crash if missing)
if [ -f /opt/scalping/.env ]; then
    set -a
    # shellcheck disable=SC1091
    . /opt/scalping/.env
    set +a
fi

notify_failure() {
    local exit_code=$1
    local line_no=$2
    local msg="Scalping backup FAILED on EC2 (exit=$exit_code line=$line_no ts=$TIMESTAMP)"
    echo "$LOG_PREFIX $msg" >&2
    if [ -n "${INFRA_TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${INFRA_TELEGRAM_CHAT_ID:-}" ]; then
        curl -s -X POST "https://api.telegram.org/bot${INFRA_TELEGRAM_BOT_TOKEN}/sendMessage" \
             --max-time 10 \
             -d "chat_id=${INFRA_TELEGRAM_CHAT_ID}" \
             -d "text=${msg}" > /dev/null || true
    fi
    rm -rf "$TMP_DIR"
}
trap 'notify_failure $? $LINENO' ERR

if [ ! -d "$DATA_DIR" ]; then
    echo "$LOG_PREFIX DATA_DIR $DATA_DIR introuvable, abort"
    exit 1
fi

for db in trades.db backtest.db macro.db; do
    if [ -f "$DATA_DIR/$db" ]; then
        # Atomic SQLite snapshot via .backup (WAL-safe, locks read-only briefly)
        echo "$LOG_PREFIX Snapshot $db (sqlite .backup)"
        sqlite3 "$DATA_DIR/$db" ".backup '$TMP_DIR/$db'"

        echo "$LOG_PREFIX Upload $db -> s3://$S3_BUCKET/$TIMESTAMP/$db"
        aws s3 cp "$TMP_DIR/$db" "s3://$S3_BUCKET/$TIMESTAMP/$db" --no-progress
    fi
done

rm -rf "$TMP_DIR"
echo "$LOG_PREFIX Backup OK ($TIMESTAMP)"
