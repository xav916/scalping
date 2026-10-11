#!/usr/bin/env python3
"""Banc : l'amplitude de l'or aux publications economiques.

Pre-inscrit dans docs/predictions/2026-10-11_amplitude_aux_publications.md
(commit 2797c11) AVANT d'ecrire ce fichier.

Source des bougies : candles_courtier.db -- les bougies DU COURTIER, en vrai
UTC. Jamais candles_5min.db, qui vient de Twelve Data.

Le fond de reference est APPARIE sur (heure UTC, jour de semaine) : les
publications americaines tombent sur le pic de la session de New York, et un
fond global remesurerait la session, pas la publication.
"""
from __future__ import annotations

import collections
import datetime as dt
import math
import random
import sqlite3
import statistics as st
import sys

BOUGIES = "/app/data/candles_courtier.db"
EVENTS = "/app/data/scalping.db"
PAIRE = "XAU/USD"

OFFSETS = (-30, -15, 0, 5, 10, 15, 30)
IMPACTS = ("High", "Medium", "Low")
DEVISE = "USD"

# Geometrie de production, en dollars (taux courtier 1,1198 USD/EUR).
TP_USD = 2.24
SL_USD = 22.40
POINT_USD = 0.01          # 1 point XAU/USD = 0,01 $ (spread_pts 5 = 0,050 $)
MAX_BOUGIES = 288         # 24 h de M5 : au-dela, le trade est dit NON RESOLU
FENETRE_B = (0, 30)       # minutes apres une High US
GARDE_MIN = 30            # un fond propre n'a aucun evenement a +/- 30 min
N_PLACEBO = 200
SEED = 20261011


