#!/usr/bin/env bash
# Envoi UNIQUE du verdict du banc WTI, dimanche 2026-10-04 a 19h Paris.
# Se desarme lui-meme apres envoi pour ne pas repartir chaque dimanche.
set -euo pipefail
docker cp /opt/scalping/jobs/envoi_banc_wti.py scalping-radar:/tmp/e.py
docker exec -w /app -e PYTHONPATH=/app scalping-radar python /tmp/e.py \
  >> /var/log/scalping/envoi_banc_wti.log 2>&1
crontab -l | grep -v envoi_banc_wti | crontab -
echo "$(date -u +%FT%TZ) envoye et desarme" >> /var/log/scalping/envoi_banc_wti.log
