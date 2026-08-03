#!/bin/bash
# Cron vendredi 17h UTC : rappelle Xavier sur sales bot si positions energy Live
# encore ouvertes. Motif : incident 2026-08-03 → gap réouverture dimanche a slippé
# 2 SL WTI de -4 USD/ticket, perte €20.75 au lieu de €4-5 attendus.
# Le pre-push filter (mt5_bridge NO_FRIDAY_LATE_OPEN_ENERGY_ENABLED) bloque les
# nouveaux trades energy après 18h UTC. Ce script complète en rappelant à Xavier
# de fermer manuellement toute position energy encore ouverte (auto-close côté
# bridge nécessiterait deploy VPS, reporté V2).

set -uo pipefail

BOT_TOKEN=$(sudo grep -E '^SALES_TELEGRAM_BOT_TOKEN=' /opt/scalping/.env | cut -d= -f2-)
CHAT_ID=$(sudo grep -E '^SALES_TELEGRAM_CHAT_ID=' /opt/scalping/.env | cut -d= -f2-)
LU=$(sudo grep -E '^MT5_BRIDGE_LIVE_URL=' /opt/scalping/.env | cut -d= -f2-)
LK=$(sudo grep -E '^MT5_BRIDGE_LIVE_API_KEY=' /opt/scalping/.env | cut -d= -f2-)

if [ -z "$BOT_TOKEN" ] || [ -z "$CHAT_ID" ] || [ -z "$LU" ] || [ -z "$LK" ]; then
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

MESSAGE="⚠️ <b>Positions énergie encore ouvertes vendredi 17h UTC</b>

Le pre-push filter bloque déjà les nouveaux trades énergie après 18h UTC.
Mais ces positions actuelles risquent un gap risk weekend (cf. incident WTI 2026-08-03 : -€20.75 sur 2 tickets à cause du gap dimanche).

<b>Positions concernées :</b>
<pre>${ENERGY_LIST}</pre>

<b>Reco</b> : ferme-les manuellement depuis MT5 mobile avant fermeture marché ven 22h UTC pour éviter le gap risk.
Sinon assume le risque et garde-les weekend."

curl -sS --max-time 10 -X POST \
  "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
  -d "chat_id=${CHAT_ID}" \
  --data-urlencode "text=${MESSAGE}" \
  -d "parse_mode=HTML" \
  -d "disable_web_page_preview=true" > /dev/null
