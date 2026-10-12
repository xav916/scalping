#!/usr/bin/env python3
"""Inverser le sens de chaque trade — la demande de Xavier du 2026-10-12.

Pre-inscrit dans docs/predictions/2026-10-12_inverser_le_sens.md AVANT
d'ecrire ce fichier (commit d066a91).

🔑 CE QU'ON CHERCHE N'EST PAS LA MOYENNE, C'EST LA DISSYMETRIE. << Demarrer
mal >> peut etre vrai dans LES DEUX SENS -- ce serait alors le cout d'entree,
et inverser n'y changerait rien.
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
MARKUP_PTS = 10.0
DEMI = MARKUP_PTS / 200.0

SL_DEPART_EUR = 13.0
PAS_MINI = 0.10
PLAFOND_EUR = 9.0
AGE_MINI_SEC = 60
CADENCE_SEC = 60
NEG_REQUIS_SEC = 30
CAP_SEC = 14400
REPOS_SEC = 300
K_PLANCHER = 2.0
K_TRAINAGE = 2.0          # la configuration ARMEE aujourd'hui


def charger():
    c = sqlite3.connect("file:%s?mode=ro" % MAGASIN, uri=True)
    rows = c.execute("SELECT ts_utc, ms, bid, ask FROM ticks "
                     "WHERE pair = 'XAU/USD' ORDER BY ts_utc, ms").fetchall()
    ts, bid, ask, idx = [], [], [], collections.defaultdict(list)
    for t, ms, b, a in rows:
        if ms and ms > 1e12:
            ts.append(ms / 1000.0)
        else:
            d = dt.datetime.fromisoformat(t).replace(tzinfo=dt.timezone.utc)
            ts.append(d.timestamp() + (ms or 0) / 1000.0)
        bid.append(b)
        ask.append(a)
        idx[str(t)[:19]].append((b, a))
    return ts, bid, ask, idx


# ─────────────────────────────────────────────────────────────────────────
# ① et ② L'EXCURSION ADVERSE IMMEDIATE, par SENS
# ─────────────────────────────────────────────────────────────────────────

def excursion(ts, bid, ask, i, achat, horizons=(30, 60, 300)):
    """Le PIRE P&L atteint dans les N premieres secondes, en euros."""
    k = 1.0 / EUR_USD
    entree = (ask[i] + DEMI) if achat else (bid[i] - DEMI)
    pires = {h: 0.0 for h in horizons}
    n = len(ts)
    j = i + 1
    hmax = max(horizons)
    while j < n and ts[j] - ts[i] <= hmax:
        b, a = bid[j] - DEMI, ask[j] + DEMI
        sortie = b if achat else a
        pnl = (sortie - entree) * k if achat else (entree - sortie) * k
        for h in horizons:
            if ts[j] - ts[i] <= h and pnl < pires[h]:
                pires[h] = pnl
        j += 1
    return pires


def bloc_excursion(ts, bid, ask, entrees):
    print("=" * 78)
    print("② L'EXCURSION ADVERSE IMMEDIATE, PAR SENS — « demarrent mal » ?")
    print("=" * 78)
    par = {True: collections.defaultdict(list), False: collections.defaultdict(list)}
    for i, achat in entrees:
        for h, v in excursion(ts, bid, ask, i, achat).items():
            par[achat][h].append(v)
    print("   %-8s %-7s %10s %10s %10s" % ("sens", "horizon", "mediane", "moyenne", "n"))
    med = {}
    for achat, lib in ((True, "ACHAT"), (False, "VENTE")):
        for h in (30, 60, 300):
            v = par[achat][h]
            med[(lib, h)] = st.median(v)
            print("   %-8s %4d s  %+10.4f %+10.4f %10d"
                  % (lib, h, st.median(v), st.fmean(v), len(v)))
    print()
    print("   🔑 LA DISSYMETRIE — c'est elle qui decide, pas la moyenne")
    ecarts = []
    for h in (30, 60, 300):
        d = med[("ACHAT", h)] - med[("VENTE", h)]
        ecarts.append(abs(d))
        print("      a %4d s : achat %+.4f  vente %+.4f  ecart %+.4f EUR"
              % (h, med[("ACHAT", h)], med[("VENTE", h)], d))
    pire = max(ecarts)
    print()
    print("   plus grand ecart entre sens : %.4f EUR" % pire)
    if pire <= 0.05:
        print("   ✅ PREDICTION n°2 TENUE : l'excursion adverse est SYMETRIQUE.")
        print("      << Demarrer mal >> est le COUT D'ENTREE, pas une erreur")
        print("      de sens — et inverser ne peut donc rien y changer.")
    else:
        print("   ⚠️ PREDICTION n°2 FAUSSE : les deux sens ne demarrent PAS")
        print("      pareil. Sa proposition a une base mecanique a examiner.")
    return pire


# ─────────────────────────────────────────────────────────────────────────
# ③ L'INVERSION APPARIEE
# ─────────────────────────────────────────────────────────────────────────

def rejouer(ts, bid, ask, i, achat):
    k = 1.0 / EUR_USD
    entree = (ask[i] + DEMI) if achat else (bid[i] - DEMI)
    t0 = ts[i]
    stop = -SL_DEPART_EUR
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
        neg_depuis = ts[j] if (pnl < 0 and neg_depuis is None) else (
            None if pnl >= 0 else neg_depuis)
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


def bloc_inversion(ts, bid, ask, entrees, jours):
    print()
    print("=" * 78)
    print("③ L'INVERSION APPARIEE — memes instants, memes ticks, cout reel")
    print("=" * 78)
    pj_o = collections.defaultdict(list)
    pj_i = collections.defaultdict(list)
    sens = {True: [], False: []}
    for i, achat in entrees:
        o = rejouer(ts, bid, ask, i, achat)
        inv = rejouer(ts, bid, ask, i, not achat)
        pj_o[jours[i]].append(o)
        pj_i[jours[i]].append(inv)
        sens[achat].append(o)
    to = [x for v in pj_o.values() for x in v]
    ti = [x for v in pj_i.values() for x in v]
    print("   %-14s %10s %10s %10s" % ("", "moyenne", "reussite", "n"))
    for lib, v in (("ORIGINAL", to), ("INVERSE", ti)):
        print("   %-14s %+10.4f %9.1f %% %10d"
              % (lib, st.fmean(v), 100 * sum(1 for x in v if x > 0) / len(v), len(v)))
    mo = [st.fmean(v) for _, v in sorted(pj_o.items())]
    mi = [st.fmean(v) for _, v in sorted(pj_i.items())]
    e = [b - a for a, b in zip(mo, mi)]
    m = st.fmean(e)
    s = st.stdev(e) if len(e) > 1 else 0.0
    t = m / (s / math.sqrt(len(e))) if s else 0.0
    print()
    print("   ecart INVERSE - ORIGINAL : %+.4f EUR/trade   t %+.2f   sur %d jours"
          % (m, t, len(e)))
    print("   jours ou l'inversion fait mieux : %d / %d"
          % (sum(1 for x in e if x > 0), len(e)))
    print()
    if t > 2.0:
        print("   ⚠️ CRITERE PASSE (t > +2). Mais voir la condition de coherence.")
    else:
        print("   ⛔ CRITERE ECHOUE (t <= +2) : l'inversion ne remplace PAS la")
        print("      production. ✅ PREDICTION n°3 tenue.")
    print()
    print("=" * 78)
    print("④ ET LA QUESTION QUI DECIDE : LES DEUX SENS PERDENT-ILS ?")
    print("=" * 78)
    for achat, lib in ((True, "ACHATS"), (False, "VENTES")):
        v = sens[achat]
        print("   %-8s n=%-5d moyenne %+8.4f   reussite %5.1f %%"
              % (lib, len(v), st.fmean(v),
                 100 * sum(1 for x in v if x > 0) / len(v)))
    a_moy, v_moy = st.fmean(sens[True]), st.fmean(sens[False])
    print()
    if a_moy < 0 and v_moy < 0:
        print("   ✅ PREDICTION n°4 TENUE : LES DEUX SENS PERDENT.")
        print("      🔑 Aucune permutation des deux ne peut gagner. Le probleme")
        print("         est la GEOMETRIE et le COUT, pas la direction.")
    else:
        print("   ⚠️ PREDICTION n°4 FAUSSE : un sens gagne (%s)."
              % ("achats" if a_moy >= 0 else "ventes"))
    return t


# ─────────────────────────────────────────────────────────────────────────

def bloc_reel():
    print("=" * 78)
    print("① LES TRADES REELS DU JOUR, par sens")
    print("=" * 78)
    try:
        from backend.services.mt5_sync import _db_path
        c = sqlite3.connect(_db_path())
        c.row_factory = sqlite3.Row
    except Exception as e:
        print("   base illisible :", e)
        return
    q = ("SELECT lower(direction) s, COUNT(*) n, SUM(pnl) t, AVG(pnl) m,"
         " SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) g"
         " FROM personal_trades WHERE pair LIKE '%XAU%'"
         " AND destination_id='admin_live' AND is_auto=1 AND pnl IS NOT NULL"
         " AND replace(created_at,'T',' ') >= date('now') GROUP BY s")
    L = list(c.execute(q))
    for r in L:
        print("   %-6s n=%-4d total %+8.2f EUR   moyenne %+7.3f   %d gagnants (%.0f %%)"
              % (r["s"], r["n"], r["t"] or 0, r["m"] or 0, r["g"] or 0,
                 100 * (r["g"] or 0) / r["n"]))
    N = sum(r["n"] for r in L)
    print("   total n=%d" % N)
    print()
    print("   ⚠️ PREDICTION n°5, posee d'avance : %d trades ne font PAS un" % N)
    print("      verdict. Ce bloc DECRIT ce que Xavier voit, il ne tranche pas.")
    print()


def main() -> int:
    bloc_reel()
    ts, bid, ask, _ = charger()
    jours = [dt.datetime.fromtimestamp(t, dt.timezone.utc).date() for t in ts]
    entrees, dernier = [], -1e18
    for i in range(1, len(ts) - 1):
        if ts[i] - dernier < REPOS_SEC:
            continue
        entrees.append((i, len(entrees) % 2 == 0))
        dernier = ts[i]
    print("magasin : %d ticks, %d jours, %d positions\n"
          % (len(ts), len(set(jours)), len(entrees)))
    bloc_excursion(ts, bid, ask, entrees)
    bloc_inversion(ts, bid, ask, entrees, jours)
    return 0


if __name__ == "__main__":
    sys.exit(main())
