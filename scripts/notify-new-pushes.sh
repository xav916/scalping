#!/bin/bash
# BUT: detecte les ordres pousses que le courtier n'a jamais confirmes
# PERIODE_MIN: 2
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
# push qui n'a jamais été confirmé. Il couvre TOUTES les destinations et part
# donc sur le fil `sales` — le fil `trades` est réservé au compte réel
# 13137475, dont les refus sont déjà portés par notify-ordres-reel.sh.
#
# Usage :
#   notify-new-pushes.sh           → alerte sur les pushes non confirmés
#   DRY_RUN=1 notify-new-pushes.sh → affiche sans envoyer
set -uo pipefail

# Surchargeables pour que le garde-fou de lecture soit VERIFIABLE, pas
# seulement plausible : cf. le test de lecture ratee ci-dessous.
DB=${DB:-/opt/scalping/data/trades.db}
ETAT=${ETAT:-/var/lib/scalping/last-failed-push-id.txt}
TOKEN="shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg"
# Le fil suit le COMPTE du push (2026-09-06).
#
# Jusqu'ici tout partait sur `channel=sales`, c'est-a-dire le bot nomme
# « IC MARKETS trades » : les echecs de push Kraken et demo s'y melaient aux
# reels. Le script connait pourtant `destination_id` a chaque ligne.
#
# La table des canaux est lue dans le MODULE, jamais recopiee ici — c'est la
# duplication qui avait deja fait afficher « Demo » sur des trades Kraken.
BASE_URL="https://app.scalping-radar.online/api/admin/notify-infra-telegram?token=${TOKEN}"
CANAUX=$(docker exec scalping-radar python -m backend.services.canaux_telegram 2>/dev/null)
canal() {  # $1 = destination_id -> canal, `infra` si inconnu ou table illisible
  local c
  c=$(echo "$CANAUX" | grep -m1 "^$1=" | cut -d= -f2)
  echo "${c:-infra}"
}

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

# ⛔ Un `sqlite3` qui echoue rend une chaine VIDE, exactement comme une requete
# sans resultat. Sans verification du code de retour, un verrou de base se lit
# « aucun push en echec » — et le curseur avance par-dessus des echecs reels,
# perdus alors pour toujours.
#
# Mesure du 2026-08-25 : 30 erreurs `database is locked` dans ce journal, et
# 13 refus `unsupported pair` (20 au 24/08) jamais signales. La cause du verrou
# etait sept sauvegardes `.bak` laissees dans /etc/cron.d, qui faisaient tourner
# ce script huit fois en parallele. Le verrou est corrige ; la CONFUSION entre
# « echec » et « vide », elle, vivait ici.
#
# `.timeout` fait patienter plutot qu'echouer sur un verrou passager.
# ⚠️ Elle REND un code, elle ne sort pas elle-meme : appelee dans `$(...)`,
# un `exit` ne quitterait que le sous-shell et le script continuerait avec une
# chaine vide — soit exactement le defaut qu'on corrige. C'est a l'appelant de
# s'arreter, avec `|| { ... exit 3; }`.
lire_base() {  # $1 = requete SQL. Rend la sortie, ou le code 3 si la lecture echoue.
  local sortie rc
  sortie=$(sqlite3 -cmd ".timeout 10000" "$DB" "$1" 2>&1); rc=$?
  if [ $rc -ne 0 ]; then
    {
      echo "$(date -Iseconds) notify-new-pushes ❌ LECTURE IMPOSSIBLE (sqlite3 rc=$rc)"
      echo "  $sortie"
    } >&2
    return 3
  fi
  printf '%s' "$sortie"
}

mkdir -p "$(dirname "$ETAT")"
[ -f "$ETAT" ] || echo 0 > "$ETAT"
dernier=$(cat "$ETAT"); dernier=${dernier:-0}

lignes=$(lire_base "
  SELECT id||'|'||coalesce(destination_id,'?')||'|'||pair||'|'||direction||'|'||
         pushed_at||'|'||replace(substr(coalesce(bridge_response,''),1,300),'|','/')
    FROM mt5_pushes
   WHERE id > $dernier
     AND ok = 0
     AND pushed_at < datetime('now','-${DELAI_MIN} minutes')
   ORDER BY id ASC LIMIT 10;") || {
  echo "  ⚠️ curseur CONSERVE a $dernier — rien n'est conclu d'une lecture ratee" >&2
  exit 3
}

echo "$(date -Iseconds) notify-new-pushes (pushes non confirmes, curseur=$dernier)"

if [ -z "$lignes" ]; then
  # Le curseur doit quand même avancer au-delà des pushes réussis, sinon la
  # requête les réexamine indéfiniment.
  max_ok=$(lire_base "SELECT coalesce(max(id),$dernier) FROM mt5_pushes
                       WHERE ok = 1 AND id > $dernier;") || {
  echo "  ⚠️ curseur CONSERVE a $dernier — rien n'est conclu d'une lecture ratee" >&2
  exit 3
}
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
    curl -sS -m 5 -X POST "${BASE_URL}&channel=$(canal "$dest")" -H "Content-Type: application/json" \
      --data "{\"title\":\"$titre\",\"body\":\"$corps\",\"dedup_key\":\"push_echec_${id}\",\"cooldown_seconds\":86400}" \
      > /dev/null || true
  fi
  max=$id
done <<< "$lignes"

[ "${DRY_RUN:-0}" = "1" ] || echo "$max" > "$ETAT"
echo "  traité jusqu'à id=$max"
