#!/bin/bash
# BUT: verifie que le bridge retient le stop REELLEMENT porte a la cloture
# PERIODE_MIN: 15
# Enveloppe cron de notify_capture_niveaux.py — la logique est en Python, dans
# le conteneur, pour n'avoir qu'une seule couche de citation.
#
# ⚠️ Tourne DANS le conteneur : `/app/data/trades.db` y est le bind mount de
# `/opt/scalping/data/`, donc l'etat de la sonde survit aux reconstructions
# d'image (contrairement a tout ce qui vivrait dans la couche applicative).
#
# Usage :
#   notify-capture-niveaux.sh                      -> surveille
#   DRY_RUN=1 notify-capture-niveaux.sh            -> affiche sans envoyer
#   DEPUIS=<iso> notify-capture-niveaux.sh         -> rejuge une fenetre,
#                                                     SANS toucher au curseur
set -uo pipefail

docker exec -i \
  -e PYTHONPATH=/app \
  -e "DRY_RUN=${DRY_RUN:-0}" \
  -e "GRACE_MIN=${GRACE_MIN:-20}" \
  -e "DEPUIS=${DEPUIS:-}" \
  -w /app scalping-radar \
  python /app/scripts/notify_capture_niveaux.py
