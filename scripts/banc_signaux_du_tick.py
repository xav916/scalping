#!/usr/bin/env python3
"""Les signaux NATIFS DU TICK portent-ils une direction ?

Pre-inscrit dans docs/predictions/2026-10-11_signaux_natifs_du_tick.md
(commit 2186044) AVANT d'ecrire ce fichier.

Quatre signaux que la bougie detruit : vitesse, acceleration, tick rate,
desequilibre des variations de bid. Deux fenetres (10 s, 60 s), deux geometries
(la production, et des bornes symetriques +/-2 EUR pour que la geometrie ne
baillonne pas le signal). 16 cellules.

⛔ Le Tick Imbalance du PDF compte des TRANSACTIONS : ce CFD n'en a pas
(buy 0 / sell 0 sur 893 ticks, mesure du 10/10). On utilise le desequilibre des
VARIATIONS DE BID, seul substitut que la donnee permette.
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
FENETRES = (10, 60)                 # secondes
SIGNAUX = ("vitesse", "acceleration", "tick_rate", "desequilibre")
GEOMETRIES = (("production", None), ("symetrique", 2.0))
SL_DEPART = 13.0
TRAINAGE = 0.5
DECLENCHE = 0.5
PLANCHER = 2.0
MARGE_FRANCHIE = 0.10
PROT_AGE_SEC = 60
PROT_NEG_SEC = 30
CADENCE_SEC = 1                     # le trainage sonde a la seconde
CAP_SEC = 14400                     # 4 h
REPOS_SEC = 300                     # pas deux entrees du meme signal en 5 min
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


def calculer_signaux(ts, bid, ask, N):
    """Les quatre signaux, pour chaque tick, sur une fenetre de N secondes."""
    n = len(ts)
    mid = [(bid[i] + ask[i]) / 2.0 for i in range(n)]
    # prefixes des hausses / baisses de bid
    pre_h = [0] * (n + 1)
    pre_b = [0] * (n + 1)
    for i in range(1, n):
        pre_h[i + 1] = pre_h[i] + (1 if bid[i] > bid[i - 1] else 0)
        pre_b[i + 1] = pre_b[i] + (1 if bid[i] < bid[i - 1] else 0)
    pre_h[1] = pre_h[1] if n > 1 else 0
    deb = [0] * n          # premier indice de la fenetre
    g = 0
    for i in range(n):
        while ts[i] - ts[g] > N:
            g += 1
        deb[i] = g
    vit = [0.0] * n
    rate = [0] * n
    des = [0.0] * n
    for i in range(n):
        j = deb[i]
        vit[i] = (mid[i] - mid[j]) / float(N)
        rate[i] = i - j
        h = pre_h[i + 1] - pre_h[j + 1]
        b = pre_b[i + 1] - pre_b[j + 1]
        des[i] = (h - b) / (h + b) if (h + b) else 0.0
    # acceleration : vitesse(i) - vitesse(au tick de ts[i] - N)
    acc = [0.0] * n
    for i in range(n):
        acc[i] = vit[i] - vit[deb[i]]
    return {"vitesse": vit, "acceleration": acc,
            "tick_rate": [float(x) for x in rate], "desequilibre": des}, vit


def rejouer(ts, bid, ask, i, achat, borne):
    """L'issue d'une entree, tick par tick. `borne` None = la production."""
    k = 1.0 / EUR_USD
    entree = ask[i] if achat else bid[i]
    t0 = ts[i]
    stop = -SL_DEPART if borne is None else -borne
    tp = 1e9 if borne is None else borne
    neg_depuis = None
    vu = -1e18
    vu_prot = -1e18
    n = len(ts)
    j = i + 1
    while j < n and ts[j] - t0 <= CAP_SEC:
        sortie = bid[j] if achat else ask[j]
        pnl = (sortie - entree) * k if achat else (entree - sortie) * k
        if pnl <= stop + 1e-12:
            return stop, ts[j] - t0
        if pnl >= tp - 1e-12:
            return tp, ts[j] - t0
        if borne is None:
            if ts[j] - vu >= CADENCE_SEC:
                vu = ts[j]
                if pnl >= DECLENCHE - 1e-9:
                    cible = pnl - TRAINAGE
                    if cible > stop and cible < pnl:
                        stop = cible
            if pnl < 0:
                if neg_depuis is None:
                    neg_depuis = ts[j]
            else:
                neg_depuis = None
            if ts[j] - vu_prot >= 60:
                vu_prot = ts[j]
                perte = -pnl
                assez = (neg_depuis is not None
                         and ts[j] - neg_depuis >= PROT_NEG_SEC)
                if ts[j] - t0 >= PROT_AGE_SEC and perte > 0 and assez:
                    d = -stop
                    pl = max(PLANCHER, perte + MARGE_FRANCHIE)
                    if d > pl:
                        v = max((d + perte) / 2.0, pl)
                        if v < d:
                            stop = -v
        j += 1
    fin = min(j, n - 1)
    sortie = bid[fin] if achat else ask[fin]
    pnl = (sortie - entree) * k if achat else (entree - sortie) * k
    return pnl, ts[fin] - t0


def main():
    rng = random.Random(SEED)
    ts, bid, ask = charger()
    print("%d ticks   %s -> %s"
          % (len(ts),
             dt.datetime.fromtimestamp(ts[0], dt.timezone.utc).isoformat(
                 timespec="seconds"),
             dt.datetime.fromtimestamp(ts[-1], dt.timezone.utc).isoformat(
                 timespec="seconds")))
    jour = [dt.datetime.fromtimestamp(t, dt.timezone.utc).date() for t in ts]
    heure = [dt.datetime.fromtimestamp(t, dt.timezone.utc).hour for t in ts]
    print("jours couverts : %d" % len(set(jour)))

    cellules = {}
    for N in FENETRES:
        sigs, vit = calculer_signaux(ts, bid, ask, N)
        print("\nfenetre %d s : signaux calcules" % N, flush=True)
        for nom in SIGNAUX:
            v = sigs[nom]
            ech = sorted(v[::211])
            p90 = ech[int(0.90 * len(ech))]
            p10 = ech[int(0.10 * len(ech))]
            # --- les instants d'entree, avec repos ---
            entrees = []
            dernier = -1e18
            for i in range(len(ts)):
                if ts[i] - dernier < REPOS_SEC:
                    continue
                if nom == "tick_rate":
                    # pas de signe : le flux dense donne le contexte, le sens
                    # vient de la vitesse concomitante
                    if v[i] >= p90 and vit[i] != 0:
                        entrees.append((i, vit[i] > 0))
                        dernier = ts[i]
                else:
                    if v[i] >= p90:
                        entrees.append((i, True))
                        dernier = ts[i]
                    elif v[i] <= p10:
                        entrees.append((i, False))
                        dernier = ts[i]
            print("   %-14s p10 %+.5f  p90 %+.5f  -> %d entrees"
                  % (nom, p10, p90, len(entrees)), flush=True)
            for gnom, borne in GEOMETRIES:
                bon = collections.defaultdict(list)
                mauvais = collections.defaultdict(list)
                for (i, achat) in entrees:
                    a, _d = rejouer(ts, bid, ask, i, achat, borne)
                    b, _d2 = rejouer(ts, bid, ask, i, not achat, borne)
                    bon[jour[i]].append(a)
                    mauvais[jour[i]].append(b)
                communs = sorted(set(bon) & set(mauvais))
                ec = [st.fmean(bon[d]) - st.fmean(mauvais[d]) for d in communs]
                if len(ec) < 3:
                    continue
                m = st.fmean(ec)
                s = st.stdev(ec)
                t = m / (s / math.sqrt(len(ec))) if s else 0.0
                moitie = len(communs) // 2
                d1 = st.fmean([st.fmean(bon[d]) - st.fmean(mauvais[d])
                               for d in communs[:moitie]])
                d2 = st.fmean([st.fmean(bon[d]) - st.fmean(mauvais[d])
                               for d in communs[moitie:]])
                cellules[(nom, N, gnom)] = {
                    "n": len(entrees), "bon": st.fmean(
                        [x for d in communs for x in bon[d]]),
                    "mauvais": st.fmean(
                        [x for d in communs for x in mauvais[d]]),
                    "ecart": m, "t": t, "jours": len(ec), "d1": d1, "d2": d2,
                    "entrees": entrees,
                }

    print("\n%-14s%6s%-13s%8s%11s%11s%10s%8s%7s"
          % ("signal", "N s", " geometrie", "n", "bon sens", "mauvais",
             "ecart", "t", "jours"))
    for (nom, N, gnom), c in sorted(cellules.items(),
                                    key=lambda kv: -abs(kv[1]["t"])):
        print("%-14s%6d%-13s%8d%+11.4f%+11.4f%+10.4f%+8.2f%7d"
              % (nom, N, " " + gnom, c["n"], c["bon"], c["mauvais"],
                 c["ecart"], c["t"], c["jours"]))

    # --- plafond par permutation, apparie sur l'heure ---
    print("\nplacebo : %d tirages d'instants FAUX, appaires sur l'heure..."
          % N_PLACEBO, flush=True)
    par_heure = collections.defaultdict(list)
    for i in range(0, len(ts), 7):
        par_heure[heure[i]].append(i)
    # on prend la cellule la plus FOURNIE comme gabarit de tirage
    gabarit = max(cellules.items(), key=lambda kv: kv[1]["n"])
    modele = gabarit[1]["entrees"]
    borne_test = 2.0            # geometrie symetrique, la plus sensible
    maxima = []
    for k in range(N_PLACEBO):
        bon = collections.defaultdict(list)
        mauvais = collections.defaultdict(list)
        for (i, achat) in modele[:400]:
            pool = par_heure.get(heure[i])
            if not pool:
                continue
            ii = rng.choice(pool)
            a, _ = rejouer(ts, bid, ask, ii, achat, borne_test)
            b, _ = rejouer(ts, bid, ask, ii, not achat, borne_test)
            bon[jour[ii]].append(a)
            mauvais[jour[ii]].append(b)
        communs = sorted(set(bon) & set(mauvais))
        ec = [st.fmean(bon[d]) - st.fmean(mauvais[d]) for d in communs]
        if len(ec) < 3:
            continue
        m = st.fmean(ec)
        s = st.stdev(ec)
        maxima.append(abs(m / (s / math.sqrt(len(ec)))) if s else 0.0)
        if (k + 1) % 50 == 0:
            print("   %d/%d..." % (k + 1, N_PLACEBO), flush=True)
    maxima.sort()
    plafond = maxima[int(0.95 * len(maxima)) - 1] if maxima else 0.0
    print("\nPLAFOND (95e centile du |t| sur %d tirages) : %.3f"
          % (len(maxima), plafond))

    print("\n=== LE CRITERE PRE-INSCRIT ===")
    retenues = []
    for (nom, N, gnom), c in cellules.items():
        ok = (abs(c["t"]) > plafond and c["n"] >= MIN_N
              and (c["d1"] > 0) == (c["d2"] > 0))
        if ok:
            retenues.append((nom, N, gnom, c))
    print("cellules retenues : %d / %d" % (len(retenues), len(cellules)))
    for nom, N, gnom, c in sorted(retenues, key=lambda x: -abs(x[3]["t"])):
        print("   %s %d s %s : ecart %+.4f  t %+.2f  n %d  moities %+.4f/%+.4f"
              % (nom, N, gnom, c["ecart"], c["t"], c["n"], c["d1"], c["d2"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
