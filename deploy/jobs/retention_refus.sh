#!/usr/bin/env bash
# Retention de `signal_rejections` : AGREGER avant de supprimer.
#
# 🔑 MESURE DU 2026-10-09 : trades.db = 1 115 Mo, dont 517 Mo pour
# `signal_rejections` seule (2 837 523 lignes, ~100 000/jour). Et le cycle
# rapide sur l or multiplie les refus d or par ~36.
#
# ⛔ ON N EFFACE PAS, ON ROULE. La purge du calendrier economique tombait a
# chaque redemarrage et LE PASSE D AVANT LE 27/09 RESTE PERDU. Toutes les
# analyses de ce depot lisent des COMPTES PAR MOTIF, jamais les lignes
# individuelles : on agrege par (jour, paire, sens, destination, motif) PUIS on
# supprime. L histoire est gardee pour toujours, a ~1/1000 du volume.
#
# 🔑 Par docker cp + docker exec : AUCUN rebuild, donc REM-002 reste arme. Un
# rebuild pour installer ceci desarmerait l execution que Xavier vient d armer,
# et c est ce qui a coute six heures de marche le 07/10.
#
# ⚠️ Une fois par jour a 02h30 UTC : apres la bascule du plafond journalier
# (00h00) et hors des heures ou le spread de l or est cher. La suppression se
# fait jour par jour, chacun dans SA transaction, pour ne pas verrouiller la
# base pendant que la production ecrit dedans.
set -uo pipefail
docker cp /opt/scalping/jobs/retention_refus.py \
  scalping-radar:/app/scripts/retention_refus.py >/dev/null
docker exec -w /app -e PYTHONPATH=/app scalping-radar \
  python /app/scripts/retention_refus.py "$@" \
  >> /var/log/scalping/retention_refus.log 2>&1
