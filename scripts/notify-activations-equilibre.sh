#!/bin/bash
# Enveloppe cron de notify_activations_equilibre.py — la logique est en
# Python, dans le conteneur, pour n'avoir qu'une seule couche de citation.
#
# ⚠️ Tourne DANS le conteneur : c'est là que vivent MT5_BRIDGE_URL /
# MT5_BRIDGE_LIVE_URL, leurs clés et le registre des destinations.
#
# Usage :
#   notify-activations-equilibre.sh              -> rapporte les activations
#   DRY_RUN=1 notify-activations-equilibre.sh    -> affiche sans envoyer
set -uo pipefail

docker exec -i \
  -e PYTHONPATH=/app \
  -e "DRY_RUN=${DRY_RUN:-0}" \
  -e "N_MIN_JUGEMENT=${N_MIN_JUGEMENT:-30}" \
  -w /app scalping-radar \
  python /app/scripts/notify_activations_equilibre.py
