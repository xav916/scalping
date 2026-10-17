#!/usr/bin/env python3
"""La volatilite dit-elle QUAND ouvrir, et DANS QUEL SENS ?

Pre-inscrit dans docs/predictions/2026-10-14_volatilite_quand_et_quel_sens.md
AVANT ce fichier (commit b46b603).

PLAFOND PAR PERMUTATION, pas un t de confort : avec 25 cellules un |t| de 2
est franchi par le hasard dans la quasi-totalite des tirages.
"""
from __future__ import annotations

import bisect
import collections
import datetime as dt
import math
import random
import statistics as st
import sys

sys.path.insert(0, "/tmp")
from banc_vitesse_adverse import charger, rejouer, EUR_USD, REPOS_SEC  # noqa

random.seed(20261014)      # graine FIXE : un banc doit etre rejouable


def amplitude(ts, bid, ask, i, fen):
    j = bisect.bisect_left(ts, ts[i] - fen)
    if j >= i:
        return None
    h, b = max(ask[j:i]), min(bid[j:i])
    return (h - b) / EUR_USD if h > b else None


def mouvement(ts, bid, ask, i, fen):
    """Le mouvement SIGNE sur `fen` secondes apres i, en euros (mid a mid)."""
    j = bisect.bisect_left(ts, ts[i] + fen)
    if j >= len(ts):
        return None
    m0 = (bid[i] + ask[i]) / 2.0
    m1 = (bid[j] + ask[j]) / 2.0
    return (m1 - m0) / EUR_USD


def mouvement_avant(ts, bid, ask, i, fen):
    j = bisect.bisect_left(ts, ts[i] - fen)
    if j >= i:
        return None
    m0 = (bid[j] + ask[j]) / 2.0
    m1 = (bid[i] + ask[i]) / 2.0
    return (m1 - m0) / EUR_USD


def correlation(paires):
    """Rend (r, t, n) ou (0, 0, n) si indefinissable."""
    pr = [(a, b) for a, b in paires if a is not None and b is not None]
    if len(pr) < 30:
        return None
    xs = [a for a, _ in pr]
    ys = [b for _, b in pr]
    mx, my = st.fmean(xs), st.fmean(ys)
    num = sum((x - mx) * (y - my) for x, y in pr)
    den = math.sqrt(sum((x - mx) ** 2 for x in xs)
                    * sum((y - my) ** 2 for y in ys))
    r = num / den if den else 0.0
    n = len(pr)
    t = r * math.sqrt(max(1, n - 2)) / math.sqrt(max(1e-12, 1 - r * r))
    return r, t, n


HORIZONS = ((300, "5 min"), (900, "15 min"), (3600, "60 min"))


