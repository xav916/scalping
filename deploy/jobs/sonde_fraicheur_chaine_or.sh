#!/usr/bin/env bash
# La chaine de l'or produit-elle encore de la DONNEE FRAICHE ?
#
# ⛔ POSEE LE 2026-10-25, apres CINQ pannes silencieuses trouvees le meme jour :
# magasin a "tranches lues : 0" sans erreur, passage PENDU 29 h sans timeout,
# `flock -n` qui faisait sauter les suivants sans une ligne, reconciliation
# morte depuis le 21/08 derriere un rapport hebdomadaire d'apparence normale,
# et l'EC2 deconnecte du tailnet (plus aucune route vers le pont, 9 jours).
#
# 🔑 CE QUI NE PROUVE RIEN, et que j'ai verifie toute la journee : un cron
# arme, un script present, un conteneur "Up 11 days". La SEULE preuve qu'une
# chaine fonctionne, c'est de la donnee RECENTE.
#
# ⚠️ Cadence 15 min, mais l'alerte NE SE REPETE PAS : elle ne reparle que si la
# liste des echecs change, ou apres 6 h. Une sonde qui repete s'apprend a
# s'ignorer (mesure du 04/09), et le retour a la normale est annonce aussi --
# sans quoi on ne sait jamais si le silence veut dire "repare" ou "la sonde est
# morte elle aussi".
#
# 🔑 Par docker cp + docker exec : AUCUN rebuild, donc REM-002 reste arme.
set -uo pipefail
docker cp /opt/scalping/jobs/sonde_fraicheur_chaine_or.py \
  scalping-radar:/app/scripts/sonde_fraicheur_chaine_or.py >/dev/null
docker exec -w /app -e PYTHONPATH=/app scalping-radar \
  python /app/scripts/sonde_fraicheur_chaine_or.py "$@" \
  >> /var/log/scalping/sonde_fraicheur_chaine_or.log 2>&1
