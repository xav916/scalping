#!/bin/bash
# BUT: eprouver la methode Vivien EN BLOC a heure liquide, une seule fois
# PERIODE_MIN: 1440
#
# ⛔ Le spread du labo est celui du tick VIVANT : il valait 0,50 dans la nuit du
# 30/09 contre 0,17 ce matin, pour une reference de 0,20. Le banc epingle donc
# 0,20, mais on le lance quand meme a heure liquide — les bougies servent aussi
# a la detection, et une session creuse ne produit pas les memes setups.
#
# ⚠️ TIR UNIQUE (marqueur) : rejouer chaque jour puis retenir le jour favorable
# serait la selection que le protocole ferme.
set -uo pipefail
M=/var/log/scalping/.banc-vivien-fait
S=/opt/scalping/scripts/banc_vivien_en_bloc.py
J=/var/log/scalping/banc-vivien.log
if [ -f "$M" ]; then echo "deja joue le $(cat "$M")"; exit 0; fi
[ -f "$S" ] || { echo "script absent" >&2; exit 1; }
/usr/bin/docker cp "$S" scalping-radar:/tmp/viv.py >/dev/null || exit 1
/usr/bin/docker exec -w /app -e PYTHONPATH=/app scalping-radar python /tmp/viv.py > "$J" 2>&1
code=$?; cat "$J"
jeton=$(grep -m1 "^TELEGRAM_BOT_TOKEN=" /opt/scalping/.env | cut -d= -f2-)
chat=$(grep -m1 "^TELEGRAM_CHAT_ID=" /opt/scalping/.env | cut -d= -f2-)
if [ -n "${jeton:-}" ] && [ -n "${chat:-}" ]; then
  corps=$(sed -n "/LE BLOC/,\$p" "$J" | head -28)
  curl -s -m 15 -o /dev/null --data-urlencode "text=🔬 METHODE VIVIEN eprouvee EN BLOC (declaration 149d85e)

$corps" --data "chat_id=$chat" "https://api.telegram.org/bot$jeton/sendMessage"
fi
date -u +%Y-%m-%dT%H:%M:%SZ > "$M"
exit $code
