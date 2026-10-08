#!/usr/bin/env python3
"""Risque ÷2 apres une perte — banc pre-inscrit `7443d16`.

    docker exec scalping-radar python /tmp/banc_risque_apres_perte.py echantillon
    docker exec scalping-radar python /tmp/banc_risque_apres_perte.py hors

⛔ LA DECLARATION EST POSEE AVANT CE FICHIER (`7443d16`). Les trois bras, la
metrique, le reechantillonnage, les deux predictions et la regle de rejet y sont
ecrits. Ce script ne fait que les executer.

## La metrique, et pourquoi ce n'est pas le R

Le laboratoire mesure en **R**, c'est-a-dire en multiples du risque PRIS.
Diviser le risque par deux **ne change pas le R** — cela change les euros.
Mesurer en R ne verrait donc rien ; mesurer en euros recompenserait
mecaniquement celui qui engage le moins, sur une population qui PERD
(R moyen -0,0231).

🔑 On mesure le rendement par unite de risque **DEPLOYEE** :

    m = somme(w_i x R_i) / somme(w_i)

Elle demande si la regle PLACE le risque au bon endroit, et elle est insensible
au fait d'en deployer moins.

## Les trois bras

    A  reference  w = 1 partout
    B  la regle   w = 0,5 si le trade PRECEDENT a perdu, 1 sinon
    C  placebo    w = 0,5 sur le MEME NOMBRE de trades, tires au HASARD

🔑 C EST LE BRAS QUI DECIDE : meme risque deploye que B, place au hasard. Si B
ne le bat pas, la serie ne porte rien et on n'a mesure que « engager moins ».

## ⛔ Les poids sont calcules UNE fois, sur la sequence REELLE

Le reechantillonnage casse l'ordre chronologique dont la regle depend. On
etiquette donc chaque trade de son poids d'abord, puis on reechantillonne des
couples `(w, R)` deja formes — jamais la regle elle-meme.
"""
from __future__ import annotations

import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, "/app")
sys.path.insert(0, "/tmp")

import banc_contre_fil_or as banc            # noqa: E402  — meme population
from backend.services import laboratoire_or as labo   # noqa: E402

FENETRES = banc.FENETRES
SPREADS = banc.SPREADS
GRAINE = 20261008
TIRAGES = 2000
FACTEUR = 0.5


def poids_regle(issues: list[bool]) -> list[float]:
    """`0,5` quand le trade PRECEDENT a perdu, `1` sinon.

    Le premier trade n'a pas de precedent : il porte `1`. Lui donner `0,5`
    supposerait une perte qu'on n'a pas vue.
    """
    out = [1.0]
    for i in range(1, len(issues)):
        out.append(FACTEUR if not issues[i - 1] else 1.0)
    return out


def poids_placebo(n: int, combien: int, alea: random.Random) -> list[float]:
    """`0,5` sur `combien` trades tires au hasard. MEME risque deploye que B.

    ⛔ C'est ce qui rend le controle APPARIE : sans l'egalite des comptes, on
    comparerait deux niveaux d'exposition et non deux placements.
    """
    w = [1.0] * n
    for i in alea.sample(range(n), min(combien, n)):
        w[i] = FACTEUR
    return w


def rendement(poids: list[float], rs: list[float]) -> float | None:
    """`somme(w x R) / somme(w)`. `None` si aucun risque n'est deploye."""
    total = sum(poids)
    if total <= 0:
        return None
    return sum(w * r for w, r in zip(poids, rs)) / total


def intervalle(ecarts: list[float]) -> tuple[float, float, float]:
    """Moyenne et bornes a 95 % d'une liste d'ecarts reechantillonnes."""
    e = sorted(ecarts)
    n = len(e)
    return (statistics.fmean(e), e[int(0.025 * n)], e[int(0.975 * n) - 1])


