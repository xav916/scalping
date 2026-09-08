#!/usr/bin/env bash
# BUT: verifier que /opt/scalping/scripts execute bien le code versionne
# PERIODE_MIN: 60
#
# ⛔ LE DEFAUT QUE CETTE SONDE SUPPRIME (2026-09-08).
#
# Les crons de l'hote executent `/opt/scalping/scripts/...`, qui est un
# **vrai dossier**, pas un lien vers le clone git. Un `git pull` + un
# `docker build` ne le touchent donc PAS.
#
# Mesure du 08/09 : **8 fichiers divergents**, dont 7 corriges le jour meme
# (fenetres SQLite, formats de date, epingles d'empreintes, bloc « or » du
# recap). Toutes ces corrections etaient **mortes** -- deployees, testees,
# annoncees, et sans effet.
#
# ⚠️ Et `notify_position_fermee.py` divergeait depuis le **06/09** : la session
# precedente avait deja le meme probleme sans le voir.
#
# 🔑 Rien ne criait. Un fichier peri me se lit exactement comme un fichier a
# jour -- c'est la forme de defaut que ce depot passe son temps a fermer.
#
# Sortie 0 = conforme. Sortie 1 = derive (la sonde crie).
set -uo pipefail

OPT=/opt/scalping/scripts
CLONE=/home/ec2-user/scalping/scripts

[ -d "$OPT" ]   || { echo "  $OPT absent — rien a verifier"; exit 0; }
[ -d "$CLONE" ] || { echo "  ⛔ clone git introuvable ($CLONE)"; exit 1; }

divergents=()
absents=()
identiques=0

cd "$OPT" || exit 1
for f in *.py *.sh; do
    [ -f "$f" ] || continue
    case "$f" in .bak-*|*.bak|*.bak.*) continue ;; esac
    if [ ! -f "$CLONE/$f" ]; then
        absents+=("$f")
        continue
    fi
    if cmp -s "$f" "$CLONE/$f"; then
        identiques=$((identiques + 1))
    else
        divergents+=("$f")
    fi
done

echo "  identiques : $identiques   divergents : ${#divergents[@]}   hors depot : ${#absents[@]}"

# ⚠️ Un script present dans /opt mais ABSENT du depot n'est pas une derive :
# c'est un fichier que personne ne versionne. On le NOMME sans faire echouer --
# `monitor_live_bridge.sh` a tourne ainsi depuis juillet sans que rien ne le
# dise, et le taire une seconde fois serait pire que de le signaler.
if [ ${#absents[@]} -gt 0 ]; then
    echo "  ⚠️ hors depot (non versionnes) :"
    for f in "${absents[@]}"; do echo "     $f"; done
fi

if [ ${#divergents[@]} -eq 0 ]; then
    echo "  ✅ /opt execute le code versionne"
    exit 0
fi

echo "  ⛔ DERIVE — ces fichiers different du depot :"
for f in "${divergents[@]}"; do
    d_opt=$(stat -c %y "$OPT/$f" 2>/dev/null | cut -d. -f1)
    d_git=$(stat -c %y "$CLONE/$f" 2>/dev/null | cut -d. -f1)
    echo "     $f   /opt=$d_opt   depot=$d_git"
done
echo "  Les crons de l'hote executent la version /opt : tout correctif"
echo "  deploye dans le clone reste SANS EFFET tant qu'il n'est pas copie."
exit 1
