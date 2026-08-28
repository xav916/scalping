#!/bin/bash
# Enveloppe cron de fermer_metaux_avant_weekend.py.
#
# ⚠️ Tourne DANS le conteneur : c'est la que vivent MT5_BRIDGE_URL /
# MT5_BRIDGE_LIVE_URL, leurs cles et le registre des destinations.
#
# `-i` indispensable : sans lui docker exec n'attache pas stdin. Une
# verification lancee sans lui n'affiche RIEN, ni erreur ni resultat.
#
# ATTENTION : ce script FERME des positions reelles. Le garde-fou du jour et
# de l'heure vit dans le PYTHON, pas ici — un fichier de cron se copie et
# `cron.d` charge meme les `.bak`. L'heure du cron n'est qu'un declencheur,
# jamais l'autorisation.
#
# Usage :
#   fermer-metaux-avant-weekend.sh              -> ferme si vendredi 20:00-20:59
#   DRY_RUN=1 fermer-metaux-avant-weekend.sh    -> affiche, ne ferme rien
#   FORCER=1 fermer-metaux-avant-weekend.sh     -> hors fenetre, et le DIT
set -uo pipefail

docker exec -i \
  -e PYTHONPATH=/app \
  -e "DRY_RUN=${DRY_RUN:-0}" \
  -e "FORCER=${FORCER:-0}" \
  -e "FERMETURE_METAUX_DESTINATIONS=${FERMETURE_METAUX_DESTINATIONS:-admin_legacy,admin_live}" \
  -w /app scalping-radar \
  python /app/scripts/fermer_metaux_avant_weekend.py
