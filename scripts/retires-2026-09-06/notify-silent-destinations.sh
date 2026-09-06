#!/bin/bash
# Alerte quotidienne : destinations silencieuses.
#
# Contexte — deux destinations sont mortes en silence sans que rien ne
# l'indique, et il a fallu des semaines pour s'en apercevoir :
#
#   - Voies A/B : `_not_a_star`, 199 setups AAPL/jour à 81,8 de confiance
#     moyenne, 0 push, 0 rejet loggé, 0 notif. Jamais tradé une action.
#   - Kraken    : `_not_admitted` sur 34 des 40 derniers signaux crypto.
#     Activé le 02/08 sur des paires rétrogradées en juin. 0 ordre, jamais.
#
# Le principe : une destination qui VOIT du trafic mais ne pousse RIEN est
# suspecte. On croise les trois journaux sur 48 h.
#
# ⚠️ Le message part TOUS LES JOURS, y compris quand tout va bien. Une alerte
# qui ne parle qu'en cas de problème rend un cron cassé indiscernable d'une
# situation saine — c'est précisément le trou qu'on referme ici.
#
# Push @xav_scalping_infra_bot chaque jour à 06h30 UTC (08h30 Paris).
set -uo pipefail

DB=/opt/scalping/data/trades.db
ENV_FILE=/opt/scalping/.env
WINDOW_HOURS=${WINDOW_HOURS:-48}

BOT_TOKEN=$(grep -E '^INFRA_TELEGRAM_BOT_TOKEN=' "$ENV_FILE" | cut -d= -f2-)
CHAT_ID=$(grep -E '^INFRA_TELEGRAM_CHAT_ID=' "$ENV_FILE" | cut -d= -f2-)

if [ -z "$BOT_TOKEN" ] || [ -z "$CHAT_ID" ]; then
  echo "missing infra telegram creds" >&2
  exit 1
fi

# Fenêtre en ISO avec le 'T' : `datetime('now')` rend "YYYY-MM-DD HH:MM:SS"
# (espace) alors que les colonnes sont en ISO avec un 'T'. La comparaison de
# chaînes laisserait alors passer toute la journée. Piège rencontré le 04/08.
SINCE=$(date -u -d "-${WINDOW_HOURS} hours" '+%Y-%m-%dT%H:%M:%S')
SINCE_DAY=$(date -u -d "-${WINDOW_HOURS} hours" '+%Y-%m-%d')
TODAY=$(date -u '+%Y-%m-%d')

