#!/usr/bin/env python3
"""Partie B du banc d'amplitude, REFAITE avec une statistique defendable.

Ma premiere version repliquait l'ecart d'une strate autant de fois qu'elle
contenait d'entrees (`diffs.extend([m_d - m_h] * len(v["dans"]))`). C'est de la
PSEUDO-REPLICATION : le t grandit avec le nombre d'entrees alors que
l'information, elle, est le nombre de STRATES. Le placebo l'a dit sans
ambiguite -- 95e centile a |t| = 46,7 sur des fenetres TIREES AU HASARD.

Ici l'unite d'observation est la STRATE (heure UTC x jour de semaine) :
n = nombre de strates, pas 5 442 jambes. Et je publie aussi le spread MOYEN,
parce que le median ne voit pas la queue (1 141 bougies a 40 points).
"""
from __future__ import annotations

import collections
import datetime as dt
import random
import statistics as st
import sys

sys.path.insert(0, "/app/scripts")

from banc_amplitude_publications import (  # noqa: E402
    FENETRE_B, N_PLACEBO, SEED, _plancher5, charger_bougies,
    charger_evenements, net_usd, simuler_barrieres, strate, t_de_student)


def par_strate_dans_hors(ts, issues, spread, instants):
    dans = set()
    k0, k1 = FENETRE_B[0] // 5, FENETRE_B[1] // 5
    for d in instants:
        base = _plancher5(d)
        for k in range(k0, k1 + 1):
            dans.add(base + dt.timedelta(minutes=5 * k))
    seaux = collections.defaultdict(lambda: {"dans": [], "hors": []})
    for i, d in enumerate(ts):
        if issues[i] is None:
            continue
        cle = "dans" if d in dans else "hors"
        for g in issues[i]:
            seaux[strate(d)][cle].append((g, spread[i], net_usd(g, spread[i])))
    return seaux


def statistique(seaux, mini_dans=20, mini_hors=20):
    """t APPARIE sur les strates : une strate = une observation."""
    ecarts = []
    n_dans = n_hors = 0
    reuss = {"dans": [0, 0], "hors": [0, 0]}
    sp = {"dans": [], "hors": []}
    net = {"dans": [], "hors": []}
    for v in seaux.values():
        if len(v["dans"]) < mini_dans or len(v["hors"]) < mini_hors:
            continue
        for cle in ("dans", "hors"):
            for g, s, nt in v[cle]:
                reuss[cle][0] += int(g)
                reuss[cle][1] += 1
                sp[cle].append(s)
                net[cle].append(nt)
        ecarts.append(st.fmean([x[2] for x in v["dans"]])
                      - st.fmean([x[2] for x in v["hors"]]))
        n_dans += len(v["dans"])
        n_hors += len(v["hors"])
    t, m = t_de_student(ecarts)
    nan = float("nan")
    return {
        "strates": len(ecarts), "n_dans": n_dans, "n_hors": n_hors,
        "reussite_dans": 100 * reuss["dans"][0] / max(1, reuss["dans"][1]),
        "reussite_hors": 100 * reuss["hors"][0] / max(1, reuss["hors"][1]),
        "spread_moy_dans": st.fmean(sp["dans"]) if sp["dans"] else nan,
        "spread_moy_hors": st.fmean(sp["hors"]) if sp["hors"] else nan,
        "spread_p95_dans": (sorted(sp["dans"])[int(.95 * len(sp["dans"]))]
                            if sp["dans"] else nan),
        "spread_p95_hors": (sorted(sp["hors"])[int(.95 * len(sp["hors"]))]
                            if sp["hors"] else nan),
        "net_dans": st.fmean(net["dans"]) if net["dans"] else nan,
        "net_hors": st.fmean(net["hors"]) if net["hors"] else nan,
        "diff": m, "t": t,
    }


def main():
    rng = random.Random(SEED + 2)
    ts, amp, hi, lo, close, spread = charger_bougies()
    evts = charger_evenements()
    high = [d for d, i in evts if i == "High"]
    print("bougies %d   publications High USD %d" % (len(ts), len(high)))

    issues = simuler_barrieres(ts, hi, lo, close)
    r = statistique(par_strate_dans_hors(ts, issues, spread, high))
    print("\n=== B2 : 2/20 dans les 30 min apres une High US ===")
    print("strates retenues : %d   jambes dans %d / hors %d"
          % (r["strates"], r["n_dans"], r["n_hors"]))
    print("reussite      dans %.2f %%    hors %.2f %%   (piece 20/22 = 90,91 %%)"
          % (r["reussite_dans"], r["reussite_hors"]))
    print("spread moyen  dans %.2f pts   hors %.2f pts"
          % (r["spread_moy_dans"], r["spread_moy_hors"]))
    print("spread p95    dans %.1f pts   hors %.1f pts"
          % (r["spread_p95_dans"], r["spread_p95_hors"]))
    print("net $/jambe   dans %+.4f    hors %+.4f" % (r["net_dans"], r["net_hors"]))
    print("dans - hors   %+.4f $   t = %+.2f   (n = %d strates)"
          % (r["diff"], r["t"], r["strates"]))

    par_strate = collections.defaultdict(list)
    for d in ts:
        par_strate[strate(d)].append(d)
    ts_faux = []
    for k in range(N_PLACEBO):
        faux = [rng.choice(par_strate[strate(_plancher5(d))])
                for d in high if par_strate.get(strate(_plancher5(d)))]
        ts_faux.append(abs(statistique(
            par_strate_dans_hors(ts, issues, spread, faux))["t"]))
        if (k + 1) % 50 == 0:
            print("  placebo %d/%d..." % (k + 1, N_PLACEBO), flush=True)
    ts_faux.sort()
    plafond = ts_faux[int(0.95 * len(ts_faux)) - 1]
    print("\nPLAFOND (95e centile de |t| sur %d fenetres FAUSSES, "
          "appariees heure x jour) : %.3f" % (N_PLACEBO, plafond))
    print("median des placebos : %.3f" % st.median(ts_faux))
    print("VERDICT :", "RETENU" if abs(r["t"]) > plafond else "SOUS LE PLAFOND")
    return 0


if __name__ == "__main__":
    sys.exit(main())
