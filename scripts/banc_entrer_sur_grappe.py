#!/usr/bin/env python3
"""PISTE 2 : entrer a l'instant d'une GRAPPE de publications.

Pre-inscrit dans docs/predictions/2026-10-11_entrer_sur_une_grappe.md
(commit 52c10d8) AVANT d'ecrire ce fichier.

L'amplitude M5 de l'or fait x1,523 sur la bougie d'une grappe de 5 chiffres ou
plus dont un High. La grille des 120 couples n'a teste que des entrees
AVEUGLES. Ce banc fait se rencontrer les deux.

Temoin : des entrees tirees au hasard dans la MEME strate (heure UTC x jour de
semaine), hors de toute publication -- 200 tirages, plafond = 95e centile du
max|t| sur les 5 couples.
"""
from __future__ import annotations

import bisect
import collections
import datetime as dt
import math
import random
import sqlite3
import statistics as st
import sys

sys.path.insert(0, "/app/scripts")

from banc_amplitude_publications import (  # noqa: E402
    charger_evenements)

MAGASIN = "/app/data/candles_courtier.db"
EUR_USD = 1.1198
POINT_USD = 0.01
CAP = 288                      # 24 h de M5
N_PLACEBO = 200
MIN_N = 200
COUPLES = ((2.0, 20.0), (2.0, 2.0), (5.0, 5.0), (10.0, 10.0), (20.0, 20.0))
TAILLE_MIN = 5                 # grappe de 5 publications ou plus
TEMOINS = 15000                # univers de controle pre-calcule
GARDE_MIN = 30
SEED = 20261011


