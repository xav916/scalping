#!/bin/bash
# Backup quotidien des SQLite vers S3.
# Usage : ajouter au cron de l'EC2 :
#   0 23 * * * /opt/scalping/scalping/deploy/backup-s3.sh >> /var/log/scalping-backup.log 2>&1
#
# Pre-requis :
#   - aws cli installe (sudo dnf install awscli)
#   - bucket S3 cree (ex: s3://scalping-backups-xav)
#   - role IAM EC2 avec permission s3:PutObject sur ce bucket
#   - variable S3_BUCKET ci-dessous a personnaliser

set -euo pipefail

S3_BUCKET="${S3_BUCKET:-scalping-backups-xav}"
DATA_DIR="/opt/scalping/data"
TIMESTAMP=$(date -u +%Y%m%d-%H%M%S)

if [ ! -d "$DATA_DIR" ]; then
    echo "[$(date)] DATA_DIR $DATA_DIR introuvable, abort"
    exit 1
fi

for db in trades.db backtest.db; do
    if [ -f "$DATA_DIR/$db" ]; then
        echo "[$(date)] Upload $db -> s3://$S3_BUCKET/$TIMESTAMP/$db"
        aws s3 cp "$DATA_DIR/$db" "s3://$S3_BUCKET/$TIMESTAMP/$db" --no-progress
    fi
done

# Garder seulement les 30 derniers backups (lifecycle automatique recommande sur le bucket)
echo "[$(date)] Backup OK"
