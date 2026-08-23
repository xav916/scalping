#!/bin/bash
# Enveloppe cron de notify_saturation_risque.py — la logique est en Python,
# dans le conteneur, pour n'avoir qu'une seule couche de citation à surveiller.
#
# ⚠️ Tourne DANS le conteneur : c'est là que vivent MT5_BRIDGE_URL /
# MT5_BRIDGE_LIVE_URL et leurs clés, et le registre des destinations.
#
# `-i` indispensable : sans lui docker exec n'attache pas stdin.
#
# Usage :
#   notify-saturation-risque.sh                      -> alerte si l'admission se ferme
#   DRY_RUN=1 notify-saturation-risque.sh            -> affiche sans envoyer
#   SEUIL_SATURATION_PCT=70 notify-saturation-risque.sh
set -uo pipefail

docker exec -i \
  -e PYTHONPATH=/app \
  -e "DRY_RUN=${DRY_RUN:-0}" \
  -e "SEUIL_SATURATION_PCT=${SEUIL_SATURATION_PCT:-85}" \
  -w /app scalping-radar \
  python /app/scripts/notify_saturation_risque.py
