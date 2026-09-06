#!/bin/bash
# Confronte les trois listes qui definissent l'univers Kraken.
#
# ⛔ Ne parle QUE en cas d'incoherence. Une verification qui annonce son succes
# chaque jour devient du bruit, et le bruit se filtre — y compris le jour ou
# elle a quelque chose a dire.
#
# Le module rend 1 si une paire est routable sans pouvoir produire de signal,
# ou routable sans etre autorisee chez le courtier. Le surplus de whitelist,
# lui, est l'etat normal apres un retrait : il ne declenche rien.
set -uo pipefail

TOKEN="shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg"
SORTIE=$(docker exec scalping-radar python -m backend.services.coherence_univers_kraken 2>&1)
CODE=$?

echo "$(date -Iseconds)"
echo "$SORTIE"

if [ "$CODE" -eq 0 ]; then
  echo "coherent — rien a signaler"
  exit 0
fi

# ⛔ Le corps du message est celui du module, pas une reformulation : une alerte
# qui reecrit ce qu'elle a mesure finit par ne plus dire la meme chose.
CORPS=$(echo "$SORTIE" | sed -n '/Univers Kraken/,$p' | tail -n +2)
if [ "${DRY_RUN:-0}" = "1" ]; then
  echo "--- DRY_RUN, message qui partirait ---"; echo "$CORPS"; exit 1
fi
curl -sS -m 8 -X POST \
  "https://app.scalping-radar.online/api/admin/notify-infra-telegram?token=${TOKEN}&channel=infra" \
  -H 'Content-Type: application/json' \
  --data "$(python3 -c "
import json, sys
print(json.dumps({'title': '🚨 Univers Kraken INCOHÉRENT',
                  'body': '''$CORPS''',
                  'dedup_key': 'coherence_univers_kraken',
                  'cooldown_seconds': 21600}))
")" -o /dev/null -w 'notify HTTP %{http_code}\n' || true
exit 1
