#!/usr/bin/env python3
"""Fermer tot les trades deja negatifs : ca aide ou ca coute ?

Pre-inscrit dans docs/predictions/2026-10-11_couper_les_negatifs_tot.md
(commit 70657c9) AVANT d'ecrire ce fichier. Demande de Xavier : "et si on
ferme tous les trades negatifs au demarrage ?" -- la pre-inscription resout
l'ambiguite en mesurant le DELAI k au lieu de le supposer.

Magasin M1 **du courtier**, bati en un seul passage (un decalage par page, lu
dans la meme reponse) : 99 999 bougies, 2026-07-01 -> 2026-10-09 20h55, cette
derniere etant la cloture reelle du vendredi.

⚠️ Ancres d'execution : 149/171 (87,1 %). Le reste est a +/-1 min, residu de
la derive du champ de decalage entre les 21 pages (+2 163 a +2 164 min). Cette
mesure est a la MINUTE, pas a la seconde : c'est suffisant ici, et dit.
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
TP_USD = 2.0 * EUR_USD
SL_USD = 20.0 * EUR_USD
POINT_USD = 0.01
PAS_ENTREE = int(os.getenv("PAS_ENTREE", "30"))     # une entree / 30 min
CAP = int(os.getenv("CAP", "1440"))                 # 24 h, puis sortie au prix
DELAIS = (1, 2, 3, 5, 10)
PLAFOND_T = 2.241                                   # pre-inscrit
MIN_N = 1000                                        # pre-inscrit


def charger():
    c = sqlite3.connect(MAGASIN)
    rows = c.execute(
        "SELECT ts_utc, high, low, close, spread_pts FROM candles "
        "WHERE pair = 'XAU/USD' ORDER BY ts_utc").fetchall()
    ts, hi, lo, cl, sp = [], [], [], [], []
    for t, h, l, c2, s in rows:
        d = dt.datetime.fromisoformat(t)
        ts.append(d.replace(tzinfo=None) if d.tzinfo else d)
        hi.append(h)
        lo.append(l)
        cl.append(c2)
        sp.append(s if s is not None else 5.0)
    return ts, hi, lo, cl, sp


def tenir(hi, lo, cl, i, achat):
    """P&L brut en USD jusqu'a une borne, et 'TP'/'SL'/'TEMPS'."""
    e = cl[i]
    tp = e + TP_USD if achat else e - TP_USD
    sl = e - SL_USD if achat else e + SL_USD
    fin = min(len(hi), i + 1 + CAP)
    for j in range(i + 1, fin):
        if achat:
            touche_sl = lo[j] <= sl
            touche_tp = hi[j] >= tp
        else:
            touche_sl = hi[j] >= sl
            touche_tp = lo[j] <= tp
        # ⛔ Une bougie qui contient les DEUX compte comme un stop.
        if touche_sl:
            return -SL_USD, "SL"
        if touche_tp:
            return TP_USD, "TP"
    d = cl[fin - 1] - e
    return (d if achat else -d), "TEMPS"


