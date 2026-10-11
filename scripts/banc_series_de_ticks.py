#!/usr/bin/env python3
"""Les SERIES de ticks : continuation contre retournement.

Pre-inscrit dans docs/predictions/2026-10-11_series_de_ticks.md AVANT d'ecrire
ce fichier. C'est la figure de Xavier dans sa forme la plus simple : une serie
de k variations de bid consecutives dans le meme sens, puis on entre -- soit
dans le sens (continuation), soit contre (retournement).
"""
from __future__ import annotations

import collections
import datetime as dt
import math
import os
import random
import sqlite3
import statistics as st
import sys

MAGASIN = os.getenv("TICKS", "/app/data/ticks_courtier.db")
EUR_USD = 1.1198
LONGUEURS = (3, 5, 8, 12)
MOMENTS = ("au k-ieme", "a la cassure")
GEOMETRIES = (("production", None), ("symetrique", 2.0))
SL_DEPART = 13.0
TRAINAGE = 0.5
DECLENCHE = 0.5
PLANCHER = 2.0
MARGE_FRANCHIE = 0.10
PROT_AGE_SEC = 60
PROT_NEG_SEC = 30
CAP_SEC = 14400
REPOS_SEC = 300
MIN_N = 200
N_PLACEBO = 200
SEED = 20261011


def charger():
    c = sqlite3.connect(MAGASIN)
    rows = c.execute("SELECT ts_utc, ms, bid, ask FROM ticks "
                     "WHERE pair = 'XAU/USD' ORDER BY ts_utc, ms").fetchall()
    ts, bid, ask = [], [], []
    for t, ms, b, a in rows:
        if ms and ms > 1e12:
            ts.append(ms / 1000.0)
        else:
            d = dt.datetime.fromisoformat(t).replace(tzinfo=dt.timezone.utc)
            ts.append(d.timestamp() + (ms or 0) / 1000.0)
        bid.append(b)
        ask.append(a)
    return ts, bid, ask


def rejouer(ts, bid, ask, i, achat, borne):
    k = 1.0 / EUR_USD
    entree = ask[i] if achat else bid[i]
    t0 = ts[i]
    stop = -SL_DEPART if borne is None else -borne
    tp = 1e9 if borne is None else borne
    neg = None
    vu = vu_prot = -1e18
    n = len(ts)
    j = i + 1
    while j < n and ts[j] - t0 <= CAP_SEC:
        sortie = bid[j] if achat else ask[j]
        pnl = (sortie - entree) * k if achat else (entree - sortie) * k
        if pnl <= stop + 1e-12:
            return stop
        if pnl >= tp - 1e-12:
            return tp
        if borne is None:
            if ts[j] - vu >= 1:
                vu = ts[j]
                if pnl >= DECLENCHE - 1e-9:
                    c = pnl - TRAINAGE
                    if c > stop and c < pnl:
                        stop = c
            if pnl < 0:
                if neg is None:
                    neg = ts[j]
            else:
                neg = None
            if ts[j] - vu_prot >= 60:
                vu_prot = ts[j]
                perte = -pnl
                if (ts[j] - t0 >= PROT_AGE_SEC and perte > 0
                        and neg is not None and ts[j] - neg >= PROT_NEG_SEC):
                    d = -stop
                    pl = max(PLANCHER, perte + MARGE_FRANCHIE)
                    if d > pl:
                        v = max((d + perte) / 2.0, pl)
                        if v < d:
                            stop = -v
        j += 1
    fin = min(j, n - 1)
    sortie = bid[fin] if achat else ask[fin]
    return (sortie - entree) * k if achat else (entree - sortie) * k


