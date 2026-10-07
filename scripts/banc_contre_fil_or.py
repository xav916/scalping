#!/usr/bin/env python3
"""Le CONTRE-FIL sur un trade colle au stop — banc pre-inscrit `3302fa5`.

    docker exec scalping-radar python /tmp/banc_contre_fil_or.py echantillon
    docker exec scalping-radar python /tmp/banc_contre_fil_or.py hors

Xavier, 2026-10-08 : « si un trade ouvert est depuis longtemps du cote du SL
sans l avoir atteint, alors ouvrir un trade dans le sens inverse ».

⛔ LA DECLARATION EST POSEE AVANT CE FICHIER (`3302fa5`, rectifiee `b33c4cf`).
Le declencheur, les 12 cellules, les quatre bras, les quatre predictions et la
regle de decision y sont ecrits. Ce script ne fait que les executer.

## Les quatre bras

    A  reference    rien, le trade court jusqu a son SL ou son TP
    B  contre-fil   ouvre l inverse au declenchement, meme risque
    C  fermer       ferme le premier au prix du declenchement
    D  placebo      contre-fil a un instant TIRE AU HASARD dans le meme trade

🔑 C EST LE BRAS QUI DECIDE : si fermer fait aussi bien, l idee est dominee par
quelque chose de plus simple et moins cher.

🔑 D est APPARIE : meme trade, meme nombre de contre-fils, instant tire dans la
vie du trade. Il separe « colle au stop » du simple fait d avoir deux jambes
opposees sur un instrument qui oscille.

## ⛔ L INVARIANT repris du laboratoire

Les entrees sont determinees UNE fois, par le bras A, puis les quatre bras sont
evalues sur EXACTEMENT les memes entrees. Le rejeu du labo est sequentiel
(`i = sortie + 1`) : un bras qui sort plus tot decalerait les entrees suivantes
et on comparerait deux populations differentes.

## ⛔ Et les R sont gardes UN PAR UN

Reconstituer les differences a partir des moyennes rendrait la variance
intra-bloc nulle et le `t` serait FABRIQUE. C est une erreur deja payee ici.
"""
from __future__ import annotations

import random
import sqlite3
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/app")

from backend.services import laboratoire_or as labo   # noqa: E402

PAIRE = "XAU/USD"
ARCHIVE = "/app/data/candles_5min.db"
MINUTES_PAR_BOUGIE = 5

# ─── Les 12 cellules, telles que declarees ────────────────────────────────
THETAS = (0.3, 0.5, 0.7)
DUREES = (30, 60, 120, 240)          # minutes
SPREADS = (0.20, 0.50)               # le verdict est exige aux DEUX

# Fenetres declarees AVANT la mesure.
FENETRES = {
    "echantillon": ("2023-08-01", "2026-01-01"),
    "hors":        ("2026-01-01", "2026-08-09"),
}

GRAINE = 20261008          # le placebo doit etre rejouable a l identique


def bougies(debut: str, fin: str) -> list[dict]:
    """Les bougies figees de l archive, au format du laboratoire.

    ⚠️ L archive porte des horodatages NAIFS ; les detecteurs comparent a des
    datetimes AWARE. Sans ce `tzinfo`, `_detect_opening_range` leve.
    """
    with sqlite3.connect(f"file:{Path(ARCHIVE)}?mode=ro", uri=True) as c:
        lignes = c.execute(
            "SELECT ts, open, high, low, close FROM candles "
            "WHERE pair = ? AND ts >= ? AND ts < ? ORDER BY ts",
            (PAIRE, debut, fin)).fetchall()
    # SELECT ts, open, high, low, close -> t, o, h, lo, cl, dans CET ordre.
    return [{"t": datetime.fromisoformat(str(t)).replace(tzinfo=timezone.utc),
             "o": o, "h": h, "l": lo, "c": cl, "v": 0}
            for t, o, h, lo, cl in lignes]


def _entrees(bgs, releve, spread: float) -> list[tuple]:
    """Les entrees du bras A, tous motifs et tous sens confondus.

    ⛔ Sequentiel, comme le laboratoire : `i = sortie + 1`. C est ce qui fixe
    la population une fois pour toutes.
    """
    out = []
    i, n = labo.FENETRE, len(bgs)
    while i < n:
        cands = list(releve.get(i, ()))
        if not cands:
            i += 1
            continue
        s = cands[0]
        entree = float(s.entry_price)
        risque = abs(entree - float(s.stop_loss))
        if risque <= 0 or entree <= 0 or risque / entree < labo.PLACEBO_PCT:
            i += 1
            continue
        objectif_r = abs(float(s.take_profit_1) - entree) / risque
        if objectif_r <= 0:
            i += 1
            continue
        signe = 1 if labo._sens(s) == "buy" else -1
        _, sortie = _issue(bgs, i, entree, risque, objectif_r, signe,
                           spread / risque)
        out.append((i, entree, risque, objectif_r, signe, sortie))
        i = sortie + 1
    return out


def _issue(bgs, depart, entree, risque, objectif_r, signe, cout):
    return labo._issue(bgs, depart, entree, risque, objectif_r, signe, cout,
                       politique=labo.POLITIQUES_SORTIE[0])


