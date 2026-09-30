#!/bin/bash
# BUT: alerter si la politique DLM ne produit plus d instantane du volume de production
# PERIODE_MIN: 1440
#
# ⛔ POURQUOI CE DETECTEUR EXISTE. Le 30/09/2026, on a decouvert que la
# politique `scalping-daily-ebs-snapshot-7d` etait en etat ERROR depuis le
# 30 MAI : quatre mois sans aucun instantane du volume de production. La
# politique existait, paraissait configuree dans la console, et ne produisait
# rien. Personne ne l a vu parce que RIEN ne regardait.
#
# ⚠️ Reactiver la politique sans poser ce detecteur aurait reproduit le meme
# defaut : un mecanisme dont la panne est silencieuse.
#
# 🔑 Deux choses sont verifiees, pas une :
#   - l ETAT de la politique (ENABLED, et pas ERROR) ;
#   - la PRESENCE d un instantane recent, car un etat vert ne prouve pas
#     qu un instantane a ete produit.
set -uo pipefail

REGION="${DLM_REGION:-eu-north-1}"
POLITIQUE="${DLM_POLICY_ID:-policy-0fc7c01ca123a51d3}"
AGE_MAX_H="${DLM_AGE_MAX_H:-48}"
ETAT="${DLM_ETAT:-/var/log/scalping/verif-dlm-etat.txt}"

alerte() {
    printf '%s\n' "$1"
    local jeton chat
    jeton=$(grep -m1 '^TELEGRAM_BOT_TOKEN=' /opt/scalping/.env 2>/dev/null | cut -d= -f2-)
    chat=$(grep -m1 '^TELEGRAM_CHAT_ID=' /opt/scalping/.env 2>/dev/null | cut -d= -f2-)
    [ -n "${jeton:-}" ] && [ -n "${chat:-}" ] || { echo "telegram non configure" >&2; return; }
    curl -s -m 10 -o /dev/null \
        --data-urlencode "text=$1" \
        --data "chat_id=$chat" \
        "https://api.telegram.org/bot$jeton/sendMessage"
}

etat_politique=$(aws dlm get-lifecycle-policy --policy-id "$POLITIQUE" \
    --region "$REGION" --query 'Policy.State' --output text 2>/dev/null)

# Le plus recent instantane produit PAR la politique (elle etiquette Source=dlm-daily).
dernier=$(aws ec2 describe-snapshots --owner-ids self --region "$REGION" \
    --filters "Name=tag:Source,Values=dlm-daily" \
    --query 'sort_by(Snapshots,&StartTime)[-1].StartTime' --output text 2>/dev/null)

maintenant=$(date -u +%s)
if [ -n "${dernier:-}" ] && [ "$dernier" != "None" ]; then
    t=$(date -u -d "$dernier" +%s 2>/dev/null || echo 0)
    age_h=$(( (maintenant - t) / 3600 ))
else
    age_h=-1
fi

echo "politique=$etat_politique  dernier_instantane=${dernier:-aucun}  age_h=$age_h"

probleme=""
[ "$etat_politique" != "ENABLED" ] && \
    probleme="politique DLM en etat $etat_politique (attendu ENABLED)"
if [ "$age_h" -lt 0 ]; then
    probleme="${probleme:+$probleme ; }aucun instantane produit par la politique"
elif [ "$age_h" -gt "$AGE_MAX_H" ]; then
    probleme="${probleme:+$probleme ; }dernier instantane il y a ${age_h} h (limite ${AGE_MAX_H} h)"
fi

if [ -z "$probleme" ]; then
    echo "  OK : instantane de ${age_h} h, politique $etat_politique"
    : > "$ETAT" 2>/dev/null || true
    exit 0
fi

# Une seule alerte par probleme identique, pour ne pas crier chaque jour.
precedent=$(cat "$ETAT" 2>/dev/null || true)
if [ "$precedent" = "$probleme" ]; then
    echo "  deja alerte pour ce probleme, silence"
    exit 0
fi

alerte "$(printf '🔴 [infra] Sauvegarde du volume de production EN PANNE\n\n%s\n\nLa politique %s ne produit plus d instantane. Le 30/09 on a decouvert quatre mois de panne SILENCIEUSE : ne pas laisser filer.' "$probleme" "$POLITIQUE")"
printf '%s' "$probleme" > "$ETAT" 2>/dev/null || true
exit 1
