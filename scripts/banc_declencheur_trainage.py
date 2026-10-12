#!/usr/bin/env python3
"""Le DECLENCHEUR du trainage, contre la production.

Pre-inscrit dans docs/predictions/2026-10-12_declencheur_du_trainage.md AVANT
d'ecrire ce fichier (commit 3cdd76e).

Xavier : << des que le trade passe en positif, alors remontez le SL >>.

🔑 On mesure ce qui est POSSIBLE de sa demande : baisser le DECLENCHEUR sans
toucher a la LARGEUR. Sa formulation litterale (stop a 0 des le 1er centime)
est deja mesuree et rejetee -- cellules C/D de 45b2526, 51 % de trades nuls.
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
PAS_MINI = 0.10
PLAFOND_EUR = 9.0
AGE_MINI_SEC = 60
CADENCE_SEC = 60
NEG_REQUIS_SEC = 30
CAP_SEC = 14400
REPOS_SEC = 300
# le plancher de la protection, ARME ce matin a k=2 x spread
K_PLANCHER = 2.0

# (nom, declenche_fixe | None, k_declenche, largeur_fixe | None, k_largeur)
CELLULES = (
    ("A production",      0.50, None, 0.50, None),
    ("B declencheur k=1", None, 1.0,  0.50, None),
    ("B declencheur k=2", None, 2.0,  0.50, None),
    ("C les deux k=1",    None, 1.0,  None, 1.0),
    ("C les deux k=2",    None, 2.0,  None, 2.0),
    ("D largeur k=1",     0.50, None, None, 1.0),
    ("D largeur k=2",     0.50, None, None, 2.0),
)


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


def rejouer(ts, bid, ask, i, achat, decl_fixe, k_decl, larg_fixe, k_larg):
    """Rend (pnl, a_declenche_le_trainage)."""
    k = 1.0 / EUR_USD
    entree = ask[i] if achat else bid[i]
    t0 = ts[i]
    stop = -SL_DEPART_EUR
    neg_depuis = None
    vu_trainage = -1e18
    vu_prot = -1e18
    declenche = False
    n = len(ts)
    j = i + 1

    while j < n and ts[j] - t0 <= CAP_SEC:
        sortie = bid[j] if achat else ask[j]
        pnl = (sortie - entree) * k if achat else (entree - sortie) * k
        if pnl <= stop + 1e-12:
            return stop, declenche

        spread = (ask[j] - bid[j]) * k

        # ── cote GAIN : le trainage, relu A LA SECONDE ──────────────────
        if ts[j] - vu_trainage >= 1:
            vu_trainage = ts[j]
            decl = decl_fixe if decl_fixe is not None else k_decl * spread
            larg = larg_fixe if larg_fixe is not None else k_larg * spread
            if pnl >= decl - 1e-9:
                declenche = True
                c2 = pnl - larg
                # ⛔ JAMAIS DANS LE SPREAD : un stop a moins d'un spread du
                # cours est franchi par le rebond bid/ask seul. C'est la
                # garde qui distingue une protection d'une fermeture.
                if c2 > stop + PAS_MINI - 1e-9 and c2 < pnl - spread:
                    stop = c2

        # ── cote PERTE : la protection a la minute, telle qu'ARMEE ───────
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
    sortie = bid[fin] if achat else ask[fin]
    pnl = (sortie - entree) * k if achat else (entree - sortie) * k
    return pnl, declenche


def main() -> int:
    ts, bid, ask = charger()
    jours = [dt.datetime.fromtimestamp(t, dt.timezone.utc).date() for t in ts]
    sp = [(a - b) / EUR_USD for a, b in zip(ask, bid)]
    print("%d ticks   %d jours   spread median %.4f EUR (%.0f points)"
          % (len(ts), len(set(jours)), st.median(sp), st.median(sp) * EUR_USD * 100))

    entrees, dernier = [], -1e18
    for i in range(1, len(ts) - 1):
        if ts[i] - dernier < REPOS_SEC:
            continue
        entrees.append((i, len(entrees) % 2 == 0))
        dernier = ts[i]
    print("%d positions par cellule, %d cellules\n" % (len(entrees), len(CELLULES)))

    res = {}
    for nom, df, kd, lf, kl in CELLULES:
        par_jour = collections.defaultdict(list)
        decl = 0
        for i, achat in entrees:
            p, d = rejouer(ts, bid, ask, i, achat, df, kd, lf, kl)
            par_jour[jours[i]].append(p)
            decl += 1 if d else 0
        tous = [x for v in par_jour.values() for x in v]
        moy = [st.fmean(v) for _, v in sorted(par_jour.items())]
        nuls = sum(1 for x in tous if abs(x) < 0.05)
        res[nom] = {"moyennes": moy, "moyenne": st.fmean(tous), "pire": min(moy),
                    "reussite": 100.0 * sum(1 for x in tous if x > 0) / len(tous),
                    "nuls": nuls, "taux_nuls": 100.0 * nuls / len(tous),
                    "declenche": 100.0 * decl / len(tous)}
        r = res[nom]
        print("  %-18s moyenne %+7.4f   pire jour %+7.3f   reussite %5.1f %%"
              "   nuls %5.1f %%   trainage declenche %5.1f %%"
              % (nom, r["moyenne"], r["pire"], r["reussite"], r["taux_nuls"],
                 r["declenche"]))

    a = res["A production"]
    print()
    print("  ECART CONTRE A, apparie sur le JOUR — CRITERE A TROIS CONDITIONS")
    print("  %-18s %9s %7s   %-9s %-11s %-9s" % ("cellule", "ecart", "t",
                                                 "1) t>-2", "2) pire jour", "3) nuls"))
    for nom, *_ in CELLULES:
        if nom == "A production":
            continue
        ec = [x - y for x, y in zip(res[nom]["moyennes"], a["moyennes"])]
        m = st.fmean(ec)
        s = st.stdev(ec) if len(ec) > 1 else 0.0
        t = m / (s / math.sqrt(len(ec))) if s else 0.0
        c1 = t > -2.0
        c2 = res[nom]["pire"] >= a["pire"]
        # ⛔ la condition posee d'AVANCE : pas plus de 25 % de nuls en relatif
        plafond_nuls = a["taux_nuls"] * 1.25
        c3 = res[nom]["taux_nuls"] <= plafond_nuls + 1e-9
        print("  %-18s %+9.4f %+7.2f   %-9s %-11s %-9s  => %s"
              % (nom, m, t, c1, c2,
                 "%.1f/%.1f" % (res[nom]["taux_nuls"], plafond_nuls),
                 "RETENU" if (c1 and c2 and c3) else "rejete"))
    print()
    print("  🔑 Prediction 5 : le trainage se declenche sur %.1f %% des trades en A"
          % a["declenche"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