def main():
    rng = random.Random(SEED)
    ts, bid, ask = charger()
    jour = [dt.datetime.fromtimestamp(t, dt.timezone.utc).date() for t in ts]
    heure = [dt.datetime.fromtimestamp(t, dt.timezone.utc).hour for t in ts]
    print("%d ticks   %d jours" % (len(ts), len(set(jour))))

    # --- la longueur de la serie en cours, pour chaque tick ---
    n = len(ts)
    serie = [0] * n          # >0 = hausses consecutives, <0 = baisses
    for i in range(1, n):
        if bid[i] > bid[i - 1]:
            serie[i] = serie[i - 1] + 1 if serie[i - 1] > 0 else 1
        elif bid[i] < bid[i - 1]:
            serie[i] = serie[i - 1] - 1 if serie[i - 1] < 0 else -1
        else:
            serie[i] = serie[i - 1]
    longueurs = collections.Counter(abs(x) for x in serie)
    tot = sum(longueurs.values())
    print("distribution des longueurs de serie :")
    for k in (1, 2, 3, 5, 8, 12, 16):
        c = sum(v for kk, v in longueurs.items() if kk >= k)
        print("   >= %-3d : %8d  (%.3f %%)" % (k, c, 100 * c / tot))

    # --- les instants d'entree ---
    entrees = {}
    for k in LONGUEURS:
        for moment in MOMENTS:
            liste = []
            dernier = -1e18
            for i in range(1, n - 1):
                if abs(serie[i]) != k:
                    continue          # exactement a la k-ieme, pas au-dela
                if ts[i] - dernier < REPOS_SEC:
                    continue
                monte = serie[i] > 0
                if moment == "au k-ieme":
                    liste.append((i, monte))      # continuation
                    dernier = ts[i]
                else:
                    # on attend le premier tick de sens OPPOSE
                    j = i + 1
                    while j < n - 1 and (
                            (serie[j] > 0) == monte and serie[j] != 0):
                        j += 1
                    if j < n - 1 and ts[j] - ts[i] <= 60:
                        liste.append((j, not monte))   # retournement
                        dernier = ts[j]
            entrees[(k, moment)] = liste
            print("   k=%-3d %-14s -> %d entrees" % (k, moment, len(liste)),
                  flush=True)

    print("\n%-5s%-15s%-13s%8s%11s%11s%10s%8s"
          % ("k", "moment", " geometrie", "n", "le sens", "l'inverse", "ecart",
             "t"))
    cellules = {}
    for (k, moment), liste in entrees.items():
        if not liste:
            continue
        for gnom, borne in GEOMETRIES:
            bon = collections.defaultdict(list)
            inv = collections.defaultdict(list)
            for (i, achat) in liste:
                bon[jour[i]].append(rejouer(ts, bid, ask, i, achat, borne))
                inv[jour[i]].append(rejouer(ts, bid, ask, i, not achat, borne))
            communs = sorted(set(bon) & set(inv))
            if len(communs) < 3:
                continue
            ec = [st.fmean(bon[d]) - st.fmean(inv[d]) for d in communs]
            m = st.fmean(ec)
            s = st.stdev(ec)
            t = m / (s / math.sqrt(len(ec))) if s else 0.0
            moitie = len(communs) // 2
            cellules[(k, moment, gnom)] = {
                "n": len(liste), "ecart": m, "t": t,
                "bon": st.fmean([x for d in communs for x in bon[d]]),
                "inv": st.fmean([x for d in communs for x in inv[d]]),
                "d1": st.fmean(ec[:moitie]), "d2": st.fmean(ec[moitie:]),
                "liste": liste,
            }
            c = cellules[(k, moment, gnom)]
            print("%-5d%-15s%-13s%8d%+11.4f%+11.4f%+10.4f%+8.2f"
                  % (k, moment, " " + gnom, c["n"], c["bon"], c["inv"],
                     c["ecart"], c["t"]))

    if not cellules:
        print("\naucune cellule exploitable")
        return 0

    print("\nplacebo : %d tirages appaires sur l'heure..." % N_PLACEBO,
          flush=True)
    par_heure = collections.defaultdict(list)
    for i in range(0, n, 11):
        par_heure[heure[i]].append(i)
    gabarit = max(cellules.values(), key=lambda c: c["n"])["liste"][:400]
    maxima = []
    for p in range(N_PLACEBO):
        bon = collections.defaultdict(list)
        inv = collections.defaultdict(list)
        for (i, achat) in gabarit:
            pool = par_heure.get(heure[i])
            if not pool:
                continue
            ii = rng.choice(pool)
            bon[jour[ii]].append(rejouer(ts, bid, ask, ii, achat, 2.0))
            inv[jour[ii]].append(rejouer(ts, bid, ask, ii, not achat, 2.0))
        communs = sorted(set(bon) & set(inv))
        ec = [st.fmean(bon[d]) - st.fmean(inv[d]) for d in communs]
        if len(ec) < 3:
            continue
        mm = st.fmean(ec)
        ss = st.stdev(ec)
        maxima.append(abs(mm / (ss / math.sqrt(len(ec)))) if ss else 0.0)
        if (p + 1) % 50 == 0:
            print("   %d/%d..." % (p + 1, N_PLACEBO), flush=True)
    maxima.sort()
    plafond = maxima[int(0.95 * len(maxima)) - 1] if maxima else 0.0
    print("\nPLAFOND (95e centile sur %d tirages) : %.3f"
          % (len(maxima), plafond))

    print("\n=== LE CRITERE PRE-INSCRIT ===")
    retenues = []
    for cle, c in cellules.items():
        if (abs(c["t"]) > plafond and c["n"] >= MIN_N
                and (c["d1"] > 0) == (c["d2"] > 0)):
            retenues.append((cle, c))
    print("cellules retenues : %d / %d" % (len(retenues), len(cellules)))
    for (k, moment, gnom), c in sorted(retenues, key=lambda x: -abs(x[1]["t"])):
        print("   k=%d %s %s : ecart %+.4f  t %+.2f  n %d  moities %+.4f/%+.4f"
              % (k, moment, gnom, c["ecart"], c["t"], c["n"], c["d1"], c["d2"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
