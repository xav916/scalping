#!/bin/bash
# Enveloppe cron de purge_file_ea.py — la logique est en Python, dans le
# conteneur, pour n'avoir qu'une seule couche de citation à surveiller.
#
# `-i` indispensable : sans lui docker exec n'attache pas stdin.
#
# Usage :
#   purge-file-ea.sh            -> périme les ordres EA au TTL dépassé
#   DRY_RUN=1 purge-file-ea.sh  -> compte sans rien changer
set -uo pipefail

docker exec -i \
  -e PYTHONPATH=/app \
  -e "DRY_RUN=${DRY_RUN:-0}" \
  -w /app scalping-radar \
  python /app/scripts/purge_file_ea.py
