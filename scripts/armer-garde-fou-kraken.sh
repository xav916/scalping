#!/bin/bash
# Arme le garde-fou des positions nues sur Kraken — en UN geste, vérifié.
#
# Trois valeurs, jamais deux : les deux drapeaux ne suffisent pas, il faut une
# DATE d'armement. Sans elle, `garde_fou_eligible` refuse tout, même avec les
# drapeaux à vrai (fail-closed délibéré).
#
#   /opt/scalping/.env       KRAKEN_SLTP_GUARD_AUTO_PROTECT_ENABLED=true
#   /opt/kraken-bridge/.env  KRAKEN_SLTP_GUARD_ENABLED=true
#   /opt/kraken-bridge/.env  KRAKEN_SLTP_GUARD_ACTIVATED_AT=<maintenant, UTC>
#
# 🔑 La date est posée par CE script, à l'instant de l'armement. Elle n'est
# jamais recalculée au démarrage : sinon une position ouverte avant un simple
# redémarrage redeviendrait éligible. Toute position ouverte AVANT reste gelée
# pour toujours — le script les NOMME avant de rendre la main, parce qu'un gel
# qu'on ne voit pas est un gel dont on ne se souvient pas.
#
# ⚠️ Ce script n'est PAS idempotent sur la date : le relancer réarme à l'instant
# présent et gèle donc tout ce qui a été ouvert entre-temps. Il refuse de le
# faire sans REARMER=1.
#
# Usage :
#   DRY_RUN=1 armer-garde-fou-kraken.sh   → montre ce qui serait fait
#   armer-garde-fou-kraken.sh             → arme pour de bon
set -uo pipefail

ENV_EC2=/opt/scalping/.env
ENV_BRIDGE=/opt/kraken-bridge/.env
HORODATAGE=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
SUFFIXE=$(date -u +%Y%m%d-%H%M%S)
DRY="${DRY_RUN:-0}"

echo "=== Armement du garde-fou Kraken ==="
echo "horodatage d'armement : $HORODATAGE"
[ "$DRY" = "1" ] && echo "(DRY_RUN — rien ne sera écrit)"
echo

DEJA=$(sudo grep -E "^KRAKEN_SLTP_GUARD_ACTIVATED_AT=." "$ENV_BRIDGE" 2>/dev/null | cut -d= -f2-)
if [ -n "$DEJA" ] && [ "${REARMER:-0}" != "1" ]; then
  echo "⛔ Déjà armé le $DEJA."
  echo "   Réarmer poserait une date NEUVE et gèlerait tout ce qui a été ouvert"
  echo "   depuis. Si c'est voulu : REARMER=1 $0"
  exit 1
fi

echo "--- Ce qui sera gelé pour toujours (ouvert avant l'armement) ---"
BK=$(sudo grep KRAKEN_BRIDGE_API_KEY "$ENV_BRIDGE" | cut -d= -f2)
curl -s -m 20 -H "X-Bridge-Key: $BK" http://127.0.0.1:8790/positions | python3 -c "
import json, sys
d = json.load(sys.stdin)
ps = d.get('positions') or []
if not ps:
    print('  (aucune position ouverte — rien à geler)')
for p in ps:
    print(f\"  {p.get('symbol')} {p.get('side')} {p.get('size')} — ouverte {p.get('fill_time') or 'DATE INCONNUE'}\")
print()
print('  ⚠️ Ces positions ne recevront JAMAIS de stop automatique, même nues.')
print('     Vérifier qu elles portent déjà leur stop avant d armer.')
" || echo "  ⚠️ positions illisibles — armer à l'aveugle n'est pas recommandé"
echo

if [ "$DRY" = "1" ]; then
  echo "--- Ce qui serait écrit ---"
  echo "  $ENV_EC2      : KRAKEN_SLTP_GUARD_AUTO_PROTECT_ENABLED=true"
  echo "  $ENV_BRIDGE   : KRAKEN_SLTP_GUARD_ENABLED=true"
  echo "  $ENV_BRIDGE   : KRAKEN_SLTP_GUARD_ACTIVATED_AT=$HORODATAGE"
  echo "  puis redémarrage de kraken-bridge.service et scalping.service"
  exit 0
fi

# Sauvegardes AVANT toute écriture, les deux côtés.
sudo cp -a "$ENV_EC2" "$ENV_EC2.bak-$SUFFIXE-gardefou"
sudo cp -a "$ENV_BRIDGE" "$ENV_BRIDGE.bak-$SUFFIXE-gardefou"
echo "sauvegardes : $ENV_EC2.bak-$SUFFIXE-gardefou et $ENV_BRIDGE.bak-$SUFFIXE-gardefou"

# `poser` remplace la ligne si la clé existe, l'ajoute sinon — jamais de
# doublon, qui laisserait la dernière occurrence décider en silence.
poser() {
  local fichier="$1" cle="$2" valeur="$3"
  if sudo grep -qE "^${cle}=" "$fichier"; then
    sudo sed -i "s|^${cle}=.*|${cle}=${valeur}|" "$fichier"
  else
    echo "${cle}=${valeur}" | sudo tee -a "$fichier" > /dev/null
  fi
}

poser "$ENV_EC2" KRAKEN_SLTP_GUARD_AUTO_PROTECT_ENABLED true
poser "$ENV_BRIDGE" KRAKEN_SLTP_GUARD_ENABLED true
poser "$ENV_BRIDGE" KRAKEN_SLTP_GUARD_ACTIVATED_AT "$HORODATAGE"

sudo systemctl restart kraken-bridge.service
sudo systemctl restart scalping

echo "--- Vérification de ce qui TOURNE (pas de ce qui est écrit) ---"
until curl -sf -m 5 -H "X-Bridge-Key: $BK" http://127.0.0.1:8790/health > /dev/null 2>&1; do sleep 2; done
curl -s -m 10 -H "X-Bridge-Key: $BK" http://127.0.0.1:8790/health | python3 -c "
import json, sys
d = json.load(sys.stdin)
for k in ('sltp_guard_enabled', 'sltp_guard_activated_at', 'sltp_guard_frozen_symbols'):
    print(f'  bridge  {k:26s} {d.get(k)}')
"
until sudo docker exec scalping-radar python -c "1" > /dev/null 2>&1; do sleep 3; done
sudo docker exec scalping-radar python -c "
from backend.services import kraken_sltp_guard as g
print(f'  radar   auto_protect_enabled       {g.AUTO_PROTECT_ENABLED}')
print(f'  radar   stop d urgence             {g.EMERGENCY_SL_PCT} % de l entree')
"
echo
echo "✅ Garde-fou Kraken armé. Le cron le passe chaque minute."
echo "   Désarmement : remettre KRAKEN_SLTP_GUARD_ENABLED=false côté bridge."
