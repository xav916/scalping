#!/usr/bin/env bash
# Temoin EXTERIEUR de l echelle de stop : rendre verifiable
# << c est passe au-dessus d 1 EUR >>.
#
# ⛔ POSE LE 2026-10-09. Xavier : << Pourquoi les SL n ont pas evolue car les
# trades sont passes au-dela d 1 EUR >>. Je n ai PAS PU REPONDRE : quand
# l echelle decide de ne rien faire, elle ne journalise RIEN -- zero ligne en
# 30 minutes. Sa question restait un DESACCORD au lieu d etre une MESURE.
#
# 🔑 UN TEMOIN EXTERIEUR, ET NON UN JOURNAL DE L ECHELLE : une echelle qui rend
# compte d elle-meme ne peut pas prouver qu elle n a rien rate. Cette sonde
# echantillonne plus VITE qu elle (5 s contre 15 s) et conserve le MAXIMUM vu.
#
# ⚠️ Chaque invocation boucle ~55 s, donc un cron a la minute donne une
# couverture CONTINUE a 5 s de pas -- plus fin que l echelle elle-meme.
#
# 🔑 Par docker cp + docker exec : AUCUN rebuild, donc REM-002 reste arme.
set -uo pipefail
docker cp /opt/scalping/jobs/sonde_echelle_or.py \
  scalping-radar:/app/scripts/sonde_echelle_or.py >/dev/null
docker exec -w /app -e PYTHONPATH=/app scalping-radar \
  python /app/scripts/sonde_echelle_or.py "$@" \
  >> /var/log/scalping/sonde_echelle_or.log 2>&1
