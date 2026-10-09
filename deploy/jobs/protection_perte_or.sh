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
# ⛔ DESARMEE par defaut : il faut PROTECTION_PERTE_OR=1 dans l environnement
# du conteneur. Fail-closed, comme toute regle qui touche un stop reel.
#
# 🔑 Elle LIT l histoire tenue par `sonde_echelle_or.py` (negatif_depuis) : si
# la sonde ne tourne pas, la duree est inconnue et la regle S ABSTIENT.
#
# 🔑 Par docker cp + docker exec : AUCUN rebuild, donc REM-002 reste arme.
set -uo pipefail
docker cp /opt/scalping/jobs/protection_perte_or.py \
  scalping-radar:/app/scripts/protection_perte_or.py >/dev/null
docker exec -w /app -e PYTHONPATH=/app scalping-radar \
  python /app/scripts/protection_perte_or.py "$@" \
  >> /var/log/scalping/protection_perte_or.log 2>&1
