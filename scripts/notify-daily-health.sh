#!/bin/bash
# BUT: sante de la chaine (bridges, crons) et RECAP de toutes les sondes
# PERIODE_MIN: 60
# Sante de la chaine + recap des sondes, sur le canal infra.
#
# Il appelle l'API Telegram EN DIRECT, et c'est VOULU : il surveille la
# chaine, donc le faire transiter par l'application le rendrait muet
# precisement quand elle tombe — le cas qu'il existe pour signaler.
#
# Répond à une seule question : « est-ce que la machine tourne ? »
#
# Remplace notify-silent-destinations.sh, qui ne couvrait que le dispatch.
# ⚠️ Trou constaté le 2026-08-04 : `scalping-bridge-monitor` ne sonde que le
# bridge Demo (8787). Le Live (8788) est couvert par monitor_live_bridge.sh,
# mais les deux bridges Kraken (8790, 8791) n'étaient surveillés par RIEN —
# alors qu'ils engagent de l'argent réel.
#
# ⚠️ Le message part TOUS LES JOURS, y compris quand tout va bien : une
# alerte qui ne parle qu'en cas de problème rend un cron cassé indiscernable
# d'une situation saine.
#
# Cron : 06h30 UTC = 08h30 Paris.
set -uo pipefail

ENV_FILE=/opt/scalping/.env
DB=/opt/scalping/data/trades.db
FENETRE_H=${FENETRE_H:-24}

BOT=$(grep -m1 '^INFRA_TELEGRAM_BOT_TOKEN=' "$ENV_FILE" | cut -d= -f2-)
CHAT=$(grep -m1 '^INFRA_TELEGRAM_CHAT_ID=' "$ENV_FILE" | cut -d= -f2-)
if [ -z "$BOT" ] || [ -z "$CHAT" ]; then
  echo "creds infra absentes" >&2
  exit 1
fi

cle() { grep -m1 "^$1=" "$ENV_FILE" | cut -d= -f2-; }

# ── 1. Bridges ───────────────────────────────────────────────────────
# Sonde directe plutôt que lecture d'un log : on veut l'état MAINTENANT,
# et un moniteur en panne ne doit pas passer pour un bridge en bonne santé.
BRIDGES=""
ALERTES=""
sonder() {  # $1 = libellé, $2 = var URL, $3 = var clé, $4 = nom du header
  local url cle_val code
  url=$(cle "$2"); cle_val=$(cle "$3")
  if [ -z "$url" ]; then
    BRIDGES="${BRIDGES}\n  ${1} — non configuré"
    return
  fi
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 8 -H "$4: ${cle_val}" "${url}/health" 2>/dev/null)
  if [ "$code" = "200" ]; then
    BRIDGES="${BRIDGES}\n  ✅ ${1}"
  else
    BRIDGES="${BRIDGES}\n  ❌ ${1} — injoignable (HTTP ${code:-0})"
    ALERTES="${ALERTES}\n• Bridge ${1} injoignable"
  fi
}
sonder "MT5 Demo"      MT5_BRIDGE_URL             MT5_BRIDGE_API_KEY             "X-API-Key"
sonder "MT5 Live"      MT5_BRIDGE_LIVE_URL        MT5_BRIDGE_LIVE_API_KEY        "X-API-Key"
sonder "Kraken"        KRAKEN_BRIDGE_URL          KRAKEN_BRIDGE_API_KEY          "X-Bridge-Key"
sonder "Kraken Spot"   KRAKEN_SPOT_BRIDGE_URL     KRAKEN_SPOT_BRIDGE_API_KEY     "X-Bridge-Key"

# ── 2. Dispatch : qui pousse, qui se tait ────────────────────────────
# Une destination muette dont les rejets sont majoritairement une coupure
# VOLONTAIRE (porte de cout, porte d'horizon, blackout earnings, gel
# week-end) est coupee par conception : elle est affichee en information,
# pas en alerte.
SINCE=$(date -u -d "-${FENETRE_H} hours" '+%Y-%m-%dT%H:%M:%S')
SINCE_J=$(date -u -d "-${FENETRE_H} hours" '+%Y-%m-%d')

DISPATCH=$(SINCE="$SINCE" SINCE_J="$SINCE_J" DB="$DB" python3 <<'PY'
import json, os, sqlite3

# Codes de refus « par conception » : une coupure volontaire, pas une panne.
# ⚠️ Tout futur code de refus volontaire (nouvelle porte, nouveau veto
# structurel) DOIT être ajouté ici, sous peine de faire déclencher une
# fausse alerte 🚨 sur des destinations correctement coupées.
CODES_PAR_CONCEPTION = frozenset({
    "fees_exceed_edge",
    "horizon_not_allowed",
    "earnings_blackout",
    "weekend_hold_blocked",
})

db, since, since_j = os.environ["DB"], os.environ["SINCE"], os.environ["SINCE_J"]
c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30)

