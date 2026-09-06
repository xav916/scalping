#!/bin/bash
# ⛔ RETIRÉ LE 2026-09-06 — son sujet n'existe plus.
#
# Ce digest ne couvre que AAPL, TSLA, NVDA et MSFT. Ces quatre paires ont été
# SORTIES DE L'UNIVERS le 06/09 : 0 signal, 0 refus, 0 ordre en 30 jours, pour
# 12 % du quota de données. Mesure faite le même jour dans `shadow_setups` :
#
#     7 jours  : 0 setup
#     30 jours : 0 setup
#     dernier  : 2026-08-06
#
# Il envoyait donc un rapport vide chaque soir à 20:15 depuis un mois. Son cron
# est commenté ; le script reste ici, intact, pour le jour où ces paires
# reviendraient — c'est une décision de PÉRIMÈTRE, pas un verdict de
# rentabilité, et rien ne les a réfutées.
#
# ⚠️ Il appelait aussi l'API Telegram en direct, hors de la table des canaux.
# Si on le rallume, il faut d'abord le faire passer par l'endpoint, comme
# notify-energy-weekend-reminder.sh et notify-promotion-candidates.sh.
# Digest quotidien des signaux equity (AAPL/TSLA/NVDA/MSFT).
#
# Contexte : ces 4 paires ont été admises en état TELEGRAM le 2026-08-04
# (rows 140-147 de pair_admission_state) après découverte qu'elles étaient
# droppées silencieusement par `_not_a_star` depuis le déploiement des Voies
# A et B le 2026-08-02 — 0 trade, 0 rejection loggée, 0 notif.
#
# État TELEGRAM = visibles, JAMAIS envoyées à un bridge (zéro argent engagé).
# Le canal d'alertes setup temps-réel étant globalement éteint
# (TELEGRAM_SETUP_VERDICTS vide dans /opt/scalping/.env), ce digest est le
# seul canal d'observation. Il ne pousse aucun ordre : il informe.
#
# Source : table shadow_setups (entry/SL/TP/RR + outcome/pnl après
# réconciliation). Les outcomes equity se résolvent avec 96h de retard
# (timeframe '1h' absent de TIMEOUT_HOURS_BY_TF → fallback 96h).
#
# Push @xav_scalping_sales_bot chaque jour à 20h15 UTC = 22h15 Paris, soit
# 15 min après la clôture NYSE (20h00 UTC) pour couvrir la séance complète.
set -uo pipefail

DB=/opt/scalping/data/trades.db
BOT_TOKEN=$(grep -E '^SALES_TELEGRAM_BOT_TOKEN=' /opt/scalping/.env | cut -d= -f2-)
CHAT_ID=$(grep -E '^SALES_TELEGRAM_CHAT_ID=' /opt/scalping/.env | cut -d= -f2-)

if [ -z "$BOT_TOKEN" ] || [ -z "$CHAT_ID" ]; then
  echo "missing sales creds" >&2
  exit 1
fi

PAIRS_SQL="'AAPL','TSLA','NVDA','MSFT'"

