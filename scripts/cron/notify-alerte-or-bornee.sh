#!/bin/bash
# BUT: prevenir des que la reprise manuelle de l or sur IC Markets a produit assez de donnee (3 ordres ou -2 R)
# PERIODE_MIN: 5
#
# ⛔ Elle ne BLOQUE rien : elle parle. Le garde-fou qui bloque reste
# `pair_pnl_regulator`, qui reprend la main des 5 trades nouveaux.
#
# ⛔ `-w /app` ET `PYTHONPATH=/app` : Python met le repertoire du SCRIPT sur
# `sys.path`, pas le repertoire courant. Sans ca, `import backend` echoue et
# le cron tombe en silence toutes les 5 minutes. Le script porte aussi son
# propre correctif, mais la ceinture reste ici : elle vaut pour toute image.
#
# Le calcul du R vit DANS le conteneur, avec `risk_eur.calculer` et le filtre
# des stops placebos du laboratoire. Le refaire en shell produirait une
# seconde arithmetique du risque : ce qui a fait poser quatre pauses fausses.
set -uo pipefail
exec /usr/bin/docker exec -w /app -e PYTHONPATH=/app scalping-radar \
     python scripts/alerte_or_ic_markets_bornee.py
