#!/bin/bash
# Garde-fou SL/TP — détecte (et, si activé, corrige) les positions LIVE
# ouvertes sans stop-loss sur les bridges MT5 (legacy Demo + live IC Markets).
#
# Contexte : incident 2026-08-05, position XAU/USD ouverte sans SL/TP à
# 02:09 UTC, découverte 7h après à -51€. La cause (échec silencieux de la
# pose SL/TP côté bridge) est corrigée en amont dans mt5-bridge/bridge.py ;
# ce script reste le filet de sécurité — il tourne par cron et alerte en
# quelques secondes si une position nue apparaît malgré tout.
#
# ⚠️ Par défaut, il DÉTECTE et ALERTE seulement — il n'agit jamais tant que
# les DEUX drapeaux suivants ne sont pas explicitement activés :
#   - SLTP_GUARD_AUTO_PROTECT_ENABLED côté backend (config/settings.py)
#   - SLTP_GUARD_ENABLED côté bridge (mt5-bridge/.env, sur le PC/VPS Windows)
# Tant qu'un seul des deux est absent, aucun ordre ne part — poser un stop
# automatique sur de l'argent réel est un changement de comportement qui
# doit s'allumer sciemment.
#
# ⚠️ Positions gelées : une position ouverte AVANT l'activation du garde-fou
# (SLTP_GUARD_ACTIVATED_AT côté bridge) ou listée dans
# SLTP_GUARD_FROZEN_TICKETS n'est JAMAIS touchée, quel que soit l'état des
# deux drapeaux ci-dessus. C'est le BRIDGE qui applique cette règle (pas ce
# script) : même si ce script est buggé ou mal configuré, le bridge refuse
# seul de toucher une position gelée.
#
# Exécuté par cron sur l'EC2 (fréquence courte recommandée, ex: */2 min —
# c'est un garde-fou de sécurité, pas un digest). Copie de référence dans le
# dépôt : /opt/scalping/scripts est la copie que le cron exécute réellement
# et doit être resynchronisée manuellement après tout changement ici (pas de
# déploiement automatique, cf. piège de synchronisation manuelle déjà connu).
#
# Usage :
#   check-live-positions-sltp.sh           → scan + alerte si positions nues
#   DRY_RUN=1 check-live-positions-sltp.sh → affiche sans notifier Telegram
set -uo pipefail

TOKEN="shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg"
NOTIFY_URL="https://app.scalping-radar.online/api/admin/notify-infra-telegram?token=${TOKEN}&channel=infra"

# ⚠️ Tickets ACQUITTÉS — positions nues connues, assumées, et volontairement
# laissées sans stop par décision explicite de Xavier. Elles n'ALERTENT plus,
# mais restent comptées et visibles dans le journal : on ne les rend pas
# invisibles, on cesse seulement de notifier ce sur quoi aucune action n'est
# attendue (cf. principe du nettoyage des pushes du 2026-08-04).
#
# ⚠️ INVARIANT : toute position nue NON acquittée continue d'alerter
# normalement. Acquitter un ticket ne désarme jamais la surveillance — c'est
# pour ça que le filtre porte sur les tickets, jamais sur le compteur global.
#
# 1353960866 : XAU/USD sell, ouvert le 2026-08-05 02:09 UTC (incident bridge).
#              Xavier a posé un TP à la main et refuse un SL — il attend un
#              rebond. À retirer d'ici dès que la position sera fermée.
ACK_TICKETS="${SLTP_ALERT_ACK_TICKETS:-1353960866}"
export SLTP_ALERT_ACK_TICKETS="$ACK_TICKETS"

echo "$(date -Iseconds) check-live-positions-sltp : scan des positions LIVE sans stop"

# Le scan + la décision (agir ou pas) vivent côté backend, dans
# backend/services/sltp_guard_check.py — testable en Python, contrairement à
# une boucle bash. Ce script n'est qu'un orchestrateur cron + relais Telegram,
# même pattern que scripts/notify-new-pushes.sh (docker exec + inline python).
RAPPORT=$(docker exec scalping-radar python -m backend.services.sltp_guard_check 2>/dev/null)

