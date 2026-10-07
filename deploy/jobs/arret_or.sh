#!/usr/bin/env bash
# Regle d arret de l or : 60 ordres OU -50 EUR d AUTOMATIQUE, le premier atteint.
# Posee le 2026-10-07 — le motif d ouverture de tous les horizons de l or
# (01/10, dc3c067) se terminait par « AUCUNE regle d arret n est posee ».
#
# Mode ALERTE : il previent et chiffre, il ne ferme RIEN de lui-meme. L or a un
# avantage A LA MAIN (+72,34 EUR sur 6 fermetures) et la main ne peut fermer que
# ce que le code OUVRE : le couper supprimerait les deux.
#
# Par docker exec depuis l hote : AUCUN rebuild, REM-002 reste arme.
set -euo pipefail
docker cp /opt/scalping/jobs/regle_arret_or.py scalping-radar:/app/backend/services/regle_arret_or.py >/dev/null
docker cp /opt/scalping/jobs/veilleur_arret_or.py scalping-radar:/app/scripts/veilleur_arret_or.py >/dev/null
docker exec -w /app -e PYTHONPATH=/app scalping-radar \
  python /app/scripts/veilleur_arret_or.py "$@" >> /var/log/scalping/arret-or.log 2>&1
