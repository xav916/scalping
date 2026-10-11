#!/usr/bin/env python3
"""Les motifs detectes EN LIVE sur les ticks, contre la detection a la CLOTURE.

Pre-inscrit dans docs/predictions/2026-10-11_detection_live_sur_les_ticks.md
AVANT d'ecrire ce fichier. Decision de Xavier, prise contre ma mesure.

🔑 Ce banc ne change NI les motifs NI les donnees. Il change **le moment ou on
regarde** : les bougies M5 sont reconstruites depuis les ticks, la derniere est
PARTIELLE, et on appelle la **vraie** fonction de production `detect_patterns`.

Trois facons de regarder :
    CLOSE          le motif n'est pris qu'a la cloture de la bougie M5 (la prod)
    LIVE BRUT      des qu'il apparait, sur la bougie en cours
    LIVE CONFIRME  il doit tenir 30 secondes avant qu'on entre
"""
from __future__ import annotations

import collections
import datetime as dt
import math
import os
import sqlite3
import statistics as st
import sys

sys.path.insert(0, "/app")

from backend.models.schemas import Candle  # noqa: E402
from backend.services.pattern_detector import (  # noqa: E402
    _est_un_achat, detect_patterns)

MAGASIN = os.getenv("TICKS", "/app/data/ticks_courtier.db")
EUR_USD = 1.1198
PAS_M5 = 300                 # secondes par bougie
N_BOUGIES = 50               # le CANDLE_COUNT de la production
CADENCE_SEC = 5              # la cadence reelle du cycle de production
CONFIRME_SEC = 30            # le live CONFIRME exige cette persistance
REPOS_SEC = 300              # pas deux entrees du meme motif en 5 min
SL_DEPART = 13.0
TRAINAGE = 0.5
DECLENCHE = 0.5
PLANCHER = 2.0
MARGE_FRANCHIE = 0.10
PROT_AGE_SEC = 60
PROT_NEG_SEC = 30
CAP_SEC = 14400
GEOMETRIES = (("production", None), ("symetrique", 2.0))
MIN_N = 100


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


