#!/usr/bin/env python3
"""Ne trader l'or QUE dans le sens de la tendance — le banc.

Règle de Xavier, 2026-10-08 : *« lorsque la trend est haussière ou baissière,
faire du buy ou du sell en fonction, pour avoir le maximum de trades
gagnants. »* Déclarée dans `docs/concepts-trading.md` au commit `f2cc6f0`,
**avant** cette ligne de code.

## 🔑 La tendance est celle de la PRODUCTION, pas la mienne

`compute_h1_trend` compare la moyenne des **5** dernières clôtures H1 à celle
des **20**, avec un seuil de **±0,15 %**. Inventer ma propre définition
mesurerait une autre règle que la sienne, et l'écart ne se verrait nulle part.

⇒ Les heures sont **calendaires** et seules les heures **complétées** avant
l'instant du signal comptent — l'heure en cours est exclue.

## Les quatre bras, tous pris dans la population de `A`

| bras | ce qu'il retient |
|---|---|
| **A** | tous les trades |
| **B** | ceux qui **concordent** avec la tendance |
| **C** | ceux qui vont **CONTRE** |
| **D** | un **tirage au hasard** du même NOMBRE que `B`, 200 fois |

🔑 **`C` peut tuer la règle** : si `B ≈ C`, la tendance ne porte rien.
🔑 **`D` est tout aussi indispensable** : retenir 40 % des trades au hasard
change déjà la moyenne. Sans contrôle apparié **en nombre**, on confondrait
« la tendance informe » avec « moins de trades, c'est mieux ».

## ⚠️ LA LIMITE, assumée d'avance

La population est celle de `A`, **figée** : on ne rejoue pas la séquence sous
filtre. Filtrer en production libérerait la place plus tôt et ferait entrer
d'autres trades. Ce banc mesure donc le **contenu informatif** de la tendance à
trades identiques — **pas** ce que le filtre rapporterait en production.
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
TP_USD = 2.24
TAUX = 1.1197

SPREADS = (0.20, 0.50)
TIRAGES = 200
GRAINE = 20261008

SEUIL_TENDANCE_PCT = 0.15     # ⚠️ la valeur de compute_h1_trend

FENETRES = {
    "echantillon": ("2025-08-08", "2026-08-08"),
    "hors":        ("2024-08-08", "2025-08-08"),
}


def bougies(debut: str, fin: str) -> list[dict]:
    with sqlite3.connect(f"file:{Path(ARCHIVE)}?mode=ro", uri=True) as c:
        lignes = c.execute(
            "SELECT ts, open, high, low, close FROM candles "
            "WHERE pair = ? AND ts >= ? AND ts < ? ORDER BY ts",
            (PAIRE, debut, fin)).fetchall()
    return [{"t": datetime.fromisoformat(str(t)).replace(tzinfo=timezone.utc),
             "o": o, "h": h, "l": lo, "c": cl, "v": 0}
            for t, o, h, lo, cl in lignes]


def tendances(bgs) -> list[str]:
    """`compute_h1_trend` reproduit pour CHAQUE index, en une passe.

    ⛔ Les heures sont CALENDAIRES, pas un pas de 12 bougies. Ma premiere
    version prenait `bgs[i - k*12]`, ce qui donne des heures GLISSANTES : avec
    les trous de week-end et les bougies manquantes, elle aurait melange des
    heures de jours differents tout en pretendant reproduire la production.
    J'avais ecrit << a l'identique >> : il fallait le rendre vrai.

    ⛔ Ne regarde que les heures COMPLETEES avant `i`. L'heure en cours est
    exclue : l'inclure lirait une bougie qui n'est pas encore fermee -- le
    futur lu a l'envers, et le biais qui avait gonfle un resultat x8 le
    2026-10-08.
    """
    # Derniere cloture de chaque heure calendaire, et l'index ou elle tombe.
    heures: list[tuple[int, float]] = []
    cle_courante = None
    for i, b in enumerate(bgs):
        cle = (b["t"].date(), b["t"].hour)
        if cle != cle_courante:
            heures.append([i, float(b["c"])])
            cle_courante = cle
        else:
            heures[-1][0] = i
            heures[-1][1] = float(b["c"])

    out = ["neutral"] * len(bgs)
    # 🔑 `h` = nombre d'heures ENTIEREMENT passees a l'index i.
    h = 0
    for i in range(len(bgs)):
        while h < len(heures) and heures[h][0] < i:
            h += 1
        # `h` heures completees, la plus recente etant heures[h-1].
        if h < 20:
            continue
        clotures = [heures[h - 1 - k][1] for k in range(20)]
        recent = statistics.fmean(clotures[:5])
        longer = statistics.fmean(clotures)
        if longer <= 0:
            continue
        diff = (recent - longer) / longer * 100
        if diff > SEUIL_TENDANCE_PCT:
            out[i] = "bullish"
        elif diff < -SEUIL_TENDANCE_PCT:
            out[i] = "bearish"
    return out


def _trade(bgs, depart: int, entree: float, signe: int, spread: float):
    risque = SL_PCT * entree
    if risque <= 0:
        return None
    return labo._issue(bgs, depart, entree, risque, TP_USD / risque, signe,
                       spread / risque, politique=labo.POLITIQUES_SORTIE[0])


def sequence(bgs, releve, spread: float, tend: list[str]):
    """La population de `A`, sequentielle comme le laboratoire."""
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
        r, sortie = t
        out.append({"r": r, "signe": signe, "tendance": tend[i]})
        i = sortie + 1
    return out


def _t_un_echantillon(v, ref: float):
    """t de Student d'une moyenne contre une reference."""
    if len(v) < 10:
        return None
    m, s = statistics.fmean(v), statistics.stdev(v)
    return None if s == 0 else (m - ref) / (s / len(v) ** 0.5)


