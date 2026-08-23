#!/bin/bash
# Enveloppe cron de notify_divergence_univers.py — la logique est en Python,
# dans le conteneur, pour n'avoir qu'une seule couche de citation à surveiller.
#
# `-i` indispensable : sans lui docker exec n'attache pas stdin.
#
# Usage :
#   notify-divergence-univers.sh            -> alerte si l'univers diverge
#   DRY_RUN=1 notify-divergence-univers.sh  -> affiche sans envoyer
set -uo pipefail

docker exec -i \
  -e PYTHONPATH=/app \
  -e "DRY_RUN=${DRY_RUN:-0}" \
  -w /app scalping-radar \
  python /app/scripts/notify_divergence_univers.py
