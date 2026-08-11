#!/bin/bash
# Fin du rodage de l'or en 4h : remet la porte horaire (posé le 2026-08-11).
#
# La porte `PAIR_TRADING_HOURS_UTC={"XAU/USD":"06-19"}` a été RETIRÉE pendant
# le rodage : elle coupait 47 % de l'échantillon pour 0,015 R de spread
# économisé, et quand on mesure la taille de l'échantillon prime.
#
# Le rodage n'a jamais eu la puissance de trancher sur l'edge — à 2,5
# setups/jour, il faudrait 2 884 trades soit ~3 ans. Il servait à vérifier la
# plomberie. Passé sa date, la porte reprend sa place.
#
# ⚠️ Le script REMET la porte, redémarre le service, notifie, et POSE UN TÉMOIN
# pour ne jamais rejouer. Un cron qui refait chaque jour un changement déjà
# fait finit par masquer une modification manuelle.
#
# ⚠️ Il ne touche à RIEN avant la date : un rodage écourté par accident vaut
# mieux qu'un rodage écourté en silence.
#
# Usage :
#   fin-rodage-or-4h.sh            -> applique si la date est atteinte
#   DRY_RUN=1 fin-rodage-or-4h.sh  -> affiche sans rien changer
set -uo pipefail

DATE_FIN="${DATE_FIN:-2026-09-01}"   # surchargeable pour TESTER la branche de fin
TEMOIN="/opt/scalping/data/.rodage-or-4h-termine"
ENVF="/opt/scalping/.env"
VALEUR='PAIR_TRADING_HOURS_UTC={"XAU/USD":"06-19"}'
TOKEN="shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg"
NOTIFY_URL="https://app.scalping-radar.online/api/admin/notify-infra-telegram?token=${TOKEN}&channel=infra"

[ -f "$TEMOIN" ] && { echo "$(date -Is) deja fait ($(cat "$TEMOIN"))"; exit 0; }

AUJ=$(date -u +%F)
if [[ "$AUJ" < "$DATE_FIN" ]]; then
    echo "$(date -Is) rodage en cours, fin prevue le $DATE_FIN"
    exit 0
fi

RAPPORT=$(docker exec scalping-radar python3 scripts/rodage_or_4h.py 2>&1 | head -30)

if [ "${DRY_RUN:-0}" = "1" ]; then
    echo "--- DRY RUN, rien ne sera modifie ---"
    echo "$RAPPORT"
    exit 0
fi

cp "$ENVF" "${ENVF}.bak-finrodage-$(date +%Y%m%d-%H%M)"
if grep -q '^PAIR_TRADING_HOURS_UTC=' "$ENVF"; then
    sed -i "s|^PAIR_TRADING_HOURS_UTC=.*|${VALEUR}|" "$ENVF"
else
    echo "$VALEUR" >> "$ENVF"
fi

# Vérifier AVANT de redémarrer : un redémarrage sur une config ratée coûte
# plus cher que pas de redémarrage du tout.
if ! grep -qF "$VALEUR" "$ENVF"; then
    echo "$(date -Is) ECHEC ecriture — la porte n'est PAS remise, rien redemarre"
    exit 1
fi

systemctl restart scalping.service
sleep 20

ACTIF=$(docker exec scalping-radar python3 -c \
  "from backend.services import mt5_bridge as m; print(m.PAIR_TRADING_HOURS_UTC)" 2>&1)

date -Is > "$TEMOIN"

printf '%s' "{\"text\":\"🥇 *Fin du rodage de l'or en 4h*\n\nLa porte horaire est remise : \`06-19 UTC\`.\nLue par le service : \`${ACTIF}\`\n\nElle coupe ~47 % des fenêtres 4h de l'or (01h, 05h, 21h) pour ~0,015 R de spread économisé — un arbitrage à revoir si l'espérance se révèle positive.\n\n⚠️ Le rodage n'avait PAS la puissance de trancher sur l'edge : il aurait fallu 2 884 trades, soit ~3 ans à ce débit.\n\nRapport final :\n\`\`\`\n${RAPPORT}\n\`\`\`\"}" \
  | curl -sS -m 10 -X POST "$NOTIFY_URL" -H 'Content-Type: application/json' --data-binary @- >/dev/null

echo "$(date -Is) porte horaire remise, temoin pose, notification envoyee"
