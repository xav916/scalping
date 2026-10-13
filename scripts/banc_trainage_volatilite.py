#!/usr/bin/env python3
"""Le TRAINAGE est-il trop serre ? Largeur indexee sur la volatilite.

Pre-inscrit dans docs/predictions/2026-10-14_trainage_indexe_sur_la_volatilite.md
AVANT ce fichier (commit 05e6097).

Le temoin D (plus LARGE sans indexer, a largeur mediane egale) est le coeur du
protocole : si elargir sans indexer fait aussi bien, la volatilite n'apporte
rien et seule la largeur comptait.
"""
from __future__ import annotations

import bisect
import collections
import datetime as dt
import math
import statistics as st
import sys

sys.path.insert(0, "/tmp")
from banc_vitesse_adverse import charger, EUR_USD, DEMI, REPOS_SEC  # noqa

PCT_PROD = 0.35 / 100.0
PAS_MINI = 0.10
PLAFOND_EUR = 9.0
AGE_MINI = 60.0
NEG_REQUISE = 30.0
CADENCE = 60.0
CAP_SEC = 14400
K_PLANCHER = 2.0
NIVEAUX = (1.0, 2.0, 3.0)      # mediane a 1x, 2x, 3x celle de A


def amplitude(ts, bid, ask, i, fen):
    j = bisect.bisect_left(ts, ts[i] - fen)
    if j >= i:
        return None
    h, b = max(ask[j:i]), min(bid[j:i])
    return (h - b) / EUR_USD if h > b else None


def rejouer(ts, bid, ask, i, achat, larg_trainage):
    """`larg_trainage` : largeur FIXE pour ce trade, en euros."""
    k = 1.0 / EUR_USD
    entree = (ask[i] + DEMI) if achat else (bid[i] - DEMI)
    t0 = ts[i]
    stop = -(ask[i] * PCT_PROD) / EUR_USD
    neg_depuis = None
    vu_tr = vu_pr = -1e18
    n = len(ts)
    j = i + 1
    while j < n and ts[j] - t0 <= CAP_SEC:
        b, a = bid[j] - DEMI, ask[j] + DEMI
        sortie = b if achat else a
        pnl = (sortie - entree) * k if achat else (entree - sortie) * k
        if pnl <= stop + 1e-12:
            return stop
        spread = (a - b) * k
        if ts[j] - vu_tr >= 1:
            vu_tr = ts[j]
            larg = larg_trainage
            # garde inchangee : jamais dans le spread
            if pnl >= larg - 1e-9:
                c2 = pnl - larg
                if c2 > stop + PAS_MINI - 1e-9 and c2 < pnl - spread:
                    stop = c2
        if pnl < 0:
            if neg_depuis is None:
                neg_depuis = ts[j]
        else:
            neg_depuis = None
        if ts[j] - vu_pr >= CADENCE:
            vu_pr = ts[j]
            perte = -pnl
            if (ts[j] - t0 >= AGE_MINI and perte > 0
                    and neg_depuis is not None
                    and ts[j] - neg_depuis >= NEG_REQUISE):
                largeur = -stop
                pl = K_PLANCHER * spread
                if largeur > pl:
                    vise = (largeur + perte) / 2.0
                    if vise < pl:
                        vise = pl
                    vise = min(vise, max(PLAFOND_EUR, perte + pl))
                    if vise < perte:
                        vise = perte + pl
                    if vise < largeur:
                        stop = -vise
        j += 1
    fin = min(j, n - 1)
    b, a = bid[fin] - DEMI, ask[fin] + DEMI
    sortie = b if achat else a
    return (sortie - entree) * k if achat else (entree - sortie) * k


def bilan(pj):
    tous = [x for v in pj.values() for x in v]
    gag = [x for x in tous if x > 0]
    per = [x for x in tous if x < 0]
    return {
        "moy": [st.fmean(v) for _, v in sorted(pj.items())],
        "pool": st.fmean(tous),
        "reussite": 100.0 * len(gag) / len(tous),
        "gain_moy": st.fmean(gag) if gag else 0.0,
        "perte_moy": st.fmean(per) if per else 0.0,
        "pire": min(st.fmean(v) for _, v in sorted(pj.items())),
    }


def ecart(res, A):
    e = [x - y for x, y in zip(res["moy"], A["moy"])]
    m = st.fmean(e)
    s = st.stdev(e) if len(e) > 1 else 0.0
    return m, (m / (s / math.sqrt(len(e))) if s else 0.0)


