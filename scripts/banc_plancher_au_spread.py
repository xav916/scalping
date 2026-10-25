#!/usr/bin/env python3
"""Plancher et declencheur indexes sur le SPREAD, contre la production.

Pre-inscrit dans docs/predictions/2026-10-12_plancher_et_declencheur_au_spread.md
AVANT d'ecrire ce fichier (commit 45b2526).

🔑 LE SPREAD EST MESURE, PAS ESTIME : le magasin de ticks porte le bid ET
l'ask, donc `(ask - bid)` est connu a chaque tick. C'est ce qui rend la
demande de Xavier -- << avoir comme variable le spread >> -- mesurable plutot
que devinable.
"""
from __future__ import annotations

import collections
import datetime as dt
import math
import os
import sqlite3
import statistics as st
import sys

MAGASIN = os.getenv("TICKS", "/app/data/ticks_courtier.db")
EUR_USD = 1.1198

SL_DEPART_EUR = 13.0
TRAINAGE = 0.50
PAS_MINI = 0.10
PLAFOND_EUR = 9.0
AGE_MINI_SEC = 60
CADENCE_SEC = 60
NEG_REQUIS_SEC = 30
CAP_SEC = 14400
REPOS_SEC = 300

# (nom, plancher_fixe_eur | None, k_plancher, declenche_fixe_eur | None, k_declenche)
#   plancher : None + k  -> plancher = k x spread courant
#   declenche: None + k  -> le stop passe a 0 des que profit >= k x spread
CELLULES = (
    ("A production",      2.0,  None, 0.50, None),
    ("B plancher k=1",    None, 1.0,  0.50, None),
    ("B plancher k=2",    None, 2.0,  0.50, None),
    ("C declenche k=1",   2.0,  None, None, 1.0),
    ("C declenche k=2",   2.0,  None, None, 2.0),
    ("D Xavier k=1",      None, 1.0,  None, 1.0),
    ("D Xavier k=2",      None, 2.0,  None, 2.0),
)


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


def rejouer(ts, bid, ask, i, achat, plancher_fixe, k_plancher,
            decl_fixe, k_decl):
    k = 1.0 / EUR_USD
    entree = ask[i] if achat else bid[i]
    t0 = ts[i]
    stop = -SL_DEPART_EUR
    au_zero = False
    neg_depuis = None
    vu_trainage = -1e18
    vu_prot = -1e18
    n = len(ts)
    j = i + 1

    while j < n and ts[j] - t0 <= CAP_SEC:
        sortie = bid[j] if achat else ask[j]
        pnl = (sortie - entree) * k if achat else (entree - sortie) * k
        if pnl <= stop + 1e-12:
            return stop

        # Le spread COURANT, en euros. C'est la variable de Xavier.
        spread_eur = (ask[j] - bid[j]) * k

        # ── cote GAIN ────────────────────────────────────────────────────
        if ts[j] - vu_trainage >= 1:
            vu_trainage = ts[j]
            # le passage a l'equilibre
            seuil = decl_fixe if decl_fixe is not None else k_decl * spread_eur
            if not au_zero and pnl >= seuil - 1e-12:
                # ⛔ jamais DERRIERE le cours : il faut laisser au moins un
                # spread entre le stop et le prix, sinon le courtier ferme au
                # marche et << protection >> devient << fermeture >>.
                cible = min(0.0, pnl - spread_eur)
                if cible > stop:
                    stop = cible
                    au_zero = True
            # puis le trainage continu
            if au_zero or pnl >= 0.50 - 1e-9:
                c2 = pnl - TRAINAGE
                if c2 > stop + PAS_MINI - 1e-9 and c2 < pnl - spread_eur:
                    stop = c2

        # ── cote PERTE ───────────────────────────────────────────────────
        if pnl < 0:
            if neg_depuis is None:
                neg_depuis = ts[j]
        else:
            neg_depuis = None

        if ts[j] - vu_prot >= CADENCE_SEC:
            vu_prot = ts[j]
            perte = -pnl
            if (ts[j] - t0 >= AGE_MINI_SEC and perte > 0
                    and neg_depuis is not None
                    and ts[j] - neg_depuis >= NEG_REQUIS_SEC):
                largeur = -stop
                pl = (plancher_fixe if plancher_fixe is not None
                      else k_plancher * spread_eur)
                if largeur > pl:
                    vise = (largeur + perte) / 2.0
                    if vise < pl:
                        vise = pl
                    # garde du cote du cours : au moins un spread de marge
                    vise = min(vise, max(PLAFOND_EUR, perte + spread_eur))
                    vise = max(vise, perte + spread_eur) if vise < perte else vise
                    if vise < largeur:
                        stop = -vise
        j += 1

    fin = min(j, n - 1)
    sortie = bid[fin] if achat else ask[fin]
    return (sortie - entree) * k if achat else (entree - sortie) * k


def main() -> int:
    ts, bid, ask = charger()
    jours = [dt.datetime.fromtimestamp(t, dt.timezone.utc).date() for t in ts]
    sp = [(a - b) / EUR_USD for a, b in zip(ask, bid)]
    print("%d ticks   %d jours   spread median %.4f EUR   p95 %.4f"
          % (len(ts), len(set(jours)), st.median(sp),
             sorted(sp)[int(0.95 * len(sp))]))

    entrees, dernier = [], -1e18
    for i in range(1, len(ts) - 1):
        if ts[i] - dernier < REPOS_SEC:
            continue
        entrees.append((i, len(entrees) % 2 == 0))
        dernier = ts[i]
    print("%d positions par cellule, %d cellules\n"
          % (len(entrees), len(CELLULES)))

    res = {}
    for nom, pf, kp, df, kd in CELLULES:
        par_jour = collections.defaultdict(list)
        for i, achat in entrees:
            par_jour[jours[i]].append(
                rejouer(ts, bid, ask, i, achat, pf, kp, df, kd))
        tous = [x for v in par_jour.values() for x in v]
        moy = [st.fmean(v) for _, v in sorted(par_jour.items())]
        res[nom] = {"moyennes": moy, "moyenne": st.fmean(tous),
                    "pire": min(moy), "tous": tous,
                    "reussite": 100.0 * sum(1 for x in tous if x > 0) / len(tous),
                    "nuls": sum(1 for x in tous if abs(x) < 0.05)}
        r = res[nom]
        print("  %-17s moyenne %+7.4f   pire jour %+7.3f   reussite %5.1f %%"
              "   trades nuls %4d" % (nom, r["moyenne"], r["pire"],
                                      r["reussite"], r["nuls"]))

    a = res["A production"]
    print()
    print("  ECART CONTRE A, apparie sur le JOUR")
    print("  %-17s %10s %8s  %s" % ("cellule", "ecart", "t", "critere"))
    for nom, *_ in CELLULES:
        if nom == "A production":
            continue
        ec = [x - y for x, y in zip(res[nom]["moyennes"], a["moyennes"])]
        m = st.fmean(ec)
        s = st.stdev(ec) if len(ec) > 1 else 0.0
        t = m / (s / math.sqrt(len(ec))) if s else 0.0
        c1 = t > -2.0
        c2 = res[nom]["pire"] >= a["pire"]
        print("  %-17s %+10.4f %+8.2f  t>-2 %-5s  pire jour OK %-5s  => %s"
              % (nom, m, t, c1, c2, "RETENU" if (c1 and c2) else "rejete"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
