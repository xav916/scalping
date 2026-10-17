#!/usr/bin/env python3
"""Un stop indexe sur la VOLATILITE, non sur le prix.

Pre-inscrit dans docs/predictions/2026-10-14_stop_indexe_sur_la_volatilite.md
AVANT d'ecrire ce fichier (commit 5180f5d).

🔑 DEUX CORRECTIONS AU BANC DU 30/09 :
  - la POPULATION est FIXE (memes entrees pour toutes les cellules) ; le banc
    d'alors passait de 10 134 trades a 1 988 selon k, donc comparait des
    echantillons differents ;
  - le spread vient du TICK, plus le markup de 10 points mesure le 12/10 ; le
    banc d'alors l'epinglait a une constante.

🔑 ET LES k SONT CALIBRES pour que chaque cellule ait la MEME largeur MEDIANE
que la production. Sans ca on mesurerait << plus large ou plus serre >> -- deja
refute -- au lieu de << indexer >>.
"""
from __future__ import annotations

import bisect
import collections
import datetime as dt
import math
import os
import sqlite3
import statistics as st
import sys

MAGASIN = os.getenv("TICKS", "/app/data/ticks_courtier.db")
EUR_USD = 1.1198
MARKUP_PTS = 10.0
DEMI = MARKUP_PTS / 200.0

PCT_PROD = 0.35 / 100.0        # la production : 0,35 % du prix
PAS_MINI = 0.10
PLAFOND_EUR = 9.0
AGE_MINI_SEC = 60
CADENCE_SEC = 60
NEG_REQUIS_SEC = 30
CAP_SEC = 14400
REPOS_SEC = 300
K_PLANCHER = 2.0
K_TRAINAGE = 2.0
PLANCHER_FRAIS_EUR = None      # calcule : prix/300, la porte des frais


def charger():
    c = sqlite3.connect("file:%s?mode=ro" % MAGASIN, uri=True)
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


def amplitude(ts, bid, ask, i, fenetre_sec):
    """L'amplitude (haut - bas) des `fenetre_sec` precedant l'entree, en EUR.

    ⛔ STRICTEMENT AVANT l'entree : utiliser le futur serait du lookahead, le
    defaut qui a gonfle un effet par 8 le 2026-10-08.
    """
    debut = ts[i] - fenetre_sec
    j = bisect.bisect_left(ts, debut)
    if j >= i:
        return None
    haut = max(ask[j:i])
    bas = min(bid[j:i])
    if haut <= bas:
        return None
    return (haut - bas) / EUR_USD


def spread_eur(bid, ask, i):
    return (ask[i] + DEMI - (bid[i] - DEMI)) / EUR_USD


# ─────────────────────────────────────────────────────────────────────────
# Les politiques de stop. Chacune rend une largeur en EUR, ou None.
# ─────────────────────────────────────────────────────────────────────────

def politiques(k_b, k_c, k_d):
    return (
        ("A production 0,35 %",
         lambda ts, b, a, i: (a[i] * PCT_PROD) / EUR_USD),
        ("B volatilite 15 min",
         lambda ts, b, a, i: (lambda v: k_b * v if v else None)(
             amplitude(ts, b, a, i, 900))),
        ("C volatilite 60 min",
         lambda ts, b, a, i: (lambda v: k_c * v if v else None)(
             amplitude(ts, b, a, i, 3600))),
        ("D spread courant",
         lambda ts, b, a, i: k_d * spread_eur(b, a, i)),
        ("E 13 EUR fixes",
         lambda ts, b, a, i: 13.0),
    )


def rejouer(ts, bid, ask, i, achat, largeur_eur):
    """Rend le P&L en EUR. `largeur_eur` est le stop INITIAL."""
    k = 1.0 / EUR_USD
    entree = (ask[i] + DEMI) if achat else (bid[i] - DEMI)
    t0 = ts[i]
    stop = -float(largeur_eur)
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
            larg = K_TRAINAGE * spread
            if pnl >= larg - 1e-9:
                c2 = pnl - larg
                if c2 > stop + PAS_MINI - 1e-9 and c2 < pnl - spread:
                    stop = c2
        if pnl < 0:
            if neg_depuis is None:
                neg_depuis = ts[j]
        else:
            neg_depuis = None
        if ts[j] - vu_pr >= CADENCE_SEC:
            vu_pr = ts[j]
            perte = -pnl
            if (ts[j] - t0 >= AGE_MINI_SEC and perte > 0
                    and neg_depuis is not None
                    and ts[j] - neg_depuis >= NEG_REQUIS_SEC):
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


def queue(valeurs, combien=3):
    """Le poids des `combien` pires, en EUR. Plus c'est NEGATIF, pire."""
    return sum(sorted(valeurs)[:combien])


