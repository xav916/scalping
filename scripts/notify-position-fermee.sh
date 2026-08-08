#!/bin/bash
# Enveloppe cron de notify_position_fermee.py — toute la logique est en Python,
# dans le conteneur, pour n'avoir qu'une seule couche de citation à surveiller.
#
# `-i` indispensable : sans lui docker exec n'attache pas stdin.
#
# Usage :
#   notify-position-fermee.sh            -> verifie + notifie
#   DRY_RUN=1 notify-position-fermee.sh  -> affiche sans notifier
set -uo pipefail

# TICKETS_ACTION_EN_ATTENTE se règle dans la ligne de crontab plutôt que dans
# le .env : il est ainsi visible d'un `crontab -l`, et le rappel qu'il déclenche
# demande lui-même de le vider — donc il ne rouille pas en silence.
docker exec -i \
  -e PYTHONPATH=/app \
  -e "DRY_RUN=${DRY_RUN:-0}" \
  -e "TICKETS_ACTION_EN_ATTENTE=${TICKETS_ACTION_EN_ATTENTE:-}" \
  -w /app scalping-radar \
  python /app/scripts/notify_position_fermee.py
