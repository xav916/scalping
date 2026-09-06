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

# Un armement qui ne s'annonce pas est un changement de comportement que
# personne ne peut dater après coup. Best-effort : la notification ne
# conditionne jamais l'armement, qui a déjà eu lieu à ce stade.
#
# ⛔ ATTENDRE que l'APPLICATION réponde, pas seulement que le conteneur existe.
# Le 06/09 l'annonce est partie pendant le démarrage et a rendu 502 : le script
# annonce à travers le service qu'il vient lui-même de redémarrer.
# `docker exec python -c 1` réussit dès que le conteneur tourne, bien avant
# qu'uvicorn ne serve. L'armement avait bien eu lieu — personne ne l'a su.
#
# 🔑 Prouver que l'alerte ARRIVE, pas qu'elle part.
TOKEN="shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg"
CODE_APP=000
for _ in $(seq 1 60); do
  CODE_APP=$(curl -s -o /dev/null -w "%{http_code}" -m 5 http://localhost:8000/api/health 2>/dev/null || echo 000)
  # 401/403 = l'application répond, elle exige seulement une authentification.
  case "$CODE_APP" in 200|401|403) break ;; esac
  sleep 2
done
echo "application joignable (HTTP $CODE_APP) — envoi de l'annonce"
GELEES=$(curl -s -m 15 -H "X-Bridge-Key: $BK" http://127.0.0.1:8790/positions \
  | python3 -c "
import json, sys
try:
    ps = json.load(sys.stdin).get('positions') or []
except Exception:
    print('(positions illisibles)'); raise SystemExit
print('\n'.join(f\"• {p.get('symbol')} {p.get('side')} {p.get('size')} — ouverte {p.get('fill_time') or 'date inconnue'}\" for p in ps) or '(aucune)')
" 2>/dev/null)

curl -sS -m 8 -X POST \
  "https://app.scalping-radar.online/api/admin/notify-infra-telegram?token=${TOKEN}&channel=infra" \
  -H 'Content-Type: application/json' --data "$(python3 -c "
import json, sys
print(json.dumps({
  'title': '🛡️ Garde-fou Kraken ARMÉ',
  'body': ('Les positions nues reçoivent désormais un stop d urgence automatique '
           'à 1 % du prix d entrée.\n\n'
           'Armé le : $HORODATAGE\n\n'
           'Gelées pour toujours (ouvertes avant l armement, jamais touchées) :\n'
           + '''$GELEES'''
           + '\n\n👉 Désarmement : KRAKEN_SLTP_GUARD_ENABLED=false côté bridge.'),
  'dedup_key': 'kraken_guard_arme',
  'cooldown_seconds': 3600,
}))
")" -o /dev/null -w 'notify HTTP %{http_code}\n' || true

# ⛔ Un seul essai laisse l'annonce à la merci d'une seconde d'indisponibilité,
# et un `|| true` avale l'échec. On VÉRIFIE qu'elle est passée, on retente, et
# on le dit si elle ne passe pas.
CODE_ANNONCE=000
for essai in 1 2 3; do
  CODE_ANNONCE=$(curl -s -o /dev/null -w "%{http_code}" -m 8 -X POST \
    "https://app.scalping-radar.online/api/admin/notify-infra-telegram?token=${TOKEN}&channel=infra" \
    -H 'Content-Type: application/json' \
    --data "{\"title\":\"🛡️ Garde-fou Kraken ARMÉ (confirmation)\",\"body\":\"Armé le $HORODATAGE. Stop d urgence automatique à 1 % sur toute position nue ouverte APRÈS cet horodatage.\",\"dedup_key\":\"kraken_guard_arme\",\"cooldown_seconds\":3600}" 2>/dev/null || echo 000)
  echo "  annonce, essai $essai : HTTP $CODE_ANNONCE"
  [ "$CODE_ANNONCE" = "200" ] && break
  sleep 5
done
if [ "$CODE_ANNONCE" != "200" ]; then
  echo "⚠️ L'ANNONCE N'EST PAS PASSÉE (HTTP $CODE_ANNONCE)."
  echo "   L'armement, lui, a bien eu lieu et est vérifié ci-dessus."
  echo "   👉 Prévenir à la main."
fi