def charger():
    c = sqlite3.connect(MAGASIN)
    rows = c.execute("SELECT ts_utc, high, low, close, spread_pts FROM candles "
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


def escaliers(hi, lo, i):
    fin = min(len(hi), i + 1 + CAP)
    jm, nm, jb, nb = [], [], [], []
    hmax, lmin = -1e18, 1e18
    for j in range(i + 1, fin):
        if hi[j] > hmax:
            hmax = hi[j]
            jm.append(j)
            nm.append(hmax)
        if lo[j] < lmin:
            lmin = lo[j]
            jb.append(j)
            nb.append(-lmin)
    return (jm, nm), (jb, nb), fin - 1


def premier_haut(esc, cible):
    js, nv = esc
    k = bisect.bisect_left(nv, cible)
    return js[k] if k < len(js) else None


def premier_bas(esc, cible):
    js, nv = esc
    k = bisect.bisect_left(nv, -cible)
    return js[k] if k < len(js) else None


def issue(i, e, monte, baisse, cfin, tp_u, sl_u, achat):
    if achat:
        t_tp = premier_haut(monte, e + tp_u)
        t_sl = premier_bas(baisse, e - sl_u)
    else:
        t_tp = premier_bas(baisse, e - tp_u)
        t_sl = premier_haut(monte, e + sl_u)
    if t_sl is not None and (t_tp is None or t_sl <= t_tp):
        return -sl_u, (t_sl - i)
    if t_tp is not None:
        return tp_u, (t_tp - i)
    d = cfin - e
    return (d if achat else -d), None


def main():
    rng = random.Random(SEED)
    ts, hi, lo, cl, sp = charger()
    index = {t: i for i, t in enumerate(ts)}
    evts = charger_evenements()
    print("bougies M5 : %d   %s -> %s" % (len(ts), ts[0].date(), ts[-1].date()))

    # --- les instants de GRAPPE, meme definition que le banc d'amplitude ---
    par_minute = collections.defaultdict(list)
    for d, imp in evts:
        par_minute[d.replace(tzinfo=None, second=0, microsecond=0)].append(imp)
    grappes = []
    sales = set()
    for m, imps in par_minute.items():
        taille, high = 0, False
        for k in range(-5, 6):
            v = par_minute.get(m + dt.timedelta(minutes=k))
            if v:
                taille += len(v)
                high = high or ("High" in v)
        base = m.replace(minute=(m.minute // 5) * 5)
        for k in range(-(GARDE_MIN // 5), GARDE_MIN // 5 + 1):
            sales.add(base + dt.timedelta(minutes=5 * k))
        if taille >= TAILLE_MIN and high and base in index:
            grappes.append(index[base])
    grappes = sorted(set(grappes))
    print("instants de grappe (>=%d publications, dont une High) dans la "
          "fenetre : %d" % (TAILLE_MIN, len(grappes)))

    # --- univers de controle : propre, et apparie par strate ---
    propres = [i for i, t in enumerate(ts) if t not in sales and i < len(ts) - 2]
    rng.shuffle(propres)
    temoins = sorted(propres[:TEMOINS])
    print("univers de controle pre-calcule : %d bougies propres" % len(temoins))

    besoins = sorted(set(grappes) | set(temoins))
    print("escaliers a calculer : %d" % len(besoins))
    paquets = {}
    for i in besoins:
        monte, baisse, dernier = escaliers(hi, lo, i)
        paquets[i] = (cl[i], monte, baisse, cl[dernier], sp[i])

    # --- resultats par couple ---
    def pnl(i, tp_e, sl_e):
        e, monte, baisse, cfin, spread = paquets[i]
        tp_u, sl_u = tp_e * EUR_USD, sl_e * EUR_USD
        cout = spread * POINT_USD
        a, da = issue(i, e, monte, baisse, cfin, tp_u, sl_u, True)
        v, dv = issue(i, e, monte, baisse, cfin, tp_u, sl_u, False)
        duree = [x for x in (da, dv) if x is not None]
        return (a - cout, v - cout,
                st.fmean(duree) if duree else float("nan"))

    def agreger(indices, tp_e, sl_e):
        par_jour = collections.defaultdict(list)
        durees = []
        for i in indices:
            a, v, d = pnl(i, tp_e, sl_e)
            par_jour[ts[i].date()].extend((a, v))
            if not math.isnan(d):
                durees.append(d)
        jours = [st.fmean(x) for x in par_jour.values()]
        if len(jours) < 3:
            return 0.0, 0.0, 0, 0.0
        m = st.fmean(jours)
        s = st.stdev(jours)
        return (m, (m / (s / math.sqrt(len(jours))) if s else 0.0),
                2 * len(indices), st.fmean(durees) if durees else float("nan"))

    par_strate = collections.defaultdict(list)
    for i in temoins:
        par_strate[(ts[i].hour, ts[i].weekday())].append(i)

    def tirer():
        out = []
        for i in grappes:
            pool = par_strate.get((ts[i].hour, ts[i].weekday()))
            if pool:
                out.append(rng.choice(pool))
        return out

    print("\n%-14s%12s%9s%8s%14s%12s%9s%11s"
          % ("couple", "GRAPPE $", "t", "n", "duree (bougies)", "TEMOIN $",
             "t", "ecart"))
    reels = {}
    for (tp_e, sl_e) in COUPLES:
        mg, tg, ng, dg = agreger(grappes, tp_e, sl_e)
        mt, tt, nt, dt_ = agreger(temoins, tp_e, sl_e)
        reels[(tp_e, sl_e)] = (mg, mt, mg - mt, ng)
        print("%-14s%12.4f%+9.2f%8d%14.1f%12.4f%+9.2f%11.4f"
              % ("TP%g/SL%g" % (tp_e, sl_e), mg, tg, ng, dg, mt, tt, mg - mt))
        print("%-14s   duree moyenne jusqu'a une borne : grappe %.1f bougies "
              "contre temoin %.1f" % ("", dg, dt_))

    # --- plafond par permutation ---
    print("\nplacebo : 200 tirages de faux instants, appaires heure x jour...")
    maxima = []
    for k in range(N_PLACEBO):
        faux = tirer()
        mx = 0.0
        for (tp_e, sl_e) in COUPLES:
            mf, tf, nf, df = agreger(faux, tp_e, sl_e)
            mt = reels[(tp_e, sl_e)][1]
            par_jour = collections.defaultdict(list)
            for i in faux:
                a, v, _ = pnl(i, tp_e, sl_e)
                par_jour[ts[i].date()].extend((a, v))
            jours = [st.fmean(x) - mt for x in par_jour.values()]
            if len(jours) > 2:
                m = st.fmean(jours)
                s = st.stdev(jours)
                t = m / (s / math.sqrt(len(jours))) if s else 0.0
                mx = max(mx, abs(t))
        maxima.append(mx)
        if (k + 1) % 50 == 0:
            print("   %d/%d..." % (k + 1, N_PLACEBO), flush=True)
    maxima.sort()
    plafond = maxima[int(0.95 * len(maxima)) - 1]
    print("\nPLAFOND (95e centile du max|t| sur %d tirages) : %.3f"
          % (N_PLACEBO, plafond))

    print("\n=== LE CRITERE PRE-INSCRIT ===")
    retenus = 0
    for (tp_e, sl_e) in COUPLES:
        mg, mt, ecart, ng = reels[(tp_e, sl_e)]
        par_jour = collections.defaultdict(list)
        for i in grappes:
            a, v, _ = pnl(i, tp_e, sl_e)
            par_jour[ts[i].date()].extend((a, v))
        jours = [st.fmean(x) - mt for x in par_jour.values()]
        m = st.fmean(jours)
        s = st.stdev(jours) if len(jours) > 2 else 0.0
        t = m / (s / math.sqrt(len(jours))) if s else 0.0
        ok = ecart > 0 and abs(t) > plafond and ng >= MIN_N
        print("   TP%g/SL%g : ecart %+.4f $, t %+.2f (plafond %.2f), n %d  ⇒ %s"
              % (tp_e, sl_e, ecart, t, plafond, ng,
                 "RETENU" if ok else "rejete"))
        retenus += int(ok)
    print("\n⇒ %d couple(s) retenu(s) sur %d" % (retenus, len(COUPLES)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
