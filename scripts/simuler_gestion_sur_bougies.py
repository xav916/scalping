#!/usr/bin/env python3
"""Rejoue chaque trade sur le CHEMIN REEL du prix, minute par minute.

Remplace `scripts/simuler_seuil_breakeven.py`, qui ne pouvait rendre que des
bornes : `mfe_pct` / `mae_pct` sont des maxima SANS ordre chronologique, donc on
ignorait si le recul avait precede ou suivi l'avancee. A 50 %, l'intervalle
allait de −0,41 a +0,16 R — il contenait zero ET le << jamais >>.

Avec les bougies M1 (`/rates`, ajoute au bridge le 2026-08-11), l'ordre est
connu : on marche dans le temps et on sait exactement quand chaque niveau est
touche. Plus de bornes, une reponse.

## Ce qui est simule

- **fixe**       : SL et TP d'origine, aucune gestion. C'est la reference.
- **BE X%**      : le stop remonte a l'entree des que le prix a parcouru X % du
                   chemin vers l'objectif.
- **BE X% + suiveur** : idem, puis le stop suit le plus haut atteint a
                   TRAIL_DISTANCE_POINTS derriere (reglage reel du bridge).

## Les deux limites qui subsistent, enoncees plutot que cachees

⚠️ **Ordre INTRA-bougie inconnu.** Si une meme minute touche le stop ET
   l'objectif, on ne sait pas lequel en premier. On tranche TOUJOURS en faveur
   du scenario defavorable : le stop d'abord. Un resultat positif obtenu sous
   cette hypothese est donc un plancher, jamais une flatterie.

⚠️ **Ni spread ni commission.** La reference les ignore aussi, donc la
   COMPARAISON reste juste ; les niveaux absolus, eux, sont optimistes.

Usage :
    python3 scripts/simuler_gestion_sur_bougies.py [--limite N]
"""
import argparse
import os
import re
import sqlite3
import statistics
import sys
from datetime import datetime, timedelta
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.telegram_service import destination_for_ticket  # noqa: E402

URL = os.getenv("MT5_BRIDGE_URL")
CLE = os.getenv("MT5_BRIDGE_API_KEY")
FENETRE_MAX = timedelta(hours=24)
TRAIL_POINTS = 150          # TRAIL_DISTANCE_POINTS du bridge
SEUILS = [None, 0, 25, 40, 50, 60, 75, 90]   # None = pas de mise a zero


def _taille_du_point(pair: str) -> float:
    """Un << point >> au sens MT5, pas un pip. Conventions du courtier :
    5 decimales sur le forex, 3 sur les paires en yen, 2 sur les metaux.
    Verifie sur le ticket 82840896 : 150 points = 1,50 $ sur l'or."""
    base = pair.split("/")[0].upper()
    quote = pair.split("/")[1].upper() if "/" in pair else ""
    if base in {"XAU", "XAG", "WTI"}:
        return 0.01
    if quote == "JPY":
        return 0.001
    return 0.00001


def _bougies(client, pair, debut, fin):
    r = client.get(f"{URL}/rates", params={
        "pair": pair, "timeframe": "M1",
        "from": debut.isoformat(), "to": fin.isoformat(),
    }, headers={"X-API-Key": CLE}, timeout=60)
    r.raise_for_status()
    return r.json().get("bougies", [])