def _t_deux(a, b):
    if len(a) < 10 or len(b) < 10:
        return None
    va = statistics.stdev(a) ** 2 / len(a)
    vb = statistics.stdev(b) ** 2 / len(b)
    d = (va + vb) ** 0.5
    return None if d == 0 else (statistics.fmean(a) - statistics.fmean(b)) / d


def main() -> int:
    quelle = sys.argv[1] if len(sys.argv) > 1 else "echantillon"
    if quelle not in FENETRES:
        print(f"fenetre inconnue : {quelle!r} — {list(FENETRES)}")
        return 1
    debut, fin = FENETRES[quelle]
    print("=== FILTRE DE TENDANCE SUR L'OR ===")
    print(f"    fenetre {quelle} : {debut} -> {fin}  (figee)")
    print(f"    tendance : moyenne 5 H1 contre 20 H1, seuil +/-{SEUIL_TENDANCE_PCT} %")
    print(f"    geometrie : stop {SL_PCT*100:.2f} %, cible {TP_USD:.2f} $ "
          f"= {TP_USD/TAUX:.2f} EUR")
    bgs = bougies(debut, fin)
    print(f"    bougies 5 min du COURTIER : {len(bgs)}")
    if len(bgs) < labo.FENETRE + 300:
        print("    pas assez de bougies")
        return 1
    releve = labo.detections(bgs)
    print(f"    setups detectes : {sum(len(v) for v in releve.values())}")
    tend = tendances(bgs)
    from collections import Counter
    c = Counter(tend)
    print(f"    tendance par bougie : {dict(c)}")

    verdicts = []
    for spread in SPREADS:
        print("")
        print(f"--- spread {spread:.2f} $ ---")
        seq = sequence(bgs, releve, spread, tend)
        if len(seq) < 100:
            print("    trop peu de trades")
            verdicts.append(False)
            continue

        A = [t["r"] for t in seq]
        # Concordance : achat en tendance haussiere, vente en baissiere.
        def concorde(t):
            return ((t["tendance"] == "bullish" and t["signe"] > 0)
                    or (t["tendance"] == "bearish" and t["signe"] < 0))

        def contre(t):
            return ((t["tendance"] == "bullish" and t["signe"] < 0)
                    or (t["tendance"] == "bearish" and t["signe"] > 0))

        B = [t["r"] for t in seq if concorde(t)]
        C = [t["r"] for t in seq if contre(t)]
        neutres = sum(1 for t in seq if t["tendance"] == "neutral")
        print(f"    A : {len(A)} trades")
        print(f"    B : {len(B)} concordent  ({len(B)*100.0/len(A):.1f} %)")
        print(f"    C : {len(C)} vont contre ({len(C)*100.0/len(A):.1f} %)")
        print(f"        {neutres} en tendance NEUTRE, ecartes des deux "
              f"({neutres*100.0/len(A):.1f} %)")
        if len(B) < 30 or len(C) < 30:
            print("    pas assez de trades dans un bras")
            verdicts.append(False)
            continue

        # ─── D : le MEME NOMBRE que B, tire au hasard dans A ─────────────
        alea = random.Random(GRAINE)
        moyennes_D = []
        for _ in range(TIRAGES):
            moyennes_D.append(statistics.fmean(alea.sample(A, len(B))))
        mD = statistics.fmean(moyennes_D)
        sdD = statistics.stdev(moyennes_D) if len(moyennes_D) > 1 else 0.0

        mA, mB, mC = (statistics.fmean(x) for x in (A, B, C))
        eur = lambda r: r * (SL_PCT * 4123.0) / TAUX   # noqa: E731
        print("")
        print(f"      A  tous           R {mA:+.4f}  = {eur(mA):+.2f} EUR")
        print(f"      B  CONCORDENT     R {mB:+.4f}  = {eur(mB):+.2f} EUR")
        print(f"      C  CONTRE         R {mC:+.4f}  = {eur(mC):+.2f} EUR")
        print(f"      D  hasard (n=|B|) R {mD:+.4f}   ({TIRAGES} tirages)")
        print("")
        tBA = _t_un_echantillon(B, mA)
        tBC = _t_deux(B, C)
        tBD = (mB - mD) / sdD if sdD > 0 else None
        battent = sum(1 for m in moyennes_D if m >= mB)

        def aff(nom, v, t, extra=""):
            return (f"      {nom} = {v:+.4f}   t = "
                    + ("n/a" if t is None else f"{t:+.2f}") + extra)
        print(aff("B - A", mB - mA, tBA))
        print(aff("B - C", mB - mC, tBC))
        print(aff("B - D", mB - mD, tBD,
                  f"   tirages qui BATTENT B : {battent}/{TIRAGES}"))
        print("")
        p1 = tBA is not None and tBA >= 2.0
        p2 = tBC is not None and tBC >= 2.0
        p3 = tBD is not None and tBD >= 2.0 and battent == 0
        print(f"      P1  B > A                        : {'PASSE' if p1 else 'ECHOUE'}")
        print(f"      P2  B > C (la tendance porte)    : {'PASSE' if p2 else 'ECHOUE'}")
        print(f"      P3  B > D (pas juste moins de n) : {'PASSE' if p3 else 'ECHOUE'}")
        pos = mB > 0
        print(f"      +   B positif en R               : "
              f"{'OUI' if pos else 'NON (%.4f)' % mB}")
        ok = p1 and p2 and p3 and pos
        verdicts.append(ok)
        print(f"      => {'RETENU a ce spread' if ok else 'REJETE a ce spread'}")

    print("")
    print("=== VERDICT ===")
    if verdicts and all(verdicts):
        print("    RETENU aux deux spreads -> justifie un SECOND banc,")
        print("    sequentiel cette fois. PAS un deploiement.")
    else:
        print("    REJETE : la regle declaree exige les trois predictions ET")
        print("    un B positif, aux DEUX spreads.")
    print("")
    print("    ⚠️ Population FIGEE sur celle de A : ce banc mesure le CONTENU")
    print("       INFORMATIF de la tendance a trades identiques, PAS ce que le")
    print("       filtre rapporterait en production (ou la place se libererait")
    print("       plus tot et ferait entrer d'autres trades).")
    print("    ⚠️ Une seule paire : pas de lecture par paire.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
