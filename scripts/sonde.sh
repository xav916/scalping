#!/bin/bash
# Enveloppe qui ENREGISTRE le passage d'une sonde, sans rien changer d'autre.
#
#   sonde.sh /opt/scalping/scripts/ma-sonde.sh [arguments...]
#
# Elle lit deux lignes d'en-tete dans le script enrobe :
#
#   # BUT: ce que cette sonde verifie, en une phrase
#   # PERIODE_MIN: 15
#
# ⛔ Le but vit AVEC la sonde. Une table de correspondance nom -> but serait
# une deuxieme table, donc une table qui derive — la lecon des trois tables de
# canaux du 06/09.
#
# ⛔ Elle est TRANSPARENTE : meme sortie, meme code de retour. Une enveloppe
# qui avale un code de sortie transformerait un echec en succes, ce qui est
# exactement le contraire de ce qu'on installe ici.
#
# ⚠️ Elle ne poste RIEN sur Telegram. 8 507 passages de cron par jour : un
# message par passage serait un message toutes les dix secondes. Le healthcheck
# lit le journal et en fait UN recap.
set -uo pipefail

CIBLE="${1:-}"
if [ -z "$CIBLE" ]; then
  echo "usage: sonde.sh <script> [args...]" >&2
  exit 2
fi
shift

if [ ! -f "$CIBLE" ]; then
  echo "sonde.sh: cible introuvable : $CIBLE" >&2
  exit 2
fi

NOM=$(basename "$CIBLE")
BUT=$(grep -m1 -E '^#\s*BUT:' "$CIBLE" 2>/dev/null | sed -E 's/^#\s*BUT:\s*//')
PERIODE=$(grep -m1 -E '^#\s*PERIODE_MIN:' "$CIBLE" 2>/dev/null | sed -E 's/^#\s*PERIODE_MIN:\s*//' | tr -dc '0-9')

DEBUT=$(date +%s%3N)
# ⚠️ La sortie est DUPLIQUEE : elle va au log comme avant, et une copie sert
# a garder les dernieres lignes en cas d'echec. Les avaler priverait le recap
# de la seule chose qui explique un KO.
SORTIE=$(mktemp)
"$CIBLE" "$@" 2>&1 | tee "$SORTIE"
CODE=${PIPESTATUS[0]}
FIN=$(date +%s%3N)
DUREE=$((FIN - DEBUT))

# ⛔ Le detail n'est garde qu'en cas d'ECHEC. Sur un succes il n'apprend rien
# et gonflerait la base a chaque passage — 8 507 par jour.
if [ "$CODE" -ne 0 ]; then
  DETAIL=$(tail -c 400 "$SORTIE" | tr '\n' ' ' | tr -d '"')
else
  DETAIL=""
fi
rm -f "$SORTIE"

# ⚠️ L'enregistrement ne doit JAMAIS faire echouer la sonde : son propre
# resultat prime. D'ou le `|| true` et la redirection.
#
# Le journal rend la DECISION d'alerter : il connait l'etat precedent, donc
# lui seul peut distinguer une nouvelle panne d'une panne qui dure.
DECISION=$(NOM="$NOM" BUT="$BUT" CODE="$CODE" DUREE="$DUREE" DETAIL="$DETAIL" \
PERIODE="$PERIODE" docker exec -i \
  -e NOM -e BUT -e CODE -e DUREE -e DETAIL -e PERIODE \
  scalping-radar python -c '
import json, os, sys
sys.path.insert(0, "/app")
from backend.services import journal_sondes as j
p = os.environ.get("PERIODE") or ""
but = os.environ.get("BUT") or None
code = int(os.environ.get("CODE") or 1)
r = j.enregistrer(
    nom=os.environ["NOM"], but=but, code_sortie=code,
    duree_ms=int(os.environ.get("DUREE") or 0),
    detail=os.environ.get("DETAIL") or None,
    periode_min=int(p) if p.isdigit() else None,
)
if r["crier"]:
    titre, corps = j.alerte(os.environ["NOM"], but, r["motif"],
                            os.environ.get("DETAIL") or None, code)
    print(json.dumps({"titre": titre, "corps": corps}, ensure_ascii=False))
' 2>/dev/null) || true

# ⛔ Le cri part de l HOTE, en direct, PAS par l endpoint de l application :
# une sonde peut echouer PARCE QUE l application est tombee, et c est
# precisement ce moment-la qu il faut pouvoir signaler. Meme raison que pour
# le healthcheck.
#
# ⚠️ Rien n est envoye quand tout va bien : sur 8 530 passages par jour, le
# silence est la norme. Le journal decide, l enveloppe se contente d obeir.
if [ -n "$DECISION" ]; then
  BOT=$(grep -m1 '^INFRA_TELEGRAM_BOT_TOKEN=' /opt/scalping/.env 2>/dev/null | cut -d= -f2-)
  CHAT=$(grep -m1 '^INFRA_TELEGRAM_CHAT_ID=' /opt/scalping/.env 2>/dev/null | cut -d= -f2-)
  if [ -n "$BOT" ] && [ -n "$CHAT" ]; then
    TEXTE=$(DECISION="$DECISION" python3 -c '
import json, os
d = json.loads(os.environ["DECISION"])
print(d["titre"] + "\n\n" + d["corps"])
' 2>/dev/null)
    [ -n "$TEXTE" ] && curl -sS --max-time 10 -X POST \
      "https://api.telegram.org/bot${BOT}/sendMessage" \
      -d "chat_id=${CHAT}" --data-urlencode "text=${TEXTE}" \
      -d "disable_web_page_preview=true" >/dev/null 2>&1 || true
  fi
fi

exit "$CODE"