def bougies_depuis_ticks(ts, mid, i, fin_exclue=False):
    """Les N_BOUGIES dernieres bougies M5 vues depuis le tick `i`.

    🔑 La derniere est PARTIELLE : de sa frontiere de 5 min jusqu'au tick `i`.
    Avec `fin_exclue`, on la retire — c'est la vue de la production, qui
    n'attend que des bougies CLOSES.
    """
    t_fin = ts[i]
    base = int(t_fin // PAS_M5) * PAS_M5
    debut = base - (N_BOUGIES - 1) * PAS_M5
    # recule jusqu'au premier tick de la fenetre
    j = i
    while j > 0 and ts[j] >= debut:
        j -= 1
    seaux = {}
    for k in range(j, i + 1):
        b = int(ts[k] // PAS_M5) * PAS_M5
        if b < debut:
            continue
        s = seaux.get(b)
        p = mid[k]
        if s is None:
            seaux[b] = [p, p, p, p]
        else:
            if p > s[1]:
                s[1] = p
            if p < s[2]:
                s[2] = p
            s[3] = p
    bornes = sorted(seaux)
    if fin_exclue and bornes and bornes[-1] == base:
        bornes = bornes[:-1]
    out = []
    for b in bornes:
        o, h, l, c = seaux[b]
        out.append(Candle(
            timestamp=dt.datetime.fromtimestamp(b, dt.timezone.utc),
            open=o, high=h, low=l, close=c, volume=0))
    return out


def rejouer(ts, bid, ask, i, achat, borne):
    k = 1.0 / EUR_USD
    entree = ask[i] if achat else bid[i]
    t0 = ts[i]
    stop = -SL_DEPART if borne is None else -borne
    tp = 1e9 if borne is None else borne
    neg = None
    vu = vu_prot = -1e18
    n = len(ts)
    j = i + 1
    while j < n and ts[j] - t0 <= CAP_SEC:
        sortie = bid[j] if achat else ask[j]
        pnl = (sortie - entree) * k if achat else (entree - sortie) * k
        if pnl <= stop + 1e-12:
            return stop
        if pnl >= tp - 1e-12:
            return tp
        if borne is None:
            if ts[j] - vu >= 1:
                vu = ts[j]
                if pnl >= DECLENCHE - 1e-9:
                    c = pnl - TRAINAGE
                    if c > stop and c < pnl:
                        stop = c
            neg = ts[j] if (pnl < 0 and neg is None) else (
                None if pnl >= 0 else neg)
            if ts[j] - vu_prot >= 60:
                vu_prot = ts[j]
                perte = -pnl
                if (ts[j] - t0 >= PROT_AGE_SEC and perte > 0 and neg is not None
                        and ts[j] - neg >= PROT_NEG_SEC):
                    d = -stop
                    pl = max(PLANCHER, perte + MARGE_FRANCHIE)
                    if d > pl:
                        v = max((d + perte) / 2.0, pl)
                        if v < d:
                            stop = -v
        j += 1
    fin = min(j, n - 1)
    sortie = bid[fin] if achat else ask[fin]
    return (sortie - entree) * k if achat else (entree - sortie) * k


def main():
    ts, bid, ask = charger()
    mid = [(bid[i] + ask[i]) / 2.0 for i in range(len(ts))]
    jour = [dt.datetime.fromtimestamp(t, dt.timezone.utc).date() for t in ts]
    print("%d ticks   %d jours" % (len(ts), len(set(jour))))

    # --- les instants d'evaluation, toutes les CADENCE_SEC ---
    instants = []
    prochain = ts[0] + N_BOUGIES * PAS_M5     # il faut l'histoire complete
    for i, t in enumerate(ts):
        if t >= prochain:
            instants.append(i)
            prochain = t + CADENCE_SEC
    print("instants d'evaluation : %d (toutes les %d s)"
          % (len(instants), CADENCE_SEC))

    # --- detection, trois facons de regarder ---
    vues = {"CLOSE": [], "LIVE BRUT": [], "LIVE CONFIRME": []}
    repos = {"CLOSE": {}, "LIVE BRUT": {}, "LIVE CONFIRME": {}}
    vu_depuis = {}            # motif -> instant de premiere apparition en live
    derniere_cloture = None
    for compte, i in enumerate(instants):
        base = int(ts[i] // PAS_M5) * PAS_M5
        # ---- CLOSE : une seule evaluation par bougie close ----
        if base != derniere_cloture:
            derniere_cloture = base
            cs = bougies_depuis_ticks(ts, mid, i, fin_exclue=True)
            if len(cs) >= 20:
                for p in detect_patterns(cs):
                    nom = p.pattern.value
                    if ts[i] - repos["CLOSE"].get(nom, -1e18) >= REPOS_SEC:
                        repos["CLOSE"][nom] = ts[i]
                        vues["CLOSE"].append((i, _est_un_achat(p.pattern), nom))
        # ---- LIVE : sur la bougie EN COURS ----
        cs = bougies_depuis_ticks(ts, mid, i, fin_exclue=False)
        if len(cs) >= 20:
            presents = set()
            for p in detect_patterns(cs):
                nom = p.pattern.value
                presents.add(nom)
                if ts[i] - repos["LIVE BRUT"].get(nom, -1e18) >= REPOS_SEC:
                    repos["LIVE BRUT"][nom] = ts[i]
                    vues["LIVE BRUT"].append(
                        (i, _est_un_achat(p.pattern), nom))
                # ---- LIVE CONFIRME : il doit TENIR ----
                if nom not in vu_depuis:
                    vu_depuis[nom] = (ts[i], _est_un_achat(p.pattern))
                elif ts[i] - vu_depuis[nom][0] >= CONFIRME_SEC:
                    if ts[i] - repos["LIVE CONFIRME"].get(nom, -1e18) >= REPOS_SEC:
                        repos["LIVE CONFIRME"][nom] = ts[i]
                        vues["LIVE CONFIRME"].append(
                            (i, vu_depuis[nom][1], nom))
            # 🔑 un motif absent a cet instant a DISPARU : le repeignage
            for nom in list(vu_depuis):
                if nom not in presents:
                    del vu_depuis[nom]
        if (compte + 1) % 20000 == 0:
            print("   %d/%d instants..." % (compte + 1, len(instants)),
                  flush=True)

    print("\ndetections :")
    for nom, v in vues.items():
        print("   %-15s %6d entrees, %d motifs distincts"
              % (nom, len(v), len({x[2] for x in v})))

    print("\n%-16s%-13s%8s%11s%11s%10s%8s%7s"
          % ("vue", " geometrie", "n", "bon sens", "mauvais", "ecart", "t",
             "jours"))
    res = {}
    for vue, entrees in vues.items():
        for gnom, borne in GEOMETRIES:
            bon = collections.defaultdict(list)
            mauvais = collections.defaultdict(list)
            for (i, achat, _nom) in entrees:
                bon[jour[i]].append(rejouer(ts, bid, ask, i, achat, borne))
                mauvais[jour[i]].append(
                    rejouer(ts, bid, ask, i, not achat, borne))
            communs = sorted(set(bon) & set(mauvais))
            if len(communs) < 3:
                continue
            ec = [st.fmean(bon[d]) - st.fmean(mauvais[d]) for d in communs]
            m = st.fmean(ec)
            s = st.stdev(ec)
            t = m / (s / math.sqrt(len(ec))) if s else 0.0
            moitie = len(communs) // 2
            res[(vue, gnom)] = {
                "n": len(entrees), "ecart": m, "t": t, "jours": len(ec),
                "bon": st.fmean([x for d in communs for x in bon[d]]),
                "mauvais": st.fmean([x for d in communs for x in mauvais[d]]),
                "d1": st.fmean(ec[:moitie]), "d2": st.fmean(ec[moitie:]),
            }
            c = res[(vue, gnom)]
            print("%-16s%-13s%8d%+11.4f%+11.4f%+10.4f%+8.2f%7d"
                  % (vue, " " + gnom, c["n"], c["bon"], c["mauvais"],
                     c["ecart"], c["t"], c["jours"]))

    print("\n=== LE CRITERE : le LIVE bat-il la detection CLOSE ? ===")
    retenues = 0
    for gnom, _b in GEOMETRIES:
        ref = res.get(("CLOSE", gnom))
        if not ref:
            continue
        for vue in ("LIVE BRUT", "LIVE CONFIRME"):
            c = res.get((vue, gnom))
            if not c:
                continue
            mieux = c["ecart"] > ref["ecart"]
            ok = (mieux and abs(c["t"]) > 2.5 and c["n"] >= MIN_N
                  and (c["d1"] > 0) == (c["d2"] > 0))
            print("   %-15s %-12s ecart %+.4f contre %+.4f (close)  t %+.2f  "
                  "⇒ %s" % (vue, gnom, c["ecart"], ref["ecart"], c["t"],
                            "RETENU" if ok else "rejete"))
            retenues += int(ok)
    print("\n⇒ %d vue(s) retenue(s)" % retenues)
    return 0


if __name__ == "__main__":
    sys.exit(main())
