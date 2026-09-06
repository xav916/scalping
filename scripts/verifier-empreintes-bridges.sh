#!/bin/bash
# BUT: verifie que les bridges deployes sont ceux du depot
# PERIODE_MIN: 1440
# Compare ce que chaque bridge EXECUTE a ce qui est VERSIONNE (2026-08-25).
#
# Pourquoi ce script existe : le repli de resolution de symbole du bridge
# Kraken, ajoute le 2026-08-08, a disparu sans que personne le voie. Le fichier
# vivait hors git, une edition manuelle l'a ecrase, et rien ne permettait de
# comparer. Cout : 13 ordres refuses en `unsupported pair` entre le 20 et le
# 24/08, sur des instruments pourtant cotes.
#
# ⛔ Une estampille que personne ne compare ne sert a rien. C'est ce script,
# pas le champ `source_sha`, qui empeche la prochaine disparition.
#
# L'empreinte est calculee A L'IMPORT cote bridge : elle dit ce qui a ete
# CHARGE, pas ce qui traine sur le disque. Un fichier deploye mais dont le
# processus n'a pas ete relance apparait donc — a juste titre — comme une
# derive.
#
# Fins de ligne neutralisees des deux cotes : les fichiers du VPS sont en CRLF,
# le depot est stocke en LF.
#
# Usage :
#   verifier-empreintes-bridges.sh            -> compare + notifie si derive
#   DRY_RUN=1 verifier-empreintes-bridges.sh  -> compare sans notifier
set -uo pipefail

# ⚠️ /app, PAS /opt/scalping : les sources versionnees sont dans l IMAGE,
# construite depuis le depot au dernier deploiement. C est bien elle la
# reference — /opt/scalping n est pas un clone git.
DEPOT=${DEPOT:-/app}
TOKEN="shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg"
NOTIFY_URL="https://app.scalping-radar.online/api/admin/notify-infra-telegram?token=${TOKEN}&channel=infra"

# destination:chemin de la source versionnee
CIBLES="
admin_live:mt5-bridge/bridge.py
admin_legacy:mt5-bridge/bridge.py
admin_kraken:kraken-bridge/bridge.py
admin_kraken_spot:kraken-spot-bridge/bridge.py
"

RAPPORT=$(docker exec -i -e PYTHONPATH=/app -w /app scalping-radar python - "$DEPOT" "$CIBLES" <<'PY' 2>/dev/null
import hashlib, json, os, sys, urllib.request
from backend.services.destinations_registry import DESTINATIONS

depot, cibles = sys.argv[1], sys.argv[2]


def empreinte(chemin):
    """Fins de ligne neutralisees — le depot est en LF, le VPS en CRLF."""
    try:
        with open(chemin, "rb") as f:
            return hashlib.sha256(
                f.read().replace(bytes([13, 10]), bytes([10]))
            ).hexdigest()[:12]
    except OSError:
        return None


lignes = []
for entree in cibles.split():
    did, relatif = entree.split(":", 1)
    dest = DESTINATIONS.get(did)
    if dest is None:
        continue
    attendue = empreinte(os.path.join(depot, relatif))
    url = os.environ.get(dest.url_env or "", "")
    annoncee, lisible = None, False
    if url:
        try:
            rq = urllib.request.Request(
                url.rstrip("/") + "/health",
                headers={dest.key_header: os.environ.get(dest.key_env, "")},
            )
            with urllib.request.urlopen(rq, timeout=12) as r:
                charge = json.load(r)
            annoncee = charge.get("source_sha")
            lisible = True
        except Exception:
            pass
    lignes.append({"id": did, "badge": dest.badge, "source": relatif,
                   "attendue": attendue, "annoncee": annoncee,
                   "lisible": lisible})
print(json.dumps({"bridges": lignes}, ensure_ascii=False))
PY
)

if [ -z "$RAPPORT" ]; then
  echo "❌ aucun rapport (docker exec a échoué) — rien n'est conclu"
  exit 1
