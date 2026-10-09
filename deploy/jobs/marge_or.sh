#!/usr/bin/env bash
# Pourquoi l or automatique dort-il ? DIRE la mesure, ne pas desserrer.
#
# ⛔ Pose le 2026-10-09. Xavier a demande pourquoi aucun ordre d or
# automatique ne partait, puis : << tu dois faire avec les 2 trades en cours >>.
# Rien n etait casse : l interrupteur etait arme, les signaux sortaient, les
# portes faisaient leur tri. Le compte ne pouvait simplement pas porter une
# position de plus -- une position d or a 0,01 lot coute ~186,75 EUR de marge,
# et notre plancher exige 30 % de l equite libre APRES l ordre. Avec deux
# positions a la main, il faudrait 800 EUR d equite ; le compte en a 524.
#
# 🔑 ET LE COURTIER, LUI, ACCEPTAIT : `/order_check` rendait `retcode 0`,
# commentaire << Done >>. Le refus venait de NOTRE plancher. Un refus
# parfaitement justifie, parfaitement invisible -- il fallait une MESURE a
# lire, pas une porte a desserrer.
#
# Mode EVENEMENT : muet quand l or peut passer. La cle de dedup porte
# l IDENTITE du blocage, donc il parle quand le blocage CHANGE et non a chaque
# passage (les positions tournent toutes les quelques minutes, et une alerte
# repetee n est plus lue -- les 8 doublons du 07/10).
#
# 🔑 Par docker cp + docker exec : AUCUN rebuild, donc REM-002 reste arme. Un
# rebuild pour installer un veilleur desarmerait l execution qu il surveille,
# et c est exactement ce qui a coute six heures de marche le 07/10.
set -uo pipefail
docker cp /opt/scalping/jobs/veilleur_marge_or.py \
  scalping-radar:/app/scripts/veilleur_marge_or.py >/dev/null
docker exec -w /app -e PYTHONPATH=/app scalping-radar \
  python /app/scripts/veilleur_marge_or.py "$@" \
  >> /var/log/scalping/marge_or.log 2>&1
