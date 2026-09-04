#!/bin/bash
# Contrôle hebdomadaire des sauvegardes S3 : télécharge la plus récente et
# vérifie qu'elle est FRAÎCHE, COMPLÈTE et RESTAURABLE.
#
# ⛔ VERSIONNE ET DURCI LE 2026-09-04. L'ancien vivait dans
# `/opt/scalping/scalping/deploy/`, hors de tout clone git, et il aurait
# annonce PASSED en pleine panne :
#
#   - il validait « le dernier prefixe » SANS REGARDER SA DATE. Le 06/09 il
#     aurait valide celui du 02/09, vieux de quatre jours.
#   - il bouclait sur `*.db` presents SANS VERIFIER QU'IL N'EN MANQUE. Le
#     prefixe du 02/09 ne contient que `trades.db` sur trois — un fichier
#     intact, donc PASSED.
#   - `integrity_check` ne dit RIEN du contenu : une base vide mais bien
#     formee passe.
#   - il n'alertait pas : son verdict finissait dans un log que personne ne lit.
#
# 🔑 Un detecteur qui ne peut pas detecter fabrique de la confiance, ce qui est
# pire que pas de detecteur du tout.
#
# Cron (root) :
#   30 0 * * 0 /home/ec2-user/scalping/deploy/restore-drill.sh >> /var/log/scalping-backup.log 2>&1

set -uo pipefail

S3_BUCKET="${S3_BUCKET:-scalping-backups-xav}"
DATA_DIR="${DATA_DIR:-/opt/scalping/data}"
# 36 h : la sauvegarde tourne a 23h00, le controle le dimanche a 00h30. Une
# sauvegarde saine a donc ~1h30. La marge absorbe un decalage de cron ou une
# nuit ratee isolee, sans laisser passer une panne installee.
AGE_MAX_H="${AGE_MAX_H:-36}"
TMP_DIR="$(mktemp -d /tmp/scalping-restore-drill.XXXXXX)"
trap 'rm -rf "$TMP_DIR"' EXIT
log() { echo "[$(date -u +'%F %T UTC')] $*"; }

if [ -f /opt/scalping/.env ]; then
    set -a
    # shellcheck disable=SC1091
    . /opt/scalping/.env 2>/dev/null || log "AVERTISSEMENT: .env illisible"
    set +a
fi

alerter() {
    log "$1"
    if [ -n "${INFRA_TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${INFRA_TELEGRAM_CHAT_ID:-}" ]; then
        curl -s -X POST "https://api.telegram.org/bot${INFRA_TELEGRAM_BOT_TOKEN}/sendMessage" \
             --max-time 10 -d "chat_id=${INFRA_TELEGRAM_CHAT_ID}" \
             -d "text=$1" > /dev/null || log "AVERTISSEMENT: envoi Telegram echoue"
    else
        log "AVERTISSEMENT: pas de jeton Telegram — echec NON signale"
    fi
}

log "Controle de restauration sur s3://$S3_BUCKET/"

recent="$(aws s3 ls "s3://$S3_BUCKET/" | grep 'PRE ' | awk '{print $2}' | sort | tail -1 | tr -d '/')"
if [ -z "$recent" ]; then
    alerter "Controle restauration ECHEC: aucune sauvegarde dans s3://$S3_BUCKET/"
    exit 1
fi
log "  plus recente : $recent"

# ── 1. FRAÎCHEUR ─────────────────────────────────────────────────────────
# Le prefixe vaut `AAAAMMJJ-HHMMSS`.
horodatage="${recent%%-*} ${recent##*-}"
epoch_backup="$(date -u -d "${horodatage:0:8} ${horodatage:9:2}:${horodatage:11:2}:${horodatage:13:2}" +%s 2>/dev/null || echo 0)"
if [ "$epoch_backup" -eq 0 ]; then
    alerter "Controle restauration ECHEC: prefixe illisible ($recent)"
    exit 1
fi
age_h=$(( ( $(date -u +%s) - epoch_backup ) / 3600 ))
log "  age : ${age_h} h (plafond ${AGE_MAX_H} h)"
if [ "$age_h" -gt "$AGE_MAX_H" ]; then
    alerter "Controle restauration ECHEC: la sauvegarde la plus recente a ${age_h} h ($recent). Le backup nocturne ne passe plus."
    exit 1
fi

# ── 2. COMPLÉTUDE ────────────────────────────────────────────────────────
# La liste attendue se DÉDUIT de ce qui existe reellement dans DATA_DIR : une
# liste ecrite en dur crierait au loup le jour ou une base disparait
# legitimement, et se tairait le jour ou une nouvelle base n'est pas sauvegardee.
attendues=()
for db in trades.db backtest.db macro.db; do
    [ -f "$DATA_DIR/$db" ] && attendues+=("$db")
done
log "  bases attendues : ${attendues[*]:-aucune}"

aws s3 sync "s3://$S3_BUCKET/$recent/" "$TMP_DIR/" --quiet
manquantes=()
for db in "${attendues[@]}"; do
    [ -f "$TMP_DIR/$db" ] || manquantes+=("$db")
done
if [ ${#manquantes[@]} -gt 0 ]; then
    alerter "Controle restauration ECHEC: sauvegarde INCOMPLETE ($recent) — manque: ${manquantes[*]}"
    exit 1
fi

# ── 3. RESTAURABILITÉ ────────────────────────────────────────────────────
resultat=0
for db in "${attendues[@]}"; do
    chemin="$TMP_DIR/$db"
    taille="$(stat -c%s "$chemin")"
    integrite="$(sqlite3 "$chemin" "PRAGMA integrity_check;" 2>&1 | head -1)"
    if [ "$integrite" != "ok" ]; then
        log "  ECHEC $db (${taille} o, integrite=$integrite)"
        resultat=1
        continue
    fi
    log "  OK    $db (${taille} o, integrite=ok)"
done

# ⚠️ `integrity_check` ne juge que la FORME. Une base vide, tronquee a la
# creation ou restauree d'un mauvais chemin la passe sans broncher. On lit donc
# le CONTENU de celle qui porte l'argent — c'est la seule qui compte vraiment.
if [ -f "$TMP_DIR/trades.db" ]; then
    n="$(sqlite3 "$TMP_DIR/trades.db" "SELECT COUNT(*) FROM personal_trades WHERE status='CLOSED';" 2>/dev/null || echo 0)"
    dernier="$(sqlite3 "$TMP_DIR/trades.db" "SELECT COALESCE(MAX(closed_at),'jamais') FROM personal_trades;" 2>/dev/null || echo inconnu)"
    log "  contenu trades.db : $n trades clotures, dernier $dernier"
    if [ "$n" -lt 1 ]; then
        log "  ECHEC trades.db : restaurable mais VIDE"
        resultat=1
    fi
fi

if [ "$resultat" -eq 0 ]; then
    log "Controle restauration REUSSI pour $recent (${age_h} h, ${#attendues[@]} base(s))"
else
    alerter "Controle restauration ECHEC pour $recent — voir /var/log/scalping-backup.log"
fi
exit "$resultat"
