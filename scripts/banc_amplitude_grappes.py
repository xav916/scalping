#!/usr/bin/env python3
"""L'amplitude repond-elle a UNE publication, ou a la GRAPPE ?

Le controle d'isolement a produit deux lectures possibles, et il ne faut pas
choisir la plus flatteuse :

    toutes les High, offset 0   rapport 1,888  t +11,87  n=653
    High ISOLEES, offset 0      rapport 1,254  t  +2,25  n=47

Le POINT lui-meme s'effondre (1,888 -> 1,254), pas seulement le t. Soit le
sous-echantillon isole manque de puissance, soit l'effet vient du PAQUET : le
calendrier americain publie plusieurs chiffres a la meme minute, et une
"publication" a 12h30 est souvent trois ou quatre chiffres d'un coup.

Ce fichier tranche en gardant TOUTE la puissance : on classe par TAILLE DE
GRAPPE (nombre d'evenements a la meme minute, +/-5 min) et on regarde si le
rapport d'amplitude MONTE avec elle.
"""
from __future__ import annotations

import collections
import datetime as dt
import random
import statistics as st
import sys

sys.path.insert(0, "/app/scripts")

from banc_amplitude_publications import (  # noqa: E402
    N_PLACEBO, SEED, _plancher5, charger_bougies, charger_evenements,
    fond_apparie, strate, t_de_student)

SEAUX = ((1, 1), (2, 2), (3, 4), (5, 99))
OFFSETS = (0, 5, 15)
RANG = {"Low": 0, "Medium": 1, "High": 2}
NOM = {0: "Low", 1: "Medium", 2: "High"}


def grappes(evts):
    """{instant pivot: (taille, impact max)} par minute, fenetre +/-5 min."""
    par_minute = collections.defaultdict(list)
    for d, imp in evts:
        par_minute[d.replace(second=0, microsecond=0)].append(imp)
    tailles = {}
    for m, imps in par_minute.items():
        taille, rang = 0, -1
        for k in range(-5, 6):
            v = par_minute.get(m + dt.timedelta(minutes=k))
            if v:
                taille += len(v)
                rang = max(rang, max(RANG[i] for i in v))
        tailles[m] = (taille, rang)
    return tailles


def mesurer(tailles, amp, fond):
    """Rend {(seau, offset, impact_max): (n, rapport, t)}."""
    res = {}
    for lo, hi in SEAUX:
        for rang in (2, 1):
            pivots = [m for m, (t, r) in tailles.items()
                      if lo <= t <= hi and r == rang]
            for off in OFFSETS:
                ecarts, obs, refs = [], [], []
                for m in pivots:
                    b = _plancher5(m + dt.timedelta(minutes=off))
                    a = amp.get(b)
                    f = fond.get(strate(b))
                    if a is None or f is None:
                        continue
                    ecarts.append(a - f)
                    obs.append(a)
                    refs.append(f)
                if len(ecarts) < 10:
                    res[((lo, hi), off, rang)] = (len(ecarts), float("nan"), 0.0)
                    continue
                t, _ = t_de_student(ecarts)
                res[((lo, hi), off, rang)] = (
                    len(ecarts), st.fmean(obs) / st.fmean(refs), t)
    return res


def main():
    rng = random.Random(SEED + 3)
    ts, amp, hi, lo, close, spread = charger_bougies()
    evts = charger_evenements()
    fond, _ = fond_apparie(ts, amp, [d for d, _ in evts])
    tailles = grappes(evts)
    print("instants distincts : %d" % len(tailles))
    rep = collections.Counter()
    for t, r in tailles.values():
        for a, b in SEAUX:
            if a <= t <= b:
                rep[(a, b), NOM[r]] += 1
    for k in sorted(rep, key=lambda x: (x[0], x[1])):
        print("   grappe %s  max=%-7s %d" % (k[0], k[1], rep[k]))

    reel = mesurer(tailles, amp, fond)
    print("\n%-10s%-8s%8s%8s%10s%9s" % ("grappe", "max", "offset", "n",
                                        "rapport", "t"))
    for seau in SEAUX:
        for rang in (2, 1):
            for off in OFFSETS:
                n, r, t = reel[(seau, off, rang)]
                print("%-10s%-8s%+8d%8d%10.3f%+9.2f"
                      % ("%d-%d" % seau, NOM[rang], off, n, r, t))

    par_strate = collections.defaultdict(list)
    for d in ts:
        par_strate[strate(d)].append(d)
    maxima = []
    for k in range(N_PLACEBO):
        faux = {}
        for m, v in tailles.items():
            pool = par_strate.get(strate(_plancher5(m)))
            if pool:
                faux[rng.choice(pool)] = v
        r = mesurer(faux, amp, fond)
        maxima.append(max(abs(x[2]) for x in r.values()))
        if (k + 1) % 50 == 0:
            print("  placebo %d/%d..." % (k + 1, N_PLACEBO), flush=True)
    maxima.sort()
    plafond = maxima[int(0.95 * len(maxima)) - 1]
    print("\nPLAFOND (95e centile du max|t| sur %d permutations) : %.3f"
          % (N_PLACEBO, plafond))
    retenues = [(k, v) for k, v in reel.items() if abs(v[2]) > plafond]
    print("cellules qui le franchissent : %d / %d" % (len(retenues), len(reel)))
    for (seau, off, rang), (n, r, t) in sorted(retenues, key=lambda x: -abs(x[1][2])):
        print("  grappe %d-%d  max=%s  %+d min : n=%d rapport=%.3f t=%+.2f"
              % (seau[0], seau[1], NOM[rang], off, n, r, t))
    return 0


if __name__ == "__main__":
    sys.exit(main())
