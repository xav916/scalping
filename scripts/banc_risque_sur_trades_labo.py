#!/usr/bin/env python3
"""Risque /2 apres une perte — sur les 360 784 trades DEJA calcules.

    banc_borne.sh banc_risque_sur_trades_labo.py

⛔ LA DECLARATION EST POSEE AVANT CE FICHIER (`21335f1`). Population,
exclusion de l'or, trois bras, double lecture, trois predictions et regle de
rejet y sont ecrits.

## Pourquoi cette population et pas les bougies

Le rejeu depuis les bougies est INFAISABLE sur ces machines : une seule paire
coute 122 Mo de bougies puis depasse 1 Go de detections, et le radar occupe
deja 1,83 Gio sur 3,75. Ce chemin a coute 56 minutes de production le
2026-10-08.

🔑 `backtest.db.trades` porte **360 784 trades avec `outcome` ET
`rr_realized`** : le travail est deja fait. Une lecture seule, pas une
detection.

## ⛔ Ce que le code protege

- `XAU/USD` est **exclu** : il a forme l'hypothese. Le garder ne serait pas une
  replication.
- « Le trade precedent » se lit **PAR PAIRE**, par `emitted_at` croissant.
  Melanger les paires fabriquerait une sequence qui n'existe pas.
- Les poids sont etiquetes sur la sequence REELLE avant tout
  reechantillonnage : on tire des couples `(w, R)` deja formes, jamais la
  regle.
- La lecture qui DECIDE est celle par PAIRE : 13 unites, pas 338 000 trades
  correles.
"""
from __future__ import annotations

import random
import sqlite3
import statistics
import sys
from pathlib import Path

sys.path.insert(0, "/app")
sys.path.insert(0, "/bancs")

import banc_risque_apres_perte as bq      # noqa: E402 — memes fonctions pures

DB = "/app/data/backtest.db"
# ⛔ XAU a FORME l'hypothese. WTI : source CONNUE FAUSSE (Twelve Data cotait un
# autre contrat). Les actions : 756 a 815 trades contre ~20 000, et des series
# qui ne sont pas continues.
EXCLUES = ("XAU/USD", "WTI/USD", "MSFT", "NVDA", "TSLA", "AAPL", "SPX")
MIN_PAR_PAIRE = 500
GRAINE = 20261008
TIRAGES = 2000
# ⛔ Un placebo tire UNE seule fois ne vaut rien : on le retire autant de fois.
PLACEBOS = 200


def charger() -> dict[str, list[tuple[str, str, float]]]:
    """Par paire : (emis, resolu, R), dans l'ordre d'emission. Lecture seule.

    ⛔ On garde `checked_at` parce que la regle en depend : le poids d'un trade
    ne peut dependre que des trades DEJA RESOLUS a son emission.
    """
    par_paire: dict[str, list[tuple[str, str, float]]] = {}
    with sqlite3.connect(f"file:{Path(DB)}?mode=ro", uri=True) as c:
        for paire, emis, resolu, r in c.execute(
                "SELECT pair, emitted_at, checked_at, rr_realized FROM trades "
                "WHERE outcome IS NOT NULL AND rr_realized IS NOT NULL "
                "AND outcome <> 'OPEN' AND checked_at IS NOT NULL "
                "ORDER BY pair, emitted_at"):
            if paire in EXCLUES:
                continue
            par_paire.setdefault(paire, []).append((emis, resolu, float(r)))
    return {p: v for p, v in par_paire.items() if len(v) >= MIN_PAR_PAIRE}


def poids_regle_causale(lignes) -> list[float]:
    """`0,5` si le dernier trade RESOLU a l'emission avait perdu.

    ⛔ LE DEFAUT DU PREMIER PASSAGE. J'avais pris le dernier trade EMIS. Mesure :
    deux trades consecutifs d'une paire sont separes de 719 s en mediane, et un
    trade met 3 363 s a se resoudre. Le precedent n'est donc PAS resolu quand le
    suivant part : la regle lisait LE FUTUR.

    🔑 Ici le poids ne depend que de ce qui etait CONNU. Si rien n'est encore
    resolu, le poids vaut 1 : on n'allege pas sur une information absente.

    ⚠️ Balayage en O(n) : les trades sont deja tries par emission, et on avance
    un curseur sur les resolutions triees. Pas de boucle imbriquee.
    """
    n = len(lignes)
    # (resolu, perdant) tries par date de resolution
    resolutions = sorted((l[1], l[2] <= 0) for l in lignes)
    poids = []
    j = 0
    dernier_perdant = None
    for emis, _res, _r in lignes:
        while j < n and resolutions[j][0] < emis:
            dernier_perdant = resolutions[j][1]
            j += 1
        if dernier_perdant is True:
            poids.append(bq.FACTEUR)
        else:
            poids.append(1.0)
    return poids


