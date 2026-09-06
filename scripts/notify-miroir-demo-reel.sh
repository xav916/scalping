#!/bin/bash
# Prévient dès qu'un ordre part sur le COMPTE RÉEL 13137475, et dit si le
# démo a suivi.
#
# ⚠️ Ancrage inversé le 2026-08-19. Le script s'ancrait sur le démo, donc un
# ordre parti sur le seul compte réel n'était jamais annoncé — c'est arrivé le
# 19/08 à 17:17 avec l'EUR/GBP, que le démo avait refusé en veto géopolitique.
# Le réel est désormais la ligne, le démo la colonne de contexte.
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
# channel=ic_markets (2026-09-06) : ce script juge le COMPTE REEL 13137475.
#
# Il ecrivait `channel=trades` en croyant viser ce compte — mais le bot
# derriere `TRADES_*` s'appelle « KRAKEN Trades ». D'ou « Position fermee —
# compte reel 13137475 » affiche dans le fil Kraken.
# ex-commentaire : fil dedie aux ordres (2026-08-19). Tant que le bot dedie
# n'est pas gree, l'endpoint retombe sur `sales` en le journalisant — donc
# basculer ici ne perd rien et la migration se fera sans retoucher ce script.
NOTIFY_URL="https://app.scalping-radar.online/api/admin/notify-infra-telegram?token=${TOKEN}&channel=ic_markets"

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

# ⚠️ ANCRAGE SUR LE COMPTE REEL (2026-08-19). Le filtre etait
# `HAVING t_demo IS NOT NULL` : un ordre parti sur le REEL sans passer par le
# demo n'etait donc jamais annonce. Ce n'est pas theorique — l'EUR/GBP du
# 2026-08-19 17:17 est parti sur le seul compte reel (le demo l'avait refuse
# en veto geopolitique) et serait passe sous silence.
#
# On liste desormais tout ce que le compte 13137475 a recu, et le demo devient
# une COLONNE DE CONTEXTE : « a-t-il suivi ? ». C'est la question posee.
q = """SELECT pair, direction, entry_price_5dp,
              MAX(CASE WHEN destination_id='admin_legacy' THEN pushed_at END) t_demo,
              MAX(CASE WHEN destination_id='admin_legacy' THEN ok END)        ok_demo,
              MAX(CASE WHEN destination_id='admin_live'   THEN pushed_at END) t_reel,
              MAX(CASE WHEN destination_id='admin_live'   THEN ok END)        ok_reel,
              MAX(CASE WHEN destination_id='admin_live'   THEN bridge_response END) rep
       FROM mt5_pushes
       WHERE pushed_at >= ? AND destination_id IN ('admin_legacy','admin_live')
       GROUP BY pair, direction, entry_price_5dp
       HAVING t_reel IS NOT NULL"""
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
print('fenetre=%s min  ordres compte reel=%d' % (d.get('fenetre_min'), len(t)))
for x in t:
    etat = 'REEL ok' if x['ok_reel'] else 'REEL REFUSE'
    demo = 'demo ok' if x['ok_demo'] else ('demo refuse' if x['t_demo'] else 'demo ABSENT')
    print('  %s %s %s  %s  %s' % (x['t_reel'], x['pair'], x['sens'], etat, demo))
"

PAYLOAD=$(echo "$RAPPORT" | python3 -c "
import json, sys

d = json.load(sys.stdin)
# Tout ce que le compte 13137475 a recu. Le demo n'est plus un filtre mais un
# CONTEXTE : la question posee est « le trade s'est-il ouvert aussi en demo ? ».
suivis = d.get('trades') or []
if not suivis:
    print('')
    raise SystemExit

ok = [x for x in suivis if x['ok_reel']]
ko = [x for x in suivis if not x['ok_reel']]

def _demo(x):
    if x['ok_demo']:
        return 'demo : ouvert aussi'
    if x['t_demo']:
        return 'demo : REFUSE'
    return 'demo : PAS de trade — le reel a agi seul'

lignes = []
for x in ok:
    lignes.append('OK  %s  %s %s @ %s' % (x['t_reel'], x['pair'], x['sens'], x['prix']))
    lignes.append('       %s' % _demo(x))
for x in ko:
    lignes.append('KO  %s  %s %s @ %s  -> refuse par le compte reel'
                  % (x['t_reel'], x['pair'], x['sens'], x['prix']))
    lignes.append('       %s' % _demo(x))
    if x['reponse']:
        lignes.append('       %s' % x['reponse'])

titre = ('✅ Compte reel 13137475 : %d ordre(s) parti(s)' % len(ok)) if ok \
        else '⚠️ Compte reel 13137475 : ordre REFUSE'
corps = '\n'.join(lignes)
if any(not x['t_demo'] for x in suivis):
    corps += ('\n\n⚠️ Un ordre parti sur le reel SANS le demo vient du dispatch '
              'direct, pas du miroir : les deux routes sont evaluees separement.')
if ko:
    corps += ('\n\nUn refus vient du COMPTE : marge, plafond de positions, '
              'ou perte journaliere.')

print(json.dumps({
    'title': titre,
    'body': corps,
    'dedup_key': 'reel_13137475_' + '_'.join(sorted(x['prix'] for x in suivis)),
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
