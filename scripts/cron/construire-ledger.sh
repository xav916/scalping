#!/bin/bash
# REM-005/006 — reconstruit le ledger financier chaque nuit.
#
# 🔑 IL COPIE LE CODE DEPUIS LE DÉPÔT À CHAQUE PASSAGE. `docker cp` ne
# survit pas à un redémarrage du conteneur : sans cette copie, le cron
# marcherait jusqu'au premier `systemctl restart`, puis échouerait en
# silence sur un `ModuleNotFoundError` que personne ne lit.
#
# ⛔ ET IL NE RECONSTRUIT PAS L'IMAGE, délibérément. Un déploiement ferme le
# verrou d'exécution REM-002 et arrête le trading jusqu'à un réarmement
# humain. Le ledger est un outil de lecture : il ne vaut pas ce prix.
set -uo pipefail

DEPOT=/home/ec2-user/scalping
CONTENEUR=scalping-radar
JOURNAL=/var/log/scalping/ledger.log

horodate() { date -u +%Y-%m-%dT%H:%M:%SZ; }

if ! docker ps --format '{{.Names}}' | grep -qx "$CONTENEUR"; then
  echo "$(horodate) conteneur absent — rien fait" >>"$JOURNAL"
  exit 0
fi

cd "$DEPOT" 2>/dev/null || { echo "$(horodate) depot introuvable" >>"$JOURNAL"; exit 1; }

for f in backend/services/trade_ledger.py scripts/construire_ledger.py; do
  if [ ! -f "$f" ]; then
    echo "$(horodate) ⛔ $f absent du depot — git pull manquant ?" >>"$JOURNAL"
    exit 1
  fi
  docker cp "$f" "$CONTENEUR:/app/$f" >/dev/null || {
    echo "$(horodate) ⛔ copie de $f refusee" >>"$JOURNAL"; exit 1; }
done

SORTIE=$(docker exec -w /app -e PYTHONPATH=/app "$CONTENEUR" \
         python scripts/construire_ledger.py 2>&1)
CODE=$?

# On ne garde que les lignes qui portent un verdict : le rapport complet fait
# 60 lignes et noierait le journal en un mois.
RESUME=$(echo "$SORTIE" | grep -E "LEDGER CONSTRUIT|VALID_ALGORITHM|HUMAN_INTER|RESEARCH_EXP|argent reel ET verifie|divergent" | tr '\n' ' | ')
if [ $CODE -ne 0 ]; then
  echo "$(horodate) ⛔ ECHEC code=$CODE : $(echo "$SORTIE" | tail -3 | tr '\n' ' ')" >>"$JOURNAL"
  exit $CODE
fi
echo "$(horodate) ok $RESUME" >>"$JOURNAL"
