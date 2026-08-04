#!/bin/bash
# Notifie le canal sales à chaque nouveau push d'ordre, toutes destinations.
#
# ⚠️ Remplace quatre scripts quasi identiques (2026-08-04) :
#   notify-new-live-pushes.sh          79 lignes
#   notify-new-legacy-pushes.sh        78
#   notify-new-kraken-pushes.sh        96
#   notify-new-kraken-spot-pushes.sh   73
#
# Même logique en quatre copies, chacune avec son fichier d'état et son
# extraction de clés. Chaque nouvelle destination imposait un cinquième
# fichier — le coût se voyait à chaque ajout de broker.
#
# Usage :
#   notify-new-pushes.sh              → toutes les destinations
#   notify-new-pushes.sh live kraken  → seulement celles-ci
#   DRY_RUN=1 notify-new-pushes.sh    → affiche sans envoyer
set -uo pipefail

DB=/opt/scalping/data/trades.db
ENV_FILE=/opt/scalping/.env
HELPER=/opt/scalping/scripts/lib_calc_risk_eur.py
TOKEN="shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg"
URL="https://app.scalping-radar.online/api/admin/notify-infra-telegram?token=${TOKEN}&channel=sales"
DASHBOARD_URL="https://app.scalping-radar.online/v2/positions"

DESTINATIONS_CONNUES="live legacy kraken kraken_spot"
CIBLES="${*:-$DESTINATIONS_CONNUES}"

# Taux EUR/USD via le bridge Live — la seule source de tick fiable dont on
# dispose côté serveur. Repli sur une valeur figée si injoignable.
LU=$(grep -m1 '^MT5_BRIDGE_LIVE_URL=' "$ENV_FILE" | cut -d= -f2-)
LK=$(grep -m1 '^MT5_BRIDGE_LIVE_API_KEY=' "$ENV_FILE" | cut -d= -f2-)
EUR_USD=$(curl -sS -m 3 -H "X-API-Key: $LK" "$LU/tick/EUR/USD" 2>/dev/null | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin); v=(d.get('bid',0)+d.get('ask',0))/2
    print(round(v,4) if v>0 else '')
except Exception: print('')" 2>/dev/null)
[ -z "$EUR_USD" ] && EUR_USD=1.155

extraire() {  # $1 = clé JSON, $2 = charset de la valeur
  echo "$RESP" | grep -oE "\"$1\":[ ]*\"?[$2]+\"?" | head -1 \
    | grep -oE "[$2]+\"?\$" | tr -d '"'
}

configurer() {
  case "$1" in
    live)
      IDS="'admin_live'";            ETAT=/var/lib/scalping/last-live-push-id.txt
      COMPTE="IC Markets Live (argent réel EUR)"
      PREFIXE="MT5 IC Markets";      SUFFIXE="";          BRIDGE_TYPE="mt5"
      LIEN_1="📱 Ouvrir MT5 mobile : metatrader5://"
      LIEN_2="🔗 Dashboard positions : ${DASHBOARD_URL}"
      OU_CHERCHER="Voir logs bridge Live." ;;
    legacy)
      IDS="'admin_legacy'";          ETAT=/var/lib/scalping/last-legacy-push-id.txt
      COMPTE="Pepperstone Demo (argent fictif)"
      PREFIXE="MT5 Demo Pepperstone"; SUFFIXE=" (fictif)"; BRIDGE_TYPE="mt5"
      LIEN_1="📱 Ouvrir MT5 mobile : metatrader5://"
      LIEN_2="🔗 Dashboard positions : ${DASHBOARD_URL}"
      OU_CHERCHER="Voir logs bridge Demo." ;;
    kraken)
      IDS="'admin_kraken','admin_kraken_stocks'"
      ETAT=/var/lib/scalping/last-kraken-push-id.txt
      COMPTE="Kraken Futures LIVE (argent réel USD)"
      PREFIXE="Kraken Futures";      SUFFIXE="";          BRIDGE_TYPE="kraken"
      LIEN_1="📱 Suivi position : https://futures.kraken.com/trade/positions"
      LIEN_2=""
      OU_CHERCHER="Logs : sudo journalctl -u kraken-bridge -f" ;;
    kraken_spot)
      IDS="'admin_kraken_spot'";     ETAT=/var/lib/scalping/last-kraken-spot-push-id.txt
      COMPTE="Kraken Spot LIVE (argent réel USD)"
      PREFIXE="Kraken Spot";         SUFFIXE="";          BRIDGE_TYPE="kraken_spot"
      LIEN_1="📱 Suivi : https://pro.kraken.com/app/trade"
      LIEN_2=""
      OU_CHERCHER="Logs : sudo journalctl -u kraken-spot-bridge -f" ;;
    *) return 1 ;;
  esac
}