def _plancher5(t):
    return t.replace(minute=(t.minute // 5) * 5, second=0, microsecond=0)


def charger_bougies():
    c = sqlite3.connect(BOUGIES)
    rows = c.execute(
        "SELECT ts_utc, high, low, close, spread_pts FROM candles "
        "WHERE pair = ? ORDER BY ts_utc", (PAIRE,)).fetchall()
    ts, amp, hi, lo, close, spread = [], {}, [], [], [], []
    for t, h, l, cl, sp in rows:
        d = dt.datetime.fromisoformat(t)
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        d = d.astimezone(dt.timezone.utc)
        ts.append(d)
        amp[d] = h - l
        hi.append(h)
        lo.append(l)
        close.append(cl)
        spread.append(sp if sp is not None else 5.0)
    return ts, amp, hi, lo, close, spread


def charger_evenements():
    c = sqlite3.connect(EVENTS)
    rows = c.execute(
        "SELECT ts_utc, impact FROM economic_events "
        "WHERE currency = ? AND impact IN ('High','Medium','Low')", (DEVISE,)
    ).fetchall()
    out = []
    for t, imp in rows:
        try:
            d = dt.datetime.fromisoformat(t)
        except (ValueError, TypeError):
            continue
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        out.append((d.astimezone(dt.timezone.utc), imp))
    return out


def strate(d):
    return (d.hour, d.weekday())


def fond_apparie(ts, amp, instants):
    """Moyenne d'amplitude par (heure, jour de semaine), hors publications."""
    sales = set()
    pas = GARDE_MIN // 5
    for d in instants:
        base = _plancher5(d)
        for k in range(-pas, pas + 1):
            sales.add(base + dt.timedelta(minutes=5 * k))
    seaux = collections.defaultdict(list)
    for d in ts:
        if d not in sales:
            seaux[strate(d)].append(amp[d])
    return {k: st.fmean(v) for k, v in seaux.items() if len(v) >= 20}, len(sales)


def t_de_student(ecarts):
    n = len(ecarts)
    if n < 3:
        return 0.0, 0.0
    m = st.fmean(ecarts)
    s = st.stdev(ecarts)
    if s == 0:
        return 0.0, m
    return m / (s / math.sqrt(n)), m


def partie_a(evts, amp, fond):
    """Rend {(impact, offset): (n, rapport, t)}."""
    res = {}
    for imp in IMPACTS:
        instants = [d for d, i in evts if i == imp]
        for off in OFFSETS:
            ecarts, obs, refs = [], [], []
            for d in instants:
                b = _plancher5(d + dt.timedelta(minutes=off))
                a = amp.get(b)
                f = fond.get(strate(b))
                if a is None or f is None:
                    continue
                ecarts.append(a - f)
                obs.append(a)
                refs.append(f)
            if not ecarts:
                res[(imp, off)] = (0, float("nan"), 0.0)
                continue
            t, _ = t_de_student(ecarts)
            res[(imp, off)] = (len(ecarts), st.fmean(obs) / st.fmean(refs), t)
    return res


def simuler_barrieres(ts, hi, lo, close):
    """Pour chaque cloture : issue du 2/20 dans les DEUX sens.

    Une bougie qui touche les DEUX bornes compte comme PERTE (hypothese la
    plus defavorable, declaree). Au-dela de MAX_BOUGIES : non resolu, ecarte.
    """
    n = len(ts)
    issues = [None] * n
    for i in range(n - 1):
        e = close[i]
        tp_a, sl_a = e + TP_USD, e - SL_USD
        tp_v, sl_v = e - TP_USD, e + SL_USD
        g_a = g_v = None
        fin = min(n, i + 1 + MAX_BOUGIES)
        for j in range(i + 1, fin):
            h, l = hi[j], lo[j]
            if g_a is None:
                if l <= sl_a:
                    g_a = False
                elif h >= tp_a:
                    g_a = True
            if g_v is None:
                if h >= sl_v:
                    g_v = False
                elif l <= tp_v:
                    g_v = True
            if g_a is not None and g_v is not None:
                break
        if g_a is None or g_v is None:
            continue
        issues[i] = (g_a, g_v)
    return issues


def net_usd(gagne, spread_pts):
    return (TP_USD if gagne else -SL_USD) - spread_pts * POINT_USD


def partie_b(ts, issues, spread, instants_high):
    """dans vs hors, stratifie sur (heure, jour)."""
    dans = set()
    k0, k1 = FENETRE_B[0] // 5, FENETRE_B[1] // 5
    for d in instants_high:
        base = _plancher5(d)
        for k in range(k0, k1 + 1):
            dans.add(base + dt.timedelta(minutes=5 * k))
    seaux = collections.defaultdict(lambda: {"dans": [], "hors": []})
    for i, d in enumerate(ts):
        if issues[i] is None:
            continue
        cle = "dans" if d in dans else "hors"
        sp = spread[i]
        # Les DEUX sens : la direction est morte, la moyenne des deux jambes
        # mesure donc la GEOMETRIE et son cout, pas un pari directionnel.
        for g in issues[i]:
            seaux[strate(d)][cle].append((g, sp, net_usd(g, sp)))
    diffs = []
    n_dans = n_hors = 0
    reussite = {"dans": [0, 0], "hors": [0, 0]}
    spreads = {"dans": [], "hors": []}
    nets = {"dans": [], "hors": []}
    for v in seaux.values():
        if not v["dans"] or len(v["hors"]) < 20:
            continue
        for cle in ("dans", "hors"):
            for g, sp, nt in v[cle]:
                reussite[cle][0] += int(g)
                reussite[cle][1] += 1
                spreads[cle].append(sp)
                nets[cle].append(nt)
        m_d = st.fmean([x[2] for x in v["dans"]])
        m_h = st.fmean([x[2] for x in v["hors"]])
        diffs.extend([m_d - m_h] * len(v["dans"]))
        n_dans += len(v["dans"])
        n_hors += len(v["hors"])
    t, m = t_de_student(diffs)
    nan = float("nan")
    return {
        "n_dans": n_dans,
        "n_hors": n_hors,
        "reussite_dans": 100 * reussite["dans"][0] / max(1, reussite["dans"][1]),
        "reussite_hors": 100 * reussite["hors"][0] / max(1, reussite["hors"][1]),
        "spread_dans": st.median(spreads["dans"]) if spreads["dans"] else nan,
        "spread_hors": st.median(spreads["hors"]) if spreads["hors"] else nan,
        "net_dans": st.fmean(nets["dans"]) if nets["dans"] else nan,
        "net_hors": st.fmean(nets["hors"]) if nets["hors"] else nan,
        "diff": m,
        "t": t,
    }


def main():
    rng = random.Random(SEED)
    ts, amp, hi, lo, close, spread = charger_bougies()
    evts = charger_evenements()
    print("bougies M5 courtier : %d   %s -> %s" % (len(ts), ts[0], ts[-1]))
    print("evenements %s : %d" % (DEVISE, len(evts)))

    fond, n_sales = fond_apparie(ts, amp, [d for d, _ in evts])
    print("fond apparie : %d strates (heure x jour), %d bougies ecartees "
          "car a +/-%d min d'une publication" % (len(fond), n_sales, GARDE_MIN))

    print("\n=== A. MECANISME : amplitude M5, rapport au fond APPARIE ===")
    reel = partie_a(evts, amp, fond)
    print("%-8s%8s%8s%10s%9s" % ("impact", "offset", "n", "rapport", "t"))
    for imp in IMPACTS:
        for off in OFFSETS:
            n, r, t = reel[(imp, off)]
            print("%-8s%+8d%8d%10.3f%+9.2f" % (imp, off, n, r, t))

    par_strate = collections.defaultdict(list)
    for d in ts:
        par_strate[strate(d)].append(d)

    maxima = []
    for k in range(N_PLACEBO):
        faux = []
        for d, imp in evts:
            pool = par_strate.get(strate(_plancher5(d)))
            if pool:
                faux.append((rng.choice(pool), imp))
        r = partie_a(faux, amp, fond)
        maxima.append(max(abs(v[2]) for v in r.values()))
        if (k + 1) % 50 == 0:
            print("  placebo A %d/%d..." % (k + 1, N_PLACEBO), flush=True)
    maxima.sort()
    plafond = maxima[int(0.95 * len(maxima)) - 1]
    print("\nPLAFOND A (95e centile du max|t| sur %d permutations) : %.3f"
          % (N_PLACEBO, plafond))
    retenues = [(k, v) for k, v in reel.items() if abs(v[2]) > plafond]
    print("cellules qui le franchissent : %d / %d" % (len(retenues), len(reel)))
    for (imp, off), (n, r, t) in sorted(retenues, key=lambda x: -abs(x[1][2])):
        print("  %s %+d min : n=%d rapport=%.3f t=%+.2f" % (imp, off, n, r, t))

    print("\n=== B. DECISION : la geometrie 2/20 dans la fenetre d'une High US ===")
    issues = simuler_barrieres(ts, hi, lo, close)
    non_resolus = sum(1 for x in issues if x is None) - 1
    print("entrees non resolues sous %d bougies (ecartees) : %d"
          % (MAX_BOUGIES, non_resolus))
    high = [d for d, i in evts if i == "High"]
    b = partie_b(ts, issues, spread, high)
    print("n dans = %d   n hors = %d" % (b["n_dans"], b["n_hors"]))
    print("reussite  dans %.2f %%   hors %.2f %%   (piece 20/22 = 90,91 %%)"
          % (b["reussite_dans"], b["reussite_hors"]))
    print("spread median  dans %.1f pts   hors %.1f pts"
          % (b["spread_dans"], b["spread_hors"]))
    print("net $/trade    dans %+.4f   hors %+.4f" % (b["net_dans"], b["net_hors"]))
    print("dans - hors (stratifie) = %+.4f $   t = %+.2f" % (b["diff"], b["t"]))

    maxima_b = []
    for k in range(N_PLACEBO):
        faux = []
        for d in high:
            pool = par_strate.get(strate(_plancher5(d)))
            if pool:
                faux.append(rng.choice(pool))
        maxima_b.append(abs(partie_b(ts, issues, spread, faux)["t"]))
        if (k + 1) % 50 == 0:
            print("  placebo B %d/%d..." % (k + 1, N_PLACEBO), flush=True)
    maxima_b.sort()
    plafond_b = maxima_b[int(0.95 * len(maxima_b)) - 1]
    print("PLAFOND B (95e centile de |t| sur %d permutations) : %.3f"
          % (N_PLACEBO, plafond_b))
    print("VERDICT B :", "RETENU" if abs(b["t"]) > plafond_b else "sous le plafond")
    return 0


if __name__ == "__main__":
    sys.exit(main())
