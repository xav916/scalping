#!/bin/bash
# Lanceur cron de la mesure Kraken vs MT5 hors crypto.
#
# ⛔ Le garde-fou jour+heure vit dans le SCRIPT PYTHON, pas ici : un fichier de
# cron se copie, s'édite, se duplique en .bak — et cron.d charge les .bak.
# Ce lanceur ne décide de rien, il appelle.
#
#   collecte  → un relevé (silencieux hors séance)
#   bilan     → médianes de la journée + envoi Telegram
set -uo pipefail
MODE="${1:---collecte}"
docker exec scalping-radar python /app/scripts/mesurer_spreads_hors_crypto.py "$MODE"
