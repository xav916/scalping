#!/bin/bash
# BUT: verifie que chaque position Kraken porte son SL et son TP
# PERIODE_MIN: 1
# Garde-fou SL/TP Kraken — détecte (et, si armé, répare) les positions ouvertes
# sans stop sur le bridge Kraken Futures.
#
# Jumeau de check-live-positions-sltp.sh, qui ne couvre QUE les bridges MT5.
# Kraken avait la détection depuis le 2026-08-19 (`positions_non_protegees`) et
# la réparation depuis le 2026-09-06 (`POST /position/sltp`) — rien ne reliait
# les deux : il fallait un humain entre le constat et le geste.
#
# ⚠️ Par défaut, il DÉTECTE et ALERTE seulement. Aucun ordre ne part tant que
# les DEUX drapeaux ne sont pas explicitement activés :
#   - KRAKEN_SLTP_GUARD_AUTO_PROTECT_ENABLED côté backend (/opt/scalping/.env)
#   - KRAKEN_SLTP_GUARD_ENABLED côté bridge (/opt/kraken-bridge/.env)
# Poser un stop automatique sur de l'argent réel est un changement de
# comportement qui doit s'allumer sciemment.
#
# ⚠️ Et même les deux allumés ne suffisent pas : KRAKEN_SLTP_GUARD_ACTIVATED_AT
# doit porter une date. Vide = fail-closed, aucune position éligible. Une
# position ouverte AVANT cette date reste gelée pour toujours — c'est le
# BRIDGE qui applique cette règle, pas ce script : même si ce script est bogué
# ou mal configuré, le bridge refuse seul.
#
# 🔑 L'enjeu dépasse la position : une position nue bloque TOUTE nouvelle
# ouverture sur Kraken (le contrôle de risque engagé refuse tant qu'un risque
# n'est pas bornable). Un garde-fou désarmé se manifeste donc par un compte qui
# cesse de trader, sans que personne sache pourquoi.
#
# Usage :
#   check-kraken-positions-sltp.sh           → scan + alerte
#   DRY_RUN=1 check-kraken-positions-sltp.sh → affiche sans notifier
set -uo pipefail

TOKEN="shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg"
NOTIFY_URL="https://app.scalping-radar.online/api/admin/notify-infra-telegram?token=${TOKEN}&channel=infra"

echo "$(date -Iseconds) check-kraken-positions-sltp : scan des positions Kraken sans stop"

# Le scan et la décision vivent côté backend, testables en Python — ce script
# n'est qu'un orchestrateur cron et un relais Telegram.
RAPPORT=$(docker exec scalping-radar python -m backend.services.kraken_sltp_guard 2>/dev/null)

if [ -z "$RAPPORT" ]; then
  echo "❌ Aucun rapport (docker exec a échoué ou n'a rien renvoyé)"
  if [ "${DRY_RUN:-0}" != "1" ]; then
    curl -sS -m 5 -X POST "$NOTIFY_URL" -H 'Content-Type: application/json' \
      --data '{"title":"🚨 Garde-fou Kraken en panne","body":"docker exec backend.services.kraken_sltp_guard n'\''a rien renvoyé — les positions Kraken nues ne sont plus surveillées. Vérifier le conteneur scalping-radar.","dedup_key":"kraken_guard_dead","cooldown_seconds":3600}' \
      > /dev/null || true
  fi
  exit 1
fi

echo "$RAPPORT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f\"joignable={d.get('joignable')} nues={d.get('nues_total')} \"
      f\"protegees={d.get('protegees_total')} auto_protect={d.get('auto_protect_enabled')}\")
for p in (d.get('nues') or []):
    print(f\"  {p.get('symbol')} {p.get('side')} {p.get('size')} — ouverte {p.get('fill_time')}\")
"

# ⛔ Un bridge injoignable est une PANNE du garde-fou, pas un compte sain.
# « 0 position nue » et « je n'ai pas pu regarder » se ressemblent, et c'est
# exactement la confusion qui rend une surveillance inutile.
JOIGNABLE=$(echo "$RAPPORT" | python3 -c "import json,sys; print('1' if json.load(sys.stdin).get('joignable') else '0')")
if [ "$JOIGNABLE" != "1" ]; then
  echo "❌ bridge Kraken injoignable — le garde-fou n'a rien pu vérifier"
  if [ "${DRY_RUN:-0}" != "1" ]; then
    curl -sS -m 5 -X POST "$NOTIFY_URL" -H 'Content-Type: application/json' \
      --data '{"title":"⚠️ Garde-fou Kraken aveugle","body":"Le bridge Kraken (port 8790) est injoignable : impossible de vérifier si une position tourne sans stop. Ce n'\''est PAS un compte sain, c'\''est une absence de mesure.","dedup_key":"kraken_guard_blind","cooldown_seconds":1800}' \
      > /dev/null || true
  fi
  exit 1
fi

NUES=$(echo "$RAPPORT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('nues_total') or 0)")

if [ "${NUES:-0}" -gt 0 ]; then
  PAYLOAD=$(echo "$RAPPORT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
lignes = [f\"• {p.get('symbol')} {p.get('side')} {p.get('size')} — entree {p.get('price')}, ouverte {p.get('fill_time') or 'date inconnue'}\"
          for p in (d.get('nues') or [])]
actions = []
for r in (d.get('resultats') or []):
    if r.get('ok'):
        etat = '✓ stop d urgence pose'
    elif r.get('exclu'):
        etat = f\"⛔ exclu par le bridge ({r.get('motif')})\"
    else:
        etat = f\"❌ echec ({r.get('error') or r.get('status') or '?'})\"
    actions.append(f\"• {r.get('symbol')} — {etat}\")

corps = 'Positions Kraken sans stop :\n' + '\n'.join(lignes)
if actions:
    corps += '\n\nActions du garde-fou :\n' + '\n'.join(actions)
else:
    corps += ('\n\nAucune action automatique — garde-fou en mode DETECTION SEULE '
              '(KRAKEN_SLTP_GUARD_AUTO_PROTECT_ENABLED et/ou KRAKEN_SLTP_GUARD_ENABLED desactives).')
corps += ('\n\n👉 Sur Kraken le stop est un ORDRE independant : verifier /openorders. '
          'Une position nue bloque aussi toute nouvelle ouverture.')

print(json.dumps({
    'title': f\"🚨 {len(lignes)} position(s) Kraken sans stop\",
    'body': corps,
    'dedup_key': 'kraken_guard_positions_nues',
    'cooldown_seconds': 900,
}))
"
  )

  if [ "${DRY_RUN:-0}" = "1" ]; then
    echo "--- DRY_RUN : payload qui serait envoyé ---"
    echo "$PAYLOAD"
  else
    curl -sS -m 5 -X POST "$NOTIFY_URL" -H 'Content-Type: application/json' \
      --data "$PAYLOAD" -o /dev/null -w 'notify HTTP %{http_code}\n' || true
  fi
else
  echo "✓ aucune position Kraken nue"
fi

echo "check-kraken-positions-sltp terminé"
