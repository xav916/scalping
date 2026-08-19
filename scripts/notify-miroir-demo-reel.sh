#!/bin/bash
# Prévient dès qu'un trade part sur LES DEUX comptes MT5 (démo puis réel).
#
# Contexte : depuis le 2026-08-06 le compte de démonstration PILOTE le compte
# réel — un fill confirmé en démo déclenche l'ouverture du même ordre sur le
# réel (cf. `mt5_bridge._mirror_fill_to_live`). Ce script est le témoin de
# cette copie : il dit si elle a abouti, et sinon pourquoi.
#
# ⚠️ Il alerte AUSSI quand la copie a été refusée. C'est le cas le plus utile :
# un miroir qui pousse dans le vide est indiscernable d'un miroir à l'arrêt si
# on ne regarde que les succès. Le 2026-08-06, le compte réel a refusé avec
# `429 Daily drawdown reached` — sans cette alerte, l'écart serait resté
# invisible jusqu'au lendemain.
#
# Cadence conseillée : toutes les 2 minutes. Dedup par ticket côté endpoint.
#
# Usage :
#   notify-miroir-demo-reel.sh           → vérifie + notifie
#   DRY_RUN=1 notify-miroir-demo-reel.sh → affiche sans notifier
set -uo pipefail

TOKEN="shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg"
# channel=sales : c'est un evenement de TRADING, pas d'infrastructure. Le bot
# infra est reserve au monitoring (cf. separation du 2026-08-02).
NOTIFY_URL="https://app.scalping-radar.online/api/admin/notify-infra-telegram?token=${TOKEN}&channel=sales"

# Fenêtre de recherche : large assez pour ne rien rater entre deux passages,
# la déduplication côté endpoint évite les répétitions.
FENETRE_MIN="${MIROIR_FENETRE_MIN:-15}"

# `-i` est indispensable : sans lui `docker exec` n'attache pas stdin et le
# heredoc part dans le vide, avec un rapport vide indiscernable d'une panne.
RAPPORT=$(docker exec -i -e PYTHONPATH=/app -w /app scalping-radar python - "$FENETRE_MIN" <<'PY' 2>/dev/null
import json, sqlite3, sys, datetime as dt
from backend.services.trade_log_service import _DB_PATH

fenetre = int(sys.argv[1])
depuis = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=fenetre)).isoformat()
c = sqlite3.connect(str(_DB_PATH))

# Un "trade miroir" = même paire/sens/prix poussé aux DEUX destinations.
q = """SELECT pair, direction, entry_price_5dp,
              MAX(CASE WHEN destination_id='admin_legacy' THEN pushed_at END) t_demo,
              MAX(CASE WHEN destination_id='admin_legacy' THEN ok END)        ok_demo,
              MAX(CASE WHEN destination_id='admin_live'   THEN pushed_at END) t_reel,
              MAX(CASE WHEN destination_id='admin_live'   THEN ok END)        ok_reel,
              MAX(CASE WHEN destination_id='admin_live'   THEN bridge_response END) rep
       FROM mt5_pushes
       WHERE pushed_at >= ? AND destination_id IN ('admin_legacy','admin_live')
       GROUP BY pair, direction, entry_price_5dp
       HAVING t_demo IS NOT NULL"""
sorties = []
for pair, sens, prix, t_demo, ok_demo, t_reel, ok_reel, rep in c.execute(q, (depuis,)):
    sorties.append({
        "pair": pair, "sens": sens, "prix": prix,
        "t_demo": str(t_demo or "")[11:19], "ok_demo": bool(ok_demo),
        "t_reel": str(t_reel or "")[11:19] if t_reel else None,
        "ok_reel": bool(ok_reel) if t_reel else None,
        "reponse": str(rep or "")[:220],
    })
print(json.dumps({"fenetre_min": fenetre, "trades": sorties}, ensure_ascii=False))
PY
)

if [ -z "$RAPPORT" ]; then
  echo "❌ Aucun rapport (docker exec a échoué)"
  exit 1
fi

echo "$RAPPORT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
t = d.get('trades') or []
print('fenetre=%s min  trades demo=%d' % (d.get('fenetre_min'), len(t)))
for x in t:
    etat = 'REEL ok' if x['ok_reel'] else ('REEL REFUSE' if x['t_reel'] else 'REEL absent')
    print('  %s %s %s  demo=%s  %s' % (x['t_demo'], x['pair'], x['sens'], x['ok_demo'], etat))
"

PAYLOAD=$(echo "$RAPPORT" | python3 -c "
import json, sys

d = json.load(sys.stdin)
suivis = [x for x in (d.get('trades') or []) if x['ok_demo']]
if not suivis:
    print('')
    raise SystemExit

ok = [x for x in suivis if x['ok_reel']]
ko = [x for x in suivis if not x['ok_reel']]

lignes = []
for x in ok:
    lignes.append('OK  %s  %s %s @ %s  -> ouvert sur LES DEUX comptes'
                  % (x['t_demo'], x['pair'], x['sens'], x['prix']))
for x in ko:
    motif = 'jamais pousse' if not x['t_reel'] else 'refuse par le compte reel'
    lignes.append('KO  %s  %s %s @ %s  -> %s' % (x['t_demo'], x['pair'], x['sens'], x['prix'], motif))
    if x['reponse']:
        lignes.append('       %s' % x['reponse'])

titre = ('✅ Miroir demo -> reel : %d trade(s) sur les deux comptes' % len(ok)) if ok \
        else ('⚠️ Miroir demo -> reel : la copie N A PAS abouti')
corps = '\n'.join(lignes)
corps += '\n\nLe demo pilote le reel depuis le 2026-08-06.'
if ko:
    corps += ' Une copie refusee vient du COMPTE, pas du miroir : marge, plafond de positions, ou perte journaliere.'

print(json.dumps({
    'title': titre,
    'body': corps,
    'dedup_key': 'miroir_demo_reel_' + '_'.join(sorted(x['prix'] for x in suivis)),
    'cooldown_seconds': 21600,
}))
")

if [ -z "$PAYLOAD" ]; then
  echo "✓ aucun trade démo dans la fenêtre — rien à signaler"
elif [ "${DRY_RUN:-0}" = "1" ]; then
  echo "--- DRY_RUN : payload qui serait envoyé ---"
  echo "$PAYLOAD"
else
  curl -sS -m 5 -X POST "$NOTIFY_URL" -H 'Content-Type: application/json' \
    --data "$PAYLOAD" -o /dev/null -w 'notify HTTP %{http_code}\n' || true
fi

echo "notify-miroir-demo-reel terminé"
