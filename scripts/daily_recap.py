"""Daily recap PnL par COMPTE — envoie le bilan 24h sur le fil infra.

Une section par compte de trading, nommée avec la convention du 06/09 —
`[RÉEL · IC_MARKETS]`, `[RÉEL · KRAKEN]`, `[DÉMO · PEPPERSTONE]` — via
`canaux_telegram.libelle()`, la seule source de ces libellés.

Source de vérité : `personal_trades` filtré sur `destination_id`.

⛔ Ce filtre remplace une jointure via `mt5_pushes` avec
`CAST(ticket AS INTEGER)`. Les tickets Kraken étant des UUID, le cast rendait
0 : **Kraken n'apparaissait dans aucun récap**, alors qu'il trade en argent
réel — 15 clôtures sur 30 jours, invisibles.

⛔ **Binance a disparu du récap.** La destination est désarmée depuis le
02/08 ; sa section affichait « Binance API keys missing » à chaque passage,
ce qui se lit comme un incident alors que c'est une décision. Le code de
collecte reste, inerte, pour le jour où elle reviendrait.

⚠️ Les devises ne s'additionnent pas : les comptes MT5 sont en EUR, Kraken en
USD. Chaque section porte la sienne.

Cron : `0 22 * * *` avec `CRON_TZ=Europe/Paris` — 22h à Paris. Sans le TZ il
partait à 22h UTC, donc à MINUIT.

Usage manuel :
    /opt/binance-bridge/venv/bin/python /opt/scalping/scripts/daily_recap.py [--since ISO]

Variables d'env requises (exporter avant l'appel ou via cron) :
- BINANCE_API_KEY / BINANCE_API_SECRET / BINANCE_ENV
- INFRA_TELEGRAM_TOKEN (le shadow public token de l'endpoint infra-telegram)
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

try:
    import httpx
except ImportError:
    print("ERROR: httpx package missing", file=sys.stderr)
    sys.exit(1)

BINANCE_ENV = os.getenv("BINANCE_ENV", "testnet").lower()
_BASE_URLS = {
    "testnet": "https://testnet.binancefuture.com",
    "live": "https://fapi.binance.com",
}
BASE_URL = _BASE_URLS.get(BINANCE_ENV)
API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")
INFRA_TELEGRAM_TOKEN = os.getenv("INFRA_TELEGRAM_TOKEN", "shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg")
SCALPING_URL = os.getenv("SCALPING_URL", "http://127.0.0.1:8000")


def _sign(params: dict[str, Any]) -> dict[str, Any]:
    params = dict(params)
    params["timestamp"] = int(time.time() * 1000)
    query = urlencode(params, doseq=True)
    sig = hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    params["signature"] = sig
    return params


def _signed_get(path: str, params: dict[str, Any] | None = None) -> Any:
    headers = {"X-MBX-APIKEY": API_KEY}
    with httpx.Client(timeout=15.0) as c:
        r = c.get(f"{BASE_URL}{path}", params=_sign(params or {}), headers=headers)
        r.raise_for_status()
        return r.json()


def fetch_binance(since_ms: int) -> dict[str, Any]:
    """Wallet snapshot + income décomposé sur 24h.

    ⚠️ BINANCE_DISABLED (2026-08-04) : la destination admin_binance est
    coupée depuis le 2026-08-02. Sans ce drapeau le recap affichait
    « Binance API keys missing », ce qui laissait croire à un incident de
    configuration alors que c'est une décision assumée.
    """
    if os.getenv("BINANCE_DISABLED"):
        return {"error": "destination désactivée (doublon Kraken, arrêtée le 02/08)"}
    if not API_KEY or not API_SECRET:
        return {"error": "Binance API keys missing"}
    try:
        wallet = _signed_get("/fapi/v2/account")
    except Exception as e:
        return {"error": f"wallet fetch: {e}"}
    try:
        rows: list[dict[str, Any]] = []
        cursor = since_ms
        end_ms = int(time.time() * 1000)
        while True:
            batch = _signed_get(
                "/fapi/v1/income",
                {"startTime": cursor, "endTime": end_ms, "limit": 1000},
            )
            if not batch:
                break
            rows.extend(batch)
            if len(batch) < 1000:
                break
            last_ts = max(int(r["time"]) for r in batch)
            if last_ts <= cursor:
                break
            cursor = last_ts + 1
    except Exception as e:
        return {"error": f"income fetch: {e}"}

    by_type: dict[str, float] = {}
    by_symbol: dict[str, float] = {}
    for r in rows:
        amt = float(r.get("income", 0))
        t = r.get("incomeType", "?")
        sym = r.get("symbol", "")
        by_type[t] = by_type.get(t, 0) + amt
        if sym:
            by_symbol[sym] = by_symbol.get(sym, 0) + amt
    top = sorted(by_symbol.items(), key=lambda kv: kv[1])[:3]  # 3 plus mauvais
    best = max(by_symbol.items(), key=lambda kv: kv[1], default=("-", 0))
    return {
        "wallet_balance": float(wallet.get("totalWalletBalance", 0)),
        "unrealized": float(wallet.get("totalUnrealizedProfit", 0)),
        "realized": by_type.get("REALIZED_PNL", 0),
        "commission": by_type.get("COMMISSION", 0),
        "funding": by_type.get("FUNDING_FEE", 0),
        "total_net": sum(by_type.values()),
        "top_losses": top,
        "best_winner": best,
        "rows_count": len(rows),
    }


def fetch_mt5(since_iso: str) -> dict[str, Any]:
    """Via docker exec scalping-radar : PnL par destination sur 24h."""
    py = f'''
import sqlite3, json
from backend.services.trade_log_service import _DB_PATH
con = sqlite3.connect(str(_DB_PATH))
con.row_factory = sqlite3.Row
out = {{}}
# KRAKEN etait ABSENT du recap. La jointure passait par `mt5_pushes` et un
# CAST(... AS INTEGER) sur le ticket : les tickets Kraken sont des UUID, donc
# le cast rendait 0 et aucune ligne ne remontait. Un compte en ARGENT REEL
# n'apparaissait dans aucun recap — 15 clotures sur 30 jours, invisibles.
#
# `personal_trades` porte deja `destination_id` : on filtre dessus, ce qui
# marche pour TOUS les courtiers au lieu d'un seul.
# ⛔ Les LIBELLES viennent du conteneur, qui seul peut importer
# `canaux_telegram`. Ce script tourne sur l'HOTE, avec un venv qui n'a pas le
# paquet `backend` : mon premier essai importait le module et retombait en
# SILENCE sur un repli qui affichait « admin_live admin_live ».
#
# Les recopier ici en ferait une deuxieme table — la faute de la journee.
from backend.services.canaux_telegram import (libelle_avec_picto as _lib,
                                              canal_pour as _cp)
from backend.services.destinations_registry import DESTINATIONS as _DEST
import os as _os, json as _json, urllib.request as _url


def _compte(dest):
    """Solde du courtier, lu chez LUI. `None` si illisible.

    ⛔ Lecture NON bloquante : un bridge muet ne doit pas tuer le recap. Mais
    elle se DIT — « compte illisible » et « compte a zero » menent a des
    conclusions opposees, et c'est la seconde qu'on lirait dans un silence.
    """
    d = _DEST.get(dest)
    if d is None:
        return None
    try:
        u = _os.environ.get(d.url_env, "")
        k = _os.environ.get(d.key_env, "")
        rq = _url.Request(u.rstrip("/") + "/account",
                          headers={{getattr(d, "key_header", None) or "X-API-Key": k}})
        with _url.urlopen(rq, timeout=10) as r:
            o = _json.load(r)
    except Exception:
        return None
    # MT5 et Kraken ne parlent pas la meme langue : on normalise ICI, une
    # fois, plutot que dans le rendu.
    if "equity" in o:
        return {{"valeur": o.get("equity"), "solde": o.get("balance"),
                 "latent": o.get("profit"), "positions": o.get("positions_count"),
                 "devise": o.get("currency") or "?"}}
    if "portfolio_value_usd" in o:
        return {{"valeur": o.get("portfolio_value_usd"), "solde": None,
                 "latent": o.get("pnl_net_usd"), "positions": None,
                 "devise": "USD"}}
    return None
DEVISES = {{"admin_live": "EUR", "admin_legacy": "EUR",
            "admin_kraken": "USD", "admin_kraken_spot": "USD"}}
for dest in ("admin_live", "admin_kraken", "admin_kraken_spot", "admin_legacy"):
    # ⚠️ Une destination absente du registre n'a pas de section : inventer une
    # ligne « 0 trade » pour un compte qui n'existe pas ferait croire a un
    # compte silencieux la ou il n'y a pas de compte.
    if dest not in _DEST:
        continue
    rows = con.execute("""
        SELECT pt.pair, pt.pnl
        FROM personal_trades pt
        WHERE pt.status='CLOSED'
          AND pt.is_auto=1
          AND pt.closed_at >= ?
          AND pt.destination_id = ?
    """, ("{since_iso}", dest)).fetchall()
    pnls = [float(r["pnl"] or 0) for r in rows]
    by_pair = {{}}
    for r in rows:
        by_pair.setdefault(r["pair"], 0)
        by_pair[r["pair"]] += float(r["pnl"] or 0)
    out[dest] = {{
        "trades": len(rows),
        "pnl_total": sum(pnls),
        "by_pair": sorted(by_pair.items(), key=lambda kv: kv[1]),
        "libelle": _lib(_cp(dest)),
        "devise": DEVISES.get(dest, "?"),
        "compte": _compte(dest),
    }}
# Les clotures SANS destination : on les compte plutot que de les taire. Une
# ligne qu'aucun compte ne reclame est un trou de tracabilite, pas un zero.
orphelines = con.execute("""
    SELECT COUNT(*) FROM personal_trades
     WHERE status='CLOSED' AND is_auto=1 AND closed_at >= ?
       AND (destination_id IS NULL OR destination_id = '')
