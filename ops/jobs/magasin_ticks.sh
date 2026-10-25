#!/usr/bin/env bash
# Entretien du magasin de TICKS de l'or — reprend ou il s'est arrete.
#
# 🔑 POURQUOI UN ENTRETIEN. `batir_magasin_ticks.py` etait un chargement
# UNIQUE (21/09 -> 09/10). Le 12/10 le magasin avait donc 3 jours de retard,
# et tout banc sur ticks mesurait un passe perime. Xavier : << faire revivre
# le magasin de ticks >>.
#
# ⛔ ET IL Y A PIRE QUE LE RETARD, MESURE LE 12/10 : la route historique
# `/ticks` rend un spread INFERIEUR DE 10 POINTS a la route `/tick` que
# l'execution utilise. 40 secondes appariees, 0 manquante, ecart median
# +10,0 pts, ecart-type 1,2 (26 fois exactement +10). Confirme par les prix
# d'execution reels, qui devient de la MOITIE de l'ecart -- exactement ce que
# predit un spread reel = magasin + 10.
#   => TOUT BANC SUR CE MAGASIN SOUS-ESTIME LE COUT DE 10 POINTS (0,089 EUR).
#   => les comparaisons APPARIEES survivent (les deux cellules paient le meme
#      cout manquant), mais les NIVEAUX absolus de P&L sont optimistes.
# La constante est inscrite dans la table `provenance` du magasin.
set -uo pipefail

# DEFAUT DU 25/10 : un passage PENDU 29 h tenait /var/lock/magasin_ticks.lock,
# et le `flock -n` de la crontab faisait sortir chaque passage suivant SANS
# ECRIRE UNE LIGNE (journal a 0 octet pendant 29 h). Le verrou est repris ICI
# pour que le SAUT SOIT DIT. Se tromper doit rendre bavard, jamais muet.
VERROU=/var/lock/magasin_ticks.lock
exec 9>"$VERROU"
if ! flock -n 9; then
  echo "$(date -u +%F' '%T) SAUTE : le passage precedent tient encore le verrou"
  exit 0
fi

DB=/app/data/ticks_courtier.db
DEBUT=$(docker exec scalping-radar python3 -c "
import sqlite3
try:
    c = sqlite3.connect('file:$DB?mode=ro', uri=True)
    v = c.execute(\"SELECT MAX(ts_utc) FROM ticks WHERE pair='XAU/USD'\").fetchone()[0]
    print(v or '2026-09-21T00:00:00')
except Exception:
    print('2026-09-21T00:00:00')
" 2>/dev/null)
FIN=$(date -u +%Y-%m-%dT%H:%M:00)
echo "$(date -u +%F' '%T) entretien : $DEBUT -> $FIN"

# DEFAUT DU 25/10 : sans timeout, un pont muet a transforme "ne repond pas"
# en "pendu 29 heures". Plafond a 1800 s, bien sous la cadence horaire.
SORTIE=$(mktemp /tmp/magasin_sortie.XXXXXX)
timeout 1800 docker exec -w /app -e PYTHONPATH=/app \
  -e TICKS_CIBLE="$DB" -e TICKS_DEBUT="$DEBUT" -e TICKS_FIN="$FIN" \
  -e TICKS_PAS_MIN=10 \
  scalping-radar python /app/scripts/batir_magasin_ticks.py >"$SORTIE" 2>&1
CODE=$?
tail -3 "$SORTIE"
rm -f "$SORTIE"
if [ "$CODE" -ne 0 ]; then
  if [ "$CODE" -eq 124 ]; then
    echo "  ECHEC : TIMEOUT a 1800 s -- le pont ne repond pas ?"
  else
    echo "  ECHEC : code $CODE"
  fi
fi

# DEFAUT DU 25/10 : du 16 au 24/10 le passage affichait "tranches lues : 0" et
# sortait SANS ERREUR -- 9 jours de donnees perdus en silence. On verifie que le
# magasin a bel et bien AVANCE, et on le dit FORT sinon.
APRES=$(docker exec scalping-radar python3 -c "
import sqlite3
try:
    c = sqlite3.connect('file:$DB?mode=ro', uri=True)
    print(c.execute(\"SELECT MAX(ts_utc) FROM ticks WHERE pair='XAU/USD'\").fetchone()[0] or '')
except Exception:
    print('')
" 2>/dev/null)
if [ "$APRES" = "$DEBUT" ]; then
  echo "  ALERTE : le magasin N A PAS AVANCE (toujours $DEBUT) alors que la plage demandee allait jusqu a $FIN"
fi

# La note de provenance : un banc qui lit le magasin doit pouvoir TROUVER le
# defaut sans relire ce fichier.
docker exec scalping-radar python3 -c "
import sqlite3
c = sqlite3.connect('$DB')
c.execute('CREATE TABLE IF NOT EXISTS provenance (cle TEXT PRIMARY KEY, valeur TEXT)')
c.executemany('INSERT OR REPLACE INTO provenance VALUES (?,?)', [
 ('markup_live_points', '10'),
 ('markup_mesure_le', '2026-10-12'),
 ('markup_preuve', '40 secondes appariees live/historique, ecart median +10,0 pts, '
  'ecart-type 1,2, 26/40 exactement +10 ; confirme par les prix d execution '
  'reels qui devient de la MOITIE de l ecart'),
 ('markup_consequence', 'AJOUTER 10 points au spread de ce magasin pour '
  'retrouver le cout REEL. Les comparaisons APPARIEES survivent sans '
  'correction ; les niveaux absolus de P&L sont optimistes de ~0,089 EUR/trade.'),
])
c.commit()
print('  provenance : markup_live_points = 10')
" 2>&1 | tail -1
