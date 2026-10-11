#!/usr/bin/env python3
"""Controle du banc d'amplitude : les publications sont-elles GROUPEES ?

Le banc principal (banc_amplitude_publications.py) donne deux resultats que ma
prediction n'attendait pas :

    High  +30 min  rapport 1,321   (je predisais une decroissance MONOTONE)
    Low    +0 min  rapport 1,204   (je predisais ~1,0 pour Low)

L'explication la plus simple n'est pas "l'effet persiste" ni "les Low comptent"
mais le GROUPEMENT : le calendrier americain publie en paquets a :00 et :30, et
une Low tombe souvent a la meme minute qu'une High. Ce fichier le MESURE, puis
refait la partie A sur les evenements ISOLES seulement.

Rien ici n'est un nouveau reglage : meme source, meme fond apparie, meme
plafond par permutation.
"""
from __future__ import annotations

import collections
import datetime as dt
import random
import sys

sys.path.insert(0, "/app/scripts")

from banc_amplitude_publications import (  # noqa: E402
    IMPACTS, N_PLACEBO, OFFSETS, SEED, _plancher5, charger_bougies,
    charger_evenements, fond_apparie, partie_a, strate)

ISOLEMENT_MIN = 45        # aucun autre evenement a +/- 45 min


def main():
    ts, amp, hi, lo, close, spread = charger_bougies()
    evts = charger_evenements()
    fond, _ = fond_apparie(ts, amp, [d for d, _ in evts])
    instants = sorted(d for d, _ in evts)

    print("=== 1. LE GROUPEMENT, mesure ===")
    par_minute = collections.Counter(d for d, _ in evts)
    print("evenements USD : %d, repartis sur %d instants distincts"
          % (len(evts), len(par_minute)))
    print("instants portant 2 evenements ou plus : %d"
          % sum(1 for v in par_minute.values() if v > 1))

    highs = [d for d, i in evts if i == "High"]
    lows = [d for d, i in evts if i == "Low"]

    def voisins(cible, autres, fenetre_min):
        """Combien de 'cible' ont un evenement de 'autres' a +/- fenetre."""
        s = set()
        pas = fenetre_min
        for d in autres:
            for k in range(-pas, pas + 1):
                s.add(d + dt.timedelta(minutes=k))
        return sum(1 for d in cible if d in s)

    n_h30 = voisins([d + dt.timedelta(minutes=30) for d in highs], instants, 5)
    print("High dont un AUTRE evenement tombe a +30 min (+/-5) : %d / %d  (%.1f %%)"
          % (n_h30, len(highs), 100 * n_h30 / len(highs)))

    hm = [d for d, i in evts if i in ("High", "Medium")]
    n_low = voisins(lows, hm, 5)
    print("Low a +/-5 min d'une High ou Medium : %d / %d  (%.1f %%)"
          % (n_low, len(lows), 100 * n_low / len(lows)))

    print("\n=== 2. PARTIE A sur les evenements ISOLES (+/-%d min) ===" % ISOLEMENT_MIN)
    voisinage = collections.Counter()
    for d in instants:
        voisinage[d] += 1
    isoles = []
    for d, imp in evts:
        seul = True
        for k in range(-ISOLEMENT_MIN, ISOLEMENT_MIN + 1):
            if k == 0:
                continue
            if (d + dt.timedelta(minutes=k)) in voisinage:
                seul = False
                break
        if seul and voisinage[d] == 1:
            isoles.append((d, imp))
    print("evenements isoles : %d / %d" % (len(isoles), len(evts)))
    for imp in IMPACTS:
        print("   %-7s %d" % (imp, sum(1 for _, i in isoles if i == imp)))

    reel = partie_a(isoles, amp, fond)
    print("%-8s%8s%8s%10s%9s" % ("impact", "offset", "n", "rapport", "t"))
    for imp in IMPACTS:
        for off in OFFSETS:
            n, r, t = reel[(imp, off)]
            print("%-8s%+8d%8d%10.3f%+9.2f" % (imp, off, n, r, t))

    rng = random.Random(SEED + 1)
    par_strate = collections.defaultdict(list)
    for d in ts:
        par_strate[strate(d)].append(d)
    maxima = []
    for k in range(N_PLACEBO):
        faux = []
        for d, imp in isoles:
            pool = par_strate.get(strate(_plancher5(d)))
            if pool:
                faux.append((rng.choice(pool), imp))
        r = partie_a(faux, amp, fond)
        maxima.append(max(abs(v[2]) for v in r.values()))
    maxima.sort()
    plafond = maxima[int(0.95 * len(maxima)) - 1]
    print("\nPLAFOND (95e centile du max|t| sur %d permutations) : %.3f"
          % (N_PLACEBO, plafond))
    retenues = [(k, v) for k, v in reel.items() if abs(v[2]) > plafond]
    print("cellules qui le franchissent : %d / %d" % (len(retenues), len(reel)))
    for (imp, off), (n, r, t) in sorted(retenues, key=lambda x: -abs(x[1][2])):
        print("  %s %+d min : n=%d rapport=%.3f t=%+.2f" % (imp, off, n, r, t))
    return 0


if __name__ == "__main__":
    sys.exit(main())
