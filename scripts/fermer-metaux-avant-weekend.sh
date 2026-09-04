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
#   fermer-metaux-avant-weekend.sh              -> ferme ce qui a franchi 1/3
#   DRY_RUN=1 fermer-metaux-avant-weekend.sh    -> affiche, ne ferme rien
#   FORCER=1 fermer-metaux-avant-weekend.sh     -> hors fenetre, et le DIT
#   BILAN=1 fermer-metaux-avant-weekend.sh      -> parle meme sans fermeture
set -uo pipefail

# ⛔ TOUTE variable posee par le cron doit etre transmise EXPLICITEMENT :
# `docker exec` n'herite PAS de l'environnement de l'appelant. `BILAN=1` pose
# dans la crontab sans la ligne ci-dessous aurait produit un passage de bilan
# MUET — et personne n'aurait su ce qui traversait le week-end. Le defaut a ete
# vu le 04/09 avant sa premiere execution, pas apres.
docker exec -i \
  -e PYTHONPATH=/app \
  -e "DRY_RUN=${DRY_RUN:-0}" \
  -e "FORCER=${FORCER:-0}" \
  -e "BILAN=${BILAN:-0}" \
  -e "FERMETURE_METAUX_DESTINATIONS=${FERMETURE_METAUX_DESTINATIONS:-admin_legacy,admin_live}" \
  -e "FERMETURE_METAUX_DEBUT_MIN=${FERMETURE_METAUX_DEBUT_MIN:-720}" \
  -e "FERMETURE_METAUX_FIN_MIN=${FERMETURE_METAUX_FIN_MIN:-1257}" \
  -e "FERMETURE_WEEKEND_AVANCEMENT_MIN=${FERMETURE_WEEKEND_AVANCEMENT_MIN:-0.3333333333}" \
  -w /app scalping-radar \
  python /app/scripts/fermer_metaux_avant_weekend.py
