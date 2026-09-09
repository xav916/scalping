#!/bin/bash
# BUT: mesure si les echelles M15/M30 produisent des signaux OR en journee
# PERIODE_MIN: 1440
# Lanceur cron du bilan « echelles agregees sur l'or ».
#
# ⛔ Ce lanceur ne decide de rien, il appelle. Le jour mesure, le verdict et le
# canal vivent dans le script Python — un fichier de cron se copie, s'edite,
# se duplique en .bak, et cron.d charge les .bak.
#
# Passage unique a 20:10 UTC : apres la seance de jour, avant la fenetre
# nocturne ou la porte de spread refuse deja l'or.
set -uo pipefail
docker exec scalping-radar python /app/scripts/mesurer_echelles_or.py
