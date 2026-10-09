#!/usr/bin/env bash
# Sondes P0 : detecter, ouvrir un ticket, REPARER, prouver, DIRE.
#
# Demande de Xavier le 2026-10-09 : des sondes sur les deux regles de gestion
# des SL et sur l ouverture de trades, avec analyse complete automatique,
# resolution sans intervention humaine, et un message Telegram a l ouverture du
# ticket d anomalie puis a sa resolution.
#
# 🔑 CE QUI EST TENABLE : reparer une ACTION QUI N A PAS ABOUTI -- stop non
# deplace, ordre non parti, sonde arretee, regle desarmee. On REEMET l action
# decidee, puis on PROUVE qu elle a pris effet.
#
# ⛔ PAS TENABLE : reparer un DEFAUT DE CODE. Le defaut du 09/10 (une validation
# qui se contredisait) demandait d ecrire du code, et le deployer desarme
# REM-002. Ces anomalies ESCALADENT avec leur diagnostic complet.
#
# ⛔ ET AUCUNE REMEDIATION NE DESSERRE UNE PORTE. Un test lit le catalogue
# entier pour l epingler.
#
# ⚠️ Toutes les 5 min, decale de 2 min apres la regle de protection : on laisse
# les deux regles agir AVANT de juger qu elles n ont pas agi.
#
# 🔑 Par docker cp + docker exec : AUCUN rebuild, donc REM-002 reste arme.
set -uo pipefail
docker cp /opt/scalping/jobs/sondes_p0.py \
  scalping-radar:/app/scripts/sondes_p0.py >/dev/null
docker exec -w /app -e PYTHONPATH=/app \
  -e PROTECTION_PERTE_OR="${PROTECTION_PERTE_OR:-0}" \
  scalping-radar \
  python /app/scripts/sondes_p0.py "$@" \
  >> /var/log/scalping/sondes_p0.log 2>&1
