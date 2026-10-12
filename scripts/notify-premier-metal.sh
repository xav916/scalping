#!/bin/bash
# BUT: alerte quand AUCUN ordre metal n'est parti depuis 24 h, et dit qui bloque
# PERIODE_MIN: 15
# Enveloppe cron de notify_premier_metal.py — la logique est en Python, dans
# le conteneur, pour n'avoir qu'une seule couche de citation à surveiller.
#
# ⚠️ Tourne DANS le conteneur : c'est là que vivent MT5_BRIDGE_URL /
# MT5_BRIDGE_LIVE_URL, leurs clés, le registre des destinations et trades.db.
#
# `-i` indispensable : sans lui docker exec n'attache pas stdin.
#
# ⛔ L'ANNONCE << Ordre metal PARTI >> A ETE RETIREE le 2026-10-12, a la
# demande de Xavier : << quelle est la valeur ajoutee de recevoir ce genre de
# message ? >>. Aucune -- il recoit deja un message d'OUVERTURE DE TRADE
# complet, avec les memes champs. Il ne reste que le DIGEST DE SILENCE, qui
# lui sert : il alerte quand rien ne part et nomme les portes qui bloquent.
#
# Usage :
#   notify-premier-metal.sh                    -> digest de silence seul
#   DRY_RUN=1 notify-premier-metal.sh          -> affiche, n'envoie ni n'avance
#   PREMIER_METAL_SILENCE_SEC=3600 ...         -> digest de silence plus court
set -uo pipefail

docker exec -i \
  -e PYTHONPATH=/app \
  -e "DRY_RUN=${DRY_RUN:-0}" \
  -e "PREMIER_METAL_SILENCE_SEC=${PREMIER_METAL_SILENCE_SEC:-86400}" \
  -w /app scalping-radar \
  python /app/scripts/notify_premier_metal.py
