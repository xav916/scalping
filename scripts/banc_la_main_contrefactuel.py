#!/usr/bin/env python3
"""PISTE 1 : la main de Xavier bat-elle le fait de ne RIEN faire ?

Pre-inscrit dans docs/predictions/2026-10-11_la_main_contre_le_contrefactuel.md
(commit 52c10d8) AVANT d'ecrire ce fichier.

Pour chaque trade ou il est INTERVENU (XAU, juillet -> 9 octobre 2026, argent
verifie chez le courtier), on compare :

    LUI   son net_pnl reellement realise
    RIEN  le meme trade laisse courir jusqu'a SES PROPRES bornes (stop /
          take_profit du ledger) ; si aucune n'est touchee avant SA cloture,
          la sortie est la MEME que la sienne (l'ecart vaut alors zero)

🔑 Le cout (spread, commission, swap) n'est pas modelise : on le DEDUIT de son
propre trade -- cout = mouvement theorique moins net_pnl realise -- et on
l'applique a l'identique au contrefactuel. Un cout modelise a la main aurait
ete un degre de liberte de plus.
"""
from __future__ import annotations

import collections
import datetime as dt
import math
import os
import sqlite3
import statistics as st
import sys

MAGASIN = os.getenv("MAGASIN", "/app/data/candles_courtier_m1_complet.db")
EUR_USD = 1.1198
DEBUT = "2026-07-01"
FIN = "2026-10-10"
PLAFOND_T = 2.5      # pre-inscrit
MIN_N = 100          # pre-inscrit
TP_DEFAUT_EUR = 2.0
SL_DEFAUT_EUR = 20.0


def charger_bougies():
    c = sqlite3.connect(MAGASIN)
    rows = c.execute("SELECT ts_utc, high, low, close FROM candles "
                     "WHERE pair = 'XAU/USD' ORDER BY ts_utc").fetchall()
    ts, hi, lo, cl = [], [], [], []
    for t, h, l, c2 in rows:
        d = dt.datetime.fromisoformat(t)
        ts.append(d.replace(tzinfo=None) if d.tzinfo else d)
        hi.append(h)
        lo.append(l)
        cl.append(c2)
    index = {t: i for i, t in enumerate(ts)}
    return ts, hi, lo, cl, index


def charger_trades():
    c = sqlite3.connect("/app/data/trades.db")
    return c.execute(
        "SELECT l.trade_id, p.direction, l.entry_executed, l.exit_executed, "
        "l.stop, l.take_profit, l.net_pnl, l.opened_at, l.closed_at, "
        "l.quantity, l.src_argent "
        "FROM trade_financial_ledger l JOIN personal_trades p "
        "ON p.id = l.trade_id "
        "WHERE l.human_intervention = 1 AND p.pair = 'XAU/USD' "
        "AND l.opened_at >= ? AND l.opened_at < ? "
        "AND l.net_pnl IS NOT NULL AND l.entry_executed IS NOT NULL "
        "AND l.exit_executed IS NOT NULL ORDER BY l.opened_at",
        (DEBUT, FIN)).fetchall()


def minute(s):
    d = dt.datetime.fromisoformat(s)
    if d.tzinfo:
        d = d.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return d.replace(second=0, microsecond=0)


