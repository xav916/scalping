#!/bin/bash
# BUT: rendre le verdict du test « la main en euros » quand la fenetre est pleine (n>=30)
# PERIODE_MIN: 10080
#
# ⛔ Elle reste MUETTE tant que n < 30, et ne calcule alors RIEN — garde-fou
# contre l arret optionnel. Et elle ne parle QU UNE FOIS (marqueur).
#
# 🔑 `docker cp` a chaque passage : le script n est pas dans l image et un
# `docker cp` ne survit pas a un redemarrage ; la copie sur l hote, si.
set -uo pipefail
S=/opt/scalping/scripts/sonde_main_en_euros.py
[ -f "$S" ] || { echo "script absent" >&2; exit 1; }
/usr/bin/docker cp "$S" scalping-radar:/tmp/sonde_main.py >/dev/null || exit 1
exec /usr/bin/docker exec -w /app -e PYTHONPATH=/app scalping-radar python /tmp/sonde_main.py