def _rejouer(bougies, entree, sl, tp, sens, seuil, trail, point):
    """Retourne le R obtenu. Marche dans le temps, bougie par bougie."""
    risque = abs(entree - sl)
    cible = (tp - entree) * sens
    declencheur = entree + sens * (seuil / 100.0) * cible if seuil is not None else None
    stop = sl
    arme = False
    sommet = entree

    for b in bougies:
        haut, bas = b["h"], b["l"]
        # Extremes du point de vue du trade : le favorable et le defavorable.
        favorable = haut if sens > 0 else bas
        defavorable = bas if sens > 0 else haut

        # ⚠️ Le defavorable est teste EN PREMIER : a l'interieur d'une minute on
        # ignore l'ordre, on retient donc toujours le pire scenario.
        if (defavorable - stop) * sens <= 0:
            return (stop - entree) * sens / risque
        if (favorable - tp) * sens >= 0:
            return cible / risque

        if (favorable - sommet) * sens > 0:
            sommet = favorable
        if declencheur is not None and not arme and (favorable - declencheur) * sens >= 0:
            arme = True
            if (entree - stop) * sens > 0:
                stop = entree
        if arme and trail:
            candidat = sommet - sens * trail * point
            if (candidat - stop) * sens > 0:
                stop = candidat

    # Fenetre epuisee sans toucher aucun niveau : on sort au dernier cours.
    if not bougies:
        return None
    return (bougies[-1]["c"] - entree) * sens / risque


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limite", type=int, default=0)
    args = ap.parse_args()
    if not URL or not CLE:
        print("bridge demo non configure")
        return 1

    t = sqlite3.connect("/app/data/trades.db")
    t.row_factory = sqlite3.Row
    lignes = t.execute(
        "SELECT mt5_ticket, pair, direction, entry_price, stop_loss, take_profit, "
        "       created_at, closed_at, notes "
        "  FROM personal_trades WHERE status = 'CLOSED' ORDER BY created_at DESC"
    ).fetchall()

    resultats = {("fixe" if s is None else f"BE {s}%"): [] for s in SEUILS}
    resultats.update({f"BE {s}% + suiveur": [] for s in SEUILS if s is not None})
    traites = sans_bougies = 0

    with httpx.Client() as client:
        for r in lignes:
            if args.limite and traites >= args.limite:
                break
            if not str(r["mt5_ticket"]).isdigit():
                continue
            if destination_for_ticket(int(r["mt5_ticket"])) != "admin_legacy":
                continue
            e, sl, tp = r["entry_price"], r["stop_loss"], r["take_profit"]
            if not e or not sl or not tp:
                continue
            sens = 1 if str(r["direction"]).lower().startswith("b") else -1
            if abs(e - sl) <= 0 or (tp - e) * sens <= 0:
                continue
            try:
                d0 = datetime.fromisoformat(str(r["created_at"]).replace("Z", "+00:00"))
            except Exception:
                continue
            try:
                d1 = datetime.fromisoformat(str(r["closed_at"]).replace("Z", "+00:00"))
            except Exception:
                d1 = d0 + FENETRE_MAX
            fin = min(d1 + timedelta(minutes=5), d0 + FENETRE_MAX)

            try:
                bg = _bougies(client, r["pair"], d0, fin)
            except Exception:
                continue
            if not bg:
                sans_bougies += 1
                continue

            point = _taille_du_point(r["pair"])
            for s in SEUILS:
                nom = "fixe" if s is None else f"BE {s}%"
                v = _rejouer(bg, e, sl, tp, sens, s, 0, point)
                if v is not None:
                    resultats[nom].append(v)
                if s is not None:
                    v2 = _rejouer(bg, e, sl, tp, sens, s, TRAIL_POINTS, point)
                    if v2 is not None:
                        resultats[f"BE {s}% + suiveur"].append(v2)
            traites += 1
            if traites % 100 == 0:
                print(f"  ... {traites} trades rejoues")

    print()
    print(f"trades rejoues sur bougies M1 : {traites}")
    print(f"  sans bougies disponibles    : {sans_bougies}")
    if not traites:
        return 1
    print()
    print("  %-22s %10s %10s %9s" % ("politique", "R moyen", "R median", "gagnants"))
    ref = statistics.mean(resultats["fixe"]) if resultats["fixe"] else 0
    for nom, vals in resultats.items():
        if not vals:
            continue
        m = statistics.mean(vals)
        ecart = "" if nom == "fixe" else "  (%+.4f)" % (m - ref)
        gag = 100 * sum(1 for v in vals if v > 0) / len(vals)
        print("  %-22s %+9.4f %+10.4f %8.1f%%%s" % (nom, m, statistics.median(vals), gag, ecart))
    print()
    print("⚠️ Ordre intra-minute inconnu : le stop est toujours teste AVANT")
    print("   l'objectif. Tout resultat positif est donc un plancher.")
    print("⚠️ Ni spread ni commission — la reference les ignore aussi, la")
    print("   comparaison reste juste, les niveaux absolus sont optimistes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