def main():
    ts, hi, lo, cl, sp = charger()
    print("magasin %s" % MAGASIN)
    print("%d bougies M1   %s -> %s" % (len(ts), ts[0], ts[-1]))
    entrees = list(range(0, len(ts) - max(DELAIS) - 1, PAS_ENTREE))
    milieu = ts[len(ts) // 2]
    print("entrees : %d toutes les %d min, DEUX sens  ⇒  %d trades"
          % (len(entrees), PAS_ENTREE, 2 * len(entrees)))
    print("bornes TP %.3f $ / SL %.3f $   plafond de duree %d min   "
          "coupure d'echantillon %s" % (TP_USD, SL_USD, CAP, milieu.date()))

    # TENIR : calcule UNE fois, il ne depend pas de k.
    base = []
    for i in entrees:
        cout = sp[i] * POINT_USD
        for achat in (True, False):
            brut, issue = tenir(hi, lo, cl, i, achat)
            base.append((i, achat, brut - cout, issue, cout))
    print("trades simules : %d" % len(base))
    issues = collections.Counter(x[3] for x in base)
    print("issues de TENIR : %s" % dict(issues))
    print("P&L de TENIR : %+.4f $/trade" % st.fmean(x[2] for x in base))

    print("\n%-6s%8s%10s%12s%12s%10s%9s%12s"
          % ("k", "n neg", "part neg", "TENIR $", "COUPER $", "ecart", "t",
             "neg -> TP"))
    resultats = {}
    for k in DELAIS:
        par_jour = collections.defaultdict(list)
        n_neg = 0
        neg_vers_tp = 0
        tenir_tot, couper_tot = [], []
        moities = {True: [], False: []}
        for (i, achat, pnl_tenir, issue, cout) in base:
            if i + k >= len(cl):
                continue
            ecart = (cl[i + k] - cl[i]) if achat else (cl[i] - cl[i + k])
            negatif = (ecart - cout) < 0
            if negatif:
                n_neg += 1
                pnl_couper = ecart - cout
                if issue == "TP":
                    neg_vers_tp += 1
            else:
                pnl_couper = pnl_tenir
            jour = ts[i].date()
            par_jour[jour].append(pnl_couper - pnl_tenir)
            tenir_tot.append(pnl_tenir)
            couper_tot.append(pnl_couper)
            moities[ts[i] < milieu].append(pnl_couper - pnl_tenir)
        jours = [st.fmean(v) for v in par_jour.values()]
        m = st.fmean(jours)
        s = st.stdev(jours) if len(jours) > 2 else 0.0
        t = m / (s / math.sqrt(len(jours))) if s else 0.0
        n = len(tenir_tot)
        print("%-6d%8d%9.1f%%%12.4f%12.4f%10.4f%+9.2f%11.1f%%"
              % (k, n_neg, 100 * n_neg / n, st.fmean(tenir_tot),
                 st.fmean(couper_tot), m, t,
                 100 * neg_vers_tp / max(1, n_neg)))
        resultats[k] = {
            "n": n, "n_neg": n_neg, "tenir": st.fmean(tenir_tot),
            "couper": st.fmean(couper_tot), "ecart": m, "t": t,
            "jours": len(jours),
            "sd_tenir": st.stdev(tenir_tot), "sd_couper": st.stdev(couper_tot),
            "pire_jour_tenir": min(st.fmean([x for x in v]) for v in
                                   _par_jour(base, ts, milieu).values()),
            "moitie_dans": st.fmean(moities[True]) if moities[True] else 0.0,
            "moitie_hors": st.fmean(moities[False]) if moities[False] else 0.0,
            "neg_vers_tp": neg_vers_tp,
        }

    print("\n=== VARIANCE ET PIRE JOURNEE (la prediction 3) ===")
    print("%-6s%14s%14s%14s%14s" % ("k", "ecart-type T", "ecart-type C",
                                    "pire jour T", "pire jour C"))
    jours_tenir = collections.defaultdict(list)
    for (i, achat, pnl_tenir, issue, cout) in base:
        jours_tenir[ts[i].date()].append(pnl_tenir)
    pire_t = min(st.fmean(v) for v in jours_tenir.values())
    for k in DELAIS:
        jours_c = collections.defaultdict(list)
        for (i, achat, pnl_tenir, issue, cout) in base:
            if i + k >= len(cl):
                continue
            ecart = (cl[i + k] - cl[i]) if achat else (cl[i] - cl[i + k])
            jours_c[ts[i].date()].append(
                (ecart - cout) if (ecart - cout) < 0 else pnl_tenir)
        pire_c = min(st.fmean(v) for v in jours_c.values())
        r = resultats[k]
        print("%-6d%14.4f%14.4f%14.4f%14.4f"
              % (k, r["sd_tenir"], r["sd_couper"], pire_t, pire_c))

    print("\n=== LES 4 CRITERES PRE-INSCRITS ===")
    retenus = []
    for k in DELAIS:
        r = resultats[k]
        c1 = r["couper"] > r["tenir"]
        c2 = abs(r["t"]) > PLAFOND_T
        c3 = r["n"] >= MIN_N
        c4 = (r["moitie_dans"] > 0) == (r["moitie_hors"] > 0)
        ok = c1 and c2 and c3 and c4
        print("   k=%-3d %s couper>tenir  %s |t|>%.3f (%+.2f)  %s n>=%d (%d)  "
              "%s signe stable (%+.4f / %+.4f)  ⇒ %s"
              % (k, "✅" if c1 else "⛔", "✅" if c2 else "⛔", PLAFOND_T,
                 r["t"], "✅" if c3 else "⛔", MIN_N, r["n"],
                 "✅" if c4 else "⛔", r["moitie_dans"], r["moitie_hors"],
                 "RETENU" if ok else "rejete"))
        if ok:
            retenus.append(k)
    print("\n⇒ %d delai(s) retenu(s) sur %d" % (len(retenus), len(DELAIS)))
    return 0


def _par_jour(base, ts, milieu):
    d = collections.defaultdict(list)
    for (i, achat, pnl_tenir, issue, cout) in base:
        d[ts[i].date()].append(pnl_tenir)
    return d


if __name__ == "__main__":
    sys.exit(main())
