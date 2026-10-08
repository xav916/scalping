#!/usr/bin/env bash
# Lance un banc dans un CONTENEUR SEPARE et BORNE, pour qu il ne puisse PAS
# etouffer le radar.
#
#   banc_borne.sh <nom_du_script.py> [args...]
#   le script doit etre dans /opt/scalping/jobs/
#
# ⛔ POURQUOI CE SCRIPT EXISTE — 2026-10-08, 56 MINUTES DE PRODUCTION PERDUES.
#
# `banc_risque_replication.py` gardait en memoire les bougies ET les detections
# des 14 paires a la fois : ~240 000 bougies et 314 769 setups PAR PAIRE.
# Mesure du jour : le radar SEUL consomme deja 1,83 Gio sur 3,75 et 103 % de
# CPU. Il n y avait jamais eu de place.
#
# De 08:58:53 a 09:54:48 UTC le radar n a evalue AUCUN signal ; ni SSH ni l API
# publique ne repondaient. Il a fallu un `aws ec2 reboot-instances`, decide par
# Xavier, pour reprendre la main.
#
# ⛔ ET MA PREMIERE VERSION DE CE GARDE-FOU ETAIT DECORATIVE.
#
# Elle faisait `systemd-run --scope -p MemoryMax=60M ... docker exec ...`.
# Essai decisif : allouer 300 Mo sous une borne de 60 Mo a REUSSI, code 0.
# `systemd-run` contraignait le CLIENT `docker exec` ; le python, lui, tournait
# dans le cgroup du CONTENEUR, hors de portee.
#
# > Un garde-fou decoratif est PIRE que pas de garde-fou : on lui fait
# > confiance.
#
# 🔑 La seule facon de borner un processus de conteneur est de lui donner SON
# conteneur. `docker exec` n accepte aucune limite ; `docker run` les accepte.
# Le radar n est pas touche : il garde son conteneur et ses ressources.
set -uo pipefail

if [ $# -lt 1 ]; then
    echo "usage : $0 <nom_du_script.py> [args...]" >&2
    echo "        le script doit etre dans /opt/scalping/jobs/" >&2
    exit 2
fi
SCRIPT="$1"; shift

MEM="${BANC_MEM_MAX:-1g}"
CPUS="${BANC_CPUS:-0.5}"
JOBS="/opt/scalping/jobs"

if [ ! -f "$JOBS/$SCRIPT" ]; then
    echo "ABANDON : $JOBS/$SCRIPT introuvable" >&2
    exit 2
fi

echo "=== banc dans un conteneur BORNE : memoire $MEM, cpus $CPUS ==="
echo "    script : $SCRIPT $*"

# `--memory-swap` egal a `--memory` : sans lui le conteneur peut swapper et
# faire ramer la machine au lieu de mourir — exactement ce qu on veut eviter.
# Les donnees sont montees en LECTURE SEULE : un banc n ecrit jamais en base.
sudo docker run --rm \
    --memory="$MEM" --memory-swap="$MEM" \
    --cpus="$CPUS" \
    --cpu-shares=128 \
    -v /opt/scalping/data:/app/data:ro \
    -v "$JOBS":/bancs:ro \
    -w /app -e PYTHONPATH=/app:/bancs \
    scalping-radar:latest \
    python "/bancs/$SCRIPT" "$@"
CODE=$?

if [ "$CODE" -eq 137 ]; then
    echo
    echo "⛔ LE BANC A ETE TUE par la borne memoire (code 137 = OOM du cgroup)."
    echo "   C est le comportement VOULU : il demandait plus que $MEM."
    echo "   Le radar, lui, n a pas bronche. Allege le banc — ne releve pas la"
    echo "   borne sans savoir POURQUOI il en demande autant."
else
    echo "=== banc termine, code $CODE ==="
fi
exit "$CODE"
