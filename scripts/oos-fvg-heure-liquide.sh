#!/bin/bash
# BUT: rejouer la validation croisee de fvg_up a une heure LIQUIDE, une seule fois
# PERIODE_MIN: 1440
#
# ⛔ POURQUOI CETTE ENVELOPPE EXISTE. Le 30/09 a 23h, 8 paires forex sur 10 sont
# sorties NON MESURABLES : le spread lu etait celui du tick vivant, a l heure la
# plus large de la journee (USD/CHF : spread 0,00108 contre un stop de 0,00110).
# La validation croisee etait donc sous-puissante par l HEURE du lancement, pas
# par la donnee. Elle teste la prediction P2 deja declaree dans `641df08`.
#
# ⚠️ UNE SEULE FOIS : un marqueur empeche de rejouer. Repeter le meme test
# chaque jour puis retenir le jour le plus favorable serait exactement la
# selection que le plafond du hasard existe pour punir.
#
# 🔑 `docker cp` a chaque passage : le script n est pas dans l image (elle date
# du 773047c) et un `docker cp` ne survit pas a un redemarrage. La copie depuis
# l hote, elle, est durable.
set -uo pipefail

MARQUEUR="/var/log/scalping/.oos-fvg-heure-liquide-fait"
SCRIPT="/opt/scalping/scripts/test_hors_echantillon_fvg_up.py"
JOURNAL="/var/log/scalping/oos-fvg-heure-liquide.log"

if [ -f "$MARQUEUR" ]; then
    echo "deja joue le $(cat "$MARQUEUR") — rien a faire"
    exit 0
fi
[ -f "$SCRIPT" ] || { echo "script absent : $SCRIPT" >&2; exit 1; }

/usr/bin/docker cp "$SCRIPT" scalping-radar:/tmp/oos.py >/dev/null || exit 1
/usr/bin/docker exec -w /app -e PYTHONPATH=/app scalping-radar \
    python /tmp/oos.py > "$JOURNAL" 2>&1
code=$?
cat "$JOURNAL"

jeton=$(grep -m1 '^TELEGRAM_BOT_TOKEN=' /opt/scalping/.env | cut -d= -f2-)
chat=$(grep -m1 '^TELEGRAM_CHAT_ID=' /opt/scalping/.env | cut -d= -f2-)
if [ -n "${jeton:-}" ] && [ -n "${chat:-}" ]; then
    corps=$(sed -n '/VALIDATION CROISEE/,$p' "$JOURNAL" | head -30)
    curl -s -m 15 -o /dev/null \
        --data-urlencode "text=🔬 fvg_up — validation croisee rejouee a HEURE LIQUIDE (P2 de 641df08)

$corps" \
        --data "chat_id=$chat" \
        "https://api.telegram.org/bot$jeton/sendMessage"
fi

date -u +%Y-%m-%dT%H:%M:%SZ > "$MARQUEUR"
exit $code