# 1. Flux du jour : setups detectes depuis 00h UTC, split session NYSE
FLOW_JSON=$(sqlite3 "$DB" "
SELECT json_group_array(json_object(
  'pair', pair, 'direction', direction,
  'n', n, 'n_session', n_session,
  'rr', rr_avg, 'entry', last_entry, 'sl', last_sl, 'tp', last_tp
))
FROM (
  SELECT pair, direction,
         COUNT(*) AS n,
         SUM(CASE WHEN CAST(strftime('%H%M', detected_at) AS INTEGER) BETWEEN 1330 AND 2000
                   AND CAST(strftime('%w', detected_at) AS INTEGER) BETWEEN 1 AND 5
                  THEN 1 ELSE 0 END) AS n_session,
         ROUND(AVG(rr), 2) AS rr_avg,
         -- MAX(detected_at) + colonnes nues : SQLite garantit que les colonnes
         -- nues proviennent de la ligne qui a produit le MAX (= le setup le
         -- plus récent), pas d'un mélange de lignes.
         MAX(detected_at) AS last_at,
         ROUND(entry_price, 2) AS last_entry,
         ROUND(stop_loss, 2) AS last_sl,
         ROUND(take_profit_1, 2) AS last_tp
    FROM shadow_setups
   WHERE pair IN ($PAIRS_SQL)
     AND detected_at >= date('now')
   GROUP BY pair, direction
);
")

# 2. Outcomes shadow resolus (cumul depuis le debut de l'observation)
OUTCOME_JSON=$(sqlite3 "$DB" "
SELECT json_group_array(json_object(
  'pair', pair, 'direction', direction,
  'n_total', n_total, 'n_resolved', n_resolved,
  'n_win', n_win, 'n_sl', n_sl, 'n_to', n_to, 'pnl_pct', pnl_pct
))
FROM (
  SELECT pair, direction,
         COUNT(*) AS n_total,
         SUM(CASE WHEN outcome IS NOT NULL THEN 1 ELSE 0 END) AS n_resolved,
         SUM(CASE WHEN outcome = 'TP1' THEN 1 ELSE 0 END) AS n_win,
         SUM(CASE WHEN outcome = 'SL' THEN 1 ELSE 0 END) AS n_sl,
         SUM(CASE WHEN outcome = 'TIMEOUT' THEN 1 ELSE 0 END) AS n_to,
         ROUND(COALESCE(SUM(pnl_pct_net), 0), 2) AS pnl_pct
    FROM shadow_setups
   WHERE pair IN ($PAIRS_SQL)
   GROUP BY pair, direction
);
")

# 3. Etat d'admission courant (row la plus recente par pair x direction)
STATE_JSON=$(sqlite3 "$DB" "
SELECT json_group_array(json_object(
  'pair', pair, 'direction', direction, 'state', state
))
FROM (
  SELECT pair, direction, state
    FROM pair_admission_state pas1
   WHERE pair IN ($PAIRS_SQL)
     AND id = (SELECT MAX(id) FROM pair_admission_state pas2
                WHERE pas2.pair = pas1.pair
                  AND pas2.direction IS pas1.direction
                  AND pas2.destination IS NULL)
);
")

BODY=$(FLOW_JSON="$FLOW_JSON" OUTCOME_JSON="$OUTCOME_JSON" STATE_JSON="$STATE_JSON" python3 <<'PY'
import json, os

flow = json.loads(os.environ.get('FLOW_JSON') or '[]')
outcomes = json.loads(os.environ.get('OUTCOME_JSON') or '[]')
states = json.loads(os.environ.get('STATE_JSON') or '[]')

state_idx = {(s['pair'], s['direction']): s['state'] for s in states}
out_idx = {(o['pair'], o['direction']): o for o in outcomes}

# Seuils de promotion : alignes sur admin_live (60) et admin_kraken_stocks (75)
MIN_CONF_LIVE = 60
MIN_CONF_STOCKS = 75

lines = []

# ─── Flux du jour ───────────────────────────────────────────────────────
if flow:
    lines.append("📊 <b>Signaux du jour</b>")
    for f in sorted(flow, key=lambda x: -x['n']):
        st = state_idx.get((f['pair'], f['direction']), 'UNKNOWN')
        hors = f['n'] - f['n_session']
        lines.append(
            f"  • <b>{f['pair']} {f['direction'].upper()}</b> [{st}] — {f['n']} setups "
            f"({f['n_session']} en séance NYSE, {hors} hors séance)"
        )
        lines.append(
            f"      entrée {f['entry']} · SL {f['sl']} · TP {f['tp']} · R:R {f['rr']}"
        )
    lines.append("")
else:
    lines.append("📊 <b>Signaux du jour</b> — aucun setup equity détecté aujourd'hui.")
    lines.append("")

# ─── Resultats shadow ───────────────────────────────────────────────────
resolved_total = sum(o['n_resolved'] for o in outcomes)
if resolved_total:
    lines.append("🎯 <b>Résultats shadow (cumul)</b>")
    pnl_global = 0.0
    for o in sorted(outcomes, key=lambda x: -x['n_resolved']):
        if not o['n_resolved']:
            continue
        decisifs = o['n_win'] + o['n_sl']
        wr = (100.0 * o['n_win'] / decisifs) if decisifs else 0.0
        pnl_global += o['pnl_pct']
        lines.append(
            f"  • {o['pair']} {o['direction'].upper()} — {o['n_resolved']}/{o['n_total']} résolus · "
            f"{o['n_win']} TP / {o['n_sl']} SL / {o['n_to']} timeout"
        )
        lines.append(f"      WR {wr:.0f}% (hors timeouts) · PnL {o['pnl_pct']:+.2f}%")
    lines.append(f"  <b>Total : {pnl_global:+.2f}%</b> sur {resolved_total} trades simulés")
    lines.append("")
else:
    pending = sum(o['n_total'] for o in outcomes)
    lines.append("🎯 <b>Résultats shadow</b>")
    lines.append(f"  {pending} setups en attente de réconciliation (délai 96h après détection).")
    lines.append("  Premiers outcomes attendus à partir du 06/08.")
    lines.append("")

# ─── Rappel de statut ───────────────────────────────────────────────────
lines.append("🔒 <b>Statut</b> — état TELEGRAM : signaux visibles, "
             "<b>aucun ordre envoyé</b>, zéro euro engagé.")
lines.append(f"<i>Pour trader : passer en AUTO_EXEC (seuil {MIN_CONF_LIVE} sur admin_live CFD IC Markets, "
             f"{MIN_CONF_STOCKS} sur admin_kraken_stocks xStocks).</i>")
lines.append("<i>⚠️ V1 reste sans edge structurel — un score élevé ≠ un bon trade. "
             "Attendre les résultats shadow avant toute promotion.</i>")

print("\n".join(lines))
PY
)

if [ -z "$BODY" ]; then
  echo "empty body" >&2
  exit 0
fi

MESSAGE=$(printf "<b>Digest actions US · %s</b>\n\n%s" "$(date -u '+%Y-%m-%d')" "$BODY")

# DRY_RUN=1 : affiche le message sans l'envoyer (diagnostic)
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

echo "$(date -Iseconds) sent equity digest"
