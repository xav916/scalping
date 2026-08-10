#!/usr/bin/env python3
"""L'edge vient-il de la GESTION DE SORTIE plutôt que du choix des entrées ?

Deux faits mesurés cohabitent et semblent se contredire :
  - le contrôle aléatoire ne trouve AUCUN edge à la sélection d'entrée
    (Δ = +0,004 R sur 29 000 trades, quand 0,073 serait viable) ;
  - le compte démo gagne pourtant **+742,55 €** sur 609 trades réels.

Les deux peuvent être vrais si l'argent ne vient pas du choix du moment
d'entrée, mais de ce que le système fait APRÈS : mise à zéro du risque,
prise partielle, stop suiveur. Le contrôle aléatoire ne simulait pas ça.

## Le test

Pour chaque trade réel, on retrouve son jumeau simulé dans `backtest.trades`,
qui suit la MÊME entrée avec un SL/TP FIXE, sans aucune gestion. On compare :

    R_reel  = pnl_eur / risk_money_eur      <- avec gestion
    R_fixe  = backtest.trades.rr_realized   <- sans gestion

⚠️ R_reel se calcule sur le RÉSULTAT EN EUROS rapporté au risque engagé, PAS
   sur le prix de sortie. Une première version comparait `exit_price` à
   l'entrée : elle donnait −0,12 R alors que le compte gagne réellement +742 €.
   La cause : le système fait des PRISES PARTIELLES. La moitié encaissée au TP1
   n'apparaît pas dans le prix de sortie final, qui ne décrit que le reliquat.
   Mesurer sur ce prix sous-estime systématiquement les trades où la gestion a
   justement fait son travail.

⚠️ `risk_money` est lu dans `notes` (écrit par le bridge à l'exécution),
   présent sur les 609 trades. Le pnl inclut swap et commission, que le
   contrefactuel ignore : l'écart est donc LÉGÈREMENT défavorable à la
   gestion, jamais l'inverse.

⚠️ Le système réémet le même signal plusieurs fois. Un trade réel a donc
   souvent plusieurs jumeaux candidats. On ne garde le rattachement que si
   TOUS les candidats s'accordent sur l'issue — sinon on écarte la ligne
   plutôt que d'en choisir une au hasard.

Usage :
    python3 scripts/tester_edge_gestion_sorties.py
"""
import re
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.telegram_service import destination_for_ticket  # noqa: E402

FENETRE_AVANT = timedelta(minutes=90)
FENETRE_APRES = timedelta(minutes=30)
TOLERANCE_PRIX = 0.002  # 0,2 % — absorbe le glissement d'entrée


