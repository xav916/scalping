#!/bin/bash
# Rapport automatique de la MESURE forex H4 (posé le 2026-08-07).
#
# Question tranchée : les stops forex en H4 passent-ils la porte de coût ?
# En 5 minutes ils sont à 0,021-0,036 % quand la porte exige ~0,33 % — rien ne
# passe, sur aucune paire. En H4 ils n'avaient jamais été mesurés, seulement
# projetés (×8,1 sur deux ancres contradictoires), et les projections tombent
# à cheval sur le seuil. Cf. `V2_MEASURE_*` dans shadow_v2_core_long.py.
#
# ⚠️ Le verdict n'est PAS calculé contre un seuil codé en dur : le script
# appelle `cost_in_r` + `exceeds_edge` avec le modèle de coût et l'edge de la
# destination MT5 réelle. Si la porte est recalibrée, le rapport suit. Un
# seuil recopié aurait divergé en silence.
#
# ⚠️ Ce rapport S'ARRÊTE TOUT SEUL. Une fois toutes les paires tranchées, il
# envoie un verdict final, pose un témoin et se tait. Un push quotidien qui
# répète un résultat acquis est exactement le bruit qu'on a nettoyé le
# 2026-08-04 — on ne pousse que ce sur quoi on peut agir.
#
# Cadence conseillée : 1×/jour. Usage :
#   check-forex-h4-mesure.sh           -> mesure + notifie
#   DRY_RUN=1 check-forex-h4-mesure.sh -> affiche sans notifier
#   FORCE=1   check-forex-h4-mesure.sh -> ignore le témoin de fin
set -uo pipefail

TOKEN="shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg"
NOTIFY_URL="https://app.scalping-radar.online/api/admin/notify-infra-telegram?token=${TOKEN}&channel=infra"

# Nombre de setups avant de prononcer un verdict sur une paire. Une médiane
# sur 5 observations n'est pas une mesure, c'est un tirage.
MIN_SAMPLE="${FOREX_H4_MIN_SAMPLE:-20}"

TEMOIN=/opt/scalping/data/.forex-h4-verdict-envoye
if [ -f "$TEMOIN" ] && [ "${FORCE:-0}" != "1" ]; then
  echo "verdict deja rendu le $(cat "$TEMOIN") — rien a faire (FORCE=1 pour relancer)"
  exit 0
fi

# `-i` est indispensable : sans lui `docker exec` n'attache pas stdin, le
# heredoc part dans le vide et le rapport vide est indiscernable d'une panne.
RAPPORT=$(docker exec -i -e PYTHONPATH=/app -w /app scalping-radar python - "$MIN_SAMPLE" <<'PY' 2>/dev/null
import json, sqlite3, statistics, sys

from backend.services.cost_model import cost_in_r, exceeds_edge
from backend.services import bridge_destinations as bd
from backend.services.trade_log_service import _DB_PATH

min_sample = int(sys.argv[1])

# Modele de cout et edge de la destination REELLE : le verdict suit la porte,
# il ne la reimplemente pas.
dest = bd._admin_live_destination() or bd._admin_legacy_destination()
modele = getattr(dest, "cost_model", None)
edge = getattr(dest, "expected_edge_r", None)

c = sqlite3.connect(str(_DB_PATH))
q = """SELECT pair, entry_price, stop_loss FROM shadow_setups
       WHERE system_id LIKE 'V2!_MEASURE!_%' ESCAPE '!'
         AND entry_price > 0 AND stop_loss IS NOT NULL"""
par_paire = {}
for pair, e, s in c.execute(q):
    par_paire.setdefault(pair, []).append((float(e), float(s)))

sorties = []
for pair, obs in sorted(par_paire.items()):
    distances = sorted(abs(e - s) / e * 100 for e, s in obs)
    bloques = sum(1 for e, s in obs
                  if exceeds_edge(cost_in_r(e, s, modele), edge, True))
    n = len(obs)
    sorties.append({
        "pair": pair,
        "n": n,
        "median_pct": round(statistics.median(distances), 3),
        "pct_passent": round((n - bloques) / n * 100, 1),
        "tranche": n >= min_sample,
    })

print(json.dumps({
    "min_sample": min_sample,
    "edge_r": edge,
    "taux_par_jambe": getattr(modele, "proportional_rate_per_leg", None),
    "paires": sorties,
    "attendues": 9,
}, ensure_ascii=False))
PY
)

