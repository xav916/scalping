#!/bin/bash
# Enveloppe cron de notify_premier_metal.py — la logique est en Python, dans
# le conteneur, pour n'avoir qu'une seule couche de citation à surveiller.
#
# ⚠️ Tourne DANS le conteneur : c'est là que vivent MT5_BRIDGE_URL /
# MT5_BRIDGE_LIVE_URL, leurs clés, le registre des destinations et trades.db.
#
# `-i` indispensable : sans lui docker exec n'attache pas stdin.
#
# Usage :
#   notify-premier-metal.sh                    -> alerte au premier ordre parti
#   DRY_RUN=1 notify-premier-metal.sh          -> affiche, n'envoie ni n'avance
#   PREMIER_METAL_SILENCE_SEC=3600 ...         -> digest de silence plus court
set -uo pipefail

docker exec -i \
  -e PYTHONPATH=/app \
  -e "DRY_RUN=${DRY_RUN:-0}" \
  -e "PREMIER_METAL_SILENCE_SEC=${PREMIER_METAL_SILENCE_SEC:-86400}" \
  -w /app scalping-radar \
  python /app/scripts/notify_premier_metal.py