""", ("{since_iso}",)).fetchone()[0]
out["_orphelines"] = orphelines
print(json.dumps(out))
'''
    try:
        r = subprocess.run(
            ["sudo", "docker", "exec", "scalping-radar", "python3", "-c", py],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            return {"error": f"docker exec failed: {r.stderr[:200]}"}
        return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception as e:
        return {"error": str(e)}


def fetch_activite(since_iso: str) -> dict:
    """Transitions d'admission + signaux refuses de peu, sur 24h.

    Remplace deux notifications temps reel supprimees le 2026-08-04. C'est en
    relisant sa journee qu'on ajuste un seuil, pas a 3h du matin.
    """
    py = (
        "import sqlite3, json" + chr(10) +
        "from backend.services.trade_log_service import _DB_PATH" + chr(10) +
        "con = sqlite3.connect('file:' + str(_DB_PATH) + '?mode=ro', uri=True)" + chr(10) +
        "s = " + repr(since_iso) + chr(10) +
        "out = {}" + chr(10) +
        "out['transitions'] = dict(con.execute('SELECT state, COUNT(*) FROM "
        "pair_admission_state WHERE state_since >= ? GROUP BY state', (s,)).fetchall())" + chr(10) +
        "out['refus'] = con.execute('SELECT COUNT(*) FROM signal_rejections WHERE "
        "reason_code = ' + chr(34) + 'below_confidence' + chr(34) + ' AND created_at >= ?', (s,)).fetchone()[0]" + chr(10) +
        "h = con.execute('SELECT pair, COUNT(*) c FROM signal_rejections WHERE reason_code = ' "
        "+ chr(34) + 'below_confidence' + chr(34) + ' AND created_at >= ? GROUP BY pair "
        "ORDER BY c DESC LIMIT 1', (s,)).fetchone()" + chr(10) +
        "out['refus_top'] = list(h) if h else None" + chr(10) +
        "print(json.dumps(out))" + chr(10)
    )
    try:
        r = subprocess.run(
            ["docker", "exec", "scalping-radar", "python3", "-c", py],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            return {"error": "docker exec failed: " + r.stderr[:200]}
        return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception as e:
        return {"error": str(e)}


def render(date_str: str, mt5_data: dict, binance: dict, activite: dict | None = None) -> str:
    lines = []

    # ── Une section PAR COMPTE, nommee comme partout ailleurs ─────────
    #
    # Les libelles etaient ecrits en dur — « Pepperstone Demo », « IC Markets
    # Live » — et ne suivaient pas la convention par compte adoptee le 06/09.
    # Ils viennent desormais de `canaux_telegram.libelle()`, la seule source.
    #
    # KRAKEN etait absent du recap alors qu'il trade en ARGENT REEL.
    #
    # BINANCE en a disparu : la destination est desarmee depuis le 02/08, et
    # sa section affichait « Binance API keys missing » a chaque passage — ce
    # qui se lit comme un incident alors que c'est une decision.
    if "error" in mt5_data:
        lines += ["⚠️ Erreur récup MT5 : " + mt5_data["error"]]
    else:
        # ⚠️ Le libelle et la devise viennent de la COLLECTE, faite dans le
        # conteneur. Les recalculer ici serait impossible — ce script tourne
        # sur l'hote, sans le paquet `backend` — et mon premier essai
        # retombait en SILENCE sur « admin_live admin_live ».
        # ⚠️ Deux destinations peuvent partager un FIL, donc un libelle :
        # `admin_kraken` et `admin_kraken_spot` sont toutes deux
        # « [REEL · KRAKEN] ». Deux sections du meme nom seraient illisibles —
        # on ajoute l'identifiant SEULEMENT quand il y a ambiguite.
        comptes = [(k, v) for k, v in mt5_data.items()
                   if not k.startswith("_") and isinstance(v, dict)]
        vus = [v.get("libelle") for _, v in comptes]
        for dest, d in comptes:
            titre = d.get("libelle") or dest
            if vus.count(titre) > 1:
                titre = f"{titre} · {dest}"
            lines += [titre]
            dev = d.get("devise") or ""
            # ⚠️ Le PnL du jour est dit MEME a zero. « Rien affiche » et
            # « rien gagne » se ressemblent trop pour qu'on laisse le lecteur
            # trancher.
            n = d.get("trades", 0)
            lines.append(f"• {n} trade(s) fermé(s) · PnL du jour "
                         f"{d.get('pnl_total', 0):+.2f} {dev}".rstrip())
            if n:
                paires = d.get("by_pair") or []
                if paires and paires[-1][1] > 0:
                    lines.append(f"• Top : {paires[-1][0]} {paires[-1][1]:+.2f}")
                if paires and paires[0][1] < 0:
                    lines.append(f"• Pire : {paires[0][0]} {paires[0][1]:+.2f}")

            # Le montant du compte, lu CHEZ LE COURTIER — pas reconstitue
            # depuis nos propres lignes, qui peuvent en manquer.
            c = d.get("compte")
            if not c or c.get("valeur") is None:
                lines.append("• ⚠️ Compte illisible — ce n'est pas « zéro », "
                             "c'est « on n'a pas pu lire ».")
            else:
                bout = f"• Compte : {c['valeur']:.2f} {c.get('devise') or ''}".rstrip()
                # Le solde et le latent ne sont dits que si le courtier les
                # rend : les inventer ferait un chiffre faux d'apparence sure.
                if c.get("solde") is not None and c.get("latent") is not None:
                    bout += (f"  (solde {c['solde']:.2f}, "
                             f"latent {c['latent']:+.2f}")
                    if c.get("positions"):
                        bout += f" sur {c['positions']} position(s)"
                    bout += ")"
                lines.append(bout)
            lines.append("")

        # ⛔ Une cloture qu'aucun compte ne reclame est un trou de tracabilite,
        # pas un zero. On la COMPTE plutot que de la taire.
        orphelines = mt5_data.get("_orphelines") or 0
        if orphelines:
            lines += [f"⚠️ {orphelines} clôture(s) SANS destination — "
                      "elles n'apparaissent dans aucune section ci-dessus.", ""]

    # Activite du radar : ce qui etait pousse en temps reel sans declencher
    # de decision. Ici, ca sert a ajuster un seuil.
    if activite and "error" not in activite:
        tr = activite.get("transitions") or {}
        total = sum(tr.values())
        refus = activite.get("refus") or 0
        if total or refus:
            lines += ["", "⚙️ Activité du radar"]
        if total:
            detail = []
            for etat, libelle in (("AUTO_EXEC", "activées"), ("TELEGRAM", "en notif"),
                                  ("PAUSED", "en pause"), ("DEMOTED", "rétrogradées"),
                                  ("OBSERVED", "en observation")):
                if tr.get(etat):
                    detail.append(str(tr[etat]) + " " + libelle)
            lines.append("• " + str(total) + " changements de mode" +
                         (" (" + ", ".join(detail) + ")" if detail else ""))
        if refus:
            ligne = "• " + str(refus) + " signaux refusés faute de confiance"
            top = activite.get("refus_top")
            if top:
                ligne += " (surtout " + str(top[0]) + ", " + str(top[1]) + ")"
            lines.append(ligne)
    return "\n".join(lines)


def post_telegram(title: str, body: str, target: str = "infra") -> dict:
    """Envoie le recap sur le bot cible.

    - target=infra (default) : via endpoint backend /api/admin/notify-infra-telegram
    ex-`target=sales` : appel direct a api.telegram.org avec
    SALES_TELEGRAM_BOT_TOKEN. RETIRE le 06/09 — il faisait atterrir un recap
    TRANSVERSE dans le fil du compte reel IC Markets.
    """
    # CORRIGE LE 06/09. Deux chemins, tous deux fautifs :
    #
    #   target=sales : appel DIRECT a api.telegram.org avec
    #     SALES_TELEGRAM_BOT_TOKEN — le bot nomme « IC MARKETS trades ». Un
    #     recap TRANSVERSE atterrissait donc chaque nuit dans le fil du compte
    #     reel, hors de la table des canaux. Et l'enveloppe cron passait
    #     `sales` PAR DEFAUT.
    #
    #   target=infra : endpoint SANS `channel` — donc le defaut SILENCIEUX.
    #     La bonne destination, par un mecanisme documente comme un piege.
    #
    # Un recap qui parle de TOUS les comptes n'appartient au fil d'aucun. Il
    # part sur `infra`, EXPLICITEMENT, comme les trois autres digests.
    url = (f"{SCALPING_URL}/api/admin/notify-infra-telegram"
           f"?token={INFRA_TELEGRAM_TOKEN}&channel=infra")
    with httpx.Client(timeout=15.0) as c:
        r = c.post(url, json={"title": title, "body": body})
        return {"status": r.status_code, "response": r.json() if r.status_code < 500 else r.text[:200]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="ISO datetime UTC ou epoch_sec. Default: 24h ago.")
    ap.add_argument("--dry-run", action="store_true", help="N'envoie pas le Telegram, affiche le message")
    ap.add_argument("--target", choices=("infra",), default="infra",
                    help="Bot Telegram cible. sales requiert SALES_TELEGRAM_BOT_TOKEN/CHAT_ID dans l'env.")
    args = ap.parse_args()

    if args.since:
        try:
            if args.since.isdigit():
                since_ms = int(args.since) * 1000
            else:
                since_dt = datetime.fromisoformat(args.since.replace("Z", "+00:00"))
                since_ms = int(since_dt.timestamp() * 1000)
        except Exception as e:
            print(f"ERROR --since: {e}", file=sys.stderr)
            return 1
    else:
        since_ms = int((time.time() - 86400) * 1000)

    since_dt = datetime.fromtimestamp(since_ms / 1000, tz=timezone.utc)
    since_iso = since_dt.isoformat()
    paris_now = datetime.now(timezone.utc) + timedelta(hours=2)
    date_str = paris_now.strftime("%Y-%m-%d")

    mt5_data = fetch_mt5(since_iso)

    activite = fetch_activite(since_iso)
    binance = fetch_binance(since_ms)
    body = render(date_str, mt5_data, binance, activite)
    title = f"Daily recap 24h {date_str}"

    if args.dry_run:
        print(f"=== {title} ===")
        print(body)
        return 0

    result = post_telegram(title, body, target=args.target)
    print(f"telegram[{args.target}] POST status={result['status']} response={result['response']}")
    return 0 if result["status"] == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
