#!/usr/bin/env bash
# Sonde horaire du calendrier. Posee le 2026-10-04 a la demande de Xavier.
# Repond a UNE question : ForexFactory nous donne-t-il un jour le chiffre
# PUBLIE ? Sans lui, la surprise (reel - prevision) est incalculable.
# Mode EVENEMENT : muette tant qu'aucun `actual` n'apparait.
# 🔑 Par docker exec depuis l'hote : AUCUN rebuild, donc REM-002 reste arme.
set -euo pipefail
docker cp /opt/scalping/jobs/sonde_calendrier.py scalping-radar:/tmp/sonde_cal.py >/dev/null
docker exec -w /app -e PYTHONPATH=/app scalping-radar \
  python /tmp/sonde_cal.py "$@" >> /var/log/scalping/sonde_calendrier.log 2>&1