def main():
    ts, hi, lo, cl, index = charger_bougies()
    trades = charger_trades()
    print("bougies M1 : %d   %s -> %s" % (len(ts), ts[0], ts[-1]))
    print("trades INTERVENUS (XAU, %s -> %s) : %d   dont argent courtier : %d"
          % (DEBUT, FIN, len(trades),
             sum(1 for t in trades if t[10] == "courtier")))

    lignes = []
    sans_bougie = 0
    for (tid, sens, entree, sortie, stop, tp, net, ouv, fer, qte, src) in trades:
        t0, t1 = minute(ouv), minute(fer)
        i = index.get(t0)
        j = index.get(t1)
        if i is None or j is None or j <= i:
            sans_bougie += 1
            continue
        achat = (sens == "buy")
        unite = (qte or 0.01) * 100.0 / EUR_USD       # EUR par dollar de mouvement
        # Bornes : les siennes si elles existent, sinon celles de production.
        if stop and stop > 0:
            niveau_sl = stop
        else:
            niveau_sl = entree - SL_DEFAUT_EUR / unite if achat \
                else entree + SL_DEFAUT_EUR / unite
        if tp and tp > 0:
            niveau_tp = tp
        else:
            niveau_tp = entree + TP_DEFAUT_EUR / unite if achat \
                else entree - TP_DEFAUT_EUR / unite
        # RIEN : premiere borne touchee entre son ouverture et sa cloture
        sortie_rien, issue = None, "SA CLOTURE"
        for k in range(i + 1, min(j + 1, len(ts))):
            if achat:
                touche_sl = lo[k] <= niveau_sl
                touche_tp = hi[k] >= niveau_tp
            else:
                touche_sl = hi[k] >= niveau_sl
                touche_tp = lo[k] <= niveau_tp
            if touche_sl:
                sortie_rien, issue = niveau_sl, "SL"
                break
            if touche_tp:
                sortie_rien, issue = niveau_tp, "TP"
                break
        if sortie_rien is None:
            sortie_rien = sortie            # identique a lui
        mvt_lui = (sortie - entree) if achat else (entree - sortie)
        mvt_rien = (sortie_rien - entree) if achat else (entree - sortie_rien)
        # 🔑 le cout est DEDUIT de son propre trade, pas modelise
        cout = mvt_lui * unite - net
        pnl_rien = mvt_rien * unite - cout
        lignes.append({
            "id": tid, "jour": t0.date(), "lui": net, "rien": pnl_rien,
            "issue": issue, "src": src, "premiere": t0 < minute("2026-09-01"),
        })
    print("trades utilisables : %d   (sans bougie : %d)"
          % (len(lignes), sans_bougie))

    def panneau(sel, nom):
        v = [x for x in lignes if sel(x)]
        if len(v) < 5:
            print("%-22s n=%d : trop peu" % (nom, len(v)))
            return
        par_jour = collections.defaultdict(list)
        for x in v:
            par_jour[x["jour"]].append(x["lui"] - x["rien"])
        jours = [st.fmean(w) for w in par_jour.values()]
        m = st.fmean(jours)
        s = st.stdev(jours) if len(jours) > 2 else 0.0
        t = m / (s / math.sqrt(len(jours))) if s else 0.0
        lui = st.fmean(x["lui"] for x in v)
        rien = st.fmean(x["rien"] for x in v)
        issues = collections.Counter(x["issue"] for x in v)
        m1 = [x["lui"] - x["rien"] for x in v if x["premiere"]]
        m2 = [x["lui"] - x["rien"] for x in v if not x["premiere"]]
        print("%-22s n=%-4d LUI %+8.2f EUR/trade   RIEN %+8.2f   "
              "ecart/jour %+7.2f   t %+5.2f   (%d jours)"
              % (nom, len(v), lui, rien, m, t, len(jours)))
        print("%-22s issues de RIEN : %s" % ("", dict(issues)))
        print("%-22s moities : %+.2f / %+.2f   total LUI %+.2f EUR, "
              "total RIEN %+.2f EUR"
              % ("", st.fmean(m1) if m1 else 0.0, st.fmean(m2) if m2 else 0.0,
                 sum(x["lui"] for x in v), sum(x["rien"] for x in v)))
        return {"n": len(v), "lui": lui, "rien": rien, "t": t, "m": m,
                "m1": st.fmean(m1) if m1 else 0.0,
                "m2": st.fmean(m2) if m2 else 0.0, "issues": issues}

    print("\n=== LUI contre RIEN ===")
    tout = panneau(lambda x: True, "tous")
    courtier = panneau(lambda x: x["src"] == "courtier", "argent courtier")
    panneau(lambda x: x["src"] != "courtier", "argent du stock")

    print("\n=== LES 4 CRITERES PRE-INSCRITS (panneau argent courtier) ===")
    r = courtier or tout
    if r:
        c1 = r["lui"] > r["rien"]
        c2 = abs(r["t"]) > PLAFOND_T
        c3 = r["n"] >= MIN_N
        c4 = (r["m1"] > 0) == (r["m2"] > 0)
        for nom, ok, det in (
                ("1. LUI > RIEN", c1, "%+.2f contre %+.2f" % (r["lui"], r["rien"])),
                ("2. |t| > %.1f" % PLAFOND_T, c2, "t = %+.2f" % r["t"]),
                ("3. n >= %d" % MIN_N, c3, "n = %d" % r["n"]),
                ("4. signe stable", c4, "%+.2f / %+.2f" % (r["m1"], r["m2"]))):
            print("   %s %-20s %s" % ("OK " if ok else "NON", nom, det))
        print("\n⇒ %s" % ("SA MAIN EST RETENUE" if (c1 and c2 and c3 and c4)
                          else "SA MAIN N'EST PAS RETENUE"))
        tot = sum(r["issues"].values())
        sl = r["issues"].get("SL", 0)
        print("   part de ses sorties qui auraient fini au STOP : %.1f %%"
              % (100 * sl / max(1, tot)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
