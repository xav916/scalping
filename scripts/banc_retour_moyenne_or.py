#!/usr/bin/env python3
"""Le retour à la moyenne a-t-il un avantage sur l'or ? — le banc.

Pré-inscription : `docs/predictions/2026-10-31_retour-moyenne-or.md`,
commitée AVANT ce fichier (`preinscrire.py` l'exige et le vérifie par git).

## Ce que ce banc mesure

24 cellules : 3 seuils (1,5σ / 2,0σ / 2,5σ) × 4 échelles (M5, M15, M30, M60)
× 2 sens. Pour chacune : `n`, `r_moyen`, `t`, et l'écart au **contrôle
aléatoire** de la même échelle. Le plafond du hasard pour 24 cellules vaut
**2,241** — c'est lui qu'il faut dépasser, pas zéro.

Verdict exigé aux **DEUX spreads** (0,20 et 0,50). C'est une conjonction :
elle durcit l'admission, elle ne multiplie pas les chances de passer.

## ⛔ Ce que ce banc ne mesure PAS

Aucun filtre de régime de tendance. Xavier l'a demandé le 31/10 ; c'est mot
pour mot la **piste N** du banc du filtre de tendance, ABANDONNÉE le 08/10
comme déclaré d'avance (`N − B` : t = +2,09 en échantillon → **+0,16** hors
échantillon sur 6 981 trades). Le refaire ici serait rejouer une question
déjà tranchée.

## 🔑 Un seul z-score dans le dépôt

Le seuil est balayé en réglant `pattern_detector.MEAN_REVERSION_SIGMA`, et le
détecteur **de production** fait la mesure. Recopier le calcul d'écart ici
créerait une seconde implémentation de la même règle, qui divergerait un jour
en silence — la leçon de `chaines_production.py`.

## Source

`candles_courtier.db` — les bougies du COURTIER, 99 750 M5 sur XAU/USD.
⛔ Jamais `candles_5min.db` : celui-là vient de Twelve Data, dont les
horodatages sont décalés de façon non constante (3,807 $ de médiane sur les
clôtures à décalage unique), ce qui le rend inutilisable dès qu'un instant
précis compte — et ici l'entrée, le stop et l'objectif en dépendent tous.

Usage, dans le conteneur de production :

    sudo docker exec -e PYTHONPATH=/app -w /app scalping-radar \\
      python scripts/banc_retour_moyenne_or.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/app")

from backend.services import laboratoire_or as labo       # noqa: E402
from backend.services import pattern_detector as pd       # noqa: E402

BOUGIES = "/app/data/candles_courtier.db"
PAIRE = "XAU/USD"

# ─── Les 24 cellules, telles que pré-inscrites ───────────────────────────
SEUILS = (1.5, 2.0, 2.5)
SENS = ("buy", "sell")
MOTIFS = {"buy": "mean_reversion_up", "sell": "mean_reversion_down"}
SPREADS = (0.20, 0.50)              # le verdict est exigé aux DEUX

CELLULES = len(SEUILS) * len(labo.ECHELLES) * len(SENS)
PLAFOND = labo.plafond_hasard(CELLULES)

# Conditions de VALIDITÉ du rejeu, pré-inscrites et distinctes du critère.
MIN_BOUGIES = 90_000
MAX_NON_RESOLUS_PCT = 5.0

# Conditions d'ADMISSION, pré-inscrites.
MIN_DELTA_HASARD = 0.02


def charger_bougies() -> list[dict]:
    """Les bougies du courtier, au format que le laboratoire parle déjà."""
    c = sqlite3.connect(BOUGIES)
    rows = c.execute(
        "SELECT ts_utc, open, high, low, close, spread_pts FROM candles "
        "WHERE pair = ? ORDER BY ts_utc", (PAIRE,)).fetchall()
    c.close()
    bougies = []
    for t, o, h, l, cl, sp in rows:
        d = datetime.fromisoformat(t)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        bougies.append({"t": d.astimezone(timezone.utc), "o": o, "h": h,
                        "l": l, "c": cl, "sp": sp})
    return bougies


def mesurer_un_seuil(bougies_m5: list[dict], seuil: float,
                     spread: float) -> list[dict]:
    """Les cellules `mean_reversion` pour UN seuil et UN spread.

    ⛔ Le seuil est posé sur le module de production, puis restauré. Le
    laisser déplacé ferait mesurer les cellules suivantes avec le réglage de
    la précédente — et le banc rendrait des chiffres qui ne correspondent à
    aucune configuration réelle.
    """
    avant = pd.MEAN_REVERSION_SIGMA
    pd.MEAN_REVERSION_SIGMA = seuil
    try:
        brut = labo.mesurer(bougies_m5, spread, pair=PAIRE)
    finally:
        pd.MEAN_REVERSION_SIGMA = avant

    gardees = []
    for cel in brut.get("cellules", []):
        if cel.get("motif") not in MOTIFS.values():
            continue
        gardees.append({**cel, "seuil": seuil, "spread": spread})
    return gardees


def verdict_cellule(cel: dict) -> str:
    """RETENU / INSUFFISANT / REFUTE, selon le critère pré-inscrit.

    ⛔ C'est `_verdict` DU LABORATOIRE qui tranche, avec le plafond de MES 24
    cellules. Recopier sa logique ici en ferait une seconde implémentation du
    verdict, et le banc pourrait un jour admettre ce que la sonde nocturne
    refuse — sans que rien ne le dise.

    ⚠️ Son `t_vs_hasard` est un t de Welch contre le contrôle aléatoire du
    MÊME SENS, et non le `t` brut de la cellule. Confronter le `t` brut au
    plafond est le défaut que le laboratoire a fermé le 2026-09-15 : sur une
    série qui dérive, tout achat a un `t` énorme — celui de la tendance.

    La seule condition que j'ajoute au-dessus de la sienne est
    `delta_hasard > 0,02`, pré-inscrite : battre le hasard d'un millième de R
    n'est pas le battre.
    """
    verdict = labo._verdict(cel, PLAFOND)
    if verdict != labo.RETENU:
        return verdict
    delta = cel.get("delta_hasard")
    if delta is None or delta <= MIN_DELTA_HASARD:
        return labo.REFUTE
    return labo.RETENU


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--essai", type=int, default=0, metavar="N",
                    help="ESSAI A BLANC sur les N dernieres bougies. "
                         "⛔ Rend 3 : la validite du rejeu n'est pas tenue, "
                         "et aucun verdict n'est publiable.")
    a = ap.parse_args(argv)

    bougies = charger_bougies()
    print("bougies M5 lues : %d" % len(bougies))

    if a.essai:
        bougies = bougies[-a.essai:]
        print("⚠️ ESSAI A BLANC sur %d bougies — ce n'est PAS une mesure."
              % len(bougies))

    if len(bougies) < MIN_BOUGIES and not a.essai:
        print("⛔ VALIDITE DU REJEU NON TENUE : %d bougies < %d exigees."
              % (len(bougies), MIN_BOUGIES))
        print("   Le banc s'arrete : mesurer sur une fenetre plus courte que")
        print("   celle annoncee rendrait un verdict sur autre chose.")
        return 2
    print("periode : %s -> %s" % (bougies[0]["t"].date(), bougies[-1]["t"].date()))
    print("cellules : %d   plafond du hasard : %.3f" % (CELLULES, PLAFOND))
    print("spreads  : %s   (verdict exige aux DEUX)" % (SPREADS,))
    print()

    toutes: list[dict] = []
    for spread in SPREADS:
        for seuil in SEUILS:
            cells = mesurer_un_seuil(bougies, seuil, spread)
            toutes.extend(cells)
            print("--- seuil %.1f sigma, spread %.2f : %d cellule(s)"
                  % (seuil, spread, len(cells)))
            for c in sorted(cells, key=lambda x: (x.get("horizon", ""),
                                                  x.get("motif", ""))):
                tvh = c.get("t_vs_hasard")
                print("    %-8s %-22s n=%-5s r=%+.4f t_vs_hasard=%s dh=%s  %s"
                      % (c.get("horizon", "?"), c.get("motif", "?"),
                         c.get("n", 0), c.get("r_moyen") or 0.0,
                         ("%+.2f" % tvh) if tvh is not None else " n/a ",
                         ("%+.4f" % c["delta_hasard"])
                         if c.get("delta_hasard") is not None else "  n/a ",
                         verdict_cellule(c)))
            print()

    # ─── Le critère, appliqué ────────────────────────────────────────
    # Une cellule n'est admise que si elle l'est aux DEUX spreads.
    par_cle: dict[tuple, list[dict]] = {}
    for c in toutes:
        par_cle.setdefault((c["seuil"], c.get("horizon"), c.get("motif")),
                           []).append(c)

    admises = [cle for cle, grp in par_cle.items()
               if len(grp) == len(SPREADS)
               and all(verdict_cellule(c) == labo.RETENU for c in grp)]

    t_max = max((c.get("t_vs_hasard") or 0.0) for c in toutes) if toutes else 0.0
    mesurables = [c for c in toutes if (c.get("n") or 0) >= labo.MIN_TRADES]
    refutees = [c for c in toutes if verdict_cellule(c) == labo.REFUTE]

    print("=" * 68)
    print("t_vs_hasard maximal : %+.3f   (plafond du hasard : %.3f)"
          % (t_max, PLAFOND))
    print("cellules mesurables (n >= %d) : %d / %d"
          % (labo.MIN_TRADES, len(mesurables), len(toutes)))
    if admises:
        print("CELLULES ADMISES aux deux spreads : %d" % len(admises))
        for seuil, horizon, motif in sorted(admises, key=str):
            print("   %.1f sigma  %-8s %s" % (seuil, horizon, motif))
    elif not mesurables:
        # ⚠️ INSUFFISANT n'est PAS REFUTE. Le dire autrement fermerait un motif
        # qui n'a simplement pas encore parle.
        print("AUCUNE cellule admise, et AUCUNE mesurable.")
        print("⇒ NON CONCLUANT : ce volume ne permet pas de trancher.")
        print("   La prediction 1 est FAUSSE : le detecteur ne declenche pas")
        print("   assez, meme sur 17 mois. Le sujet n'est donc pas son")
        print("   esperance mais sa condition — autre pre-inscription.")
    else:
        print("AUCUNE cellule admise  (%d refutee(s), %d mesurable(s))."
              % (len(refutees), len(mesurables)))
        print("⇒ NON ADMIS, comme predit. Rien a desserrer, rien a armer.")

    if a.essai:
        print()
        print("⛔ ESSAI A BLANC : validite du rejeu NON TENUE "
              "(%d bougies < %d). Aucun verdict publiable."
              % (len(bougies), MIN_BOUGIES))
        return 3

    with open("/app/data/banc_retour_moyenne_or.json", "w") as fh:
        json.dump({"cellules": toutes, "plafond": PLAFOND,
                   "t_max": t_max, "admises": [list(x) for x in admises],
                   "bougies": len(bougies)}, fh, default=str, indent=1)
    print("detail ecrit dans /app/data/banc_retour_moyenne_or.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