plateforme() {  # $1 = paire, $2 = destination_id de la ligne
  local p; p=$(echo "$1" | tr '[:lower:]' '[:upper:]')
  if [ "$2" = "admin_kraken_stocks" ]; then
    echo "Kraken Futures · xStock (equity tokenisée USD)"; return
  fi
  case "$BRIDGE_TYPE" in
    kraken|kraken_spot) echo "${PREFIXE} · Perpetuel Crypto USD"; return ;;
  esac
  case "$p" in
    XAU*|XAG*)                    echo "${PREFIXE} · CFD Métal${SUFFIXE}" ;;
    WTI*|BRENT*|XTI*|XBR*|NGAS*)  echo "${PREFIXE} · CFD Énergie${SUFFIXE}" ;;
    AAPL|TSLA|NVDA|MSFT|GOOGL|AMZN|META|AMD|NFLX|COIN|HOOD|MSTR|SPY|QQQ|PLTR|SHOP)
                                  echo "${PREFIXE} · CFD Action US${SUFFIXE}" ;;
    SPX|NDX|DAX|CAC40|FTSE|US30|US500|NAS100)
                                  echo "${PREFIXE} · CFD Indice${SUFFIXE}" ;;
    BTC*|ETH*|LTC*|XRP*|SOL*|ADA*|DOGE*|BCH*|DOT*)
                                  echo "${PREFIXE} · CFD Crypto${SUFFIXE}" ;;
    *)                            echo "${PREFIXE} · CFD Forex${SUFFIXE}" ;;
  esac
}

