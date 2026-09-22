#!/bin/bash
# BUT: commande forcee SSH — rapports de diagnostic en LECTURE SEULE
#
# ⛔ CE FICHIER EST UNE FRONTIERE DE SECURITE, PAS UN OUTIL.
#
# Il est la commande forcee de la cle `diag-key` dans ~/.ssh/authorized_keys :
#
#   command="/usr/local/bin/diag-lecture-seule.sh",no-port-forwarding,\
#   no-agent-forwarding,no-pty,no-X11-forwarding ssh-ed25519 AAAA... diag
#
# Quoi que le client demande, sshd execute CE script et rien d'autre. La cle ne
# donne donc pas « un acces SSH » : elle donne acces aux rapports listes plus
# bas, et a rien de plus.
#
# ## Les trois regles
#
# 1. ⛔ `SSH_ORIGINAL_COMMAND` n'est JAMAIS evalue, jamais interpole dans une
#    requete, jamais passe a un shell. Il sert uniquement a choisir un nom dans
#    une liste ecrite ici. Un client qui envoie du SQL obtient un refus, pas une
#    execution.
# 2. ⛔ Toute lecture passe par `sqlite3 -readonly`. Le fichier de base ne peut
#    pas etre modifie, meme par erreur de frappe dans ce script.
# 3. ⛔ Aucun secret n'est lu ni affiche. Pas de `.env`, pas de cle d'API, pas
#    de mot de passe. Un rapport qui en aurait besoin n'a pas sa place ici.
#
# 🔑 Ajouter un rapport = ajouter un `case` ci-dessous, et c'est un acte
# deliberé qui se relit en diff. C'est le but : la surface s'etend par decision,
# jamais par requete du client.
set -euo pipefail

readonly BASE="/opt/scalping/data/trades.db"
readonly DEMANDE="${SSH_ORIGINAL_COMMAND:-}"

lire() { sqlite3 -readonly -cmd ".timeout 5000" "$BASE" "$1"; }

case "$DEMANDE" in

  rejets-wti)
    echo "=== WTI refuse sur admin_live depuis la reouverture ==="
    lire "SELECT direction, reason_code, COUNT(*) n, ROUND(AVG(confidence),1) conf,
                 MAX(created_at) dernier
          FROM signal_rejections
          WHERE pair='WTI/USD' AND destination_id='admin_live'
            AND created_at >= '2026-09-22T04:07'
          GROUP BY 1,2 ORDER BY n DESC;"
    echo "=== drops silencieux (absents de signal_rejections) ==="
    lire "SELECT direction, reason_code, count, last_at FROM silent_drop_counters
          WHERE pair='WTI/USD' AND day >= '2026-09-22';"
    echo "=== ordres partis ==="
    lire "SELECT pushed_at, direction, ok, mt5_ticket, pattern, horizon
          FROM mt5_pushes WHERE pair='WTI/USD' AND destination_id='admin_live'
            AND pushed_at >= '2026-09-22T04:07';"
    echo "=== TEMOIN : des setups WTI existent-ils, toutes destinations ? ==="
    lire "SELECT destination_id, reason_code, COUNT(*) n, MAX(created_at)
          FROM signal_rejections WHERE pair='WTI/USD'
            AND created_at >= '2026-09-22T04:07'
          GROUP BY 1,2 ORDER BY n DESC LIMIT 12;"
    ;;

  rejets-or)
    echo "=== XAU/USD refuse sur admin_live depuis la reouverture ==="
    lire "SELECT direction, reason_code, COUNT(*) n, ROUND(AVG(confidence),1) conf,
                 MAX(created_at) dernier
          FROM signal_rejections
          WHERE pair='XAU/USD' AND destination_id='admin_live'
            AND created_at >= '2026-09-22T04:07'
          GROUP BY 1,2 ORDER BY n DESC;"
    echo "=== drops silencieux ==="
    lire "SELECT direction, reason_code, count, last_at FROM silent_drop_counters
          WHERE pair='XAU/USD' AND day >= '2026-09-22';"
    echo "=== ordres partis ==="
    lire "SELECT pushed_at, direction, ok, mt5_ticket, pattern, horizon
          FROM mt5_pushes WHERE pair='XAU/USD' AND destination_id='admin_live'
            AND pushed_at >= '2026-09-22T04:07';"
    ;;

  admission)
    echo "=== etat d'admission, XAU et WTI, dernieres transitions ==="
    lire "SELECT pair, direction, destination, state, state_since, transitioned_by,
                 substr(reason,1,70)
          FROM pair_admission_state WHERE pair IN ('XAU/USD','WTI/USD')
          ORDER BY state_since DESC LIMIT 20;"
    echo "=== pauses du regulateur PnL en cours ==="
    lire "SELECT pair, destination, paused_at, expires_at, ROUND(pnl_pct,2),
                 trades_in_window
          FROM auto_paused_pairs WHERE resumed_at IS NULL ORDER BY paused_at DESC;"
    ;;

  banc)
    echo "=== essais declares ==="
    lire "SELECT slug, status, passed, declared_at, min_sample, variants_declared
          FROM bench_trials ORDER BY declared_at DESC LIMIT 15;"
    echo "=== N (somme des variantes declarees) ==="
    lire "SELECT COALESCE(SUM(variants_declared),0) FROM bench_trials;"
    echo "=== octrois d'anteriorite sur XAU et WTI ==="
    lire "SELECT pair, direction, destination FROM bench_legacy_grants
          WHERE pair IN ('XAU/USD','WTI/USD');"
    ;;

  trades-recents)
    echo "=== clotures reelles des 3 derniers jours ==="
    lire "SELECT closed_at, pair, direction, ROUND(pnl,2) pnl, close_reason,
                 destination_id
          FROM personal_trades WHERE status='CLOSED' AND destination_id='admin_live'
            AND closed_at >= date('now','-3 days')
          ORDER BY closed_at DESC LIMIT 40;"
    echo "=== positions OUVERTES ==="
    lire "SELECT created_at, pair, direction, entry_price, stop_loss, mt5_ticket,
                 destination_id
          FROM personal_trades WHERE status='OPEN' ORDER BY created_at DESC;"
    ;;

  sante)
    echo "=== le radar produit-il, et sur quoi ? (24 h) ==="
    lire "SELECT pair, COUNT(*) n, MAX(created_at) dernier FROM signal_rejections
          WHERE created_at >= datetime('now','-1 day')
          GROUP BY 1 ORDER BY n DESC LIMIT 20;"
    ;;

  *)
    echo "Rapport inconnu : « ${DEMANDE:-aucun} »" >&2
    echo "Disponibles : rejets-wti rejets-or admission banc trades-recents sante" >&2
    exit 64
    ;;
esac