pousses, bloques, bloques_porte_cout = {}, {}, {}
for d, n in c.execute(
        "SELECT destination_id, SUM(CASE WHEN ok=1 THEN 1 ELSE 0 END) "
        "  FROM mt5_pushes WHERE pushed_at >= ? GROUP BY 1", (since,)):
    if d:
        pousses[d] = n or 0
for d, code, n in c.execute(
        "SELECT destination_id, reason_code, COUNT(*) FROM signal_rejections "
        " WHERE created_at >= ? GROUP BY 1, 2", (since,)):
    if d:
        bloques[d] = bloques.get(d, 0) + n
        if code in CODES_PAR_CONCEPTION:
            bloques_porte_cout[d] = bloques_porte_cout.get(d, 0) + n
try:
    for d, code, n in c.execute(
            "SELECT destination_id, reason_code, SUM(count) FROM silent_drop_counters "
            " WHERE day >= ? GROUP BY 1, 2", (since_j,)):
        if d:
            bloques[d] = bloques.get(d, 0) + (n or 0)
            if code in CODES_PAR_CONCEPTION:
                bloques_porte_cout[d] = bloques_porte_cout.get(d, 0) + (n or 0)
except sqlite3.OperationalError:
    pass

vues = sorted(set(pousses) | set(bloques))
muettes_toutes = [d for d in vues if not pousses.get(d)]
# Une destination coupee par conception (majorite des rejets dans
# CODES_PAR_CONCEPTION) n'est pas une panne : elle est affichee en
# information, sans declencher l'alerte.
muettes_porte_cout = [
    d for d in muettes_toutes
    if bloques.get(d) and bloques_porte_cout.get(d, 0) > bloques[d] / 2
]
muettes = [d for d in muettes_toutes if d not in muettes_porte_cout]
actives = [(d, pousses[d]) for d in vues if pousses.get(d)]
print(json.dumps({
    "muettes": muettes,
    "muettes_porte_cout": muettes_porte_cout,
    "actives": actives,
    "bloques": bloques,
}))
PY
)

# ── 3. Crons critiques : ont-ils tourné ? ────────────────────────────
CRONS=""
verifier_cron() {  # $1 = libellé, $2 = fichier de log, $3 = âge max en heures
  local age_max_s=$(( $3 * 3600 ))
  if [ ! -f "$2" ]; then
    CRONS="${CRONS}\n  ❌ ${1} — aucun log"
    ALERTES="${ALERTES}\n• Cron ${1} sans trace"
    return
  fi
  local age=$(( $(date +%s) - $(stat -c %Y "$2") ))
  if [ "$age" -le "$age_max_s" ]; then
    CRONS="${CRONS}\n  ✅ ${1}"
  else
    CRONS="${CRONS}\n  ❌ ${1} — muet depuis $(( age / 3600 )) h"
    ALERTES="${ALERTES}\n• Cron ${1} muet depuis $(( age / 3600 )) h"
  fi
}
verifier_cron "Récap quotidien"  /var/log/scalping-daily-recap.log        30
verifier_cron "Notifs de push"   /var/log/scalping/notify-pushes.log       1
verifier_cron "Sauvegarde S3"    /var/log/scalping-backup.log             30

