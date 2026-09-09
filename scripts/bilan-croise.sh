#!/bin/bash
# BUT: bilan de la nuit sur TOUS les instruments mesures, et sa concordance
# PERIODE_MIN: 1440
# Lanceur cron du bilan croise.
#
# ⛔ `PYTHONPATH=/app -w /app` : cette sonde importe `backend.services`, ce que
# les precedentes ne faisaient pas. Sans cela, ModuleNotFoundError — attrape par
# l'essai a blanc AVANT que le cron ne tourne. Meme forme que
# `notify-ordres-reel.sh`, qui importe aussi le paquet.
#
# ⛔ `docker exec` n'herite PAS de l'environnement de l'hote : sans le relais de
# DRY_RUN, une repetition a blanc posterait un VRAI message. Mesure le 09/09, en
# le faisant, sur la sonde des echelles.
#
# Passage a 06:05 UTC (08h05 Paris) : le cycle nocturne demarre a 03:40 et met
# ~8 minutes sur 20 instruments — deux heures de marge.
set -uo pipefail
docker exec -e PYTHONPATH=/app -w /app ${DRY_RUN:+-e DRY_RUN=1} \
  scalping-radar python /app/scripts/mesurer_bilan_croise.py