if [ -z "$RAPPORT" ]; then
  echo "❌ Impossible d'obtenir le rapport (docker exec a échoué ou n'a rien renvoyé)"
  if [ "${DRY_RUN:-0}" != "1" ]; then
    curl -sS -m 5 -X POST "$NOTIFY_URL" -H 'Content-Type: application/json' \
      --data '{"title":"🚨 Garde-fou SL/TP en panne","body":"docker exec backend.services.sltp_guard_check n'\''a rien renvoyé — le garde-fou ne surveille plus les positions LIVE nues. Vérifier le conteneur scalping-radar.","dedup_key":"sltp_guard_dead","cooldown_seconds":3600}' \
      > /dev/null || true
  fi
  exit 1
fi

echo "$RAPPORT" | python3 -c "
import json, os, sys
d = json.load(sys.stdin)
ack = {t.strip() for t in os.environ.get('SLTP_ALERT_ACK_TICKETS', '').split(',') if t.strip()}
print(f\"naked_total={d.get('naked_total')} protected_total={d.get('protected_total')} auto_protect_enabled={d.get('auto_protect_enabled')}\")
for label, b in (d.get('bridges') or {}).items():
    nus = b.get('naked') or []
    acq = [p for p in nus if str(p.get('ticket')) in ack]
    print(f\"  {label}: reachable={b.get('reachable')} naked={len(nus)} acquittes={len(acq)} a_alerter={len(nus) - len(acq)}\")
"

# On n'alerte que sur les positions nues NON acquittées. Le compteur global
# reste inchangé dans le journal ci-dessus — seule la notification est filtrée.
NAKED_TOTAL=$(echo "$RAPPORT" | python3 -c "
import json, os, sys
d = json.load(sys.stdin)
ack = {t.strip() for t in os.environ.get('SLTP_ALERT_ACK_TICKETS', '').split(',') if t.strip()}
n = 0
for b in (d.get('bridges') or {}).values():
    for p in (b.get('naked') or []):
        if str(p.get('ticket')) not in ack:
            n += 1
print(n)
")

if [ "${NAKED_TOTAL:-0}" -gt 0 ]; then
  PAYLOAD=$(echo "$RAPPORT" | python3 -c "
import json, os, sys

d = json.load(sys.stdin)
bridges = d.get('bridges') or {}
ack = {t.strip() for t in os.environ.get('SLTP_ALERT_ACK_TICKETS', '').split(',') if t.strip()}

lignes = []
acquittees = []
for label, b in bridges.items():
    for p in (b.get('naked') or []):
        desc = f\"• {label} #{p.get('ticket')} {p.get('symbol')} {p.get('type')} — ouvert {p.get('time')}\"
        if str(p.get('ticket')) in ack:
            acquittees.append(desc)
        else:
            lignes.append(desc)

actions = []
for label, b in bridges.items():
    for r in (b.get('protect_results') or []):
        if r.get('ok'):
            etat = '✓ SL posé automatiquement'
        elif r.get('excluded'):
            etat = f\"⛔ exclu par le bridge ({r.get('reason')})\"
        else:
            etat = f\"❌ échec ({r.get('error') or '?'})\"
        actions.append(f\"• {label} #{r.get('ticket')} — {etat}\")

titre = f\"🚨 {len(lignes)} position(s) LIVE sans stop\"
corps = 'Positions détectées sans SL :\n' + '\n'.join(lignes)
if acquittees:
    corps += ('\n\nAussi sans stop, mais acquittées (aucune alerte attendue) :\n'
              + '\n'.join(acquittees))
if actions:
    corps += '\n\nActions du garde-fou automatique :\n' + '\n'.join(actions)
else:
    corps += ('\n\nAucune action automatique — garde-fou en mode détection seule '
              '(SLTP_GUARD_AUTO_PROTECT_ENABLED et/ou SLTP_GUARD_ENABLED désactivés).')
corps += '\n\n👉 Vérifier immédiatement côté MT5.'

print(json.dumps({
    'title': titre,
    'body': corps,
    'dedup_key': 'sltp_guard_naked_positions',
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
  echo "✓ aucune position nue à alerter (les tickets acquittés ne notifient pas)"
fi

echo "check-live-positions-sltp terminé"
