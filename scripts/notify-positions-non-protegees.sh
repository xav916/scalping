#!/bin/bash
# BUT: detecte les positions ouvertes SANS stop
# PERIODE_MIN: 2
# Enveloppe cron de notify_positions_non_protegees.py — toute la logique est en
# Python, dans le conteneur, pour n'avoir qu'une seule couche de citation à
# surveiller (même parti pris que notify-position-fermee.sh).
#
# `-i` indispensable : sans lui docker exec n'attache pas stdin.
#
# Usage :
#   notify-positions-non-protegees.sh            -> vérifie + alerte
#   DRY_RUN=1 notify-positions-non-protegees.sh  -> affiche sans alerter
set -uo pipefail

docker exec -i \
  -e PYTHONPATH=/app \
  -e "DRY_RUN=${DRY_RUN:-0}" \
  -w /app scalping-radar \
  python /app/scripts/notify_positions_non_protegees.py
