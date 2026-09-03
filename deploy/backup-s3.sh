#!/bin/bash
# Backup quotidien des SQLite vers S3.
#
# ⛔ VERSIONNE DEPUIS LE 2026-09-04. L'ancien vivait dans
# `/opt/scalping/scalping/deploy/`, un dossier qui n'est PAS un clone git — un
# fichier orphelin, en DEUX copies divergentes sur le serveur, dont une seule
# tournait. Le cron pointe desormais sur le clone `/home/ec2-user/scalping`,
# donc `git pull` le met a jour et la derive devient impossible.
# Meme lecon que le correctif Kraken disparu (13 ordres perdus).
#
# Cron (utilisateur root) :
#   0 23 * * * /home/ec2-user/scalping/deploy/backup-s3.sh >> /var/log/scalping-backup.log 2>&1
#
# Pre-requis : aws cli + sqlite3, bucket S3, role IAM s3:PutObject,
# INFRA_TELEGRAM_BOT_TOKEN + INFRA_TELEGRAM_CHAT_ID dans /opt/scalping/.env.

set -uo pipefail

S3_BUCKET="${S3_BUCKET:-scalping-backups-xav}"
DATA_DIR="/opt/scalping/data"
TMP_DIR="$(mktemp -d /tmp/scalping-backup.XXXXXX)"
TIMESTAMP="$(date -u +%Y%m%d-%H%M%S)"
log() { echo "[$(date -u +'%Y-%m-%d %H:%M:%S UTC')] $*"; }

if [ -f /opt/scalping/.env ]; then
    set -a
    # shellcheck disable=SC1091
    . /opt/scalping/.env 2>/dev/null || log "AVERTISSEMENT: .env illisible, alerte Telegram indisponible"
    set +a
fi

notifier() {
    local msg="$1"
    log "$msg"
    if [ -n "${INFRA_TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${INFRA_TELEGRAM_CHAT_ID:-}" ]; then
        curl -s -X POST "https://api.telegram.org/bot${INFRA_TELEGRAM_BOT_TOKEN}/sendMessage" \
             --max-time 10 \
             -d "chat_id=${INFRA_TELEGRAM_CHAT_ID}" \
             -d "text=${msg}" > /dev/null || log "AVERTISSEMENT: envoi Telegram echoue"
    else
        log "AVERTISSEMENT: pas de jeton Telegram — echec NON signale"
    fi
}

nettoyer() { rm -rf "$TMP_DIR"; }
trap nettoyer EXIT

if [ ! -d "$DATA_DIR" ]; then
    notifier "Scalping backup FAILED: $DATA_DIR introuvable"
    exit 1
fi

# ⛔ Chaque base est INDEPENDANTE (2026-09-04).
#
# Avant, `set -e` faisait sortir la boucle a la premiere erreur : le 02/09,
# `trades.db` etait deja sur S3 quand `backtest.db` a echoue, et la nuit
# entiere a ete comptee en echec. Pire, le 03/09 `trades.db` a echoue en
# PREMIER et les suivantes n'ont meme pas ete tentees.
#
# 🔑 Perdre la sauvegarde de la base qui porte les trades parce qu'une base
# d'analyse est verrouillee, c'est laisser une panne mineure en creer une
# majeure. On tente TOUT, on signale ce qui a rate.
echecs=()
reussites=()

for db in trades.db backtest.db macro.db; do
    src="$DATA_DIR/$db"
    [ -f "$src" ] || continue
    snap="$TMP_DIR/$db"

    # ⛔ `VACUUM INTO` et non `.backup` — c'est LA correction du 2026-09-04.
    #
    # L'API `.backup` copie page par page et **repart de zero a chaque commit
    # d'un writer**. Le radar ecrit en continu (7 a 10 000 rejets/jour, plus
    # les snapshots polymarket et le heartbeat) : sur une base de 322 Mo, la
    # copie n'atteignait jamais la fin et rendait « database is locked ».
    # Cinq nuits d'echec d'affilee, du 30/08 au 03/09.
    #
    # `VACUUM INTO` prend UNE transaction en lecture et ecrit une copie
    # compacte d'un seul tenant : les writers ne la font pas repartir. Elle
    # defragmente au passage, donc l'objet S3 est plus petit.
    log "Snapshot $db (VACUUM INTO)"
    if ! sqlite3 "$src" \
            -cmd ".timeout 120000" \
            "VACUUM INTO '$snap';" 2>&1 | sed 's/^/    /'; then
        echecs+=("$db (snapshot)")
        rm -f "$snap"
        continue
    fi

    # ⚠️ Verifier AVANT d'envoyer. Une sauvegarde corrompue est pire qu'une
    # sauvegarde absente : l'absence se voit, la corruption se decouvre le
    # jour ou on en a besoin.
    verdict="$(sqlite3 "$snap" "PRAGMA quick_check;" 2>&1 | head -1)"
    if [ "$verdict" != "ok" ]; then
        echecs+=("$db (integrite: $verdict)")
        rm -f "$snap"
        continue
    fi

    taille="$(du -h "$snap" | cut -f1)"
    log "Upload $db ($taille) -> s3://$S3_BUCKET/$TIMESTAMP/$db"
    if ! aws s3 cp "$snap" "s3://$S3_BUCKET/$TIMESTAMP/$db" --no-progress; then
        echecs+=("$db (upload)")
        rm -f "$snap"
        continue
    fi
    reussites+=("$db")
    # Libere tout de suite : sinon le pic disque vaut la SOMME des bases
    # (~2,5 Go), sur une racine qui a deja frole les 90 %.
    rm -f "$snap"
done

if [ ${#echecs[@]} -gt 0 ]; then
    notifier "Scalping backup PARTIEL ($TIMESTAMP) — OK: ${reussites[*]:-aucune} | ECHEC: ${echecs[*]}"
    exit 1
fi

log "Backup OK ($TIMESTAMP) — ${reussites[*]}"