if [ -z "$RAPPORT" ]; then
  echo "❌ Aucun rapport (docker exec a échoué)"
  exit 1
fi

echo "$RAPPORT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print('edge=%s  taux/jambe=%s  min_sample=%s' % (d['edge_r'], d['taux_par_jambe'], d['min_sample']))
for p in d['paires']:
    print('  %-9s n=%-4d median=%6.3f%%  passent=%5.1f%%  %s'
          % (p['pair'], p['n'], p['median_pct'], p['pct_passent'],
             'TRANCHE' if p['tranche'] else 'en cours'))
"

PAYLOAD=$(echo "$RAPPORT" | python3 -c "
import json, sys

d = json.load(sys.stdin)
paires = d['paires']
if not paires:
    print('')
    raise SystemExit

tranchees = [p for p in paires if p['tranche']]
complet = len(tranchees) >= d['attendues']

# Une paire 'passe' si la porte de cout laisse passer la majorite de ses
# setups. C'est la porte qui tranche, pas une distance recopiee.
passent = [p for p in tranchees if p['pct_passent'] >= 50]
refusees = [p for p in tranchees if p['pct_passent'] < 50]

lignes = []
for p in sorted(passent, key=lambda x: -x['pct_passent']):
    lignes.append('PASSE   %-8s stop median %.3f%%  (%d setups, %.0f%% admis)'
                  % (p['pair'], p['median_pct'], p['n'], p['pct_passent']))
for p in sorted(refusees, key=lambda x: -x['pct_passent']):
    lignes.append('refuse  %-8s stop median %.3f%%  (%d setups, %.0f%% admis)'
                  % (p['pair'], p['median_pct'], p['n'], p['pct_passent']))
en_cours = [p for p in paires if not p['tranche']]
if en_cours:
    lignes.append('')
    lignes.append('encore trop peu de donnees : ' +
                  ', '.join('%s (%d/%d)' % (p['pair'], p['n'], d['min_sample'])
                            for p in en_cours))

if complet:
    titre = 'VERDICT FINAL - forex en 4h : %d paires sur %d passent la porte de cout' % (len(passent), len(paires))
else:
    titre = 'Mesure forex 4h : %d paires sur %d tranchees' % (len(tranchees), d['attendues'])

corps = chr(10).join(lignes)
corps += chr(10) + chr(10) + (
    'Rappel : en 5 minutes AUCUNE paire ne passe (stops 10x trop serres). '
    'Une paire qui passe en 4h devient tradable sur le reel avec le capital '
    'actuel - il faut environ 90 a 270 euros par paire, contre 4117 pour l or.')
if complet:
    corps += chr(10) + 'Mesure terminee, ce rapport ne se repetera plus.'
corps += chr(10) + chr(10) + (
    'Attention : passer la porte de cout est necessaire, pas suffisant. '
    'Ca garantit que les frais ne mangent pas l esperance, pas qu il y ait une esperance.')

print(json.dumps({
    'title': titre,
    'body': corps,
    'dedup_key': 'forex_h4_mesure_' + ('final' if complet else str(len(tranchees))),
    'cooldown_seconds': 43200,
    'complet': complet,
}))
")

if [ -z "$PAYLOAD" ]; then
  echo "✓ aucun setup mesuré pour l'instant — rien à signaler"
  exit 0
fi

COMPLET=$(echo "$PAYLOAD" | python3 -c "import json,sys; print(json.load(sys.stdin)['complet'])")

if [ "${DRY_RUN:-0}" = "1" ]; then
  echo "--- DRY_RUN : payload qui serait envoyé ---"
  echo "$PAYLOAD" | python3 -m json.tool
else
  echo "$PAYLOAD" | python3 -c "
import json,sys
d = json.load(sys.stdin); d.pop('complet', None)
sys.stdout.write(json.dumps(d))
" | curl -sS -m 5 -X POST "$NOTIFY_URL" -H 'Content-Type: application/json' \
    --data @- -o /dev/null -w 'notify HTTP %{http_code}\n' || true

  if [ "$COMPLET" = "True" ]; then
    date -u '+%Y-%m-%dT%H:%M:%SZ' > "$TEMOIN"
    echo "témoin posé : le rapport se taira désormais"
  fi
fi

echo "check-forex-h4-mesure terminé"
