#!/usr/bin/env python3
"""TP +2 EUR / SL -12 EUR : le stop est-il « rarement atteint » ?

Question de Xavier le 2026-10-08 : « un take profit a 2 euros et un stop loss a
moins 12 euros, est-ce qu'on ne serait pas gagnant, sachant que le stop a
moins 12 est tres rarement atteint ? »

## 🔑 POURQUOI CETTE MESURE ET PAS LA PRECEDENTE

La mesure `7e0c833` se servait de `mfe_pct` : elle savait si le prix EST PASSE
par l'objectif, pas s'il y est passe AVANT le stop. Or c'est exactement la
question ici.

⛔ Ce banc utilise `laboratoire_or._issue`, qui teste le stop AVANT l'objectif
dans chaque bougie — « dans une bougie qui contient les deux, on ne sait pas
lequel est venu en premier, et supposer l'objectif fabriquerait une
performance ». L'ordre est donc respecte, et le resultat n'est plus optimiste.

## La configuration de Xavier, en R

Son stop de 12 EUR vaut ~13,5 $ sur l'or, soit ~0,33 % du prix — pratiquement
le stop en place (14,41 $ = 0,35 %). Son TP de 2 EUR vaut donc :

    2 / 12 = 0,167 R

On balaye autour, pour que le verdict ne tienne pas a une seule valeur.

## ⚠️ Fenetre reduite, et c'est dit

Une paire entiere sur trois ans depasse 1 Go de detections et s'est fait tuer
par le cgroup. On mesure donc UN AN d'or, declare ici : c'est moins de trades,
mais l'ordre est exact — et un chiffre exact sur un an vaut mieux qu'un chiffre
optimiste sur trois.
"""
from __future__ import annotations

import sqlite3
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/app")
sys.path.insert(0, "/bancs")

from backend.services import laboratoire_or as labo   # noqa: E402

ARCHIVE = "/app/data/candles_5min.db"
PAIRE = "XAU/USD"
DEBUT, FIN = "2025-08-09", "2026-08-09"      # un an, declare

# En R. 0,167 = les 2 EUR de Xavier sur son stop de 12 EUR.
OBJECTIFS = (0.10, 0.167, 0.25, 0.50, 1.00, 1.80)
SPREADS = (0.20, 0.50)                        # en dollars sur l'or


def bougies() -> list[dict]:
    with sqlite3.connect(f"file:{Path(ARCHIVE)}?mode=ro", uri=True) as c:
        lignes = c.execute(
            "SELECT ts, open, high, low, close FROM candles "
            "WHERE pair = ? AND ts >= ? AND ts < ? ORDER BY ts",
            (PAIRE, DEBUT, FIN)).fetchall()
    return [{"t": datetime.fromisoformat(str(t)).replace(tzinfo=timezone.utc),
             "o": o, "h": h, "l": lo, "c": cl, "v": 0}
            for t, o, h, lo, cl in lignes]


def main() -> int:
    bgs = bougies()
    print("=== TP COURT / STOP LARGE — l'ordre est RESPECTE ===")
    print(f"    {PAIRE}, {DEBUT} -> {FIN}, {len(bgs)} bougies de 5 min")
    print("    `_issue` teste le STOP AVANT l'objectif dans chaque bougie\n")
    releve = labo.detections(bgs)
    print(f"    {sum(len(v) for v in releve.values())} setups detectes\n")

    for spread in SPREADS:
        # Les entrees sont celles du bras de reference, une fois pour toutes.
        ent = []
        i, n = labo.FENETRE, len(bgs)
        while i < n:
            cands = list(releve.get(i, ()))
            if not cands:
                i += 1
                continue
            s = cands[0]
            e = float(s.entry_price)
            r = abs(e - float(s.stop_loss))
            if r <= 0 or e <= 0 or r / e < labo.PLACEBO_PCT:
                i += 1
                continue
            signe = 1 if labo._sens(s) == "buy" else -1
            _R, sortie = labo._issue(bgs, i, e, r, 1.8, signe, spread / r,
                                     politique=labo.POLITIQUES_SORTIE[0])
            ent.append((i, e, r, signe))
            i = sortie + 1

        print(f"  --- spread {spread:.2f} $ — {len(ent)} entrees ---")
        print(f"  {'objectif':>9s} {'% au TP':>9s} {'% au STOP':>10s} "
              f"{'R moyen':>9s} {'EUR/trade':>10s} {'requis':>8s}")
        for obj in OBJECTIFS:
            rs, au_tp = [], 0
            for i, e, r, signe in ent:
                R, _s = labo._issue(bgs, i, e, r, obj, signe, spread / r,
                                    politique=labo.POLITIQUES_SORTIE[0])
                rs.append(R)
                if R > 0:
                    au_tp += 1
            moy = statistics.fmean(rs)
            pct_tp = au_tp * 100 / len(rs)
            # 12 EUR de risque : un R vaut 12 EUR
            eur = moy * 12.0
            requis = 100 / (1 + obj)
            marque = "  <- Xavier" if abs(obj - 0.167) < 1e-9 else ""
            print(f"  {obj:9.3f} {pct_tp:8.1f} % {100 - pct_tp:9.1f} % "
                  f"{moy:+9.4f} {eur:+10.2f} {requis:7.1f} %{marque}")
        print()

    print("  🔑 « % au STOP » repond directement a la question : le stop de")
    print("     12 EUR est-il rarement atteint quand le TP est a 2 EUR ?")
    print("  🔑 « EUR/trade » suppose 12 EUR de risque par trade, donc 1 R = 12 EUR.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
