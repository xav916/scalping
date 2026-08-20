#!/bin/bash
# Enveloppe cron de notify_ibkr_etat.py — la logique est en Python, dans le
# conteneur, pour n'avoir qu'une seule couche de citation à surveiller.
#
# `-i` indispensable : sans lui docker exec n'attache pas stdin.
#
# Usage :
#   notify-ibkr-etat.sh             -> signale les mouvements de position
#   DIGEST=1 notify-ibkr-etat.sh    -> état complet, même sans mouvement
#   DRY_RUN=1 notify-ibkr-etat.sh   -> affiche sans envoyer
set -uo pipefail

docker exec -i \
  -e PYTHONPATH=/app \
  -e "DRY_RUN=${DRY_RUN:-0}" \
  -e "DIGEST=${DIGEST:-0}" \
  -w /app scalping-radar \
  python /app/scripts/notify_ibkr_etat.py