fi

echo "$RAPPORT" | python3 -c "
import json, sys

# Derives RECONNUES.
#
# Ce n'est PAS un mecanisme pour faire taire une alerte : chaque entree
# epingle les DEUX empreintes. Si le depot change, ou si le bridge change,
# la paire ne correspond plus et l'alarme revient d'elle-meme.
#
# Et l'etat reste AFFICHE, avec son motif. Une derive invisible serait le
# defaut qu'on evite : une alarme qui crie tous les matins finit par ne
# plus etre lue, et la vraie derive suivante passe avec elle.
ACCEPTEES = {
    ('admin_live', 'b0cc7eaa8606', 'dd8af8d61b7b'):
        'commentaire seul, renommage du 06/09 — non redemarre sur decision',
    ('admin_legacy', 'b0cc7eaa8606', 'dd8af8d61b7b'):
        'commentaire seul, idem admin_live',
}
d = json.load(sys.stdin)
for b in d['bridges']:
    if not b['lisible']:
        etat = 'INJOIGNABLE'
    elif b['annoncee'] is None:
        etat = 'PAS D EMPREINTE'
    elif b['attendue'] is None:
        etat = 'SOURCE INTROUVABLE'
    elif b['annoncee'] == b['attendue']:
        etat = 'conforme'
    elif (b['id'], b['attendue'], b['annoncee']) in ACCEPTEES:
        etat = 'derive ACCEPTEE'
    else:
        etat = 'DERIVE'
    motif = ACCEPTEES.get((b['id'], b['attendue'], b['annoncee']), '')
    print('  %-18s %-18s depot=%s bridge=%s%s' % (b['id'], etat, b['attendue'], b['annoncee'], ('  <- ' + motif) if motif else ''))
"

PAYLOAD=$(echo "$RAPPORT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
soucis = []
for b in d['bridges']:
    # ⚠️ Un bridge injoignable n'est PAS une dérive : le dire ainsi enverrait
    # chercher un écart de version là où il y a une panne réseau. Il a déjà
    # ses propres alertes.
    if not b['lisible']:
        continue
    if b['annoncee'] is None:
        soucis.append('%s  %s : aucune empreinte annoncee (bridge non estampille ?)'
                      % (b['badge'], b['id']))
    elif b['attendue'] is None:
        soucis.append('%s  %s : source versionnee introuvable (%s)'
                      % (b['badge'], b['id'], b['source']))
    elif b['annoncee'] != b['attendue']:
        soucis.append('%s  %s : DERIVE\n     depot  %s  (%s)\n     bridge %s'
                      % (b['badge'], b['id'], b['attendue'], b['source'], b['annoncee']))
if not soucis:
    print(''); raise SystemExit

corps = chr(10).join(soucis)
corps += chr(10) + chr(10) + (
    'Le bridge n execute pas ce qui est versionne. Soit le fichier a ete '
    'edite a la main sur le serveur, soit un deploiement n a pas ete suivi '
    'du redemarrage -- l empreinte est calculee au CHARGEMENT.')
print(json.dumps({
    'title': 'Bridges : derive entre code execute et code versionne',
    'body': corps,
    'dedup_key': 'derive_bridges_' + '_'.join(sorted(
        b['id'] for b in d['bridges'] if b['lisible'] and b['annoncee'] != b['attendue'])),
    'cooldown_seconds': 43200,
}))
")

if [ -z "$PAYLOAD" ]; then
  echo "✓ les bridges lisibles executent le code versionné"
  exit 0
fi

if [ "${DRY_RUN:-0}" = "1" ]; then
  echo "--- DRY_RUN : payload qui serait envoyé ---"
  echo "$PAYLOAD" | python3 -m json.tool
else
  echo "$PAYLOAD" | curl -sS -m 10 -X POST "$NOTIFY_URL" \
    -H 'Content-Type: application/json' --data @- \
    -o /dev/null -w 'notify HTTP %{http_code}\n' || true
fi