def mesurer(rs: list[float]) -> dict | None:
    """Les trois bras, et l'incertitude par reechantillonnage."""
    n = len(rs)
    if n < 30:
        return None
    issues = [r > 0 for r in rs]
    wA = [1.0] * n
    wB = poids_regle(issues)
    combien = sum(1 for w in wB if w == FACTEUR)
    alea = random.Random(GRAINE)
    wC = poids_placebo(n, combien, alea)

    mA, mB, mC = (rendement(w, rs) for w in (wA, wB, wC))

    # Reechantillonnage de COUPLES deja etiquetes.
    tirage = random.Random(GRAINE)
    dBA, dBC = [], []
    for _ in range(TIRAGES):
        idx = [tirage.randrange(n) for _ in range(n)]
        r2 = [rs[i] for i in idx]
        a = rendement([wA[i] for i in idx], r2)
        b = rendement([wB[i] for i in idx], r2)
        c = rendement([wC[i] for i in idx], r2)
        if None in (a, b, c):
            continue
        dBA.append(b - a)
        dBC.append(b - c)
    if len(dBA) < TIRAGES // 2:
        return None
    return {
        "n": n, "allegés": combien,
        "A": mA, "B": mB, "C": mC,
        "BA": intervalle(dBA), "BC": intervalle(dBC),
        # Pour information seulement : le total en R pondere, qui FAVORISE
        # mecaniquement celui qui engage moins. Il ne decide rien.
        "total_A": sum(wA[i] * rs[i] for i in range(n)),
        "total_B": sum(wB[i] * rs[i] for i in range(n)),
        "total_C": sum(wC[i] * rs[i] for i in range(n)),
    }


def main() -> int:
    quelle = sys.argv[1] if len(sys.argv) > 1 else "echantillon"
    if quelle not in FENETRES:
        print(f"fenetre inconnue : {quelle!r} — {list(FENETRES)}")
        return 1
    debut, fin = FENETRES[quelle]
    print(f"=== RISQUE /2 APRES UNE PERTE — fenetre {quelle} : "
          f"{debut} -> {fin} ===")
    bgs = banc.bougies(debut, fin)
    print(f"bougies 5 min : {len(bgs)}")
    releve = labo.detections(bgs)
    print(f"setups detectes : {sum(len(v) for v in releve.values())}")

    for spread in SPREADS:
        ent = banc._entrees(bgs, releve, spread)
        rs = [banc._issue(bgs, i, e, r, o, s, spread / r)[0]
              for i, e, r, o, s, _srt in ent]
        m = mesurer(rs)
        print(f"\n--- spread {spread:.2f} $ — {len(rs)} entrees ---")
        if m is None:
            print("  trop peu de trades")
            continue
        taux = sum(1 for r in rs if r > 0) / len(rs) * 100
        print(f"  taux de reussite {taux:.1f} %, "
              f"{m['allegés']} trades alleges sur {m['n']} "
              f"({m['allegés'] * 100 // m['n']} %)")
        print(f"  rendement par unite de risque DEPLOYEE")
        print(f"    A reference {m['A']:+.5f}")
        print(f"    B la regle  {m['B']:+.5f}")
        print(f"    C placebo   {m['C']:+.5f}")
        for cle, nom in (("BA", "B - A"), ("BC", "B - C")):
            moy, bas, haut = m[cle]
            verdict = ("POSITIF" if bas > 0 else
                       "NEGATIF" if haut < 0 else "indecidable (0 dedans)")
            print(f"    {nom} = {moy:+.5f}   95 % [{bas:+.5f} ; {haut:+.5f}]"
                  f"   -> {verdict}")
        print(f"  (pour information, totaux en R pondere — ne decident RIEN : "
              f"A {m['total_A']:+.2f}  B {m['total_B']:+.2f}  "
              f"C {m['total_C']:+.2f})")

    print("\nRegle : retenu seulement si B-A ET B-C sont strictement positifs,")
    print("aux DEUX spreads. Si B <= C, rejet — on n a mesure qu engager moins.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
