#!/usr/bin/env bash
# L interrupteur d execution est-il ARME ? Sinon, le dire.
#
# ⛔ Pose le 2026-10-08. Le 07/10 a 22h14 UTC un deploiement a desarme
# l execution (REM-002, comportement attendu) et personne ne l a lu : 456 refus
# execution_globale_fermee sur l or, SIX HEURES de marche sans un ordre.
# `deploy-v2.sh` verifie desormais au deploiement, mais cela ne couvre que les
# deploiements qui passent par lui. Ce job couvre tout le reste.
#
# Mode EVENEMENT : muet tant que l execution est armee.
# 🔑 Par docker cp + docker exec : AUCUN rebuild, donc REM-002 reste arme —
# un rebuild pour installer ce veilleur desarmerait ce qu il surveille.
set -uo pipefail
docker cp /opt/scalping/jobs/veilleur_interrupteur_execution.py \
  scalping-radar:/app/scripts/veilleur_interrupteur_execution.py >/dev/null
docker exec -w /app -e PYTHONPATH=/app scalping-radar \
  python /app/scripts/veilleur_interrupteur_execution.py "$@" \
  >> /var/log/scalping/interrupteur.log 2>&1
