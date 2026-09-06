#!/bin/bash
# Cron vendredi 17h UTC : rappelle Xavier sur sales bot si positions energy Live
# encore ouvertes. Motif : incident 2026-08-03 → gap réouverture dimanche a slippé
# 2 SL WTI de -4 USD/ticket, perte €20.75 au lieu de €4-5 attendus.
# Le pre-push filter (mt5_bridge NO_FRIDAY_LATE_OPEN_ENERGY_ENABLED) bloque les
# nouveaux trades energy après 18h UTC. Ce script complète en rappelant à Xavier
# de fermer manuellement toute position energy encore ouverte (auto-close côté
# bridge nécessiterait deploy VPS, reporté V2).

set -uo pipefail

# Le jeton du bot n'est plus lu ici : l'endpoint le detient.
LU=$(sudo grep -E '^MT5_BRIDGE_LIVE_URL=' /opt/scalping/.env | cut -d= -f2-)
LK=$(sudo grep -E '^MT5_BRIDGE_LIVE_API_KEY=' /opt/scalping/.env | cut -d= -f2-)

if [ -z "$LU" ] || [ -z "$LK" ]; then
  echo "missing creds/URL" >&2
  exit 1
fi

# Fetch positions Live + filter energy symbols (XTIUSD, USOIL, BRENT, NGAS, XTIUSD.NAS variants)
POSITIONS_JSON=$(curl -sS --max-time 8 -H "X-API-Key: $LK" "$LU/positions" 2>/dev/null || echo '{"positions":[]}')

ENERGY_LIST=$(POSITIONS="$POSITIONS_JSON" python3 -c "
import json, os
data = json.loads(os.environ.get('POSITIONS') or '{}')
positions = data.get('positions', [])
energy_symbols = ['XTIUSD', 'USOIL', 'BRENT', 'BRENTUSD', 'NGAS', 'NATGAS', 'XBRUSD']
found = []
for p in positions:
    sym = p.get('symbol', '').upper()
    if any(sym.startswith(e) or e in sym for e in energy_symbols):
        pnl = p.get('profit', 0)
        found.append(f\"#{p.get('ticket','?')} {sym} {p.get('type','?')} vol={p.get('volume','?')} PnL={pnl:+.2f}\")
if found:
    print('\n'.join(found))
")

if [ -z "$ENERGY_LIST" ]; then
  # Pas de position energy ouverte, silence complet
  exit 0
fi

# ── Passe par l'endpoint, canal `ic_markets` (2026-09-06) ────────────
#
# ⛔ Ce script appelait l'API Telegram EN DIRECT, en lisant
# `SALES_TELEGRAM_BOT_TOKEN` dans le .env : il echappait donc entierement a la
# table des canaux, et rien ne l'aurait suivi si le bot changeait de role.
#
# Il interroge `MT5_BRIDGE_LIVE_URL` : il ne parle que du compte reel IC
# Markets. Son fil est donc celui de ce compte.
#
# ⚠️ Les balises <b> ont disparu : l'endpoint passe le corps dans
# `html.escape`, elles s'afficheraient telles quelles. Le titre porte
# l'emphase — meme format que toutes les autres notifications.
TITRE="⚠️ Positions énergie encore ouvertes vendredi 17h UTC"
CORPS="Le pre-push filter bloque déjà les nouveaux trades énergie après 18h UTC.
Mais ces positions risquent un gap de week-end (incident WTI du 2026-08-03 :
−20,75 € sur 2 tickets à cause du gap du dimanche).

Positions concernées :
${ENERGY_LIST}

Reco : ferme-les à la main depuis MT5 mobile avant la clôture du marché,
vendredi 22h UTC. Sinon, assume le risque et garde-les le week-end."

TOKEN_NOTIFY="shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg"
CORPS_JSON=$(TITRE="$TITRE" CORPS="$CORPS" python3 -c '
import json, os
print(json.dumps({"title": os.environ["TITRE"], "body": os.environ["CORPS"],
                  "dedup_key": "energie-weekend", "cooldown_seconds": 3600}))
')
curl -sS --max-time 10 -X POST   "https://app.scalping-radar.online/api/admin/notify-infra-telegram?token=${TOKEN_NOTIFY}&channel=ic_markets"   -H "Content-Type: application/json" --data "$CORPS_JSON" > /dev/null