# ── 4. Message ───────────────────────────────────────────────────────
CORPS=$(DISPATCH="$DISPATCH" BRIDGES="$BRIDGES" CRONS="$CRONS" \
        ALERTES="$ALERTES" FENETRE_H="$FENETRE_H" python3 <<'PY'
import json, os

d = json.loads(os.environ.get("DISPATCH") or "{}")
alertes = [a for a in os.environ.get("ALERTES", "").split("\\n") if a.strip()]
muettes, actives, bloques = d.get("muettes", []), d.get("actives", []), d.get("bloques", {})
muettes_porte_cout = d.get("muettes_porte_cout", [])

for m in muettes:
    alertes.append(f"• {m} n'a rien exécuté ({bloques.get(m, 0)} tentatives bloquées)")

lignes = []
if alertes:
    lignes.append(f"🚨 <b>{len(alertes)} problème(s)</b>")
    lignes.append("")
    lignes.extend(alertes)
    lignes.append("")
else:
    lignes.append("✅ <b>Chaîne opérationnelle</b>")
    lignes.append("")

lignes.append("<b>Bridges</b>" + os.environ.get("BRIDGES", ""))
lignes.append("")
lignes.append("<b>Dispatch</b>")
if actives:
    for dest, n in sorted(actives, key=lambda x: -x[1]):
        lignes.append(f"  ✅ {dest} — {n} ordre(s) sur {os.environ.get('FENETRE_H')} h")
else:
    lignes.append("  ⚠️ aucun ordre passé, toutes destinations confondues")
for m in muettes:
    lignes.append(f"  ❌ {m} — 0 ordre, {bloques.get(m, 0)} bloqués")
for m in muettes_porte_cout:
    lignes.append(f"  ℹ️ {m} — arrêtée par la porte de coût ({bloques.get(m, 0)} refus)")
if not actives and not muettes and not muettes_porte_cout:
    lignes.append("  ⚠️ aucune destination n'apparaît dans les journaux")
lignes.append("")
lignes.append("<b>Crons</b>" + os.environ.get("CRONS", ""))

print("\\n".join(lignes).replace("\\\\n", "\\n"))
PY
)

# ── Le recap de TOUTES les sondes (2026-09-06) ───────────────────────
#
# Demande : savoir, pour chaque sonde, ce qu'elle verifie et si elle est OK
# ou KO. Un message par PASSAGE serait 8 507 messages par jour — un toutes
# les dix secondes. On enregistre chaque passage (scripts/sonde.sh) et on le
# DIT ici, en un seul bloc, a chaque passage du healthcheck.
#
# Lecture non bloquante : si le conteneur est injoignable, la sante des
# BRIDGES doit partir quand meme — c'est justement le moment ou elle compte.
# Mais l'echec se DIT : un bloc absent en silence se lirait comme « aucune
# sonde a signaler ».
RECAP_SONDES=$(docker exec -i scalping-radar python -c '
import sys
sys.path.insert(0, "/app")
from backend.services import journal_sondes as j
titre, corps = j.message(j.bilan())
print(titre)
print(corps)
' 2>/dev/null)
if [ -z "$RECAP_SONDES" ]; then
  RECAP_SONDES="Journal des sondes ILLISIBLE — ce n'est pas « aucune sonde a signaler », c'est « on ne sait pas »."
fi

MESSAGE=$(printf "<b>Santé · %s</b>

%s

───────────────
%s" "$(date -u '+%d/%m %H:%M')" "$CORPS" "$RECAP_SONDES")

if [ "${DRY_RUN:-0}" = "1" ]; then
  echo "----- DRY RUN -----"
  echo -e "$MESSAGE"
  exit 0
fi

# ⛔ La reponse de Telegram etait JETEE : le script sortait en SUCCES meme si
# l'envoi etait refuse — jeton revoque, chat introuvable, balise HTML mal
# formee. Le recap qui surveille tout le reste ne surveillait donc pas sa
# PROPRE arrivee, et son silence se serait lu comme « tout va bien ».
#
# 🔑 En sortant en ECHEC, il se signale lui-meme : l'enveloppe `sonde.sh` le
# voit KO et crie immediatement. C'est le seul message dont l'echec ne peut
# pas etre annonce par un autre message.
REPONSE=$(curl -sS --max-time 15 -X POST \
  "https://api.telegram.org/bot${BOT}/sendMessage" \
  -d "chat_id=${CHAT}" \
  --data-urlencode "text=$(echo -e "$MESSAGE")" \
  -d "parse_mode=HTML" -d "disable_web_page_preview=true" 2>&1)

if echo "$REPONSE" | grep -q '"ok":true'; then
  # ⛔ L'IDENTIFIANT du message est journalise. « Telegram a confirme » ne
  # suffisait pas : quand Xavier a dit ne pas avoir recu le recap de 22h, il a
  # fallu renvoyer un temoin pour prouver ou il etait parti. Avec l'id, le log
  # devient verifiable — un objet qu'on peut retrouver dans la conversation.
  ID=$(echo "$REPONSE" | grep -oE '"message_id":[0-9]+' | head -1 | cut -d: -f2)
  CIBLE=$(echo "$REPONSE" | grep -oE '"username":"[^"]+"' | head -1 | cut -d'"' -f4)
  echo "$(date -Iseconds) sante envoyee — Telegram a CONFIRME (message ${ID:-?} vers @${CIBLE:-?})"
else
  echo "$(date -Iseconds) sante NON DELIVREE : $(echo "$REPONSE" | head -c 300)" >&2
  exit 1
fi
