#!/bin/bash
# BUT: verifie que l'horizon des essais se remplit
# PERIODE_MIN: 60
# Enveloppe cron de notify_horizon_rempli.py — la logique est en Python, dans le
# conteneur, pour n'avoir qu'une seule couche de citation.
#
# ⚠️ Tourne DANS le conteneur : `/app/data/trades.db` y est le bind mount de
# `/opt/scalping/data/`, donc l'état de la sonde survit aux reconstructions
# d'image (contrairement à tout ce qui vivrait dans la couche applicative).
#
# Usage :
#   notify-horizon-rempli.sh                  -> surveille
#   DRY_RUN=1 notify-horizon-rempli.sh        -> juge et affiche, n'envoie RIEN
#                                                et n'écrit RIEN
#   FENETRE_H=72 notify-horizon-rempli.sh     -> élargit la fenêtre de lecture
set -uo pipefail

docker exec -i \
  -e PYTHONPATH=/app \
  -e "DRY_RUN=${DRY_RUN:-0}" \
  -e "FENETRE_H=${FENETRE_H:-24}" \
  -e "ESSAI_SLUG=${ESSAI_SLUG:-or-4h-2026-08-26}" \
  -w /app scalping-radar \
  python /app/scripts/notify_horizon_rempli.py