def main() -> int:
    print("=== RISQUE /2 APRES UNE PERTE — 360 784 trades du laboratoire ===")
    print(f"⛔ EXCLU : {', '.join(EXCLUES)} (a forme l hypothese)\n")

    par_paire = charger()
    if len(par_paire) < 5:
        print("pas assez de paires")
        return 1

    # ── Etiquetage sur la sequence REELLE de chaque paire ────────────────
    par_index_rs: dict[str, tuple] = {}
    detail = {}
    alea = random.Random(GRAINE)
    for paire in sorted(par_paire):
        lignes = par_paire[paire]
        rs = [l[2] for l in lignes]
        issues = [r > 0 for r in rs]
        wB = poids_regle_causale(lignes)
        combien = sum(1 for w in wB if w == bq.FACTEUR)
        wC = bq.poids_placebo(len(rs), combien, alea)
        par_index_rs[paire] = ([1.0] * len(rs), wB, wC)
        a = bq.rendement([1.0] * len(rs), rs)
        b = bq.rendement(wB, rs)
        cc = bq.rendement(wC, rs)
        detail[paire] = {"n": len(rs), "taux": sum(issues) * 100 / len(rs),
                         "A": a, "B": b, "C": cc, "BC": b - cc, "BA": b - a}
        print(f"  {paire:9s} {len(rs):6d} trades  taux {detail[paire]['taux']:4.1f} %"
              f"  A {a:+.4f}  B {b:+.4f}  C {cc:+.4f}")

    # ── Sommes PRECALCULEES par paire ────────────────────────────────────
    #
    # ⛔ Pourquoi. Reechantillonner 338 000 trades 2 000 fois demande des
    # centaines de millions d'operations : irrealisable en Python pur, le
    # premier essai n'a jamais rendu. Or la metrique est un RAPPORT DE SOMMES :
    # il suffit de garder, par paire, somme(w x R) et somme(w) pour chaque bras.
    #
    # 🔑 Le reechantillonnage PAR PAIRE — celui qui DECIDE — devient alors une
    # somme de 13 nombres. Instantane, et exact : aucune approximation.
    sommes = {}
    for paire in sorted(par_paire):
        rs = [l[2] for l in par_paire[paire]]
        idx = par_index_rs[paire]
        sommes[paire] = tuple(
            (sum(w * r for w, r in zip(poids, rs)), sum(poids))
            for poids in idx)

    def rendement_du_groupe(paires, bras: int):
        num = sum(sommes[p][bras][0] for p in paires)
        den = sum(sommes[p][bras][1] for p in paires)
        return None if den <= 0 else num / den

    noms = sorted(sommes)
    mA, mB, mC = (rendement_du_groupe(noms, k) for k in range(3))
    n_total = sum(len(par_paire[p]) for p in noms)
    print("")
    print(f"  {n_total} trades sur {len(noms)} paires")
    print("  rendement par unite de risque DEPLOYEE")
    print(f"    A {mA:+.5f}   B {mB:+.5f}   C {mC:+.5f}")

    # ── La lecture qui DECIDE : par PAIRE, 13 unites ────────────────────
    t2 = random.Random(GRAINE)
    d2a, d2c = [], []
    for _ in range(TIRAGES):
        choisies = [noms[t2.randrange(len(noms))] for _ in range(len(noms))]
        a, b, cc = (rendement_du_groupe(choisies, k) for k in range(3))
        if None not in (a, b, cc):
            d2a.append(b - a)
            d2c.append(b - cc)

    print("  lecture par PAIRE (DECIDE) — 2 000 tirages des "
          f"{len(noms)} paires")
    for nom, ec in (("B-A", d2a), ("B-C", d2c)):
        moy, bas, haut = bq.intervalle(ec)
        v = ("POSITIF" if bas > 0 else
             "NEGATIF" if haut < 0 else "indecidable (0 dedans)")
        print(f"    {nom} {moy:+.5f}  95 % [{bas:+.5f} ; {haut:+.5f}]  -> {v}")
    print("  ⚠️ La lecture par TRADE est ABANDONNEE : 338 000 x 2 000 tirages")
    print("     ne rendent pas en Python pur, et ce n'etait pas elle qui")
    print("     decidait. Son absence est DITE, pas cachee.")

    pos = sum(1 for d in detail.values() if d["BC"] > 0)
    # ── ⛔ LE PLACEBO NE DOIT PAS ETRE TIRE UNE SEULE FOIS ───────────────
    #
    # `C` ci-dessus est UN tirage, avec UNE graine. `B-C` comparait donc la
    # regle a un seul coup de hasard, pas au hasard : une graine malchanceuse
    # suffisait a rendre `B-C` positif pour la mauvaise raison.
    #
    # 🔑 On retire le placebo PLACEBOS fois et on regarde ou tombe `B` dans la
    # distribution. C'est le vrai controle.
    print("")
    print(f"  --- placebo retire {PLACEBOS} fois (un tirage unique ne vaut rien) ---")
    tirs = random.Random(GRAINE + 1)
    rendements = []
    for _ in range(PLACEBOS):
        num = den = 0.0
        for paire in noms:
            rs = [l[2] for l in par_paire[paire]]
            nb = sum(1 for w in par_index_rs[paire][1] if w == bq.FACTEUR)
            w = bq.poids_placebo(len(rs), nb, tirs)
            num += sum(x * r for x, r in zip(w, rs))
            den += sum(w)
        rendements.append(num / den)
    rendements.sort()
    bas = rendements[int(0.025 * PLACEBOS)]
    haut = rendements[int(0.975 * PLACEBOS) - 1]
    moy = statistics.fmean(rendements)
    au_dessus = sum(1 for x in rendements if x >= mB)
    print(f"    placebo : moyenne {moy:+.5f}   95 % [{bas:+.5f} ; {haut:+.5f}]")
    print(f"    B       : {mB:+.5f}")
    print(f"    placebos qui EGALENT ou BATTENT B : {au_dessus} sur {PLACEBOS}")
    print(f"    p = {au_dessus / PLACEBOS:.3f}")
    print("    -> " + ("B SORT de la distribution du hasard"
                       if au_dessus / PLACEBOS < 0.05
                       else "B est DANS la distribution du hasard"))

    print(f"\n  P3 : B-C positif sur {pos} des {len(detail)} paires (exige >= 8)")
    print("\nRegle : P1 et P2 en lecture PAR PAIRE, et P3. Si B <= C, rejet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
