#!/usr/bin/env python3
"""Risque /2 apres une perte — REPLICATION sur 14 paires, pre-inscrit `ff61d9a`.

    docker exec scalping-radar python /tmp/banc_risque_replication.py

⛔ LA DECLARATION EST POSEE AVANT CE FICHIER (`ff61d9a`). La population, les
exclusions et leurs raisons, les trois bras, la double lecture, les trois
predictions et la regle de rejet y sont ecrits.

## Pourquoi une replication et pas une nouvelle decoupe

L'hypothese a ete formee sur `XAU/USD` (banc `7443d16` : `B-A` positif, `B-C`
contient zero — indecidable). Elle est testee ici sur **14 paires qui n'ont
jamais servi a la former**. L'or est donc EXCLU, et c'est volontaire.

## ⚠️ La correlation entre paires impose DEUX lectures

`EUR/USD`, `GBP/USD`, `EUR/GBP`, `USD/CHF` bougent ensemble. Reechantillonner
par TRADE les traite comme independants et gonflerait la precision.

    1. par trade  2 000 tirages de trades          -> optimiste
    2. par PAIRE  2 000 tirages des 14 paires      -> 14 unites, DECIDE

## ⛔ « Le trade precedent » se lit PAR PAIRE

Chronologiquement, et jamais a travers les paires : une perte sur l'argent ne
dit rien du prochain trade sur l'euro. Melanger fabriquerait une sequence qui
n'existe pas.
"""
from __future__ import annotations

import random
import sqlite3
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/app")
sys.path.insert(0, "/tmp")

import banc_risque_apres_perte as bq        # noqa: E402 — memes fonctions pures
from backend.services import laboratoire_or as labo   # noqa: E402

ARCHIVE = "/app/data/candles_5min.db"
DEBUT, FIN = "2023-08-01", "2026-08-09"
SPREADS_REL = (0.0001, 0.00025)   # 0,20 $ et 0,50 $ de l'or, en FRACTION du prix
GRAINE = 20261008
TIRAGES = 2000

# Population declaree. L'or est exclu : il a FORME l'hypothese.
PAIRES = ("XAG/USD", "EUR/USD", "GBP/USD", "USD/JPY", "EUR/GBP", "USD/CHF",
          "AUD/USD", "USD/CAD", "EUR/JPY", "GBP/JPY",
          "LTC/USD", "BCH/USD", "DOT/USD", "ADA/USD")


def bougies(paire: str) -> list[dict]:
    with sqlite3.connect(f"file:{Path(ARCHIVE)}?mode=ro", uri=True) as c:
        lignes = c.execute(
            "SELECT ts, open, high, low, close FROM candles "
            "WHERE pair = ? AND ts >= ? AND ts < ? ORDER BY ts",
            (paire, DEBUT, FIN)).fetchall()
    return [{"t": datetime.fromisoformat(str(t)).replace(tzinfo=timezone.utc),
             "o": o, "h": h, "l": lo, "c": cl, "v": 0}
            for t, o, h, lo, cl in lignes]


# ⚠️ La detection coute ~190 s par paire sur 240 000 bougies. Elle ne depend
# PAS du spread : la calculer par spread doublait le temps du banc pour un
# resultat identique. On la garde donc en memoire, par paire.
_CACHE: dict[str, tuple] = {}


def _bougies_et_releve(paire: str):
    if paire not in _CACHE:
        bgs = bougies(paire)
        if len(bgs) < labo.FENETRE + 500:
            _CACHE[paire] = (None, None, None)
        else:
            _CACHE[paire] = (bgs, labo.detections(bgs),
                             statistics.median(float(b["c"]) for b in bgs))
    return _CACHE[paire]


def rs_de_la_paire(paire: str, spread_rel: float) -> list[float]:
    """Les R de cette paire, dans l'ORDRE du temps.

    ⚠️ Le spread est donne en FRACTION du prix et non en dollars : 0,20 $ sur
    l'or a 4 100 ne veut rien dire sur l'euro a 1,08. On le convertit au prix
    median de la paire, sinon on comparerait des couts incomparables.
    """
    bgs, releve, prix_med = _bougies_et_releve(paire)
    if bgs is None:
        return []
    spread = prix_med * spread_rel
    ent = bq.banc._entrees(bgs, releve, spread)
    return [bq.banc._issue(bgs, i, e, r, o, s, spread / r)[0]
            for i, e, r, o, s, _srt in ent]


