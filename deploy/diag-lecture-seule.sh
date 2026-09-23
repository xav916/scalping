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

  divergence)
    # ⚠️ SEUL rapport qui lise autre chose que la base. Justification : la
    # magnitude de la divergence (`entry`, `mid`) N'EST PAS persistee. Le
    # `details` d'un refus ne porte que `signal_pattern` et `horizon` — on sait
    # qu'un ordre a ete bloque, jamais de combien les deux prix s'ecartaient.
    # C'est exactement le manque que le projet avait comble pour `event_blackout`
    # en y ajoutant `entry`/`stop`/`tp1`. Tant qu'il ne l'est pas ici, le chiffre
    # ne vit que dans le journal du conteneur.
    #
    # ⛔ Le filtre est FIXE et DOUBLE : prefixe du logueur ET code du refus.
    # Aucune entree client n'y entre. La ligne produite par
    # `bridge_tick_validator` ne contient que paire, entry, mid et pourcentage —
    # aucun jeton, aucun identifiant de compte. Elargir ce filtre exposerait le
    # journal entier : ne pas le faire sans relire ce qui y transite.
    echo "=== divergences radar/bridge mesurees (24 h, 40 dernieres) ==="
    docker logs --since 24h scalping-radar 2>&1 \
      | grep -F 'bridge_tick_validator [' \
      | grep -F 'price_divergence' \
      | tail -40 \
      || echo "(aucune ligne — journal vide, conteneur absent, ou droits docker manquants)"
    ;;

  macro)
    # ⚠️ Lit le journal, comme `divergence`, et pour une raison du meme ordre :
    # le regime macro n'est persiste NULLE PART. `get_macro_snapshot()` rend
    # `_cache_snapshot`, qui vit dans la MEMOIRE du processus serveur — un
    # `docker exec` demarre un interpreteur neuf et ne peut donc pas le lire.
    # C'est le meme obstacle que le projet avait deja nomme pour le solde du
    # plafond journalier. La ligne `macro_applied` est la seule trace de ce qui
    # a REELLEMENT ete applique.
    #
    # ⛔ Filtre FIXE et DOUBLE : prefixe du logueur ET paire. Aucune entree
    # client n'y entre. La ligne ne porte que paire, sens, score et
    # multiplicateur — aucun jeton, aucun identifiant de compte.
    #
    # 🔑 Ce que la colonne `final max` tranche : si aucun achat d'or n'atteint
    # 60 alors que les ventes y sont, R-21 est confirme par la mesure et non
    # plus deduit de la repartition.
    _agrege() {
      awk '
        { delete v; for (i=1;i<=NF;i++) { split($i,a,"="); if (a[1]!="") v[a[1]]=a[2] }
          k = v["dir"] " x" v["mult"]
          n[k]++; sf[k]+=v["final"]; sb[k]+=v["base"]
          if (!(k in mf) || v["final"]+0 > mf[k]) mf[k]=v["final"]+0
          if (v["final"]+0 >= 60) ok[k]++ }
        END { for (k in n) printf "%-14s %6d %10.1f %10.1f %10.1f %7d%%\n",
                k, n[k], sb[k]/n[k], sf[k]/n[k], mf[k], (ok[k]*100)/n[k] }' | sort
    }
    for paire in XAU/USD WTI/USD EUR/USD; do
      echo "=== multiplicateur macro applique a ${paire} (24 h) ==="
      printf '%-14s %6s %10s %10s %10s %8s\n' "sens x mult" "n" "base moy" "final moy" "final max" ">= 60"
      docker logs --since 24h scalping-radar 2>&1 \
        | grep -F "macro_applied pair=${paire}" \
        | _agrege \
        || echo "(aucune ligne — journal vide, conteneur absent, ou droits docker manquants)"
    done
    echo "=== dernieres lignes brutes sur l'or (8) ==="
    docker logs --since 24h scalping-radar 2>&1 \
      | grep -F 'macro_applied pair=XAU/USD' | tail -8 || true
    ;;

  bridge)
    # ⚠️ Date une panne de bridge DEPUIS L'EC2, sans rien demander au VPS.
    # Quand le bridge ne repond plus, le backend continue de pousser et
    # d'echouer : chaque echec laisse une ligne `bridge_timeout` ou
    # `bridge_error` dans `signal_rejections`. Le premier horodatage borne le
    # debut de la panne, le dernier dit si elle dure.
    #
    # 🔑 Ajoute le 2026-09-23 parce que le controle automatique cense jouer ce
    # role ne le joue pas : tous ses tests sont dans une boucle sur une liste
    # d'utilisateurs vide, donc il rend « All healthy » quoi qu'il arrive
    # (R-23). Celui-ci lit des faits, pas une absence de faits.
    echo "=== echecs de bridge, 7 jours, par destination et par jour ==="
    lire "SELECT substr(created_at,1,10) jour, destination_id, reason_code,
                 COUNT(*) n, MIN(created_at) premier, MAX(created_at) dernier
          FROM signal_rejections
          WHERE reason_code IN ('bridge_timeout','bridge_error')
            AND created_at >= date('now','-7 days')
          GROUP BY 1,2,3 ORDER BY 1 DESC, n DESC LIMIT 40;"
    echo "=== dernier ordre REELLEMENT parti, par destination ==="
    lire "SELECT destination_id, MAX(pushed_at) dernier_push, COUNT(*) n_7j
          FROM mt5_pushes WHERE pushed_at >= date('now','-7 days')
          GROUP BY 1 ORDER BY 2 DESC;"
    echo "=== positions encore OUVERTES (leur stop vit chez le courtier) ==="
    lire "SELECT created_at, pair, direction, entry_price, stop_loss,
                 mt5_ticket, destination_id
          FROM personal_trades WHERE status='OPEN' ORDER BY created_at DESC;"
    ;;

  *)
    echo "Rapport inconnu : « ${DEMANDE:-aucun} »" >&2
    echo "Disponibles : rejets-wti rejets-or divergence macro bridge admission banc trades-recents sante" >&2
    exit 64
    ;;
esac
