#!/bin/bash
# BUT: surveille la sante du bridge live IC Markets
# PERIODE_MIN: 15
# Moniteur du bridge Live (IC Markets) — ping /health toutes les 15 min.
#
# ⛔ RECUPERE DE LA PROD LE 06/09/2026. Ce script tournait toutes les quinze
# minutes depuis le 14/07 sans exister dans le depot, sous AUCUN nom : personne
# ne pouvait le relire, le tester, ni savoir qu'il avait change. C'est le
# moniteur du bridge live — celui-la meme qui etait reste MUET trois mois.
# Verse ici tel quel, a une exception pres, ci-dessous.
#
# ⚠️ Il omettait `channel`, et tombait donc sur le fil infra par le DEFAUT
# SILENCIEUX de l'endpoint. C'est le bon fil — la sante d'un bridge est de
# l'infra, pas un evenement de compte — mais le dire vaut mieux que le subir :
# le defaut est documente comme un piege, et un jour il changera.
#
# Alerte si : HTTP injoignable, ok:false, ou cles manquantes. Dedup 60 min.
set -euo pipefail

URL_HEALTH="${URL_HEALTH:-http://100.74.160.72:8788/health}"
TOKEN="shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg"
URL_NOTIFY="https://app.scalping-radar.online/api/admin/notify-infra-telegram?token=${TOKEN}&channel=infra"
STATE_DIR="/var/lib/scalping"
STATE_OK="${STATE_DIR}/live-bridge-last-ok.txt"

mkdir -p "$STATE_DIR"

TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
RESP=$(curl -sS -m 6 "$URL_HEALTH" 2>/dev/null || echo "")

send_alert() {
  local title="$1" body="$2" dedup="$3"
  curl -sS -m 5 -X POST "$URL_NOTIFY" \
    -H "Content-Type: application/json" \
    --data "{\"title\":\"$title\",\"body\":\"$body\",\"dedup_key\":\"$dedup\",\"cooldown_seconds\":3600}" \
    > /dev/null || true
}

if [ -z "$RESP" ]; then
  echo "$TS DOWN unreachable"
  send_alert "🔴 Bridge Live UNREACHABLE" \
    "Le bridge Live IC Markets ne répond plus (VPS 100.74.160.72:8788).\n\nAucun trade Live ne peut être exécuté tant que ça n'est pas résolu.\n\nAction : RDP au VPS scalping-bridge-vps → vérifier tâche ScalpingBridge_Live." \
    "live_bridge_unreachable"
  exit 0
fi

OK_VAL=$(echo "$RESP" | grep -oE '"ok"[[:space:]]*:[[:space:]]*(true|false)' | grep -oE '(true|false)' | head -1)

if [ "$OK_VAL" = "true" ]; then
  echo "$TS OK $RESP"
  echo "$TS" > "$STATE_OK"
  exit 0
fi

echo "$TS DOWN ok=$OK_VAL resp=$RESP"
send_alert "🟠 Bridge Live MT5 déconnecté" \
  "Le bridge Live répond mais MT5 IC Markets est déconnecté du broker (ok:false).\n\nLogin 13137475 · Server ICMarketsEU-MT5-5.\n\nAction : RDP au VPS → MT5 Live → clic droit compte → Se connecter." \
  "live_bridge_mt5_down"
