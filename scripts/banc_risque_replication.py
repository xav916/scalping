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
# ⚠️ ECART TROUVE LE 2026-10-08, PENDANT le premier passage. La declaration
# `ff61d9a` dit « 0,20 et 0,50 $ ». J'avais pose 0,0001 et 0,00025, qui valent
# 0,41 $ et 1,02 $ sur l'or a 4 100 — soit DEUX FOIS plus que declare.
#
# 🔑 L'ecart est CONSERVATEUR : un spread plus large degrade tous les bras, il
# ne peut pas fabriquer un resultat positif. Et il est a peu pres NEUTRE sur la
# comparaison B-C, qui est ce qui decide : le cout frappe les trois bras.
#
# Corrige ici pour qu'un rejeu colle a la declaration. Le premier passage est
# rapporte avec son ecart dit, pas efface.
_OR_REF = 4100.0            # prix de reference de l'or, pour la conversion
SPREADS_REL = (0.20 / _OR_REF, 0.50 / _OR_REF)
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


# ⛔ CE CACHE A FAIT TOMBER LA PRODUCTION — 2026-10-08, 56 MINUTES.
#
# J'avais mis les detections en cache PAR PAIRE pour ne pas les recalculer a
# chaque spread. L'intention etait bonne, l'effet desastreux : le cache gardait
# en memoire, SIMULTANEMENT pour les 14 paires, ~240 000 bougies ET le relevé de
# detections (314 769 setups pour le seul XAU). La machine a 3 839 Mo.
#
# Mesure : de 08:58:53 a 09:54:48 UTC, le radar n'a evalue AUCUN signal. Ni SSH
# ni l'API publique ne repondaient. Il a fallu un `aws ec2 reboot-instances`,
# decide par Xavier, pour reprendre la main.
#
# 🔑 L'optimisation que j'avais ajoutee POUR ALLER PLUS VITE est ce qui a coute
# 56 minutes de marche. Une paire a la fois, memoire plate : on recalcule la
# detection une fois par paire et on s'en sert pour LES DEUX spreads dans la
# meme passe, puis on libere.
def rs_de_la_paire_tous_spreads(paire: str,
                                spreads: tuple) -> dict[float, list[float]]:
    """Les R de cette paire pour CHAQUE spread, en UNE passe de detection.

    ⛔ Rien n'est garde entre deux paires : c'est ce qui borne la memoire.

    ⚠️ Le spread est donne en FRACTION du prix et non en dollars : 0,20 $ sur
    l'or a 4 100 ne veut rien dire sur l'euro a 1,08. On le convertit au prix
    median de la paire, sinon on comparerait des couts incomparables.
    """
    bgs = bougies(paire)
    if len(bgs) < labo.FENETRE + 500:
        return {}
    prix_med = statistics.median(float(b["c"]) for b in bgs)
    releve = labo.detections(bgs)
    out = {}
    for sr in spreads:
        spread = prix_med * sr
        ent = bq.banc._entrees(bgs, releve, spread)
        out[sr] = [bq.banc._issue(bgs, i, e, r, o, s, spread / r)[0]
                   for i, e, r, o, s, _srt in ent]
    del bgs, releve          # explicite : la paire suivante ne doit rien herite
    return out


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

    # ⛔ UNE SEULE boucle sur les paires, les deux spreads a l'interieur : c'est
    # ce qui garde la memoire plate. Voir le bloc au-dessus de
    # `rs_de_la_paire_tous_spreads` — l'inverse a coute 56 min de production.
    par_spread: dict[float, dict[str, list[float]]] = {s: {} for s in SPREADS_REL}
    for paire in PAIRES:
        res = rs_de_la_paire_tous_spreads(paire, SPREADS_REL)
        if not res:
            print(f"  {paire:9s} ecartee (trop peu de bougies)")
            continue
        for sr, rs in res.items():
            if rs:
                par_spread[sr][paire] = rs
        n0 = len(res[SPREADS_REL[0]])
        print(f"  {paire:9s} {n0:5d} entrees")

    for spread_rel in SPREADS_REL:
        print("")
        print(f"--- spread {spread_rel * 100:.3f} % du prix "
              f"(~{spread_rel * 4100:.2f} $ sur l or) ---")
        par_paire = par_spread[spread_rel]
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
