#!/bin/bash
# BUT: verifie que le slippage est bien instrumente
# PERIODE_MIN: 1440
# Vérifie que la mesure du coût d'exécution enregistre réellement quelque chose.
#
# Contexte : `slippage_pips` et `fill_price` sont restés vides sur 1581/1581
# trades réels pendant onze mois. Le calcul existait ; rien ne signalait que la
# colonne ne se remplissait jamais. Corrigé le 2026-08-06 (`fd369ab`) — ce
# contrôle existe pour que ce silence ne puisse pas se réinstaller.
#
# Il surveille l'INSTRUMENT DE MESURE, pas le trading. Il ne dit rien sur la
# performance et ne doit jamais servir à décider d'un trade.
#
# La décision vit côté backend dans backend/services/slippage_instrumentation_check.py
# (testable en Python, contrairement à une boucle bash) ; ce script n'est qu'un
# orchestrateur cron + relais Telegram — même patron que
# check-live-positions-sltp.sh.
#
# Cadence : QUOTIDIENNE. La couverture d'une colonne évolue en jours, pas en
# minutes ; alerter plus souvent produirait du bruit sans avancer la décision.
#
# Usage :
#   check-slippage-instrumentation.sh           → vérifie + alerte si besoin
#   DRY_RUN=1 check-slippage-instrumentation.sh → affiche sans notifier
set -uo pipefail

TOKEN="shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg"
NOTIFY_URL="https://app.scalping-radar.online/api/admin/notify-infra-telegram?token=${TOKEN}&channel=infra"

echo "$(date -Iseconds) check-slippage-instrumentation : couverture de la mesure d'exécution"

RAPPORT=$(docker exec scalping-radar python -m backend.services.slippage_instrumentation_check 2>/dev/null)

if [ -z "$RAPPORT" ]; then
  echo "❌ Aucun rapport (docker exec a échoué ou n'a rien renvoyé)"
  if [ "${DRY_RUN:-0}" != "1" ]; then
    curl -sS -m 5 -X POST "$NOTIFY_URL" -H 'Content-Type: application/json' \
      --data '{"title":"🔧 Contrôle du glissement en panne","body":"docker exec backend.services.slippage_instrumentation_check n'\''a rien renvoyé — plus personne ne vérifie que le coût d'\''exécution est enregistré. Vérifier le conteneur scalping-radar.","dedup_key":"slippage_check_dead","cooldown_seconds":86400}' \
      > /dev/null || true
  fi
  exit 1
fi

echo "$RAPPORT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print('verdict=%s trades_depuis=%s fill=%s/%s slippage=%s/%s' % (
    d.get('verdict'), d.get('trades_depuis'),
    d.get('avec_fill_price'), d.get('trades_depuis'),
    d.get('avec_slippage'), d.get('trades_depuis')))
print('  ' + str(d.get('message')))
"

ALERTE=$(echo "$RAPPORT" | python3 -c "import json,sys; print('1' if json.load(sys.stdin).get('alerte') else '0')")

if [ "${ALERTE:-0}" = "1" ]; then
  PAYLOAD=$(echo "$RAPPORT" | python3 -c "
import json, sys

d = json.load(sys.stdin)
verdict = d.get('verdict')

titres = {
    'MORTE': '🔧 La mesure du coût d\'exécution est muette',
    'PARTIELLE': '🔧 Mesure du coût d\'exécution incomplète',
    'ERREUR': '🔧 Contrôle du glissement illisible',
}
corps = [str(d.get('message'))]
if verdict in ('MORTE', 'PARTIELLE'):
    corps.append('')
    corps.append('Depuis %s :' % d.get('depuis'))
    corps.append('• %s trade(s) automatique(s)' % d.get('trades_depuis'))
    corps.append('• fill_price sur %s' % d.get('avec_fill_price'))
    corps.append('• glissement mesurable sur %s' % d.get('avec_slippage'))
    corps.append('')
    corps.append('Ce n\'est pas une alerte de trading : rien n\'est en danger. '
                 'C\'est la mesure qui ne s\'enregistre plus.')

print(json.dumps({
    'title': titres.get(verdict, '🔧 Mesure du coût d\'exécution'),
    'body': '\n'.join(corps),
    'dedup_key': 'slippage_instrumentation_' + str(verdict).lower(),
    'cooldown_seconds': 86400,
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
  echo "✓ rien à signaler"
fi

echo "check-slippage-instrumentation terminé"
