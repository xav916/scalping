#!/bin/bash
# BUT: compare les deux definitions du gap (FVG standard vs regle de la 3e bougie)
# PERIODE_MIN: 1440
# Lanceur cron du face-a-face des gaps.
#
# ⛔ `docker exec` n'herite PAS de l'environnement de l'hote : sans le relais
# de DRY_RUN, une repetition a blanc posterait un VRAI message. Mesure le 09/09,
# en le faisant, sur la sonde des echelles.
#
# Passage a 06:00 UTC (08h00 Paris) : le laboratoire mesure a 03:40 UTC, ses
# cellules sont donc ecrites depuis plus de deux heures.
set -uo pipefail
docker exec ${DRY_RUN:+-e DRY_RUN=1} scalping-radar \
  python /app/scripts/mesurer_face_a_face_gaps.py
