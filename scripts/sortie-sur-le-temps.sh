#!/bin/bash
# BUT: observe la sortie sur le temps, desarmee, sur le demo
# PERIODE_MIN: 30
# Sortie sur le temps — DEMO PEPPERSTONE uniquement, en OBSERVATION.
#
# ⛔ Deux mesures pointent en sens opposes, et la plus lourde dit NON :
#     porte de duree 16 h, 13/08 : n=5690  Δ=-0,151 R  t=-6,83
#     sorties manuelles, 06/09   : n=  21  Δ=+0,660 R  t=+2,27
#
# Ce lanceur ne ferme donc RIEN par defaut : il journalise ce que la regle
# aurait ferme. C'est le seul usage que les donnees autorisent aujourd'hui.
set -uo pipefail
docker exec scalping-radar python -c "
import asyncio, json, os
import httpx
from backend.services import sortie_sur_le_temps as st
from backend.services.bridge_destinations import _admin_legacy_destination

cfg = st.reglages()
d = _admin_legacy_destination()
if d is None:
    print(json.dumps({'erreur': 'destination demo non configuree'})); raise SystemExit(0)

async def main():
    async with httpx.AsyncClient(timeout=12.0) as c:
        r = await c.get(d.bridge_url.rstrip('/') + '/positions',
                        headers={'X-API-Key': d.bridge_api_key})
        positions = r.json().get('positions') or []
    # ⚠️ Le bridge MT5 nomme le champ 'time', pas 'fill_time'.
    rap = st.passer(positions, 'admin_legacy', fermer=None, cfg=cfg)
    rap['positions_lues'] = len(positions)
    # Le rejeu APPARIE : on renseigne le R reellement obtenu des que la
    # position s'est fermee, puis on compare sur les MEMES trades.
    rap['resolues'] = st.resoudre_observations()
    rap['bilan_apparie'] = st.bilan_apparie('admin_legacy')
    print(json.dumps(rap, ensure_ascii=False, indent=1))
asyncio.run(main())
"
