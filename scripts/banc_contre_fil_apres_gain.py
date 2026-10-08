#!/usr/bin/env python3
"""Ouvrir dans l'AUTRE SENS dès qu'un trade d'or touche ses 2 € — le banc.

Règle de Xavier, 2026-10-08 : *« je veux que lorsque le 1er trade est à
2 euros de l'entrée vers le TP, alors ouvrir un trade dans l'autre sens. »*
Le TP de l'or vaut 2 € = 2,24 $ : « à 2 € vers le TP » **est** le TP.

Déclaré dans `docs/concepts-trading.md` au commit `b624909`, **avant** cette
ligne de code. Critère, prédictions et règle de rejet y sont figés.

## Les quatre bras, et pourquoi il en faut quatre

À l'instant où un trade touche sa cible de 2 € :

| bras | ce qu'il ouvre |
|---|---|
| **A** | rien — le comportement actuel |
| **B** | le sens **OPPOSÉ** : la règle de Xavier |
| **C** | le sens opposé, à un instant **TIRÉ AU HASARD**, 200 tirages |
| **D** | le sens **IDENTIQUE** (continuation) |

🔑 **C isole le MOMENT** (les mêmes directions, à des instants quelconques) et
**D isole la DIRECTION** (le même instant, le sens inverse). Sans les deux, un
`B` positif ne dirait pas si l'on mesure le moment, le sens, ou seulement le
coût d'un trade de plus — l'erreur commise le 01/10 avec un contrôle aléatoire
non apparié (`97e3c39`).

## ⛔ Ce qui a déjà été réfuté, et qu'on ne refait pas

Le contre-fil sur un trade **collé au stop** a été rejeté le même jour
(`3302fa5`) : son placebo le battait franchement, *« collé au stop, le
mouvement adverse a déjà eu lieu »*. Ici la prémisse est **inversée** — le prix
vient de courir 2,24 $ **en notre faveur** et la règle parie sur le retour.
Hypothèse de retour à la moyenne, et non de continuation.

## Les pièges tenus

- **Bougies DU COURTIER** (`candles_5min.db`), fenêtres **figées** dans le
  code : trois passages sur une fenêtre glissante avaient rendu 0, puis 1,
  puis 0 retenue.
- `labo._issue` teste le **stop AVANT la cible** dans chaque bougie. Tout le
  sujet est là : supposer la cible fabriquerait la performance.
- Séquentiel comme le laboratoire (`i = sortie + 1`), ce qui fige la population.
- Spread facturé aux **deux jambes**, verdict exigé aux **deux** valeurs.
- ⚠️ Une seule paire ⇒ **pas de lecture par paire**. La borne vient du
  bootstrap par trade, et c'est une **limite**, pas un détail.
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

# ─── La géométrie de PRODUCTION, pas celle des setups ────────────────────
# 🔑 Les setups du laboratoire portent leurs propres niveaux ; la règle de
# Xavier vit dans la configuration ARMÉE. On impose donc le stop et la cible
# de production, sinon on mesurerait une autre stratégie que la sienne.
SL_PCT = 0.35 / 100           # XAU_SL_PCT
TP_USD = 2.24                 # 2,00 € au taux de 1,1197
TAUX = 1.1197

SPREADS = (0.20, 0.50)        # le verdict est exigé aux DEUX
TIRAGES = 200                 # le placebo est retiré 200 fois
GRAINE = 20261008

# ⛔ Alignées sur la FIN DES DONNÉES (l'archive du courtier s'arrête au
# 2026-08-08), et posées AVANT le premier passage. Choisir les bornes après
# avoir vu un résultat serait choisir le résultat.
FENETRES = {
    "echantillon": ("2025-08-08", "2026-08-08"),   # un an plein
    "hors":        ("2024-08-08", "2025-08-08"),   # l'année précédente
}


def bougies(debut: str, fin: str) -> list[dict]:
    """⚠️ L'archive porte des horodatages NAÏFS ; les détecteurs comparent à
    des datetimes AWARE. Sans `tzinfo`, `_detect_opening_range` lève."""
    with sqlite3.connect(f"file:{Path(ARCHIVE)}?mode=ro", uri=True) as c:
        lignes = c.execute(
            "SELECT ts, open, high, low, close FROM candles "
            "WHERE pair = ? AND ts >= ? AND ts < ? ORDER BY ts",
            (PAIRE, debut, fin)).fetchall()
    return [{"t": datetime.fromisoformat(str(t)).replace(tzinfo=timezone.utc),
             "o": o, "h": h, "l": lo, "c": cl, "v": 0}
            for t, o, h, lo, cl in lignes]


def _trade(bgs, depart: int, entree: float, signe: int, spread: float):
    """Un trade à la géométrie de PRODUCTION. Rend (R, indice de sortie)."""
    risque = SL_PCT * entree
    if risque <= 0:
        return None
    objectif_r = TP_USD / risque
    r, sortie = labo._issue(bgs, depart, entree, risque, objectif_r, signe,
                            spread / risque,
                            politique=labo.POLITIQUES_SORTIE[0])
    return r, sortie, risque, objectif_r


def sequence_A(bgs, releve, spread: float):
    """Le bras A : la suite séquentielle des trades, géométrie de production.

    ⛔ `i = sortie + 1`, comme le laboratoire. C'est ce qui fige la population
    une fois pour toutes, au lieu de la laisser dépendre du bras testé.
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
        if entree <= 0:
            i += 1
            continue
        signe = 1 if labo._sens(s) == "buy" else -1
        t = _trade(bgs, i, entree, signe, spread)
        if t is None:
            i += 1
            continue
        r, sortie, risque, objectif_r = t
        # 🔑 Le trade a-t-il touché SA CIBLE ? C'est la condition de Xavier.
        #    `_issue` rend `objectif_r - cout` au TP et `-1 - cout` au stop.
        au_tp = r > 0
        out.append({"i": i, "entree": entree, "signe": signe, "r": r,
                    "sortie": sortie, "risque": risque, "au_tp": au_tp,
                    # prix de sortie au TP : l'entrée du contre-fil
                    "prix_tp": entree + signe * TP_USD})
        i = sortie + 1
    return out