def _lecture(par_paire: dict[str, list[float]], spread_rel: float) -> dict:
    """Les trois bras, les deux lectures, et le detail par paire."""
    # Poids calcules PAR PAIRE, sur la sequence reelle de chacune.
    etiquettes: list[tuple[str, float, float, float, float]] = []
    detail = {}
    alea = random.Random(GRAINE)
    for paire, rs in par_paire.items():
        if len(rs) < 30:
            continue
        issues = [r > 0 for r in rs]
        wB = bq.poids_regle(issues)
        combien = sum(1 for w in wB if w == bq.FACTEUR)
        wC = bq.poids_placebo(len(rs), combien, alea)
        for k, r in enumerate(rs):
            etiquettes.append((paire, r, 1.0, wB[k], wC[k]))
        a = bq.rendement([1.0] * len(rs), rs)
        b = bq.rendement(wB, rs)
        c = bq.rendement(wC, rs)
        detail[paire] = {"n": len(rs), "A": a, "B": b, "C": c,
                         "BA": b - a, "BC": b - c}

    def m(idx, col):
        poids = [etiquettes[i][col] for i in idx]
        rs = [etiquettes[i][1] for i in idx]
        return bq.rendement(poids, rs)

    tous = list(range(len(etiquettes)))
    mA, mB, mC = m(tous, 2), m(tous, 3), m(tous, 4)

    # ── Lecture 1 : par TRADE ────────────────────────────────────────────
    t1 = random.Random(GRAINE)
    n = len(etiquettes)
    dBA1, dBC1 = [], []
    for _ in range(TIRAGES):
        idx = [t1.randrange(n) for _ in range(n)]
        a, b, c = m(idx, 2), m(idx, 3), m(idx, 4)
        if None in (a, b, c):
            continue
        dBA1.append(b - a)
        dBC1.append(b - c)

    # ── Lecture 2 : par PAIRE — c'est elle qui decide ───────────────────
    par_index: dict[str, list[int]] = {}
    for i, (paire, *_r) in enumerate(etiquettes):
        par_index.setdefault(paire, []).append(i)
    noms = sorted(par_index)
    t2 = random.Random(GRAINE)
    dBA2, dBC2 = [], []
    for _ in range(TIRAGES):
        choisies = [noms[t2.randrange(len(noms))] for _ in range(len(noms))]
        idx = [i for p in choisies for i in par_index[p]]
        a, b, c = m(idx, 2), m(idx, 3), m(idx, 4)
        if None in (a, b, c):
            continue
        dBA2.append(b - a)
        dBC2.append(b - c)

    return {"n": n, "paires": len(noms), "A": mA, "B": mB, "C": mC,
            "trade": {"BA": bq.intervalle(dBA1), "BC": bq.intervalle(dBC1)},
            "paire": {"BA": bq.intervalle(dBA2), "BC": bq.intervalle(dBC2)},
            "detail": detail}


def main() -> int:
    print(f"=== REPLICATION du risque /2 — {len(PAIRES)} paires, "
          f"{DEBUT} -> {FIN} ===")
    print("⛔ XAU/USD EXCLU : il a FORME l hypothese.\n")

    for spread_rel in SPREADS_REL:
        print(f"--- spread {spread_rel * 100:.3f} % du prix "
              f"(~{spread_rel * 4100:.2f} $ sur l or) ---")
        par_paire = {}
        for paire in PAIRES:
            rs = rs_de_la_paire(paire, spread_rel)
            if rs:
                par_paire[paire] = rs
                print(f"  {paire:9s} {len(rs):5d} entrees")
            else:
                print(f"  {paire:9s} ecartee (trop peu de bougies)")
        if len(par_paire) < 5:
            print("  pas assez de paires")
            continue

        m = _lecture(par_paire, spread_rel)
        print(f"\n  {m['n']} entrees sur {m['paires']} paires")
        print(f"  rendement par unite de risque DEPLOYEE")
        print(f"    A {m['A']:+.5f}   B {m['B']:+.5f}   C {m['C']:+.5f}")
        for cle, nom in (("trade", "par TRADE (optimiste)"),
                         ("paire", "par PAIRE (DECIDE)")):
            print(f"  lecture {nom}")
            for k, lib in (("BA", "B-A"), ("BC", "B-C")):
                moy, bas, haut = m[cle][k]
                v = ("POSITIF" if bas > 0 else
                     "NEGATIF" if haut < 0 else "indecidable (0 dedans)")
                print(f"    {lib} {moy:+.5f}  95 %% [{bas:+.5f} ; {haut:+.5f}]"
                      .replace("%%", "%") + f"  -> {v}")
        pos = sum(1 for d in m["detail"].values() if d["BC"] > 0)
        print(f"  P3 : B-C positif sur {pos} des {len(m['detail'])} paires "
              f"(exige >= 8)")
        print("  detail par paire :")
        for p, d in sorted(m["detail"].items(), key=lambda kv: -kv[1]["BC"]):
            print(f"    {p:9s} n={d['n']:5d}  A {d['A']:+.4f}  B {d['B']:+.4f}"
                  f"  C {d['C']:+.4f}  B-C {d['BC']:+.4f}")
        print()

    print("Regle : P1 et P2 en lecture PAR PAIRE, et P3 >= 8 paires, aux DEUX")
    print("spreads. Si B <= C, rejet — on n a mesure qu engager moins.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