traiter() {
  local cible="$1"
  configurer "$cible" || { echo "  destination inconnue : $cible"; return 1; }
  [ -f "$ETAT" ] || echo 0 > "$ETAT"
  local dernier; dernier=$(cat "$ETAT"); dernier=${dernier:-0}

  local lignes
  lignes=$(sqlite3 "$DB" "
    SELECT id||'|'||pair||'|'||direction||'|'||ok||'|'||
           substr(coalesce(bridge_response,''),1,500)||'|'||pushed_at||'|'||
           coalesce(destination_id,'')
      FROM mt5_pushes
     WHERE id > $dernier AND destination_id IN ($IDS)
     ORDER BY id ASC LIMIT 10;")
  if [ -z "$lignes" ]; then
    echo "  ${cible}: rien de nouveau (dernier id=$dernier)"
    return 0
  fi

  local max=$dernier
  while IFS='|' read -r id pair dir okval RESP ts dest_id; do
    [ -z "$id" ] && continue

    # MT5 renvoie ticket/price, Kraken market_order_id/avg_price : on tente
    # les deux plutôt que de dupliquer le script par famille de bridge.
    local ref prix volume sl tp
    ref=$(extraire "ticket" "0-9"); [ -z "$ref" ] && ref=$(extraire "market_order_id" "a-f0-9-")
    prix=$(extraire "price" "0-9."); [ -z "$prix" ] && prix=$(extraire "avg_price" "0-9.")
    volume=$(extraire "volume" "0-9.")
    sl=$(extraire "sl" "0-9."); tp=$(extraire "tp" "0-9.")

    local dir_mot="ACHAT"; [ "$dir" = "sell" ] && dir_mot="VENTE"
    local plat; plat=$(plateforme "$pair" "$dest_id")

    local ligne_rr=""
    if [ -n "$prix" ] && [ -n "$sl" ] && [ -n "$tp" ] && [ -n "$volume" ]; then
      local j risk reward rr
      j=$(python3 "$HELPER" --pair "$pair" --entry "$prix" --sl "$sl" --tp "$tp" \
            --volume "$volume" --bridge-type "$BRIDGE_TYPE" --eur-usd "$EUR_USD" 2>/dev/null || echo '{}')
      risk=$(echo "$j"   | python3 -c "import json,sys;print(json.load(sys.stdin).get('risk_eur',''))" 2>/dev/null)
      reward=$(echo "$j" | python3 -c "import json,sys;print(json.load(sys.stdin).get('reward_eur',''))" 2>/dev/null)
      rr=$(echo "$j"     | python3 -c "import json,sys;print(json.load(sys.stdin).get('rr',''))" 2>/dev/null)
      [ -n "$risk" ] && [ "$risk" != "0" ] && \
        ligne_rr="\n🛡️ Stop Loss : ${sl}  →  -€${risk}\n🎯 Take Profit : ${tp}  →  +€${reward}\n📊 Ratio R:R : 1:${rr}"
    fi

    # Protection SL/TP. Trois états, et surtout PAS d'alarme quand on ne sait
    # pas : les bridges MT5 posent bien les stops mais ne les renvoient pas
    # dans leur réponse. Afficher « SL/TP absents » sur chaque push MT5 serait
    # une fausse alerte — on préfère ne rien dire que crier à tort.
    local prot=""
    local sl_err tp_err
    sl_err=$(echo "$RESP" | grep -oE '"sl_error":[ ]*"[^"]+"' | head -1)
    tp_err=$(echo "$RESP" | grep -oE '"tp_error":[ ]*"[^"]+"' | head -1)
    if [ -n "$sl_err" ] || [ -n "$tp_err" ]; then
      prot="⚠️ SL NON placé"
      [ -n "$sl_err" ] && prot="⚠️ SL NON placé ($sl_err)"
      [ -n "$tp_err" ] && prot="$prot | ⚠️ TP NON placé"
    elif [ -n "$sl" ] && [ -n "$tp" ]; then
      prot="✅ SL + TP protégés"
    fi

    local titre corps
    if [ "$okval" = "1" ]; then
      titre="🟢 $plat · $pair $dir_mot"
      corps="Plateforme : ${plat}\nCompte : ${COMPTE}\n\n📋 Détail\nRéférence : ${ref:-n/a}\nPrix : ${prix:-?}\nVolume : ${volume:-?}${ligne_rr}\n\nEnvoyé : ${ts}"
      [ -n "$prot" ] && corps="${corps}\n${prot}"
      corps="${corps}\n\n${LIEN_1}"
      [ -n "$LIEN_2" ] && corps="${corps}\n${LIEN_2}"
    else
      titre="❌ $plat REFUSÉ · $pair $dir_mot"
      corps="Plateforme : ${plat}\n\n📋 Détail\nVolume tenté : ${volume:-?}\nTenté : ${ts}\n\nℹ️ ${OU_CHERCHER}"
    fi

    if [ "${DRY_RUN:-0}" = "1" ]; then
      echo "  ----- ${cible} id=${id} -----"
      echo "  $titre"
      echo -e "$corps" | sed 's/^/    /'
    else
      curl -sS -m 5 -X POST "$URL" -H "Content-Type: application/json" \
        --data "{\"title\":\"$titre\",\"body\":\"$corps\",\"dedup_key\":\"${cible}_push_${id}\",\"cooldown_seconds\":86400}" \
        > /dev/null || true
    fi
    max=$id
  done <<< "$lignes"

  [ "${DRY_RUN:-0}" = "1" ] || echo "$max" > "$ETAT"
  echo "  ${cible}: traité jusqu'à id=$max"
}

echo "$(date -Iseconds) notify-new-pushes (eur_usd=$EUR_USD)"
for c in $CIBLES; do traiter "$c"; done
