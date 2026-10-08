#!/usr/bin/env python3
"""Contre-fil quand le trade est en PERTE de 2 € — le banc de l'épisode complet.

Règle de Xavier, corrigée le 2026-10-08 : *« à 2 euros de l'entrée vers le
SL »*. Déclarée dans `docs/concepts-trading.md` au commit `4e8bd18`, **avant**
cette ligne de code.

> Quand un trade d'or est en perte de **2 € (2,24 $)**, ouvrir une position de
> **sens opposé**, même stop (14,43 $) et même cible (2,24 $). Le premier trade
> **reste ouvert**.

## 🔑 Pourquoi l'ÉPISODE et pas le contre-fil seul

La question de Xavier est *« est-ce que l'ajouter améliore le résultat ? »*, pas
*« le contre-fil gagne-t-il tout seul ? »*. On somme donc **les deux jambes**.

⚠️ À lots égaux et sens opposés, l'exposition nette est **zéro** : la paire
n'est plus un pari directionnel mais une structure dont les jambes ont des
sorties différentes (achat : cible +2,24 / stop −14,43 ; vente ouverte 2,24
plus bas : cible −4,48 / stop +12,19). Ce qu'elle rend ne se devine pas.

## 🔑 Son seuil est SOUS tout ce qui a été mesuré

```
theta de Xavier = 2,24 / 14,43 = 0,155
thetas rejetes le 08/10 (3302fa5) : 0,30   0,50   0,70
```

48 % sous le plus bas θ testé, et **sans** la condition de durée de ce banc-là.
Le rejet du contre-fil **ne couvre pas** cette cellule : l'argument *« collé au
stop, le mouvement adverse a déjà eu lieu »* perd sa force à 15,5 % du stop.

## Les quatre bras

| bras | l'épisode |
|---|---|
| **A** | le trade seul |
| **B** | le trade **+** le contre-fil à −2 € |
| **C** | le trade **+** un contre-fil à un instant **TIRÉ AU HASARD**, 200 tirages |
| **D** | le trade **+** un renfort de **MÊME sens** à −2 € |

`C` isole le **moment**, `D` isole la **direction**.

## Les pièges tenus

- Bougies **DU COURTIER**, fenêtres **figées** (`cc26d1c`).
- `labo._issue` teste le **stop AVANT la cible** dans chaque bougie.
- Le déclenchement cherche **−2,24 $ AVANT la résolution** de la jambe 1, en
  parcourant les bougies dans l'ordre : lire la perte après coup serait du
  futur lu à l'envers.
- Spread facturé **aux deux jambes de chaque trade**, donc **quatre** jambes
  dans `B`. Un contre-fil gratuit gagnerait mécaniquement.
- ⚠️ Une seule paire ⇒ pas de lecture par paire : la borne vient du bootstrap
  par trade, et c'est une **limite**.
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

SL_PCT = 0.35 / 100
TP_USD = 2.24                 # 2,00 € — la cible, ET le seuil de déclenchement
TAUX = 1.1197

SPREADS = (0.20, 0.50)
TIRAGES = 200
GRAINE = 20261008

# ⛔ Figées au commit cc26d1c, alignées sur la fin des données (2026-08-08).
FENETRES = {
    "echantillon": ("2025-08-08", "2026-08-08"),
    "hors":        ("2024-08-08", "2025-08-08"),
}


def bougies(debut: str, fin: str) -> list[dict]:
    """⚠️ Horodatages NAÏFS en archive, détecteurs AWARE : sans `tzinfo`,
    `_detect_opening_range` lève."""
    with sqlite3.connect(f"file:{Path(ARCHIVE)}?mode=ro", uri=True) as c:
        lignes = c.execute(
            "SELECT ts, open, high, low, close FROM candles "
            "WHERE pair = ? AND ts >= ? AND ts < ? ORDER BY ts",
            (PAIRE, debut, fin)).fetchall()
    return [{"t": datetime.fromisoformat(str(t)).replace(tzinfo=timezone.utc),
             "o": o, "h": h, "l": lo, "c": cl, "v": 0}
            for t, o, h, lo, cl in lignes]


def _r(bgs, depart: int, entree: float, signe: int, spread: float):
    """Un trade à la géométrie de production. Rend (R, indice de sortie)."""
    risque = SL_PCT * entree
    if risque <= 0 or depart >= len(bgs):
        return None
    r, sortie = labo._issue(bgs, depart, entree, risque, TP_USD / risque,
                            signe, spread / risque,
                            politique=labo.POLITIQUES_SORTIE[0])
    return r, sortie, risque


def _declenchement(bgs, depart: int, sortie: int, entree: float, signe: int):
    """Première bougie où la perte atteint 2,24 $, AVANT la résolution.

    ⛔ Parcours dans l'ORDRE, borné par `sortie` : chercher au-delà lirait le
    futur, et c'est exactement le biais qui a gonflé un résultat ×8 le 08/10.
    """
    seuil = entree - signe * TP_USD
    for j in range(depart, min(sortie + 1, len(bgs))):
        b = bgs[j]
        # Pour un ACHAT la perte est un BAS ; pour une VENTE, un HAUT.
        atteint = (float(b["l"]) <= seuil) if signe > 0 else (float(b["h"]) >= seuil)
        if atteint:
            return j, seuil
    return None, None


def episodes(bgs, releve, spread: float):
    """La population, figée : séquentielle comme le laboratoire."""
    out = []
    i, n = labo.FENETRE, len(bgs)
    while i < n:
        cands = list(releve.get(i, ()))
        if not cands:
            i += 1
            continue
        s = cands[0]
        entree = float(s.entry_price)
        if entree <= 0:
            i += 1
            continue
        signe = 1 if labo._sens(s) == "buy" else -1
        a = _r(bgs, i, entree, signe, spread)
        if a is None:
            i += 1
            continue
        rA, sortie, _risque = a
        j, prix_decl = _declenchement(bgs, i, sortie, entree, signe)
        out.append({"i": i, "entree": entree, "signe": signe, "rA": rA,
                    "sortie": sortie, "j": j, "prix": prix_decl})
        i = sortie + 1
    return out


def _euros(r: float, prix: float = 4123.0) -> float:
    """1 R = le risque = 0,35 % du prix, converti en euros."""
    return r * (SL_PCT * prix) / TAUX


def mesurer(bgs, eps, spread: float, alea: random.Random):
    armes = [e for e in eps if e["j"] is not None]
    if len(armes) < 30:
        return None

    A, B, D, sens_list = [], [], [], []
    for e in armes:
        dep = e["j"] + 1                      # la bougie SUIVANTE
        if dep >= len(bgs):
            continue
        b = _r(bgs, dep, e["prix"], -e["signe"], spread)
        d = _r(bgs, dep, e["prix"], e["signe"], spread)
        if b is None or d is None:
            continue
        A.append(e["rA"])
        B.append(e["rA"] + b[0])              # l'EPISODE : les deux jambes
        D.append(e["rA"] + d[0])
        sens_list.append(-e["signe"])

    if len(B) < 30:
        return None

    # ─── C : mêmes sens, instants TIRÉS AU HASARD, apparié en nombre ─────
    bas, haut = labo.FENETRE, len(bgs) - 3
    moyennes_C = []
    for _ in range(TIRAGES):
        vals = []
        for k, sens in enumerate(sens_list):
            j = alea.randint(bas, haut)
            c = _r(bgs, j + 1, float(bgs[j]["c"]), sens, spread)
            if c is not None:
                vals.append(A[k] + c[0])
        if vals:
            moyennes_C.append(statistics.fmean(vals))
    if not moyennes_C:
        return None

    def _t(diffs):
        if len(diffs) < 10:
            return None
        m, s = statistics.fmean(diffs), statistics.stdev(diffs)
        return None if s == 0 else m / (s / (len(diffs) ** 0.5))

    mA, mB, mD = statistics.fmean(A), statistics.fmean(B), statistics.fmean(D)
    mC = statistics.fmean(moyennes_C)
    sdC = statistics.stdev(moyennes_C) if len(moyennes_C) > 1 else 0.0
    return {
        "n_eps": len(eps), "n_armes": len(armes), "n": len(B),
        "A": mA, "B": mB, "C": mC, "D": mD,
        "tBA": _t([b - a for a, b in zip(A, B)]),
        "tBD": _t([b - d for b, d in zip(B, D)]),
        "tBC": ((mB - mC) / sdC) if sdC > 0 else None,
        "battent": sum(1 for m in moyennes_C if m >= mB),
        "eurA": _euros(mA), "eurB": _euros(mB), "eurD": _euros(mD),
    }


def main() -> int:
    quelle = sys.argv[1] if len(sys.argv) > 1 else "echantillon"
    if quelle not in FENETRES:
        print(f"fenetre inconnue : {quelle!r} — {list(FENETRES)}")
        return 1
    debut, fin = FENETRES[quelle]
    print("=== CONTRE-FIL A -2 EUR (vers le STOP) — EPISODE COMPLET ===")
    print(f"    fenetre {quelle} : {debut} -> {fin}  (figee au code)")
    print(f"    theta = {TP_USD:.2f} / {SL_PCT*4123:.2f} = "
          f"{TP_USD/(SL_PCT*4123):.4f}   (rejetes : 0,30 / 0,50 / 0,70)")
    bgs = bougies(debut, fin)
    print(f"    bougies 5 min du COURTIER : {len(bgs)}")
    if len(bgs) < labo.FENETRE + 200:
        print("    pas assez de bougies")
        return 1
    releve = labo.detections(bgs)
    print(f"    setups detectes : {sum(len(v) for v in releve.values())}")

    verdicts = []
    for spread in SPREADS:
        print("")
        print(f"--- spread {spread:.2f} $ ---")
        eps = episodes(bgs, releve, spread)
        armes = sum(1 for e in eps if e["j"] is not None)
        print(f"    episodes : {len(eps)}, dont {armes} atteignent -2 EUR "
              f"({armes*100.0/max(len(eps),1):.1f} %)")
        alea = random.Random(GRAINE)
        m = mesurer(bgs, eps, spread, alea)
        if m is None:
            print("    trop peu de declenchements pour mesurer")
            verdicts.append(False)
            continue
        print(f"    episodes jouables : {m['n']}")
        print("")
        print(f"      A  trade seul              R {m['A']:+.4f}  "
              f"= {m['eurA']:+.2f} EUR")
        print(f"      B  + contre-fil a -2 EUR   R {m['B']:+.4f}  "
              f"= {m['eurB']:+.2f} EUR")
        print(f"      C  + contre-fil au HASARD  R {m['C']:+.4f}   "
              f"({TIRAGES} tirages)")
        print(f"      D  + MEME sens a -2 EUR    R {m['D']:+.4f}  "
              f"= {m['eurD']:+.2f} EUR")
        print("")

        def aff(nom, v, t):
            return (f"      {nom} = {v:+.4f}   t = "
                    + ("n/a" if t is None else f"{t:+.2f}"))
        print(aff("B - A", m["B"] - m["A"], m["tBA"]))
        print(aff("B - C", m["B"] - m["C"], m["tBC"])
              + f"   tirages qui BATTENT B : {m['battent']}/{TIRAGES}")
        print(aff("B - D", m["B"] - m["D"], m["tBD"]))
        print("")
        p1 = m["tBA"] is not None and m["tBA"] >= 2.0
        p2 = (m["tBC"] is not None and m["tBC"] >= 2.0 and m["battent"] == 0)
        p3 = m["tBD"] is not None and m["tBD"] >= 2.0
        print(f"      P1  B > A (la jambe sert)        : {'PASSE' if p1 else 'ECHOUE'}")
        print(f"      P2  B > C (le moment porte)      : {'PASSE' if p2 else 'ECHOUE'}")
        print(f"      P3  B > D (le sens porte)        : {'PASSE' if p3 else 'ECHOUE'}")
        pos = m["eurB"] > 0
        print(f"      +   B positif EN EUROS           : "
              f"{'OUI' if pos else 'NON (%.2f EUR)' % m['eurB']}")
        ok = p1 and p2 and p3 and pos
        verdicts.append(ok)
        print(f"      => {'RETENU a ce spread' if ok else 'REJETE a ce spread'}")

    print("")
    print("=== VERDICT ===")
    if verdicts and all(verdicts):
        print("    RETENU aux deux spreads -> a reprendre HORS echantillon")
    else:
        print("    REJETE : la regle declaree exige les trois predictions ET un")
        print("    B positif en euros, aux DEUX spreads.")
    print("")
    print("    ⚠️ Une seule paire : pas de lecture par paire. La borne vient du")
    print("       bootstrap par trade, et c'est une LIMITE, pas un detail.")
    print("    ⚠️ A est deja un bras perdant (-0,70 EUR/trade mesure) : le")
    print("       battre ne suffit pas, d'ou l'exigence de B positif.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
