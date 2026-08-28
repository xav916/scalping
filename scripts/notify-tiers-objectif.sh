#!/bin/bash
# Enveloppe cron de notify_tiers_objectif.py — la logique est en Python, dans
# le conteneur, pour n'avoir qu'une seule couche de citation a surveiller.
#
# ⚠️ Tourne DANS le conteneur : c'est la que vivent MT5_BRIDGE_LIVE_URL, sa
# cle et le registre des destinations.
#
# `-i` indispensable : sans lui docker exec n'attache pas stdin. Une
# verification lancee sans lui n'a rien affiche du tout, ni erreur ni
# resultat — un silence qui ressemblait a « tout va bien ».
#
# Usage :
#   notify-tiers-objectif.sh                       -> alerte au franchissement
#   DRY_RUN=1 notify-tiers-objectif.sh             -> affiche, n'envoie rien
#   TIERS_OBJECTIF_FRACTION=0.5 ...                -> la moitie au lieu du tiers
set -uo pipefail

docker exec -i \
  -e PYTHONPATH=/app \
  -e "DRY_RUN=${DRY_RUN:-0}" \
  -e "TIERS_OBJECTIF_FRACTION=${TIERS_OBJECTIF_FRACTION:-0.3333333}" \
  -e "TIERS_OBJECTIF_DESTINATION=${TIERS_OBJECTIF_DESTINATION:-admin_live}" \
  -w /app scalping-radar \
  python /app/scripts/notify_tiers_objectif.py
