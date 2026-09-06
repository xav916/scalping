#!/bin/bash
# Prévient dès qu'un ordre part RÉELLEMENT sur Kraken (2026-08-08).
#
# Manque comblé : `notify-new-pushes.sh` ne signale que les ÉCHECS (`ok = 0`),
# et `notify-miroir-demo-reel.sh` ne couvre que les deux comptes MT5. Aucun
# script ne disait « un trade est parti sur Kraken » — la route qui vient de
# passer de 2 à 18 instruments tradables.
#
# ⚠️ Notifie AUSSI les refus du courtier. Un ordre qui part et se fait refuser
# est indiscernable d'une route inerte si on ne regarde que les succès — c'est
# la leçon du miroir démo→réel, où seul le suivi des refus a revélé que la
# marge bloquait tout.
#
# Cadence : toutes les 2 minutes. Dédup par identifiant de push côté endpoint.
#
# Usage :
#   notify-kraken-trade.sh            -> vérifie + notifie
#   DRY_RUN=1 notify-kraken-trade.sh  -> affiche sans notifier
set -uo pipefail

TOKEN="shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg"
# channel=kraken (2026-09-06) : ce script ne parle QUE de Kraken.
#
# Il postait sur `sales`, c'est-a-dire le bot nomme « IC MARKETS trades » :
# des ordres crypto s'affichaient dans le fil du compte forex reel. L'ancien
# commentaire disait vrai a l'envers — `trades` visait le bot Kraken.
# ex-commentaire : le fil `trades` est reserve au COMPTE REEL 13137475
# (2026-08-19, demande de Xavier). Kraken est une autre route, il reste ici.
NOTIFY_URL="https://app.scalping-radar.online/api/admin/notify-infra-telegram?token=${TOKEN}&channel=kraken"
ETAT=/var/lib/scalping/last-kraken-trade-id.txt

mkdir -p "$(dirname "$ETAT")"
[ -f "$ETAT" ] || echo 0 > "$ETAT"
DERNIER=$(cat "$ETAT"); DERNIER=${DERNIER:-0}

# `-i` indispensable : sans lui docker exec n'attache pas stdin, le heredoc
# part dans le vide, et un rapport vide est indiscernable d'une panne.
RAPPORT=$(docker exec -i -e PYTHONPATH=/app -w /app scalping-radar python - "$DERNIER" <<'PY' 2>/dev/null
import json, sqlite3, sys
from backend.services.trade_log_service import _DB_PATH

# Un push est inséré à `ok=0` AVANT l'envoi, puis passé à `ok=1` s'il aboutit.
# Un `ok=0` de moins de DELAI_MIN minutes est donc peut-être simplement EN VOL.
# Le crier serait une fausse alerte — et surtout, avancer le curseur par-dessus
# ferait perdre sa réussite pour toujours. Même marge que notify-new-pushes.sh.
DELAI_MIN = 5

dernier = int(sys.argv[1])
c = sqlite3.connect(str(_DB_PATH))
q = """SELECT id, pushed_at, pair, direction, ok,
              substr(bridge_response, 1, 260),
              (pushed_at < datetime('now', '-{} minutes')) AS tranche
         FROM mt5_pushes
        WHERE destination_id = 'admin_kraken' AND id > ?
        ORDER BY id""".format(DELAI_MIN)
lignes = []
for i, t, p, d, ok, rep, tranche in c.execute(q, (dernier,)):
    # ⚠️ ARRÊT au premier ordre non tranché. Tout ce qui suit attendra le
    # prochain passage : le curseur ne franchit jamais un push en vol.
    if not ok and not tranche:
        break
    lignes.append({"id": i, "heure": str(t)[11:19], "pair": p,
                   "sens": d, "ok": bool(ok), "reponse": rep or ""})
print(json.dumps({"dernier": dernier, "trades": lignes}, ensure_ascii=False))
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
print('curseur=%s  nouveaux pushes Kraken=%d' % (d['dernier'], len(t)))
for x in t:
    print('  #%d %s %s %s ok=%s' % (x['id'], x['heure'], x['pair'], x['sens'], x['ok']))
"

PAYLOAD=$(echo "$RAPPORT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
t = d.get('trades') or []
if not t:
    print(''); raise SystemExit

ok = [x for x in t if x['ok']]
ko = [x for x in t if not x['ok']]
lignes = []
for x in ok:
    lignes.append('OK  %s  %s %s  -> ORDRE PARTI sur Kraken' % (x['heure'], x['pair'], x['sens']))
for x in ko:
    lignes.append('KO  %s  %s %s  -> refuse par le courtier' % (x['heure'], x['pair'], x['sens']))
    if x['reponse']:
        lignes.append('       %s' % x['reponse'])

titre = ('Kraken : %d ordre(s) parti(s)' % len(ok)) if ok else 'Kraken : ordre REFUSE par le courtier'
corps = chr(10).join(lignes)
corps += chr(10) + chr(10) + 'Route crypto journaliere, LONG ONLY, 1 % de risque par trade.'
if ko:
    corps += ' Un refus vient du COMPTE (marge, plafond de positions), pas du filtrage.'

print(json.dumps({
    'title': titre,
    'body': corps,
    'dedup_key': 'kraken_trade_' + '_'.join(str(x['id']) for x in t),
    'cooldown_seconds': 3600,
    'max_id': max(x['id'] for x in t),
}))
")

if [ -z "$PAYLOAD" ]; then
  echo "✓ aucun nouveau push Kraken"
  exit 0
fi

MAXID=$(echo "$PAYLOAD" | python3 -c "import json,sys; print(json.load(sys.stdin)['max_id'])")

if [ "${DRY_RUN:-0}" = "1" ]; then
  echo "--- DRY_RUN : payload qui serait envoyé ---"
  echo "$PAYLOAD" | python3 -m json.tool
else
  echo "$PAYLOAD" | python3 -c "
import json, sys
d = json.load(sys.stdin); d.pop('max_id', None)
sys.stdout.write(json.dumps(d))
" | curl -sS -m 5 -X POST "$NOTIFY_URL" -H 'Content-Type: application/json' \
    --data @- -o /dev/null -w 'notify HTTP %{http_code}\n' || true
  # ⚠️ Le curseur n'avance QU'APRÈS l'envoi : un échec réseau doit rejouer,
  # pas sauter le trade.
  echo "$MAXID" > "$ETAT"
  echo "curseur avance a $MAXID"
fi

echo "notify-kraken-trade termine"