def main() -> int:
    ts, bid, ask = charger()
    jours = [dt.datetime.fromtimestamp(t, dt.timezone.utc).date() for t in ts]
    ent, dernier = [], -1e18
    for i in range(1, len(ts) - 1):
        if ts[i] - dernier < REPOS_SEC:
            continue
        if amplitude(ts, bid, ask, i, 900) is None:
            continue
        ent.append((i, len(ent) % 2 == 0))
        dernier = ts[i]
    print("%d ticks, %d jours, %d positions FIXES\n"
          % (len(ts), len(set(jours)), len(ent)))

    tj = sorted(set(jours[i] for i, _ in ent))
    moitie = len(tj) // 2
    dedans, dehors = set(tj[:moitie]), set(tj[moitie:])
    ent_in = [(i, a) for i, a in ent if jours[i] in dedans]

    sp = {i: (ask[i] + DEMI - (bid[i] - DEMI)) / EUR_USD for i, _ in ent}
    a5 = {i: amplitude(ts, bid, ask, i, 300) for i, _ in ent}
    a15 = {i: amplitude(ts, bid, ask, i, 900) for i, _ in ent}

    # largeur de reference : la production, 2 x spread
    ref = st.median([2.0 * sp[i] for i, _ in ent_in])
    print("largeur de trainage de A (mediane, 1re moitie) : %.4f EUR" % ref)
    print("amplitude mediane 5 min %.2f   15 min %.2f EUR"
          % (st.median([v for v in (a5[i] for i, _ in ent_in) if v]),
             st.median([v for v in (a15[i] for i, _ in ent_in) if v])))

    # calibration sur la PREMIERE MOITIE
    ks = {}
    for nom, src in (("B", a5), ("C", a15)):
        med = st.median([v for v in (src[i] for i, _ in ent_in) if v])
        ks[nom] = {n: (n * ref) / med for n in NIVEAUX}
    med_sp = st.median([sp[i] for i, _ in ent_in])
    ks["D"] = {n: (n * ref) / med_sp for n in NIVEAUX}
    print("k calibres : B %s" % {n: round(v, 3) for n, v in ks["B"].items()})
    print("             C %s" % {n: round(v, 3) for n, v in ks["C"].items()})
    print("             D %s (multiples du spread)"
          % {n: round(v, 1) for n, v in ks["D"].items()})
    print()

    def largeur(nom, niveau, i):
        if nom == "A":
            return 2.0 * sp[i]
        if nom == "B":
            return ks["B"][niveau] * (a5[i] or ref)
        if nom == "C":
            return ks["C"][niveau] * (a15[i] or ref)
        return ks["D"][niveau] * sp[i]

    def passe(sel, titre):
        e = [(i, a) for i, a in ent if jours[i] in sel]
        res = {}
        pj = collections.defaultdict(list)
        for i, achat in e:
            pj[jours[i]].append(rejouer(ts, bid, ask, i, achat, 2.0 * sp[i]))
        res[("A", 0)] = bilan(pj)
        for nom in ("B", "C", "D"):
            for niv in NIVEAUX:
                pj = collections.defaultdict(list)
                lg = []
                for i, achat in e:
                    w = largeur(nom, niv, i)
                    lg.append(w)
                    pj[jours[i]].append(rejouer(ts, bid, ask, i, achat, w))
                res[(nom, niv)] = bilan(pj)
                res[(nom, niv)]["larg"] = st.median(lg)
        print("=" * 86)
        print(titre)
        print("=" * 86)
        A = res[("A", 0)]
        print("   %-18s %7s %9s %9s %9s %9s %9s %7s"
              % ("cellule", "larg", "poolee", "gain moy", "perte", "reussite",
                 "ecart/j", "t"))
        print("   %-18s %7.3f %+9.4f %+9.3f %+9.3f %8.1f %% %9s %7s"
              % ("A production", 2.0 * med_sp, A["pool"], A["gain_moy"],
                 A["perte_moy"], A["reussite"], "-", "-"))
        for nom in ("B", "C", "D"):
            for niv in NIVEAUX:
                r = res[(nom, niv)]
                m, t = ecart(r, A)
                print("   %-18s %7.3f %+9.4f %+9.3f %+9.3f %8.1f %% %+9.4f %+7.2f"
                      % ("%s x%.0f" % (nom, niv), r["larg"], r["pool"],
                         r["gain_moy"], r["perte_moy"], r["reussite"], m, t))
        return res

    r_in = passe(dedans, "DANS L ECHANTILLON (k calibres ici)")
    print()
    r_out = passe(dehors, "HORS ECHANTILLON (memes k)")

    print()
    print("=" * 86)
    print("LE CRITERE — et la condition 3 : BATTRE SON TEMOIN D")
    print("=" * 86)
    A_in, A_out = r_in[("A", 0)], r_out[("A", 0)]
    for nom in ("B", "C"):
        for niv in NIVEAUX:
            m1, t1 = ecart(r_in[(nom, niv)], A_in)
            m2, t2 = ecart(r_out[(nom, niv)], A_out)
            d1, _ = ecart(r_in[("D", niv)], A_in)
            c1 = t1 > 2.0
            c2 = (m1 > 0) == (m2 > 0)
            c3 = m1 > d1
            print("   %-10s 1) t>+2 %-6s 2) signe %-6s 3) bat D (%+0.4f vs %+0.4f) %-6s"
                  "  => %s" % ("%s x%.0f" % (nom, niv), c1, c2, m1, d1, c3,
                               "RETENU" if (c1 and c2 and c3) else "rejete"))
    print()
    print("=" * 86)
    print("LA MESURE QUE JE REGARDE MEME SI RIEN NE PASSE : le GAIN MOYEN")
    print("=" * 86)
    print("   %-18s %12s %12s %12s" % ("cellule", "gain dedans",
                                       "gain dehors", "vs A dedans"))
    for nom in ("B", "C", "D"):
        for niv in NIVEAUX:
            g1 = r_in[(nom, niv)]["gain_moy"]
            g2 = r_out[(nom, niv)]["gain_moy"]
            pct = 100.0 * (g1 - A_in["gain_moy"]) / A_in["gain_moy"]
            print("   %-18s %+12.3f %+12.3f %+11.1f %%"
                  % ("%s x%.0f" % (nom, niv), g1, g2, pct))
    print()
    print("   et la REUSSITE, l'autre face de la piece :")
    print("   %-18s %12s %12s" % ("cellule", "dedans", "dehors"))
    print("   %-18s %11.1f %% %11.1f %%" % ("A production", A_in["reussite"],
                                            A_out["reussite"]))
    for nom in ("B", "C", "D"):
        for niv in NIVEAUX:
            print("   %-18s %11.1f %% %11.1f %%"
                  % ("%s x%.0f" % (nom, niv), r_in[(nom, niv)]["reussite"],
                     r_out[(nom, niv)]["reussite"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