def _bras(bgs, depart: int, entree: float, signe: int, spread: float):
    """Le trade ouvert par B, C ou D. Rend son R, ou None si injouable."""
    t = _trade(bgs, depart, entree, signe, spread)
    return None if t is None else t[0]


def _t_apparie(diffs: list[float]):
    """t de Student sur les écarts APPARIÉS. ⛔ Apparié : comparer deux
    moyennes indépendantes ignorerait que les bras partagent les mêmes
    instants, et gonflerait l'incertitude."""
    n = len(diffs)
    if n < 10:
        return None, None
    m = statistics.fmean(diffs)
    if n < 2:
        return m, None
    s = statistics.stdev(diffs)
    if s == 0:
        return m, None
    return m, m / (s / (n ** 0.5))


def mesurer(bgs, seq, spread: float, alea: random.Random):
    """Compare B, C et D sur les trades qui ont touché leur cible."""
    gagnants = [t for t in seq if t["au_tp"]]
    if len(gagnants) < 30:
        return None

    rB, rD, paires = [], [], []
    for t in gagnants:
        j = t["sortie"]
        if j + 1 >= len(bgs):
            continue
        prix = t["prix_tp"]
        b = _bras(bgs, j + 1, prix, -t["signe"], spread)
        d = _bras(bgs, j + 1, prix, t["signe"], spread)
        if b is None or d is None:
            continue
        rB.append(b)
        rD.append(d)
        paires.append((-t["signe"], b, d))

    if len(rB) < 30:
        return None

    # ─── C : les MÊMES directions, à des instants TIRÉS AU HASARD ────────
    # ⛔ Apparié en NOMBRE et en DIRECTION : un placebo qui change aussi la
    #    direction mesurerait deux choses à la fois.
    bas, haut = labo.FENETRE, len(bgs) - 2
    moyennes_C = []
    for _ in range(TIRAGES):
        vals = []
        for sens, _b, _d in paires:
            j = alea.randint(bas, haut)
            prix = float(bgs[j]["c"])
            v = _bras(bgs, j + 1, prix, sens, spread)
            if v is not None:
                vals.append(v)
        if vals:
            moyennes_C.append(statistics.fmean(vals))
    if not moyennes_C:
        return None

    mB = statistics.fmean(rB)
    mD = statistics.fmean(rD)
    mC = statistics.fmean(moyennes_C)
    # ⛔ Combien de tirages BATTENT B ? C'est la lecture qui compte, pas la
    #    moyenne : un seul tirage ne vaut rien (leçon du 08/10).
    battent = sum(1 for m in moyennes_C if m >= mB)

    _, tBD = _t_apparie([b - d for _s, b, d in paires])
    sdC = statistics.stdev(moyennes_C) if len(moyennes_C) > 1 else 0.0
    tBC = (mB - mC) / sdC if sdC > 0 else None

    au_tp_B = sum(1 for v in rB if v > 0) * 100.0 / len(rB)
    return {
        "n_gagnants": len(gagnants), "n": len(rB),
        "B": mB, "C": mC, "D": mD,
        "tBC": tBC, "tBD": tBD, "battent": battent,
        "au_tp_B": au_tp_B,
        # R moyen -> euros : 1 R = le risque, soit 0,35 % du prix, en EUR
        "eur_B": mB * (SL_PCT * 4123.0) / TAUX,
    }


