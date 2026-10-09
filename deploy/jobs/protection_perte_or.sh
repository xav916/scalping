#!/usr/bin/env bash
# Protection des pertes : resserrer le stop d un trade durablement negatif.
#
# Regle dictee par Xavier le 2026-10-09 : laisser le trade evoluer 5 min, et
# s il est negatif depuis la MOITIE de la fourchette (2 min 30), poser le stop
# au POINT MILIEU entre le stop actuel et le cours. Son exemple : SL 20 EUR,
# perte 5 EUR => (20+5)/2 = 12,50 EUR.
#
# ⚠️ PLANCHER DE 2 EUR, decide par Xavier APRES mesure de la convergence : sans
# lui la formule colle le stop au prix en ~25 min (marge residuelle 0,47 EUR
# contre ~0,25 EUR d oscillation normale), et le trade sortirait au BRUIT.
#
# ⛔ DESARMEE par defaut (fail-closed). L armement se fait par la CRONTAB :
#     */5 * * * * PROTECTION_PERTE_OR=1 /opt/scalping/jobs/protection_perte_or.sh
#
# 🔑 ET L ARMEMENT PASSE PAR `docker exec -e`, PAS PAR L ENVIRONNEMENT DU
# CONTENEUR. Ajouter une variable dans /opt/scalping/.env imposerait un
# redemarrage ET pourrait faire basculer `configuration_drift` de REM-002, donc
# DESARMER l execution que Xavier vient d armer. Ici la variable ne vit que le
# temps du processus, et l armement reste VISIBLE dans la crontab -- auditable.
#
# 🔑 Elle LIT l histoire tenue par `sonde_echelle_or.py` (`negatif_depuis`) : si
# la sonde ne tourne pas, la duree est inconnue et la regle S ABSTIENT.
#
# 🔑 Par docker cp + docker exec : AUCUN rebuild, donc REM-002 reste arme.
set -uo pipefail
docker cp /opt/scalping/jobs/protection_perte_or.py \
  scalping-radar:/app/scripts/protection_perte_or.py >/dev/null
docker exec -w /app -e PYTHONPATH=/app \
  -e PROTECTION_PERTE_OR="${PROTECTION_PERTE_OR:-0}" \
  -e PROTECTION_PERTE_MARGE_MIN_EUR="${PROTECTION_PERTE_MARGE_MIN_EUR:-2.0}" \
  scalping-radar \
  python /app/scripts/protection_perte_or.py "$@" \
  >> /var/log/scalping/protection_perte_or.log 2>&1
