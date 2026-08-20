#!/bin/bash
# Enveloppe cron de notify_execution_client.py — la logique est en Python,
# dans le conteneur, pour n'avoir qu'une seule couche de citation à surveiller.
#
# `-i` indispensable : sans lui docker exec n'attache pas stdin.
#
# Usage :
#   notify-execution-client.sh              -> alerte les clients sans exécution
#   DRY_RUN=1 notify-execution-client.sh    -> affiche sans envoyer
#   SILENCE_EA_H=6 notify-execution-client.sh
set -uo pipefail

docker exec -i \
  -e PYTHONPATH=/app \
  -e "DRY_RUN=${DRY_RUN:-0}" \
  -e "SILENCE_EA_H=${SILENCE_EA_H:-24}" \
  -e "FENETRE_EXEC_J=${FENETRE_EXEC_J:-7}" \
  -e "SEUIL_FILE=${SEUIL_FILE:-20}" \
  -w /app scalping-radar \
  python /app/scripts/notify_execution_client.py
