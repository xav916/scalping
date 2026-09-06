#!/bin/bash
# BUT: surveille le niveau de marge du compte reel
# PERIODE_MIN: 15
# Alerte quand le niveau de marge d'un compte RÉEL approche la liquidation.
#
# Contexte : le 2026-08-06 le compte Live est tombé à 95,5 % de niveau de marge
# — déjà sous l'appel de marge — à cause d'une seule position XAU/USD tenue
# volontairement sans stop, en attente de son objectif. Rien ne surveillait
# cette grandeur.
#
# ⚠️ Ce contrôle ne juge PAS la position. Tenir une position perdante est une
# décision assumée. Il surveille la seule chose qui pourrait retirer cette
# décision à Xavier : une liquidation forcée par le courtier, au prix du marché
# et au moment qu'il choisit.
#
# La décision vit dans backend/services/margin_level_check.py (testable) ; ce
# script est un orchestrateur cron + relais Telegram.
#
# Cadence : toutes les 15 min. Une marge se dégrade en heures, pas en jours —
# mais alerter chaque minute noierait le signal.
#
# Usage :
#   check-margin-level.sh           → vérifie + alerte si besoin
#   DRY_RUN=1 check-margin-level.sh → affiche sans notifier
set -uo pipefail

TOKEN="shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg"
NOTIFY_URL="https://app.scalping-radar.online/api/admin/notify-infra-telegram?token=${TOKEN}&channel=infra"

echo "$(date -Iseconds) check-margin-level : niveau de marge des comptes reels"

RAPPORT=$(docker exec scalping-radar python -m backend.services.margin_level_check 2>/dev/null)

if [ -z "$RAPPORT" ]; then
  echo "❌ Aucun rapport (docker exec a échoué)"
  exit 1
fi

echo "$RAPPORT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print('seuil=%s%%' % d.get('seuil_alerte_pct'))
for k, v in (d.get('comptes') or {}).items():
    print('  %s: joignable=%s niveau=%s%% equite=%s marge=%s positions=%s' % (
        k, v.get('joignable'), v.get('niveau_marge_pct'),
        v.get('equite'), v.get('marge'), v.get('positions')))
"

ALERTE=$(echo "$RAPPORT" | python3 -c "import json,sys; print('1' if json.load(sys.stdin).get('alerte') else '0')")

if [ "${ALERTE:-0}" = "1" ]; then
  PAYLOAD=$(echo "$RAPPORT" | python3 -c "
import json, sys

d = json.load(sys.stdin)
seuil = d.get('seuil_alerte_pct')
lignes = []
for k, v in (d.get('comptes') or {}).items():
    if not v.get('alerte'):
        continue
    lignes.append('• compte %s : niveau de marge %s%%' % (k, v.get('niveau_marge_pct')))
    lignes.append('   equite %s EUR pour %s EUR de marge, %s position(s)'
                  % (v.get('equite'), v.get('marge'), v.get('positions')))

corps = '\n'.join(lignes)
corps += ('\n\nLa liquidation automatique intervient vers 50 %. En dessous, '
          'le courtier ferme la position lui-meme, au prix du marche.')
corps += '\n\nRien n a ete ferme automatiquement. La decision reste la tienne.'

print(json.dumps({
    'title': '⚠️ Marge basse sur un compte reel (seuil %s%%)' % seuil,
    'body': corps,
    'dedup_key': 'margin_level_low',
    'cooldown_seconds': 3600,
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
  echo "✓ niveau de marge au-dessus du seuil"
fi

echo "check-margin-level terminé"