def main() -> int:
    quelle = sys.argv[1] if len(sys.argv) > 1 else "echantillon"
    if quelle not in FENETRES:
        print(f"fenetre inconnue : {quelle!r} — {list(FENETRES)}")
        return 1
    debut, fin = FENETRES[quelle]
    print("=== CONTRE-FIL APRES UN GAIN DE 2 EUR ===")
    print(f"    fenetre {quelle} : {debut} -> {fin}  (figee au code)")
    bgs = bougies(debut, fin)
    print(f"    bougies 5 min du COURTIER : {len(bgs)}")
    if len(bgs) < labo.FENETRE + 200:
        print("    pas assez de bougies")
        return 1
    releve = labo.detections(bgs)
    print(f"    setups detectes : {sum(len(v) for v in releve.values())}")
    print("")
    print("    geometrie IMPOSEE (celle de la production, pas celle des setups) :")
    print(f"      stop {SL_PCT*100:.2f} %   cible {TP_USD:.2f} $ = "
          f"{TP_USD/TAUX:.2f} EUR   seuil de rentabilite 85,7 %")

    for spread in SPREADS:
        print("")
        print(f"--- spread {spread:.2f} $ ---")
        seq = sequence_A(bgs, releve, spread)
        gag = sum(1 for t in seq if t["au_tp"])
        print(f"    bras A : {len(seq)} trades, dont {gag} au TP "
              f"({gag*100.0/max(len(seq),1):.1f} %)")
        alea = random.Random(GRAINE)
        m = mesurer(bgs, seq, spread, alea)
        if m is None:
            print("    trop peu de gagnants pour mesurer")
            continue
        print(f"    contre-fils jouables : {m['n']}")
        print("")
        print(f"      B (sens OPPOSE)   R = {m['B']:+.4f}   "
              f"= {m['eur_B']:+.2f} EUR/trade   au TP {m['au_tp_B']:.1f} %")
        print(f"      C (hasard, {TIRAGES} tirages) R = {m['C']:+.4f}")
        print(f"      D (sens IDENTIQUE)       R = {m['D']:+.4f}")
        print("")
        print(f"      B - C = {m['B']-m['C']:+.4f}   t = "
              + ("n/a" if m["tBC"] is None else f"{m['tBC']:+.2f}")
              + f"   tirages qui BATTENT B : {m['battent']}/{TIRAGES}")
        print(f"      B - D = {m['B']-m['D']:+.4f}   t = "
              + ("n/a" if m["tBD"] is None else f"{m['tBD']:+.2f}"))
        print("")
        # ─── Les trois predictions, telles que declarees ─────────────────
        p1 = (m["tBC"] is not None and m["tBC"] >= 2.0 and m["battent"] == 0)
        p2 = (m["tBD"] is not None and m["tBD"] >= 2.0)
        p3 = m["au_tp_B"] >= 85.7
        print(f"      P1  B > C (200 tirages)      : {'PASSE' if p1 else 'ECHOUE'}")
        print(f"      P2  B > D (le sens porte)    : {'PASSE' if p2 else 'ECHOUE'}")
        print(f"      P3  B atteint 85,7 % au TP   : {'PASSE' if p3 else 'ECHOUE'}")
        print(f"      => {'RETENU a ce spread' if (p1 and p2 and p3) else 'REJETE a ce spread'}")

    print("")
    print("    Rappel de la regle declaree : les TROIS predictions doivent")
    print("    passer, aux DEUX spreads. Battre le hasard sans atteindre")
    print("    85,7 % ne donne qu'une facon moins mauvaise de perdre.")
    print("    ⚠️ Une seule paire : pas de lecture par paire. La borne vient")
    print("       du bootstrap par trade, et c'est une LIMITE.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
