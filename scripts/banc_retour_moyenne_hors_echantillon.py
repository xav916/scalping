#!/usr/bin/env python3
"""Le retour à la moyenne, HORS ÉCHANTILLON — le banc.

Pré-inscription : `docs/predictions/2026-11-01_retour-moyenne-hors-echantillon.md`,
commitée AVANT ce fichier et dont le bloc machine ne sera plus touché.

## La fenêtre

XAU/USD, **2023-08-01 → 2025-05-13**, 125 845 bougies M5 — toute la période
**antérieure** au magasin du courtier, que la première mesure a consommé en
entier. Jamais lue par moi.

## ⚠️ LA LIMITE, assumée

Cette fenêtre vient de `candles_5min.db`, donc de **Twelve Data**, dont ce
dépôt a mesuré l'écart aux bougies du courtier (3,807 $ de médiane sur quinze
mois à décalage unique) et conclu qu'un banc d'OBJECTIF ou de STOP doit être
refait sur bougies courtier avant d'être tenu pour acquis. Ce banc place une
entrée, un stop et un objectif.

⛔ Il ne peut donc rendre qu'une **réfutation** utile. Une admission serait
suspecte par construction et exigerait une reprise sur bougies courtier avant
tout armement — c'est écrit dans la pré-inscription.

## Ce qu'il émet

Un JSON **plat**, dont chaque champ cité par le critère existe réellement :

    forme, n, t, valide, cellules_retenues, cellules_mesurables,
    non_resolus_pct, bougies_m5, plafond_applique,
    min_delta_hasard_applique, min_trades_applique, spreads_exiges

🔑 Les quatre derniers sont les seuils que CE banc applique, publiés pour que
les clauses de validité les épinglent. Un seuil qui dérive dans le code sans
bouger dans le critère est la faute que ce lien nom-par-nom empêche.

Usage, dans le conteneur de production :

    sudo docker exec -e PYTHONPATH=/app -w /app scalping-radar \\
      python scripts/banc_retour_moyenne_hors_echantillon.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/app")

from backend.services import laboratoire_or as labo       # noqa: E402
from backend.services import pattern_detector as pd       # noqa: E402

# ⛔ Twelve Data, et le schéma diffère du magasin courtier : la colonne est
# `ts`, pas `ts_utc`, et il n'y a pas de `spread_pts`. Supposer l'un pour
# l'autre rendrait un magasin vide en croyant lire une fenêtre.
ARCHIVE = "/app/data/candles_5min.db"
PAIRE = "XAU/USD"
DEBUT, FIN = "2023-08-01", "2025-05-14"     # borne haute EXCLUE

SEUILS = (1.5, 2.0, 2.5)
MOTIFS = ("mean_reversion_up", "mean_reversion_down")
SPREADS = (0.20, 0.50)

CELLULES = len(SEUILS) * len(labo.ECHELLES) * len(MOTIFS)   # 24
PLAFOND = labo.plafond_hasard(CELLULES)                     # 2.241

# Les seuils appliqués, publiés pour être épinglés par le critère.
MIN_DELTA_HASARD = 0.02
MIN_TRADES = labo.MIN_TRADES

# Validité pré-inscrite.
MIN_BOUGIES = 120_000
MAX_NON_RESOLUS_PCT = 5.0


def charger() -> list[dict]:
    c = sqlite3.connect(ARCHIVE)
    rows = c.execute(
        "SELECT ts, open, high, low, close FROM candles "
        "WHERE pair = ? AND ts >= ? AND ts < ? ORDER BY ts",
        (PAIRE, DEBUT, FIN)).fetchall()
    c.close()
    out = []
    for t, o, h, l, cl in rows:
        d = datetime.fromisoformat(str(t))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        out.append({"t": d, "o": o, "h": h, "l": l, "c": cl})
    return out


def verdict_cellule(cel: dict) -> str:
    """Le verdict DU LABORATOIRE, avec le plafond des 24 cellules, plus la
    seule clause pré-inscrite que j'ajoute (`delta_hasard > 0,02`)."""
    v = labo._verdict(cel, PLAFOND)
    if v != labo.RETENU:
        return v
    d = cel.get("delta_hasard")
    return labo.RETENU if (d is not None and d > MIN_DELTA_HASARD) \
        else labo.REFUTE