def main() -> int:
    ts, bid, ask = charger()
    jours = [dt.datetime.fromtimestamp(t, dt.timezone.utc).date() for t in ts]
    print("=" * 78)
    print("MAGASIN : %d ticks, %d jours" % (len(ts), len(set(jours))))
    print("=" * 78)

    # population FIXE
    entrees, dernier = [], -1e18
    for i in range(1, len(ts) - 1):
        if ts[i] - dernier < REPOS_SEC:
            continue
        if amplitude(ts, bid, ask, i, 3600) is None:
            continue          # pas d'historique : ecartee POUR TOUTES
        entrees.append((i, len(entrees) % 2 == 0))
        dernier = ts[i]
    print("%d positions, IDENTIQUES pour toutes les cellules\n" % len(entrees))

    # ── ① LE MECANISME : la volatilite predit-elle la perte ? ──────────
    print("=" * 78)
    print("① LE MECANISME — l'agitation d'AVANT predit-elle la perte ?")
    print("=" * 78)
    larg_prod = [(ask[i] * PCT_PROD) / EUR_USD for i, _ in entrees]
    pnl_prod = [rejouer(ts, bid, ask, i, a, w)
                for (i, a), w in zip(entrees, larg_prod)]
    for fen, lib in ((900, "15 min"), (3600, "60 min")):
        amp = [amplitude(ts, bid, ask, i, fen) for i, _ in entrees]
        paires = [(v, p) for v, p in zip(amp, pnl_prod) if v]
        xs = [v for v, _ in paires]
        ys = [p for _, p in paires]
        mx, my = st.fmean(xs), st.fmean(ys)
        num = sum((x - mx) * (y - my) for x, y in paires)
        den = math.sqrt(sum((x - mx) ** 2 for x in xs)
                        * sum((y - my) ** 2 for y in ys))
        r = num / den if den else 0.0
        n = len(paires)
        t = r * math.sqrt(max(1, n - 2)) / math.sqrt(max(1e-12, 1 - r * r))
        print("   amplitude %s : r = %+.4f   t = %+.2f   n = %d"
              % (lib, r, t, n))
        print("      amplitude mediane %.3f EUR   p90 %.3f"
              % (st.median(xs), sorted(xs)[int(0.9 * len(xs))]))
    print()
    print("   🔑 PREDICTION n°5 : je predisais r POSITIF et significatif.")
    print("      Si r est nul, la largeur du stop est le MAUVAIS LEVIER.")
    print()

    # ── ② CALIBRATION des k : meme largeur MEDIANE que A ───────────────
    print("=" * 78)
    print("② CALIBRATION — chaque cellule a la MEME largeur mediane que A")
    print("=" * 78)
    cible = st.median(larg_prod)
    print("   largeur mediane de A : %.3f EUR" % cible)
    ks = {}
    for nom, fen in (("B", 900), ("C", 3600)):
        v = [x for x in (amplitude(ts, bid, ask, i, fen) for i, _ in entrees) if x]
        ks[nom] = cible / st.median(v)
        print("   %s : amplitude mediane %.3f -> k = %.3f"
              % (nom, st.median(v), ks[nom]))
    v = [spread_eur(bid, ask, i) for i, _ in entrees]
    ks["D"] = cible / st.median(v)
    print("   D : spread median %.4f -> k = %.1f" % (st.median(v), ks["D"]))
    print()

    # ── ③ LES CELLULES ─────────────────────────────────────────────────
    print("=" * 78)
    print("③ LES CELLULES — population fixe, cout reel")
    print("=" * 78)
    res = {}
    for nom, f in politiques(ks["B"], ks["C"], ks["D"]):
        par_jour = collections.defaultdict(list)
        larg = []
        for i, achat in entrees:
            w = f(ts, bid, ask, i)
            if w is None or w <= 0:
                w = cible           # repli : jamais d'echantillon different
            larg.append(w)
            par_jour[jours[i]].append(rejouer(ts, bid, ask, i, achat, w))
        tous = [x for v in par_jour.values() for x in v]
        moy = [st.fmean(v) for _, v in sorted(par_jour.items())]
        qj = [queue(v) for _, v in sorted(par_jour.items())]
        res[nom] = {"moyennes": moy, "queues": qj, "moyenne": st.fmean(tous),
                    "pire": min(moy), "larg_med": st.median(larg),
                    "larg_p90": sorted(larg)[int(0.9 * len(larg))],
                    "reussite": 100.0 * sum(1 for x in tous if x > 0) / len(tous),
                    "queue": st.fmean(qj)}
        r = res[nom]
        print("   %-21s largeur med %5.2f  p90 %5.2f  moyenne %+7.4f"
              "  pire jour %+7.3f  reussite %5.1f %%  queue %+7.2f"
              % (nom, r["larg_med"], r["larg_p90"], r["moyenne"], r["pire"],
                 r["reussite"], r["queue"]))

    # ── ④ LE CRITERE A TROIS CONDITIONS ────────────────────────────────
    A = res["A production 0,35 %"]
    print()
    print("=" * 78)
    print("④ LE CRITERE — les TROIS conditions, posees d'avance")
    print("=" * 78)
    print("   %-21s %9s %7s  %-9s %-12s %-12s" % ("cellule", "ecart", "t",
                                                  "1) t>-2", "2) pire jour",
                                                  "3) queue"))
    for nom in res:
        if nom.startswith("A "):
            continue
        e = [x - y for x, y in zip(res[nom]["moyennes"], A["moyennes"])]
        m = st.fmean(e)
        s = st.stdev(e) if len(e) > 1 else 0.0
        t = m / (s / math.sqrt(len(e))) if s else 0.0
        c1 = t > -2.0
        c2 = res[nom]["pire"] > A["pire"]
        c3 = res[nom]["queue"] > A["queue"]      # moins negatif = plus fine
        print("   %-21s %+9.4f %+7.2f  %-9s %-12s %-12s  => %s"
              % (nom, m, t, c1, c2, c3,
                 "RETENU" if (c1 and c2 and c3) else "rejete"))
    print()
    print("   🔑 La condition 3 est le coeur : c'est la seule qui repond a")
    print("      << perdre le moins possible >>. Queue de A : %+.2f EUR"
          % A["queue"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
