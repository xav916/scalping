#!/usr/bin/env bash
# BUT : armer le verrou REM-002 pour LE deploiement actuellement en cours.
#
# ⛔ POURQUOI CE SCRIPT EXISTE. Le 2026-10-01, l armement a ete transmis comme
# une ligne `docker exec ... python -c "..."` a coller dans un terminal. Les
# guillemets echappes pour bash ne survivent pas a PowerShell : la commande n a
# jamais tourne, le fichier d etat n a pas bouge, et l execution est restee
# fermee sans que personne ne s en apercoive avant de relire le mtime.
#
# 🔑 Un geste de gouvernance ne doit pas dependre d un echappement. Ici : aucune
# guillemet imbriquee a taper, la raison vit dans le fichier, et le script
# RELIT l etat apres ecriture pour dire si l armement a reellement pris.
#
# Usage :  sudo /opt/scalping/scripts/armer-execution.sh [qui] [raison]
set -euo pipefail

PAR="${1:-Xavier}"
RAISON="${2:-correctif du garde de correlation 39b8fe8 : positions ouvertes lues chez le courtier avec repli sur personal_trades, et sans cache — le cache de 10 s du cap par paire aurait rendu le correctif cosmetique. 8 tests dont 6 echouent sans lui, suite complete 4525 verts. Verifie a chaud sur 2744f48 : admin_live portant USD/CAD buy, USD/CHF buy et EUR/USD sell sont refuses, XAU/USD sell passe.}"

docker exec -i -w /app -e PYTHONPATH=/app \
    -e REM002_PAR="$PAR" -e REM002_RAISON="$RAISON" \
    scalping-radar python - <<'PY'
import os

from backend.services.global_execution_switch import arm, execution_allowed

d = arm(os.environ["REM002_RAISON"], by=os.environ["REM002_PAR"])
print("armement    ->", d.decision, d.reason_code)

# ⛔ On RELIT. Un `arm()` qui rend ALLOW sans que l etat soit ecrit laisserait
# croire que c est fait — exactement ce qui vient de se produire autrement.
v = execution_allowed()
print("verification ->", v.decision, v.reason_code)
print("arme pour   :", v.fingerprint_armed, "| tourne :", v.fingerprint_running)
raise SystemExit(0 if v.allowed else 1)
PY