def main() -> int:
    bougies = charger()
    print("fenetre : %s -> %s (borne haute exclue)" % (DEBUT, FIN))
    print("bougies M5 lues : %d" % len(bougies))
    if bougies:
        print("reellement : %s -> %s" % (bougies[0]["t"].date(),
                                         bougies[-1]["t"].date()))
    print("cellules : %d   plafond : %.3f   spreads : %s"
          % (CELLULES, PLAFOND, SPREADS))
    print()

    toutes: list[dict] = []
    for spread in SPREADS:
        for seuil in SEUILS:
            avant = pd.MEAN_REVERSION_SIGMA
            pd.MEAN_REVERSION_SIGMA = seuil
            try:
                brut = labo.mesurer(bougies, spread, pair=PAIRE)
            finally:
                pd.MEAN_REVERSION_SIGMA = avant
            cells = [{**c, "seuil": seuil, "spread": spread}
                     for c in brut.get("cellules", [])
                     if c.get("motif") in MOTIFS]
            toutes.extend(cells)
            print("--- %.1f sigma, spread %.2f" % (seuil, spread))
            for c in sorted(cells, key=lambda x: (x.get("horizon", ""),
                                                  x.get("motif", ""))):
                tvh = c.get("t_vs_hasard")
                print("    %-8s %-22s n=%-5s nr=%-4s r=%+.4f tvh=%s dh=%s  %s"
                      % (c.get("horizon", "?"), c.get("motif", "?"),
                         c.get("n", 0), c.get("non_resolus", 0),
                         c.get("r_moyen") or 0.0,
                         ("%+.2f" % tvh) if tvh is not None else " n/a ",
                         ("%+.4f" % c["delta_hasard"])
                         if c.get("delta_hasard") is not None else "  n/a ",
                         verdict_cellule(c)))
            print()

    # ─── Les agrégats que le critère engage, NOM PAR NOM ─────────────
    # Une hypothèse = (seuil, échelle, sens). Elle n'est retenue ou mesurable
    # que si elle l'est aux DEUX spreads — la conjonction pré-inscrite.
    par_hypothese: dict[tuple, list[dict]] = {}
    for c in toutes:
        par_hypothese.setdefault(
            (c["seuil"], c.get("echelle"), c.get("sens")), []).append(c)

    complets = [g for g in par_hypothese.values() if len(g) == len(SPREADS)]
    retenues = [g for g in complets
                if all(verdict_cellule(c) == labo.RETENU for c in g)]
    mesurables = [g for g in complets
                  if all((c.get("n") or 0) >= MIN_TRADES for c in g)]

    trades = sum((c.get("n") or 0) for c in toutes)
    non_resolus = sum((c.get("non_resolus") or 0) for c in toutes)
    non_resolus_pct = (100.0 * non_resolus / trades) if trades else 0.0
    t_max = max((c.get("t_vs_hasard") or 0.0) for c in toutes) if toutes else 0.0

    # ⛔ `valide` dit si le REJEU tient, pas si le motif marche. La porte
    # recalcule les clauses de toute façon — ce drapeau ne peut qu'ajouter un
    # refus, jamais en retirer un.
    valide = bool(len(bougies) >= MIN_BOUGIES
                  and non_resolus_pct < MAX_NON_RESOLUS_PCT)

    resultat = {
        "forme": "placebo",
        "n": trades,
        "t": t_max,
        "valide": valide,
        "cellules_retenues": len(retenues),
        "cellules_mesurables": len(mesurables),
        "non_resolus_pct": round(non_resolus_pct, 4),
        "bougies_m5": len(bougies),
        "plafond_applique": PLAFOND,
        "min_delta_hasard_applique": MIN_DELTA_HASARD,
        "min_trades_applique": MIN_TRADES,
        "spreads_exiges": len(SPREADS),
        "t_vs_hasard_max": t_max,
        "fenetre": [DEBUT, FIN],
        "source": ARCHIVE,
        "cellules": toutes,
    }

    print("=" * 70)
    for cle in ("n", "t", "valide", "cellules_retenues", "cellules_mesurables",
                "non_resolus_pct", "bougies_m5", "plafond_applique",
                "min_delta_hasard_applique", "min_trades_applique",
                "spreads_exiges"):
        print("  %-28s %s" % (cle, resultat[cle]))

    chemin = "/app/data/banc_retour_moyenne_hors_echantillon.json"
    with open(chemin, "w") as fh:
        json.dump(resultat, fh, default=str, indent=1)
    print()
    print("resultat ecrit dans %s" % chemin)
    print("⛔ AUCUN VERDICT ICI : il sort de or-verdict, pas de ce banc.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
