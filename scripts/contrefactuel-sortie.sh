#!/bin/bash
# Contrefactuel de sortie : ce que le SL/TP AURAIT donne sur les trades sortis
# autrement. Balayage en LECTURE — ne ferme rien, ne modifie aucun trade.
#
# ⛔ Il repond a une question que les chiffres bruts ne peuvent pas trancher :
# les sorties automatiques font -0,40 R et les autres +0,42 R, mais on compare
# les trades qu'on a CHOISI de couper a ceux qu'on a CHOISI de laisser. Le biais
# est dans la selection.
set -uo pipefail
docker exec scalping-radar python -c "
import asyncio, json
from backend.services import contrefactuel_sortie as cf
n = cf.balayer()
c = asyncio.run(cf.resoudre())
print(json.dumps({'nouvelles_lignes': n, 'resolutions': c,
                  'bilan_reel': cf.bilan('admin_live'),
                  'bilan_demo': cf.bilan('admin_legacy')},
                 ensure_ascii=False, indent=1))
"