def _dt(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def _sens(direction: str) -> int:
    return 1 if str(direction).strip().lower().startswith("b") else -1


def main() -> int:
    t = sqlite3.connect("/app/data/trades.db")
    t.row_factory = sqlite3.Row
    b = sqlite3.connect("/app/data/backtest.db")
    b.row_factory = sqlite3.Row

    lignes = t.execute(
        "SELECT mt5_ticket, pnl, notes, pair, direction, entry_price, stop_loss, "
        "       take_profit, exit_price, close_reason, created_at "
        "  FROM personal_trades "
        " WHERE status = 'CLOSED' AND exit_price IS NOT NULL"
    ).fetchall()

    demo = [
        r for r in lignes
        if str(r["mt5_ticket"]).isdigit()
        and destination_for_ticket(int(r["mt5_ticket"])) == "admin_legacy"
    ]

    apparies = []
    ecartes = Counter()

    for r in demo:
        d0 = _dt(r["created_at"])
        e, sl, x = r["entry_price"], r["stop_loss"], r["exit_price"]
        if not d0 or not e or not sl or x is None:
            ecartes["donnees manquantes"] += 1
            continue
        risque = abs(e - sl)
        if risque <= 0:
            ecartes["stop colle a l'entree"] += 1
            continue
        m = re.search(r"risk_money=([0-9.]+)", r["notes"] or "")
        if not m or float(m.group(1)) <= 0:
            ecartes["risk_money absent"] += 1
            continue
        risk_money = float(m.group(1))

        cands = b.execute(
            "SELECT outcome, rr_realized, mfe_pct, mae_pct, entry_price "
            "  FROM trades "
            " WHERE pair = ? AND direction = ? AND outcome != 'OPEN' "
            "   AND emitted_at BETWEEN ? AND ?",
            (r["pair"], r["direction"],
             (d0 - FENETRE_AVANT).isoformat(), (d0 + FENETRE_APRES).isoformat()),
        ).fetchall()
        proches = [c for c in cands
                   if abs(c["entry_price"] - e) <= abs(e) * TOLERANCE_PRIX]
        if not proches:
            ecartes["aucun jumeau simule"] += 1
            continue
        issues = {c["outcome"] for c in proches}
        if len(issues) > 1:
            ecartes["jumeaux en desaccord"] += 1
            continue

        r_reel = r["pnl"] / risk_money
        r_prix = (x - e) * _sens(r["direction"]) / risque
        r_fixe = statistics.median([c["rr_realized"] for c in proches])
        apparies.append({
            "pair": r["pair"],
            "cause": r["close_reason"],
            "issue_fixe": proches[0]["outcome"],
            "r_reel": r_reel,
            "r_prix": r_prix,
            "r_fixe": r_fixe,
            "mfe": statistics.median([c["mfe_pct"] for c in proches]),
        })

    print(f"trades demo clotures    : {len(demo)}")
    print(f"apparies au contrefactuel: {len(apparies)}")
    for k, n in ecartes.most_common():
        print(f"  ecartes — {k:26s} {n:4d}")
    if not apparies:
        print("\nechantillon vide : test impossible.")
        return 1

    reels = [a["r_reel"] for a in apparies]
    fixes = [a["r_fixe"] for a in apparies]
    n = len(apparies)
    delta = [a["r_reel"] - a["r_fixe"] for a in apparies]

    print()
    print("=== R moyen sur les MEMES trades ===")
    print(f"  (rappel) R calcule sur le seul prix de sortie : "
          f"{statistics.mean([a['r_prix'] for a in apparies]):+.4f} R "
          f"— BIAISE par les prises partielles, ne pas utiliser")
    print(f"  avec gestion de sortie : {statistics.mean(reels):+.4f} R")
    print(f"  SL/TP fixe, sans rien  : {statistics.mean(fixes):+.4f} R")
    print(f"  ecart                  : {statistics.mean(delta):+.4f} R par trade")
    if n > 1:
        et = statistics.stdev(delta)
        err = et / (n ** 0.5)
        print(f"  ecart-type de l'ecart  : {et:.4f}  |  erreur-type {err:.4f}")
        print(f"  intervalle 95 %        : "
              f"[{statistics.mean(delta) - 1.96 * err:+.4f} ; "
              f"{statistics.mean(delta) + 1.96 * err:+.4f}] R")
        print(f"  t ~ {statistics.mean(delta) / err:+.2f}")

    print()
    print("=== decomposition : ce que la gestion fait selon l'issue SANS elle ===")
    par_issue = defaultdict(list)
    for a in apparies:
        par_issue[a["issue_fixe"]].append(a)
    print("  %-10s %5s %12s %12s %12s" % ("issue fixe", "n", "R fixe", "R reel", "ecart"))
    for issue, lot in sorted(par_issue.items(), key=lambda kv: -len(kv[1])):
        rf = statistics.mean([a["r_fixe"] for a in lot])
        rr = statistics.mean([a["r_reel"] for a in lot])
        print("  %-10s %5d %+11.4f %+12.4f %+12.4f" % (issue, len(lot), rf, rr, rr - rf))

    print()
    print("=== par cause de cloture reelle ===")
    par_cause = defaultdict(list)
    for a in apparies:
        par_cause[a["cause"] or "(NULL)"].append(a)
    print("  %-14s %5s %12s %12s" % ("cause", "n", "R reel", "ecart"))
    for cause, lot in sorted(par_cause.items(), key=lambda kv: -len(kv[1])):
        rr = statistics.mean([a["r_reel"] for a in lot])
        ec = statistics.mean([a["r_reel"] - a["r_fixe"] for a in lot])
        print("  %-14s %5d %+11.4f %+12.4f" % (cause, len(lot), rr, ec))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