def main() -> int:
    ts, bid, ask = charger()
    jours = [dt.datetime.fromtimestamp(t, dt.timezone.utc).date() for t in ts]
    ent, dernier = [], -1e18
    for i in range(1, len(ts) - 1):
        if ts[i] - dernier < REPOS_SEC:
            continue
        if amplitude(ts, bid, ask, i, 900) is None:
            continue
        ent.append(i)
        dernier = ts[i]
    print("%d ticks, %d jours, %d instants\n"
          % (len(ts), len(set(jours)), len(ent)))

    tj = sorted(set(jours[i] for i in ent))
    moitie = len(tj) // 2
    dedans, dehors = set(tj[:moitie]), set(tj[moitie:])
    amp = {i: amplitude(ts, bid, ask, i, 900) for i in ent}

    # QUINTILES CALCULES SUR LA PREMIERE MOITIE SEULEMENT
    a_in = sorted(amp[i] for i in ent if jours[i] in dedans)
    bornes = [a_in[int(q * len(a_in))] for q in (0.2, 0.4, 0.6, 0.8)]
    print("bornes de quintile (1re moitie) : %s"
          % ["%.2f" % b for b in bornes])

    def quint(i):
        return bisect.bisect_right(bornes, amp[i])

    idx_in = [i for i in ent if jours[i] in dedans]
    pre = {i: mouvement_avant(ts, bid, ask, i, 900) for i in idx_in}
    suiv = {f: {i: mouvement(ts, bid, ask, i, f) for i in idx_in}
            for f, _ in HORIZONS}

    print()
    print("=" * 76)
    print("① LE SENS — le mouvement SUIVANT est-il predit par le PRECEDENT ?")
    print("=" * 76)
    print("   %-9s %-8s %9s %9s %8s %9s" % ("quintile", "horizon", "r", "t",
                                            "n", "ampl.med"))
    ts_obs = []
    for q in range(5):
        idx = [i for i in idx_in if quint(i) == q]
        if not idx:
            continue
        for f, lib in HORIZONS:
            c = correlation([(pre[i], suiv[f][i]) for i in idx])
            if c is None:
                continue
            r, t, n = c
            ts_obs.append(abs(t))
            print("   Q%-8d %-8s %+9.4f %+9.2f %8d %9.2f"
                  % (q + 1, lib, r, t, n,
                     st.median([amp[i] for i in idx])))

    print()
    print("=" * 76)
    print("LE PLAFOND — 200 melanges des etiquettes de quintile")
    print("=" * 76)
    maxs = []
    taille = len(idx_in) // 5
    for _ in range(200):
        melange = list(idx_in)
        random.shuffle(melange)
        pire = 0.0
        for q in range(5):
            bloc = melange[q * taille:(q + 1) * taille]
            for f, _ in HORIZONS:
                c = correlation([(pre[i], suiv[f][i]) for i in bloc])
                if c is None:
                    continue
                pire = max(pire, abs(c[1]))
        maxs.append(pire)
    maxs.sort()
    plafond = maxs[int(0.95 * len(maxs))]
    obs = max(ts_obs) if ts_obs else 0.0
    print("   |t| maximal du HASARD : median %.3f   p95 %.3f   max %.3f"
          % (st.median(maxs), plafond, maxs[-1]))
    print("   |t| maximal OBSERVE  : %.3f" % obs)
    print()
    if obs > plafond:
        print("   ⚠️ UNE CELLULE DEPASSE LE PLAFOND — a rejouer hors echantillon")
    else:
        print("   ⛔ AUCUNE CELLULE NE DEPASSE LE PLAFOND.")
        print("      ✅ PREDICTION n°1 TENUE : le SENS reste muet, meme")
        print("         conditionne a la volatilite.")

    print()
    print("=" * 76)
    print("② QUAND — que rend un trade ouvert dans ce regime ? (les 2 sens)")
    print("=" * 76)
    print("   %-9s %10s %10s %10s %8s %8s"
          % ("quintile", "ACHATS", "VENTES", "les deux", "n", "ampl."))
    garde = {}
    for sel, lib in ((dedans, "dedans"), (dehors, "dehors")):
        print("   --- %s ---" % lib)
        garde[lib] = {}
        for q in range(5):
            idx = [i for i in ent if quint(i) == q and jours[i] in sel]
            if len(idx) < 30:
                continue
            A = [rejouer(ts, bid, ask, i, True, 60., 30., 60., False,
                         False, None)[0] for i in idx]
            V = [rejouer(ts, bid, ask, i, False, 60., 30., 60., False,
                         False, None)[0] for i in idx]
            garde[lib][q] = st.fmean(A + V)
            print("   Q%-8d %+10.4f %+10.4f %+10.4f %8d %8.2f"
                  % (q + 1, st.fmean(A), st.fmean(V), st.fmean(A + V),
                     len(idx), st.median([amp[i] for i in idx])))

    print()
    print("=" * 76)
    print("LA MONOTONIE — condition 3, posee d'avance")
    print("=" * 76)
    for lib in ("dedans", "dehors"):
        v = [garde[lib][q] for q in sorted(garde[lib])]
        if len(v) < 3:
            continue
        decroit = all(a >= b for a, b in zip(v, v[1:]))
        ecart = v[0] - v[-1]
        print("   %-8s Q1 %+8.4f -> Q%d %+8.4f   ecart %+8.4f   monotone %s"
              % (lib, v[0], len(v), v[-1], ecart, decroit))
    print()
    print("   🔑 PREDICTION n°2 : rendement PIRE dans les quintiles hauts, et")
    print("      MONOTONE, avec au moins 0,05 EUR entre Q1 et Q5.")
    print("   🔑 PREDICTION n°4 : les deux sens negatifs PARTOUT, donc un")
    print("      filtre qui fait PERDRE MOINS, jamais gagner.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
