#!/usr/bin/env bash
# Rappel UNIQUE : reprendre la veille des canaux, samedi 2026-10-03 a 20h Paris.
# Se desarme lui-meme apres envoi.
set -euo pipefail
docker cp /opt/scalping/jobs/rappel_veille.py scalping-radar:/tmp/rv.py
docker exec -w /app -e PYTHONPATH=/app scalping-radar python /tmp/rv.py \
  >> /var/log/scalping/rappel_veille.log 2>&1
crontab -l | grep -v rappel_veille | crontab -
echo "$(date -u +%FT%TZ) envoye et desarme" >> /var/log/scalping/rappel_veille.log
