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
#
# ⛔ Le `:-67` ci-dessous ECRASE l'environnement du conteneur : c'est lui qui
# fait foi pour le cron, pas /opt/scalping/.env. Il doit rester egal au defaut
# de notify_saturation_risque.py, sans quoi le cron et la commande `risque` a
# la demande alerteraient a deux seuils differents. Un test epingle l'egalite.
set -uo pipefail

docker exec -i \
  -e PYTHONPATH=/app \
  -e "DRY_RUN=${DRY_RUN:-0}" \
  -e "SEUIL_SATURATION_PCT=${SEUIL_SATURATION_PCT:-67}" \
  -w /app scalping-radar \
  python /app/scripts/notify_saturation_risque.py
