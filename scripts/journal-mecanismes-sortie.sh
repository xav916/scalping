#!/bin/bash
# Journal des mecanismes de sortie — lit l'audit des bridges MT5, persiste les
# activations de la soupape d'equilibre, puis attribue les clotures.
#
# ⛔ Pourquoi ce script existe : la soupape ecrivait bien `status="equilibre"`
# dans l'audit du bridge, mais cet audit n'est PAS un journal — il est borne et
# vit sur le VPS. La sonde ecrite le 24/08 pour le lire n'avait AUCUN cron. Une
# activation en 14 jours sur le reel, zero sur le demo : sans persistance, on ne
# pouvait meme pas le savoir.
#
# 🔑 « Un mecanisme qu'on ne peut pas compter est un mecanisme auquel on ne peut
# que croire. »
set -uo pipefail

docker exec scalping-radar python -c "
import asyncio, json, httpx
from backend.services import motif_interne_cloture as mi
from backend.services.bridge_destinations import (_admin_live_destination,
                                                  _admin_legacy_destination)

async def aspirer(d, did):
    # ⛔ On repart du CURSEUR, pas de zero : l'audit compte 4 000 lignes et les
    # relire en entier a chaque passage couterait pour rien.
    since = mi.curseur(did)
    lues, dernier = [], since
    async with httpx.AsyncClient(timeout=25.0) as c:
        while True:
            r = await c.get(d.bridge_url.rstrip('/') + '/audit',
                            params={'since_id': dernier},
                            headers={'X-API-Key': d.bridge_api_key})
            o = r.json().get('orders') or []
            if not o:
                break
            lues += o
            m = max(x['id'] for x in o)
            if m == dernier:
                break
            dernier = m
    return mi.enregistrer_activations(did, lues, dernier if lues else None), len(lues)

async def main():
    rapport = {}
    for f, did in ((_admin_live_destination, 'admin_live'),
                   (_admin_legacy_destination, 'admin_legacy')):
        d = f()
        if d is None:
            rapport[did] = 'non configuree'
            continue
        try:
            n, lues = await aspirer(d, did)
            rapport[did] = {'nouvelles_activations': n, 'lignes_lues': lues,
                            'curseur': mi.curseur(did)}
        except Exception as e:
            # ⛔ Un bridge injoignable se DIT. Zero activation et « je n'ai pas
            # pu lire » menent a des conclusions opposees.
            rapport[did] = {'erreur': str(e)}
    rapport['enrichissement'] = mi.enrichir()
    rapport['bilan'] = mi.bilan()
    print(json.dumps(rapport, ensure_ascii=False, indent=1))

asyncio.run(main())
"
