#!/bin/bash
# BUT: verifie que la sortie sur le temps observe vraiment
# PERIODE_MIN: 1440
# Sonde de sante QUOTIDIENNE de la sortie sur le temps — [DEMO PEPPERSTONE].
#
# ⛔ Elle ne surveille pas « est-ce que ca tourne » mais les TROIS facons dont
# cette mesure meurt sans bruit :
#   1. la regle ne passe plus, et le silence se lit « rien a observer » ;
#   2. les observations ne se resolvent jamais (la jointure a deja casse le
#      06/09 : `mt5_ticket` et non `ticket`) ;
#   3. ⛔ la portee a derive vers un compte REEL, ou le mode observation est
#      tombe — la regle fermerait alors de l'argent reel.
#
# ⚠️ Elle parle TOUS LES JOURS, contrairement aux autres sondes de ce projet.
# C'est voulu : la mesure prend des semaines, et un compteur de progression est
# ce qui rend l'attente lisible plutot que subie. Mais les ALERTES sont
# separees des INFOS, et seules les premieres appellent une action.
set -uo pipefail

TOKEN="shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg"
CANAL="infra"

RAPPORT=$(docker exec scalping-radar python -c "
import asyncio, json, httpx
from backend.services import sortie_sur_le_temps as st
from backend.services.bridge_destinations import _admin_legacy_destination

async def main():
    positions = []
    d = _admin_legacy_destination()
    if d is not None:
        try:
            async with httpx.AsyncClient(timeout=12.0) as c:
                r = await c.get(d.bridge_url.rstrip('/') + '/positions',
                                headers={'X-API-Key': d.bridge_api_key})
                positions = r.json().get('positions') or []
        except Exception as e:
            # ⛔ Bridge injoignable : on le DIT. Une liste vide ferait conclure
            # « aucune position eligible », donc « tout va bien ».
            print(json.dumps({'ok': False, 'alertes': ['BRIDGE DEMO INJOIGNABLE : ' + str(e)],
                              'infos': ['sante non evaluable'], 'reglages': {}}, ensure_ascii=False))
            return
    st.resoudre_observations()
    print(json.dumps(st.sante(positions_ouvertes=positions), ensure_ascii=False, indent=1))
asyncio.run(main())
" 2>/dev/null)

if [ -z "$RAPPORT" ]; then
  echo "❌ aucun rapport — la sonde elle-meme est muette"
  if [ "${DRY_RUN:-0}" != "1" ]; then
    curl -sS -m 5 -X POST "https://app.scalping-radar.online/api/admin/notify-infra-telegram?token=${TOKEN}&channel=${CANAL}" \
      -H 'Content-Type: application/json' \
      --data '{"title":"🚨 Sonde sortie-sur-le-temps MUETTE","body":"docker exec n a rien renvoye — la mesure du demo n est plus surveillee.","dedup_key":"sante_sortie_temps_morte","cooldown_seconds":21600}' \
      -o /dev/null || true
  fi
  exit 1
fi

echo "$RAPPORT"

PAYLOAD=$(echo "$RAPPORT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
al = d.get('alertes') or []
inf = d.get('infos') or []
titre = ('🚨 Sortie sur le temps — ANOMALIE' if al
         else '📏 Sortie sur le temps (démo) — mesure en cours')
corps = ''
if al:
    corps += '⛔ À CORRIGER :\n' + '\n'.join('• ' + a for a in al) + '\n\n'
corps += '\n'.join('• ' + i for i in inf)
r = d.get('reglages') or {}
if r:
    corps += (f\"\n\nRéglages : seuil {r.get('heures')} h · \"
              f\"{'OBSERVATION' if r.get('observer') else 'ACTIF'} · \"
              f\"{','.join(r.get('destinations') or [])}\")
print(json.dumps({'title': titre, 'body': corps,
                  'dedup_key': 'sante_sortie_temps',
                  'cooldown_seconds': 3600}, ensure_ascii=False))
")

if [ "${DRY_RUN:-0}" = "1" ]; then
  echo "--- DRY_RUN ---"; echo "$PAYLOAD"; exit 0
fi
curl -sS -m 8 -X POST "https://app.scalping-radar.online/api/admin/notify-infra-telegram?token=${TOKEN}&channel=${CANAL}" \
  -H 'Content-Type: application/json' --data "$PAYLOAD" \
  -o /dev/null -w 'notify HTTP %{http_code}\n' || true