# 1. Pushes effectifs par destination (ok=1 = ordre reellement accepte)
PUSHES=$(sqlite3 "$DB" "
SELECT json_group_array(json_object('dest', destination_id, 'n', n, 'ko', ko))
  FROM (SELECT destination_id,
               SUM(CASE WHEN ok = 1 THEN 1 ELSE 0 END) AS n,
               SUM(CASE WHEN ok = 1 THEN 0 ELSE 1 END) AS ko
          FROM mt5_pushes WHERE pushed_at >= '$SINCE' GROUP BY 1);
")

# 2. Rejets publics par destination
REJECTS=$(sqlite3 "$DB" "
SELECT json_group_array(json_object('dest', destination_id, 'n', n, 'top', top))
  FROM (SELECT destination_id, COUNT(*) AS n,
               (SELECT reason_code FROM signal_rejections r2
                 WHERE r2.destination_id IS r1.destination_id
                   AND r2.created_at >= '$SINCE'
                 GROUP BY reason_code ORDER BY COUNT(*) DESC LIMIT 1) AS top
          FROM signal_rejections r1
         WHERE created_at >= '$SINCE' GROUP BY destination_id);
")

# 3. Drops silencieux par destination (codes prives, agreges par jour)
SILENT=$(sqlite3 "$DB" "
SELECT json_group_array(json_object('dest', destination_id, 'n', n, 'top', top, 'pair', pair))
  FROM (SELECT destination_id, SUM(count) AS n,
               reason_code AS top,
               (SELECT pair FROM silent_drop_counters s2
                 WHERE s2.destination_id IS s1.destination_id
                   AND s2.day >= '$SINCE_DAY'
                 GROUP BY pair ORDER BY SUM(count) DESC LIMIT 1) AS pair
          FROM silent_drop_counters s1
         WHERE day >= '$SINCE_DAY' GROUP BY destination_id);
")

BODY=$(PUSHES="$PUSHES" REJECTS="$REJECTS" SILENT="$SILENT" \
       WINDOW="$WINDOW_HOURS" python3 <<'PY'
import json, os

W = os.environ.get("WINDOW", "48")
pushes = {r["dest"]: r for r in json.loads(os.environ.get("PUSHES") or "[]")}
rejects = {r["dest"]: r for r in json.loads(os.environ.get("REJECTS") or "[]")}
silent = {r["dest"]: r for r in json.loads(os.environ.get("SILENT") or "[]")}

LABELS = {
    "_not_admitted": "paire non admise à l'auto-exec",
    "_not_a_star": "hors portefeuille stars",
    "_not_configured": "bridge non configuré",
    "_user_excluded_pair": "paire exclue pour ce user",
    "below_confidence": "confiance sous le seuil",
    "pattern_not_allowed": "pattern hors whitelist",
    "market_closed": "marché fermé",
    "sl_too_close": "stop trop serré",
    "pair_not_whitelisted": "paire hors whitelist",
    "asset_class_blocked": "classe d'actif non supportée",
    "max_positions_per_pair": "plafond de positions atteint",
    "price_divergence": "prix divergent du broker",
    "bridge_timeout": "bridge injoignable",
    "kill_switch": "kill switch actif",
    "energy_pre_weekend_freeze": "gel énergie avant week-end",
}
lab = lambda c: LABELS.get(c, c or "?")

# Une destination "vue" est une destination qui apparait dans au moins un
# des trois journaux : elle recoit donc du trafic et devrait vivre.
seen = {d for d in (*pushes, *rejects, *silent) if d and d != "None"}

muettes, vivantes = [], []
for d in sorted(seen):
    ok = pushes.get(d, {}).get("n", 0) or 0
    ko = pushes.get(d, {}).get("ko", 0) or 0
    bloques = (rejects.get(d, {}).get("n", 0) or 0) + (silent.get(d, {}).get("n", 0) or 0)
    # Le motif dominant : on privilegie le drop silencieux, plus revelateur
    # d'un blocage structurel qu'un rejet public conjoncturel.
    s, r = silent.get(d), rejects.get(d)
    motif = lab(s["top"]) if s and s.get("n") else (lab(r["top"]) if r else "—")
    pair = (s or {}).get("pair")
    (muettes if ok == 0 else vivantes).append(
        {"d": d, "ok": ok, "ko": ko, "bloques": bloques, "motif": motif, "pair": pair}
    )

lines = []
if not seen:
    # Cas le plus grave : aucune destination n'apparaît nulle part. Ce n'est
    # pas « tout va bien », c'est « le dispatch est coupé en amont ».
    lines.append("⚠️ <b>Aucune destination n'apparaît dans les journaux.</b>")
    lines.append("")
    lines.append("Radar arrêté, dispatch coupé en amont, ou base inaccessible. "
                 "À vérifier en priorité — ce n'est pas un signe de calme.")
    print("\n".join(lines))
    raise SystemExit(0)

if muettes:
    lines.append(f"🔇 <b>{len(muettes)} destination(s) muette(s)</b> sur {W} h")
    lines.append("")
    for m in muettes:
        lines.append(f"  • <b>{m['d']}</b> — 0 ordre passé, {m['bloques']} tentatives bloquées")
        detail = f"      cause dominante : {m['motif']}"
        if m["pair"]:
            detail += f" (surtout {m['pair']})"
        lines.append(detail)
        if m["ko"]:
            lines.append(f"      ⚠️ {m['ko']} envois refusés par le bridge")
    lines.append("")
    lines.append("<i>Une destination qui voit du trafic sans rien exécuter est "
                 "soit mal admise, soit mal configurée. Vérifier son état dans "
                 "pair_admission_state avant de toucher à l'infra.</i>")
else:
    lines.append(f"✅ <b>Aucune destination muette</b> sur {W} h")

if vivantes:
    lines.append("")
    lines.append("📤 <b>Destinations actives</b>")
    for v in sorted(vivantes, key=lambda x: -x["ok"]):
        suffix = f" · {v['ko']} refusés" if v["ko"] else ""
        lines.append(f"  • {v['d']} — {v['ok']} ordre(s){suffix}, {v['bloques']} bloqués")

print("\n".join(lines))
PY
)

if [ -z "$BODY" ]; then
  echo "empty body" >&2
  exit 1
fi

MESSAGE=$(printf "<b>Destinations · %s</b>\n\n%s" "$TODAY" "$BODY")

# DRY_RUN=1 : affiche sans envoyer
if [ "${DRY_RUN:-0}" = "1" ]; then
  echo "----- DRY RUN -----"
  echo "$MESSAGE"
  exit 0
fi

curl -sS --max-time 10 -X POST \
  "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
  -d "chat_id=${CHAT_ID}" \
  --data-urlencode "text=${MESSAGE}" \
  -d "parse_mode=HTML" \
  -d "disable_web_page_preview=true" > /dev/null

echo "$(date -Iseconds) sent silent-destinations alert"
