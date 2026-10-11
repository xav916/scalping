#!/usr/bin/env bash
# Attend que le terminal MT5 se reconnecte (reouverture dimanche 22h00 UTC),
# batit un magasin M1 de l'or DEPUIS LE COURTIER, puis repond a la question de
# Xavier du 2026-10-11 : la bougie suivante va-t-elle dans le sens du motif ?
#
# Lance detache sur l'EC2. Ecrit tout dans /tmp/m1_suivante.log et poste UNE
# ligne sur le fil Telegram du compte reel a la fin.
#
# Rien n'ecrit sur le pont : /rates est en LECTURE SEULE.
set -u

JOURNAL=/tmp/m1_suivante.log
CIBLE=/app/data/candles_courtier_m1.db
PAUSE=600          # 10 min entre deux essais
MAX_ESSAIS=150     # ~25 h, puis abandon avec un message

echo "=== attente du pont, demarree $(date -u +%FT%TZ) ===" > "$JOURNAL"

pret() {
  docker exec -i scalping-radar python - <<'PY' 2>/dev/null
import json, os, sys, urllib.parse, urllib.request
base = os.environ["MT5_BRIDGE_LIVE_URL"].rstrip("/")
cle = os.environ["MT5_BRIDGE_LIVE_API_KEY"]
q = urllib.parse.urlencode({"pair": "XAU/USD", "timeframe": "M1",
                            "from": "2026-10-08T12:00:00",
                            "to": "2026-10-08T12:30:00"})
try:
    rq = urllib.request.Request(base + "/rates?" + q, headers={"X-API-Key": cle})
    o = json.loads(urllib.request.urlopen(rq, timeout=30).read())
except Exception as e:
    print("PAS_PRET", type(e).__name__, e)
    sys.exit(1)
if o.get("bougies"):
    print("PRET", len(o["bougies"]), "bougies")
    sys.exit(0)
print("PAS_PRET", o.get("error") or o)
sys.exit(1)
PY
}

for i in $(seq 1 "$MAX_ESSAIS"); do
  if sortie=$(pret); then
    echo "[$(date -u +%FT%TZ)] pont PRET apres $i essai(s) : $sortie" >> "$JOURNAL"
    break
  fi
  echo "[$(date -u +%FT%TZ)] essai $i : $sortie" >> "$JOURNAL"
  if [ "$i" -eq "$MAX_ESSAIS" ]; then
    echo "ABANDON : le pont n'a pas repondu en $MAX_ESSAIS essais" >> "$JOURNAL"
    docker exec scalping-radar python -c "
from backend.services.canaux_telegram import notifier, canal_pour
notifier(canal_pour('admin_live'), 'Banc M1 abandonne',
         'Le pont MT5 n a pas repondu en 25 h : le tableau bougie suivante en M1 n a pas pu etre mesure.')
" >> "$JOURNAL" 2>&1
    exit 1
  fi
  sleep "$PAUSE"
done

echo "=== 1. magasin M1 du courtier ===" >> "$JOURNAL"
docker exec \
  -e MAGASIN_TF=M1 -e MAGASIN_PAS_MIN=1 \
  -e MAGASIN_DEBUT=2026-09-01 -e MAGASIN_FIN=2026-10-10 \
  -e MAGASIN_CIBLE="$CIBLE" \
  scalping-radar python /app/scripts/batir_magasin_courtier.py >> "$JOURNAL" 2>&1

echo "=== 2. banc bougie suivante, M1 ===" >> "$JOURNAL"
docker exec \
  -e MAGASIN="$CIBLE" -e ECHELLE=M1 \
  scalping-radar python /app/scripts/banc_bougie_suivante.py >> "$JOURNAL" 2>&1

REPONSE=$(grep -A1 "=== LA REPONSE ===" "$JOURNAL" | tail -1)
RETENUS=$(grep "motifs qui le franchissent" "$JOURNAL" | tail -1)
PLAFOND=$(grep "^PLAFOND" "$JOURNAL" | tail -1)

docker exec -i scalping-radar python - <<PY >> "$JOURNAL" 2>&1
from backend.services.canaux_telegram import notifier, canal_pour
corps = """Question du 11/10 : en M1, la bougie suivante suit-elle le motif ?

$REPONSE
$RETENUS
$PLAFOND

Bougies M1 DU COURTIER, 01/09 au 09/10. Detail : /tmp/m1_suivante.log"""
notifier(canal_pour('admin_live'), 'Banc M1 : la bougie suivante',
         corps.replace('_', '-'))
PY

echo "=== fini $(date -u +%FT%TZ) ===" >> "$JOURNAL"
