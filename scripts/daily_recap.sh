#!/bin/bash
# Wrapper cron du recap quotidien.
#
# ⚠️ Corrige le 2026-08-04. L'ancienne version lisait les cles Binance dans
# l'environnement du service `binance-bridge-rd` :
#
#     BRIDGE_PID=$(systemctl show binance-bridge-rd.service -p MainPID --value)
#     BINANCE_KEYS=$(cat /proc/$BRIDGE_PID/environ | ...)
#
# Depuis la desactivation d'admin_binance le 2026-08-02, ce service est
# arrete, MainPID vaut 0, et `cat /proc/0/environ` echoue. Avec `set -e`, le
# script mourait AVANT sa premiere ligne de log — donc chaque nuit a 22h,
# sans la moindre trace ni alerte. Dernier recap recu : 2026-08-01.
#
# Deux principes appliques :
#   - une source de donnees absente degrade le recap, elle ne l'annule pas
#   - un echec du recap se signale sur le canal infra, il ne se tait pas
set -uo pipefail   # PAS -e : cf. ci-dessus

ENV_FILE=/opt/scalping/.env
LOG=/var/log/scalping-daily-recap.log
# Le defaut etait `sales`, c'est-a-dire le bot « IC MARKETS trades » : un
# recap transverse partait chaque nuit dans le fil du compte reel.
TARGET="${RECAP_TARGET:-infra}"

alerter() {
  # Le recap qui echoue doit le dire. Cles lues dans le .env, pas dans un
  # processus qui peut etre arrete — c'est ce qui a cause la panne.
  local msg="$1"
  local tok chat
  tok=$(grep -m1 '^INFRA_TELEGRAM_BOT_TOKEN=' "$ENV_FILE" 2>/dev/null | cut -d= -f2-)
  chat=$(grep -m1 '^INFRA_TELEGRAM_CHAT_ID=' "$ENV_FILE" 2>/dev/null | cut -d= -f2-)
  [ -n "$tok" ] && [ -n "$chat" ] && curl -sS --max-time 10 -X POST \
    "https://api.telegram.org/bot${tok}/sendMessage" \
    -d "chat_id=${chat}" \
    --data-urlencode "text=🚨 Recap quotidien en echec — ${msg}" > /dev/null
}

{
  echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) daily_recap start target=$TARGET ==="

  # ── Cles Binance : optionnelles ────────────────────────────────────
  BINANCE_KEYS=""
  BINANCE_FLAG=""
  BRIDGE_PID=$(systemctl show binance-bridge-rd.service -p MainPID --value 2>/dev/null || echo 0)
  if [ "${BRIDGE_PID:-0}" != "0" ] && [ -r "/proc/${BRIDGE_PID}/environ" ]; then
    BINANCE_KEYS=$(tr '\0' '\n' < "/proc/${BRIDGE_PID}/environ" \
      | grep -E '^BINANCE_(API_KEY|API_SECRET|ENV)=' || true)
    echo "binance: service actif (pid ${BRIDGE_PID})"
  else
    BINANCE_FLAG="BINANCE_DISABLED=1"
    echo "binance: service arrete — bloc degrade, le recap continue"
  fi

  # ── Cles Telegram : indispensables ─────────────────────────────────
  RADAR_PID=$(docker inspect --format '{{.State.Pid}}' scalping-radar 2>/dev/null || echo 0)
  SALES_KEYS=""
  if [ "${RADAR_PID:-0}" != "0" ] && [ -r "/proc/${RADAR_PID}/environ" ]; then
    SALES_KEYS=$(tr '\0' '\n' < "/proc/${RADAR_PID}/environ" \
      | grep -E '^(SALES|INFRA)_TELEGRAM_(BOT_TOKEN|CHAT_ID)=' || true)
  fi
  if [ -z "$SALES_KEYS" ]; then
    echo "ERREUR: cles Telegram illisibles (conteneur arrete ?) — abandon"
    alerter "cles Telegram illisibles, conteneur scalping-radar arrete ?"
    echo "=== done (echec) ==="
    exit 1
  fi

  env -i HOME=/tmp \
    PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    $BINANCE_FLAG $BINANCE_KEYS $SALES_KEYS \
    /opt/binance-bridge/venv/bin/python /opt/scalping/scripts/daily_recap.py --target "$TARGET"
  CODE=$?
  if [ $CODE -ne 0 ]; then
    echo "ERREUR: daily_recap.py sortie $CODE"
    alerter "daily_recap.py a echoue (code $CODE)"
  fi
  echo "=== done ==="
} >> "$LOG" 2>&1
