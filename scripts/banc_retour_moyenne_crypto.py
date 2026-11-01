#!/usr/bin/env python3
"""Le retour a la moyenne sur BTC et ETH -- le banc.

Pre-inscription : `docs/predictions/2026-11-01_retour-moyenne-btc-eth.md`,
commitee AVANT ce fichier et dont le bloc machine ne sera plus touche.

## Pourquoi ces deux paires

`mean_reversion` est arme sur le demo PLUS LARGEMENT sur la crypto que sur
l'or : BTC et ETH dans les DEUX sens, l'or en vente seulement. Le verdict du
01/11 a rejete le motif sur l'or ; les deux paires les plus largement armees
n'avaient jamais ete mesurees.

## ⚠️ Deux limites, assumees d'avance

**Source Twelve Data**, et il n'existe AUCUNE bougie courtier pour la crypto :
ce verdict ne pourra jamais etre « refait sur bougies courtier » comme la regle
du depot l'exige pour un banc d'objectif ou de stop. Il restera le meilleur
disponible, pas un definitif.

**Spread non mesure chez le courtier.** Mesure sur Kraken le 2026-11-01 :
BTC 1,00 $ (0,0013 % du prix), ETH 0,10 $ (0,0044 %) -- des futures
perpetuels, plus serres qu'un CFD MT5. On encadre : borne basse = la valeur
mesuree, borne haute = un CFD pessimiste.

🔑 Le sens de l'erreur est SUR pour une refutation : un spread plus serre ne
peut qu'AIDER le motif. Un echec a la borne basse ne s'explique donc pas par
un cout surestime.

## Ce qu'il emet

Un JSON PLAT dont chaque champ cite par le critere existe reellement, y
compris les seuils appliques -- pour que les clauses de validite les EPINGLENT.

Usage, dans le conteneur de production :

    sudo docker exec -e PYTHONPATH=/app -w /app scalping-radar \\
      python scripts/banc_retour_moyenne_crypto.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/app")

from backend.services import laboratoire_or as labo       # noqa: E402
from backend.services import pattern_detector as pd       # noqa: E402

# ⛔ Twelve Data : la colonne est `ts`, pas `ts_utc`, et il n'y a pas de
# `spread_pts`. Supposer le schema du magasin courtier rendrait une fenetre
# vide en croyant lire trois ans.
ARCHIVE = "/app/data/candles_5min.db"
DEBUT, FIN = "2023-08-01", "2026-08-09"      # borne haute EXCLUE

SEUILS = (1.5, 2.0, 2.5)
MOTIFS = ("mean_reversion_up", "mean_reversion_down")

# (paire, spread BAS mesure sur Kraken, spread HAUT pessimiste type CFD)
PAIRES = (
    ("BTC/USD", 1.00, 40.00),
    ("ETH/USD", 0.10, 3.00),
)

# 48 = 3 seuils x 4 echelles x 2 sens x 2 paires.
CELLULES = len(SEUILS) * len(labo.ECHELLES) * len(MOTIFS) * len(PAIRES)
PLAFOND = labo.plafond_hasard(CELLULES)      # 2.496

MIN_DELTA_HASARD = 0.02
MIN_TRADES = labo.MIN_TRADES
MIN_BOUGIES = 600_000
MAX_NON_RESOLUS_PCT = 5.0


def charger(paire: str) -> list[dict]:
    c = sqlite3.connect(ARCHIVE)
    rows = c.execute(
        "SELECT ts, open, high, low, close FROM candles "
        "WHERE pair = ? AND ts >= ? AND ts < ? ORDER BY ts",
        (paire, DEBUT, FIN)).fetchall()
    c.close()
    out = []
    for t, o, h, l, cl in rows:
        d = datetime.fromisoformat(str(t))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        out.append({"t": d, "o": o, "h": h, "l": l, "c": cl})
    return out


def verdict_cellule(cel: dict) -> str:
    """Le verdict DU LABORATOIRE, avec le plafond des 48 cellules, plus la
    seule clause pre-inscrite que j'ajoute (`delta_hasard > 0,02`).

    ⛔ Recopier sa logique ici en ferait une seconde implementation, et le banc
    pourrait un jour admettre ce que la sonde nocturne refuse.
    """
    v = labo._verdict(cel, PLAFOND)
    if v != labo.RETENU:
        return v
    d = cel.get("delta_hasard")
    return labo.RETENU if (d is not None and d > MIN_DELTA_HASARD) \
        else labo.REFUTE


def main() -> int:
    toutes: list[dict] = []
    bougies_lues = 0
    paires_faites = 0

    for paire, bas, haut in PAIRES:
        bougies = charger(paire)
        print("=== %s : %d bougies M5  (%s -> %s)"
              % (paire, len(bougies),
                 bougies[0]["t"].date() if bougies else "?",
                 bougies[-1]["t"].date() if bougies else "?"))
        if not bougies:
            print("    AUCUNE bougie, paire ecartee")
            continue
        bougies_lues += len(bougies)
        paires_faites += 1

        for spread in (bas, haut):
            etiquette = "BAS (mesure)" if spread == bas else "HAUT (CFD pessimiste)"
            for seuil in SEUILS:
                avant = pd.MEAN_REVERSION_SIGMA
                pd.MEAN_REVERSION_SIGMA = seuil
                try:
                    brut = labo.mesurer(bougies, spread, pair=paire)
                finally:
                    pd.MEAN_REVERSION_SIGMA = avant
                cells = [{**c, "seuil": seuil, "spread": spread, "paire": paire}
                         for c in brut.get("cellules", [])
                         if c.get("motif") in MOTIFS]
                toutes.extend(cells)
                print("  --- %.1f sigma, spread %.2f %s" % (seuil, spread, etiquette))
                for c in sorted(cells, key=lambda x: (x.get("horizon", ""),
                                                      x.get("motif", ""))):
                    tvh = c.get("t_vs_hasard")
                    print("      %-8s %-22s n=%-6s nr=%-5s r=%+.4f tvh=%s dh=%s  %s"
                          % (c.get("horizon", "?"), c.get("motif", "?"),
                             c.get("n", 0), c.get("non_resolus", 0),
                             c.get("r_moyen") or 0.0,
                             ("%+.2f" % tvh) if tvh is not None else " n/a ",
                             ("%+.4f" % c["delta_hasard"])
                             if c.get("delta_hasard") is not None else "  n/a ",
                             verdict_cellule(c)))
        print()

    # ─── Les agregats que le critere engage, NOM PAR NOM ─────────────
    # Une hypothese = (paire, seuil, echelle, sens). Elle n'est retenue ou
    # mesurable que si elle l'est aux DEUX spreads -- la conjonction
    # pre-inscrite.
    par_hypothese: dict[tuple, list[dict]] = {}
    for c in toutes:
        par_hypothese.setdefault(
            (c["paire"], c["seuil"], c.get("echelle"), c.get("sens")), []
        ).append(c)

    complets = [g for g in par_hypothese.values() if len(g) == 2]
    retenues = [g for g in complets
                if all(verdict_cellule(c) == labo.RETENU for c in g)]
    mesurables = [g for g in complets
                  if all((c.get("n") or 0) >= MIN_TRADES for c in g)]

    trades = sum((c.get("n") or 0) for c in toutes)
    non_res = sum((c.get("non_resolus") or 0) for c in toutes)
    non_resolus_pct = (100.0 * non_res / trades) if trades else 0.0
    t_max = max((c.get("t_vs_hasard") or 0.0) for c in toutes) if toutes else 0.0

    valide = bool(bougies_lues >= MIN_BOUGIES
                  and non_resolus_pct < MAX_NON_RESOLUS_PCT
                  and paires_faites >= 2)

    resultat = {
        "forme": "placebo",
        "n": trades,
        "t": t_max,
        "valide": valide,
        "cellules_retenues": len(retenues),
        "cellules_mesurables": len(mesurables),
        "non_resolus_pct": round(non_resolus_pct, 4),
        "bougies_m5": bougies_lues,
        "paires_mesurees": paires_faites,
        "plafond_applique": PLAFOND,
        "min_delta_hasard_applique": MIN_DELTA_HASARD,
        "min_trades_applique": MIN_TRADES,
        "spreads_exiges": 2,
        "t_vs_hasard_max": t_max,
        "fenetre": [DEBUT, FIN],
        "source": ARCHIVE,
        "cellules": toutes,
    }

    print("=" * 72)
    for cle in ("n", "t", "valide", "cellules_retenues", "cellules_mesurables",
                "non_resolus_pct", "bougies_m5", "paires_mesurees",
                "plafond_applique", "min_delta_hasard_applique",
                "min_trades_applique", "spreads_exiges"):
        print("  %-28s %s" % (cle, resultat[cle]))

    # Par paire, pour la prediction 4 : BTC et ETH doivent se comporter pareil.
    print("  --- t_vs_hasard maximal par paire ---")
    for paire, _, _ in PAIRES:
        vals = [c.get("t_vs_hasard") or 0.0 for c in toutes if c["paire"] == paire]
        if vals:
            print("  %-28s %+.3f" % (paire, max(vals)))

    chemin = "/app/data/banc_retour_moyenne_crypto.json"
    with open(chemin, "w") as fh:
        json.dump(resultat, fh, default=str, indent=1)
    print()
    print("resultat ecrit dans %s" % chemin)
    print("⛔ AUCUN VERDICT ICI : il sort de or-verdict, pas de ce banc.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
