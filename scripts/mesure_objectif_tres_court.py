#!/usr/bin/env python3
"""Un objectif TRES COURT paie-t-il ? Mesure sur 360 784 trades.

Question de Xavier le 2026-10-08 : « mettre des TP tres bas, proche de
l'ouverture, pour empocher ce tres petit gain ».

## 🔑 POURQUOI CETTE MESURE EST VOLONTAIREMENT TROP GENEREUSE

On se sert de `mfe_pct`, la meilleure excursion favorable du trade. On suppose
qu'un objectif place a `x` R est atteint des que `mfe >= x`.

⛔ C'est FAUX dans le sens FAVORABLE : `mfe_pct` et `mae_pct` sont des maxima
SANS ORDRE. Un trade qui a touche son stop PUIS remonte compte ici comme
gagnant. Le laboratoire, lui, teste toujours le stop AVANT l'objectif,
precisement pour ne pas fabriquer de performance.

🔑 Et c'est ce qui rend la mesure utile : elle est **optimiste par
construction**. Si l'objectif court echoue MEME AINSI, la question est
tranchee. S'il reussit, cela ne prouve rien — il faudra le banc complet.

## Le cout, qui est le sujet

Le modele du depot facture le rapport notionnel/risque :

    cout_R = (entree / distance_du_stop) x 0,00005 x 2 jambes

Un objectif court ne reduit PAS ce cout : il reduit le gain. Le cout est le
meme pour viser 0,2 R ou 2 R, et il se paie dans les deux cas.
"""
from __future__ import annotations

import sqlite3
import statistics
import sys
from pathlib import Path

DB = "/app/data/backtest.db"
EXCLUES = ("WTI/USD", "MSFT", "NVDA", "TSLA", "AAPL", "SPX")

# Objectifs balayes, en R. 1,8 est la regle en place.
OBJECTIFS = (0.1, 0.2, 0.3, 0.5, 0.8, 1.0, 1.5, 1.8, 2.5)

# Cout en R, mesure sur ce depot : l'or a 0,35 % de stop paie
# (1 / 0.0035) x 1e-4 x ... -> ~0,029 R par aller-retour. On balaye deux
# valeurs pour que le verdict ne depende pas d'un seul chiffre.
COUTS = (0.029, 0.058)


def charger():
    """(mfe en R, R realise) par trade, converti EXACTEMENT. Lecture seule.

    ⛔ Ma premiere version convertissait `mfe_pct` en R avec UNE calibration
    mediane pour tous les trades. C'etait faux : chaque trade a SA distance de
    stop, et un trade au stop serre atteint 1,8 R avec une excursion bien plus
    petite. Les niveaux absolus en sortaient inutilisables (-0,24 la ou le R
    reel moyen vaut +0,037).

    🔑 Ici la conversion est exacte, trade par trade :

        mfe_en_R = (mfe_pct / 100 x entree) / |entree - stop|

    `entry_price`, `stop_loss` : les deux sont en base. Aucune calibration.
    """
    out = []
    with sqlite3.connect(f"file:{Path(DB)}?mode=ro", uri=True) as c:
        for paire, rr, mfe, e, sl in c.execute(
                "SELECT pair, rr_realized, mfe_pct, entry_price, stop_loss "
                "FROM trades WHERE outcome IS NOT NULL AND outcome <> 'OPEN' "
                "AND rr_realized IS NOT NULL AND mfe_pct IS NOT NULL "
                "AND entry_price IS NOT NULL AND stop_loss IS NOT NULL"):
            if paire in EXCLUES:
                continue
            e = float(e); sl = float(sl)
            risque = abs(e - sl)
            if risque <= 0 or e <= 0:
                continue
            out.append(((float(mfe) / 100.0 * e) / risque, float(rr)))
    return out


def main() -> int:
    lignes = charger()
    print("=== UN OBJECTIF TRES COURT PAIE-T-IL ? ===")
    print(f"    {len(lignes)} trades, mesure VOLONTAIREMENT optimiste")
    print("    (on suppose l objectif atteint des que mfe >= objectif,")
    print("     sans verifier que le stop n a pas ete touche AVANT)\n")

    reels = [rr for _mfe, rr in lignes]
    print(f"  temoin : R realise moyen de la population = "
          f"{statistics.fmean(reels):+.4f}")
    print("  (une re-simulation qui s en ecarte beaucoup a 1,8 R est suspecte)")
    print("")

    for cout in COUTS:
        print(f"  --- cout {cout:.3f} R par aller-retour ---")
        print(f"  {'objectif':>9s} {'atteint':>8s} {'R moyen':>9s} "
              f"{'% gagnants':>11s} {'reussite requise':>17s}")
        for obj in OBJECTIFS:
            rs = []
            touche = 0
            for mfe, _rr in lignes:
                if mfe >= obj:
                    rs.append(obj - cout)
                    touche += 1
                else:
                    rs.append(-1.0 - cout)
            moy = statistics.fmean(rs)
            gag = touche * 100 / len(rs)
            requis = 100 / (1 + obj / 1.0) if obj > 0 else 100.0
            marque = "  <- regle en place" if abs(obj - 1.8) < 1e-9 else ""
            print(f"  {obj:9.2f} {touche:8d} {moy:+9.4f} {gag:10.1f} % "
                  f"{requis:16.1f} %{marque}")
        print()

    print("  🔑 Lecture : « reussite requise » est le taux qu il FAUT pour ne")
    print("     rien perdre a cet objectif, AVANT cout. Un objectif court la")
    print("     fait monter vers 100 %, et le cout s ajoute par-dessus.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
