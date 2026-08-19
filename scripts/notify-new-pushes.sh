#!/bin/bash
# Alerte infra sur les pushes d'ordre qui n'ont PAS abouti.
#
# ⚠️ Ce script n'envoie plus le message « trade ouvert » (2026-08-04).
#
# Il en existait deux versions en parallèle, et personne ne l'avait vu :
#
#   send_trade_opened (Python)   canal Scalping Radar · format complet
#                                (SL, TP, montants en euros, justification)
#                                branché sur MT5 et Binance seulement
#
#   ce script (shell)            canal sales · format dégradé, sans SL ni TP,
#                                prix brut `63924.00000000001`, broker répété
#                                deux fois — mais branché sur TOUTES les
#                                destinations
#
# D'où le symptôme : les trades Kraken n'arrivaient que par le second, dans
# le mauvais format et sur le mauvais canal. Le hook Python couvre désormais
# Kraken Futures et Spot ; ce script cesse de le doubler.
#
# Ce qu'il reste à faire ici, et que le hook ne peut pas faire : signaler un
# push qui n'a jamais été confirmé. C'est un évènement d'infrastructure —
# il part donc sur le canal infra, conformément à la répartition convenue
# (infra → Xav Scalping Infra, trades → Scalping Radar, récap → Sales).
#
# Usage :
#   notify-new-pushes.sh           → alerte sur les pushes non confirmés
#   DRY_RUN=1 notify-new-pushes.sh → affiche sans envoyer
set -uo pipefail

DB=/opt/scalping/data/trades.db
ETAT=/var/lib/scalping/last-failed-push-id.txt
TOKEN="shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg"
# channel=sales : un push refuse est un evenement de TRADING, pas d'infra. Le
# bot infra est reserve au monitoring (cf. separation du 2026-08-02).
URL="https://app.scalping-radar.online/api/admin/notify-infra-telegram?token=${TOKEN}&channel=sales"

# Un push est inséré à `ok=0` AVANT l'envoi, puis passé à `ok=1` s'il aboutit.
# Un `ok=0` récent est donc peut-être simplement en vol : on laisse une marge
# avant de crier. Sans cela, chaque ordre normal déclencherait une alerte.
DELAI_MIN=5

# Libellés lus dans le registre des destinations — plus de table recopiée ici.
# C'est la duplication qui avait fait afficher « Démo » sur des trades Kraken
# engageant de l'argent réel.
REGISTRE=$(docker exec scalping-radar python -m backend.services.destinations_registry 2>/dev/null)
[ -z "$REGISTRE" ] && REGISTRE='{}'

libelle() {  # $1 = destination_id → libellé lisible, ou l'id brut si inconnu
  echo "$REGISTRE" | REG_ID="$1" python3 -c "
import json, os, sys
try:
    d = json.load(sys.stdin).get(os.environ['REG_ID'])
    print(d['mode'] if d else os.environ['REG_ID'])
except Exception:
    print(os.environ['REG_ID'])
" 2>/dev/null || echo "$1"
}

mkdir -p "$(dirname "$ETAT")"
[ -f "$ETAT" ] || echo 0 > "$ETAT"
dernier=$(cat "$ETAT"); dernier=${dernier:-0}

lignes=$(sqlite3 "$DB" "
  SELECT id||'|'||coalesce(destination_id,'?')||'|'||pair||'|'||direction||'|'||
         pushed_at||'|'||replace(substr(coalesce(bridge_response,''),1,300),'|','/')
    FROM mt5_pushes
   WHERE id > $dernier
     AND ok = 0
     AND pushed_at < datetime('now','-${DELAI_MIN} minutes')
   ORDER BY id ASC LIMIT 10;")

echo "$(date -Iseconds) notify-new-pushes (pushes non confirmes, curseur=$dernier)"

if [ -z "$lignes" ]; then
  # Le curseur doit quand même avancer au-delà des pushes réussis, sinon la
  # requête les réexamine indéfiniment.
  max_ok=$(sqlite3 "$DB" "SELECT coalesce(max(id),$dernier) FROM mt5_pushes
                           WHERE ok = 1 AND id > $dernier;")
  [ "${DRY_RUN:-0}" = "1" ] || echo "${max_ok:-$dernier}" > "$ETAT"
  echo "  aucun push en echec"
  exit 0
fi

max=$dernier
while IFS='|' read -r id dest pair dir ts reponse; do
  [ -z "$id" ] && continue
  plateforme=$(libelle "$dest")
  dir_mot="ACHAT"; [ "$dir" = "sell" ] && dir_mot="VENTE"

  # La réponse dit si l'issue est connue (rejet explicite) ou indéterminée
  # (timeout, exception). Le second cas est le plus important : un ordre a
  # pu être rempli sans que le système le sache.
  if echo "$reponse" | grep -qiE "timeout|error.*:.*\"[^\"]"; then
    titre="⚠️ Push non confirmé · ${pair} ${dir_mot}"
    entete="Un ordre a pu partir chez le broker sans confirmation."
    action="Vérifier les positions ouvertes chez le broker AVANT de relancer."
  else
    titre="❌ Push refusé · ${pair} ${dir_mot}"
    entete="L'ordre n'a pas été accepté."
    action="Aucune position ouverte de ce fait."
  fi

  corps="${entete}\n\nPlateforme : ${plateforme}\nTenté : ${ts}\n\n📋 Réponse du bridge\n${reponse:-(vide)}\n\n👉 ${action}"

  if [ "${DRY_RUN:-0}" = "1" ]; then
    echo "  ----- id=${id} -----"
    echo "  $titre"
    echo -e "$corps" | sed 's/^/    /'
  else
    curl -sS -m 5 -X POST "$URL" -H "Content-Type: application/json" \
      --data "{\"title\":\"$titre\",\"body\":\"$corps\",\"dedup_key\":\"push_echec_${id}\",\"cooldown_seconds\":86400}" \
      > /dev/null || true
  fi
  max=$id
done <<< "$lignes"

[ "${DRY_RUN:-0}" = "1" ] || echo "$max" > "$ETAT"
echo "  traité jusqu'à id=$max"
