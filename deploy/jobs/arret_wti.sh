#!/usr/bin/env bash
# Regle d arret du WTI : 10 ordres OU -30 EUR, le premier atteint.
# Posee le 2026-10-05 a la demande de Xavier — le motif de reouverture du 03/10
# disait « AUCUNE regle d arret n est posee ».
# Mode EVENEMENT : muet tant que la borne n est pas atteinte.
# 🔑 Par docker exec depuis l hote : AUCUN rebuild, REM-002 reste arme.
set -euo pipefail
docker cp /opt/scalping/jobs/regle_arret_wti.py scalping-radar:/app/backend/services/regle_arret_wti.py >/dev/null
docker cp /opt/scalping/jobs/veilleur_arret_wti.py scalping-radar:/app/scripts/veilleur_arret_wti.py >/dev/null
docker exec -w /app -e PYTHONPATH=/app scalping-radar \
  python /app/scripts/veilleur_arret_wti.py "$@" >> /var/log/scalping/arret-wti.log 2>&1
