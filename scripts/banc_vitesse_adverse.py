#!/usr/bin/env python3
"""Un declencheur sur la VITESSE du mouvement adverse, contre la production.

Pre-inscrit dans docs/predictions/2026-10-14_declencheur_sur_la_vitesse.md
AVANT d'ecrire ce fichier (commit 189c67e).

🔑 LES DEUX TEMOINS SONT LE COEUR DU PROTOCOLE. `D` regarde plus SOUVENT
(cadence 15 s) et `E` regarde plus TOT (aucun age minimum), tous deux sans
mesurer la vitesse. Si l'un d'eux fait aussi bien que `B`, alors la vitesse
n'apporte RIEN et seul le delai comptait.
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
DEMI = 10.0 / 200.0            # le markup mesure, par cote

PCT_PROD = 0.35 / 100.0
PAS_MINI = 0.10
PLAFOND_EUR = 9.0
CAP_SEC = 14400
REPOS_SEC = 300
K_PLANCHER = 2.0
K_TRAINAGE = 2.0
FEN_VITESSE = 30.0             # la fenetre glissante de mesure de vitesse

# (nom, age_mini, neg_requise, cadence, vitesse_active, ferme_au_marche)
CELLULES = (
    ("A production",        60.0, 30.0, 60.0, False, False),
    ("B vitesse resserre",  60.0, 30.0, 60.0, True,  False),
    ("C vitesse ferme",     60.0, 30.0, 60.0, True,  True),
    ("D TEMOIN cadence 15", 60.0, 30.0, 15.0, False, False),
    ("E TEMOIN sans age",    0.0, 30.0, 60.0, False, False),
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


def rejouer(ts, bid, ask, i, achat, age_mini, neg_requise, cadence,
            vitesse_active, ferme, seuil_v):
    """Rend (pnl, vitesse_max_vue, s_est_declenchee)."""
    k = 1.0 / EUR_USD
    entree = (ask[i] + DEMI) if achat else (bid[i] - DEMI)
    t0 = ts[i]
    largeur0 = (ask[i] * PCT_PROD) / EUR_USD
    stop = -largeur0
    neg_depuis = None
    vu_tr = vu_pr = -1e18
    n = len(ts)
    j = i + 1
    # fenetre glissante : (instant, pnl) pour mesurer la VITESSE
    fen = collections.deque()
    v_max = 0.0
    declenche = False

    while j < n and ts[j] - t0 <= CAP_SEC:
        b, a = bid[j] - DEMI, ask[j] + DEMI
        sortie = b if achat else a
        pnl = (sortie - entree) * k if achat else (entree - sortie) * k
        if pnl <= stop + 1e-12:
            return stop, v_max, declenche
        spread = (a - b) * k

        # ── LA VITESSE : chute de P&L sur 30 s glissantes ───────────────
        fen.append((ts[j], pnl))
        while fen and ts[j] - fen[0][0] > FEN_VITESSE:
            fen.popleft()
        if len(fen) > 1:
            # la vitesse est la CHUTE depuis le plus haut de la fenetre
            haut = max(p for _, p in fen)
            v = haut - pnl
            if v > v_max:
                v_max = v
            if vitesse_active and seuil_v is not None and v >= seuil_v:
                declenche = True
                if ferme:
                    # ⛔ fermeture au marche : on sort au prix courant, pas au
                    # stop. C'est ce qui distingue C de B.
                    return pnl, v_max, declenche
                perte = -pnl
                if perte > 0:
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

        # ── le trainage, identique partout ─────────────────────────────
        if ts[j] - vu_tr >= 1:
            vu_tr = ts[j]
            larg = K_TRAINAGE * spread
            if pnl >= larg - 1e-9:
                c2 = pnl - larg
                if c2 > stop + PAS_MINI - 1e-9 and c2 < pnl - spread:
                    stop = c2

        # ── la protection, cadence et conditions propres a la cellule ──
        if pnl < 0:
            if neg_depuis is None:
                neg_depuis = ts[j]
        else:
            neg_depuis = None
        if ts[j] - vu_pr >= cadence:
            vu_pr = ts[j]
            perte = -pnl
            if (ts[j] - t0 >= age_mini and perte > 0
                    and neg_depuis is not None
                    and ts[j] - neg_depuis >= neg_requise):
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
    p = (sortie - entree) * k if achat else (entree - sortie) * k
    return p, v_max, declenche


def queue(v, combien=3):
    return sum(sorted(v)[:combien])


def tableau(ts, bid, ask, ent, jours, seuil_v, titre):
    res = {}
    for nom, age, neg, cad, vit, fer in CELLULES:
        pj = collections.defaultdict(list)
        n_decl = 0
        for i, achat in ent:
            p, _vm, d = rejouer(ts, bid, ask, i, achat, age, neg, cad, vit,
                                fer, seuil_v)
            pj[jours[i]].append(p)
            n_decl += 1 if d else 0
        tous = [x for v in pj.values() for x in v]
        moy = [st.fmean(v) for _, v in sorted(pj.items())]
        qj = [queue(v) for _, v in sorted(pj.items())]
        res[nom] = {"moy": moy, "q": qj, "pool": st.fmean(tous),
                    "pire": min(moy), "queue": st.fmean(qj),
                    "reussite": 100.0 * sum(1 for x in tous if x > 0) / len(tous),
                    "decl": 100.0 * n_decl / len(tous)}
    A = res["A production"]
    print("=" * 80)
    print(titre)
    print("=" * 80)
    print("   %-21s %9s %9s %9s %8s %8s %9s %7s"
          % ("cellule", "poolee", "pire j", "queue", "reussite", "declen.",
             "ecart/j", "t"))
    for nom, *_ in CELLULES:
        r = res[nom]
        e = [x - y for x, y in zip(r["moy"], A["moy"])]
        m = st.fmean(e)
        s = st.stdev(e) if len(e) > 1 else 0.0
        t = m / (s / math.sqrt(len(e))) if s else 0.0
        print("   %-21s %+9.4f %+9.3f %+9.2f %7.1f %% %7.1f %% %+9.4f %+7.2f"
              % (nom, r["pool"], r["pire"], r["queue"], r["reussite"],
                 r["decl"], m, t))
    return res


def main() -> int:
    ts, bid, ask = charger()
    jours = [dt.datetime.fromtimestamp(t, dt.timezone.utc).date() for t in ts]
    entrees, dernier = [], -1e18
    for i in range(1, len(ts) - 1):
        if ts[i] - dernier < REPOS_SEC:
            continue
        entrees.append((i, len(entrees) % 2 == 0))
        dernier = ts[i]
    print("%d ticks, %d jours, %d positions FIXES\n"
          % (len(ts), len(set(jours)), len(entrees)))

    tj = sorted(set(jours[i] for i, _ in entrees))
    moitie = len(tj) // 2
    dedans = set(tj[:moitie])
    dehors = set(tj[moitie:])
    ent_in = [(i, a) for i, a in entrees if jours[i] in dedans]
    ent_out = [(i, a) for i, a in entrees if jours[i] in dehors]

    # ── CALIBRATION de V sur la PREMIERE MOITIE seulement ──────────────
    print("=" * 80)
    print("CALIBRATION de V — sur la premiere moitie SEULEMENT")
    print("=" * 80)
    vs = []
    for i, achat in ent_in:
        _p, vm, _d = rejouer(ts, bid, ask, i, achat, 60.0, 30.0, 60.0,
                             False, False, None)
        vs.append(vm)
    vs.sort()
    seuil_v = vs[int(0.90 * len(vs))]      # les 10 % de descentes les + rapides
    print("   chute de P&L sur 30 s : mediane %.3f   p90 %.3f   p99 %.3f EUR"
          % (st.median(vs), vs[int(0.90 * len(vs))], vs[int(0.99 * len(vs))]))
    print("   => V = %.3f EUR / 30 s  (les 10 %% les plus rapides)" % seuil_v)
    print("   echantillon %s -> %s   hors %s -> %s"
          % (tj[0], tj[moitie - 1], tj[moitie], tj[-1]))
    print()

    r_in = tableau(ts, bid, ask, ent_in, jours, seuil_v,
                   "DANS L ECHANTILLON (V calibre ici)")
    print()
    r_out = tableau(ts, bid, ask, ent_out, jours, seuil_v,
                    "HORS ECHANTILLON (meme V)")

    # ── LE CRITERE A QUATRE CONDITIONS ─────────────────────────────────
    print()
    print("=" * 80)
    print("LE CRITERE — les QUATRE conditions, posees d'avance")
    print("=" * 80)
    A_in, A_out = r_in["A production"], r_out["A production"]

    def ec(res, A, nom):
        e = [x - y for x, y in zip(res[nom]["moy"], A["moy"])]
        m = st.fmean(e)
        s = st.stdev(e) if len(e) > 1 else 0.0
        return m, (m / (s / math.sqrt(len(e))) if s else 0.0)

    for nom, *_ in CELLULES:
        if nom.startswith("A "):
            continue
        m1, t1 = ec(r_in, A_in, nom)
        m2, t2 = ec(r_out, A_out, nom)
        c1 = t1 > 2.0
        c2 = r_in[nom]["queue"] > A_in["queue"]
        c3 = (m1 > 0) == (m2 > 0)
        c4 = m2 > 0
        print("   %-21s 1) t>+2 %-6s 2) queue %-6s 3) signe %-6s 4) dehors>0 %-6s"
              "  => %s" % (nom, c1, c2, c3, c4,
                           "RETENU" if (c1 and c2 and c3 and c4) else "rejete"))
    print()
    print("=" * 80)
    print("LA QUEUE — ce que << perdre le moins possible >> veut dire")
    print("=" * 80)
    print("   %-21s %12s %12s %10s" % ("cellule", "queue dedans",
                                       "queue dehors", "gain %"))
    for nom, *_ in CELLULES:
        g_in = 100.0 * (r_in[nom]["queue"] - A_in["queue"]) / abs(A_in["queue"])
        g_out = 100.0 * (r_out[nom]["queue"] - A_out["queue"]) / abs(A_out["queue"])
        print("   %-21s %+12.2f %+12.2f   %+5.1f / %+5.1f"
              % (nom, r_in[nom]["queue"], r_out[nom]["queue"], g_in, g_out))
    print()
    print("   🔑 PREDICTION n°3, celle qui decide : si `D TEMOIN cadence 15`")
    print("      affine la queue autant que `B vitesse`, alors la VITESSE")
    print("      n'apporte RIEN et seul le DELAI comptait.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