def _declenchement(bgs, depart, sortie, entree, risque, objectif_r, signe,
                   theta: float, duree_min: int) -> int | None:
    """L indice ou le declencheur est franchi, ou `None`.

    `a = signe * (entree - close) / risque` : 0 a l entree, 1 au stop. On exige
    `a >= theta` sur `duree_min / 5` bougies CONSECUTIVES, sans que le stop ait
    ete touche entre-temps.

    ⛔ On s arrete a la sortie du trade : declencher apres coup serait lire le
    futur.
    """
    besoin = max(1, duree_min // MINUTES_PAR_BOUGIE)
    suite = 0
    for j in range(depart, min(sortie + 1, len(bgs))):
        b = bgs[j]
        haut, bas = float(b["h"]), float(b["l"])
        pire = min(signe * (haut - entree), signe * (bas - entree)) / risque
        mieux = max(signe * (haut - entree), signe * (bas - entree)) / risque
        if pire <= -1.0 or mieux >= objectif_r:
            return None                      # sorti avant d avoir declenche
        a = signe * (entree - float(b["c"])) / risque
        suite = suite + 1 if a >= theta else 0
        if suite >= besoin:
            return j
    return None


def _contre_fil(bgs, j, entree_inv, risque, objectif_r, signe, cout):
    """Le R de la jambe inverse, entree au CLOSE de `j`, evaluee des `j+1`.

    ⛔ Evaluer des `j` laisserait la bougie du declenchement decider de sa
    propre issue — du futur lu a l envers.
    """
    if j + 1 >= len(bgs):
        return None
    return _issue(bgs, j + 1, entree_inv, risque, objectif_r, -signe, cout)[0]


def _t_apparie(diffs: list[float]) -> tuple[float, float] | tuple[None, None]:
    """Moyenne et `t` APPARIE des differences. `None` sous 3 points."""
    n = len(diffs)
    if n < 3:
        return None, None
    m = statistics.fmean(diffs)
    sd = statistics.stdev(diffs)
    if sd <= 0:
        return m, None
    return m, m / (sd / n ** 0.5)


def mesurer(bgs, ent, spread: float, theta: float, duree: int,
            alea: random.Random) -> dict | None:
    """Les quatre bras sur les memes entrees. R un par un, jamais de moyennes.

    ⚠️ `ent` est calcule UNE fois par spread et passe ici. Le recalculer par
    cellule couterait 24 rejeux sequentiels de trois ans pour un resultat
    identique — les entrees ne dependent que du spread, pas du declencheur.
    """
    if not ent:
        return None
    A, B, C, D = [], [], [], []
    declenches = 0
    for i, e, r, o, signe, sortie in ent:
        cout = spread / r
        ra = _issue(bgs, i, e, r, o, signe, cout)[0]
        j = _declenchement(bgs, i, sortie, e, r, o, signe, theta, duree)
        if j is None:
            continue                 # hors population : aucun bras ne joue
        declenches += 1
        p = float(bgs[j]["c"])
        inv = _contre_fil(bgs, j, p, r, o, signe, cout)
        if inv is None:
            continue
        # ⛔ Le placebo tire son instant dans la vie du MEME trade, pas dans
        # celle d un autre : c est ce qui le rend apparie.
        jp = alea.randint(i, max(i, sortie))
        inv_p = _contre_fil(bgs, jp, float(bgs[jp]["c"]), r, o, signe, cout)
        if inv_p is None:
            continue
        A.append(ra)
        B.append(ra + inv)
        C.append(signe * (p - e) / r - cout)
        D.append(ra + inv_p)
    if len(A) < 3:
        return None
    return {
        "n_entrees": len(ent), "n_declenches": declenches, "n": len(A),
        "A": statistics.fmean(A), "B": statistics.fmean(B),
        "C": statistics.fmean(C), "D": statistics.fmean(D),
        "BA": _t_apparie([b - a for a, b in zip(A, B)]),
        "BC": _t_apparie([b - c for b, c in zip(B, C)]),
        "BD": _t_apparie([b - d for b, d in zip(B, D)]),
    }


def main() -> int:
    quelle = sys.argv[1] if len(sys.argv) > 1 else "echantillon"
    if quelle not in FENETRES:
        print(f"fenetre inconnue : {quelle!r} — {list(FENETRES)}")
        return 1
    debut, fin = FENETRES[quelle]
    print(f"=== BANC DU CONTRE-FIL — fenetre {quelle} : {debut} -> {fin} ===")
    bgs = bougies(debut, fin)
    print(f"bougies 5 min : {len(bgs)}")
    if len(bgs) < labo.FENETRE + 100:
        print("pas assez de bougies")
        return 1
    releve = labo.detections(bgs)
    print(f"setups detectes : {sum(len(v) for v in releve.values())}")

    for spread in SPREADS:
        print(f"\n--- spread {spread:.2f} $ ---")
        print(f"{'theta':>6s} {'D':>4s} {'n':>5s} "
              f"{'A':>8s} {'B':>8s} {'C':>8s} {'D':>8s} | "
              f"{'B-A':>8s} {'t':>6s} | {'B-C':>8s} {'t':>6s} | "
              f"{'B-D':>8s} {'t':>6s}")
        for theta in THETAS:
            for duree in DUREES:
                alea = random.Random(GRAINE)      # rejouable a l identique
                m = mesurer(bgs, ent, spread, theta, duree, alea)
                if m is None:
                    print(f"{theta:6.1f} {duree:4d} {'-':>5s}  "
                          f"trop peu de declenchements")
                    continue

                def c(paire):
                    v, t = m[paire]
                    return (f"{v:+8.4f} " + ("  n/a" if t is None
                                             else f"{t:+6.2f}"))
                print(f"{theta:6.1f} {duree:4d} {m['n']:5d} "
                      f"{m['A']:+8.4f} {m['B']:+8.4f} {m['C']:+8.4f} "
                      f"{m['D']:+8.4f} | {c('BA')} | {c('BC')} | {c('BD')}")
    print("\nRappel de la regle : B retenu seulement si B-A, B-C et B-D sont")
    print("tous > 0 avec t >= 2,0, aux DEUX spreads. Si B <= C, rejet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
