#!/usr/bin/env python3
"""Sans gestion de sortie, on gagne plus par trade — mais combien de trades ?

Mesure du 2026-08-11 : sur l'or, la gestion de sortie coute **−0,329 R par
trade** (t = −4,38). Mais elle ferme les positions PLUS TOT, donc elle libere
les places. Avec `MAX_OPEN_POSITIONS = 3`, la supprimer allonge la duree de
detention et pourrait refuser des signaux. C'est le seul inconnu qui reste.

## La simulation

Evenements discrets, chronologiques. Chaque trade occupe une place jusqu'a sa
sortie — calculee sur les bougies M1, politique par politique. Un signal qui
arrive alors que les 3 places sont prises est **refuse**, et ce refus change
l'occupation pour la suite : c'est une boucle de retroaction, pas un simple
comptage.

⚠️ **Toutes les paires occupent des places**, y compris les cryptos placebo :
   elles ne rapportaient rien mais bloquaient bel et bien un creneau. Le R,
   lui, n'est compte que sur les instruments correctement dimensionnes.

⚠️ Fenetre bornee a 24 h. Un trade qui n'a touche aucun niveau est considere
   sorti au bout — ce qui SOUS-estime la duree de detention de la politique
   fixe, donc **sous-estime le cout en volume**. Le biais joue contre la
   conclusion qu'on cherche a valider.

Usage :
    python3 scripts/chiffrer_cout_en_volume.py
"""
import os
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
TRAIL_POINTS = 150
MAX_PLACES = 3
PAIRES_QUI_COMPTENT = {"XAU/USD", "WTI/USD"}

POLITIQUES = {
    "fixe (aucune gestion)": (None, 0),
    "BE 75% sans suiveur": (75, 0),
    "BE 50% + suiveur (PROD)": (50, TRAIL_POINTS),
}


def _point(pair):
    base = pair.split("/")[0].upper()
    quote = pair.split("/")[1].upper() if "/" in pair else ""
    if base in {"XAU", "XAG", "WTI"}:
        return 0.01
    if quote == "JPY":
        return 0.001
    return 0.00001


def _rejouer(bougies, entree, sl, tp, sens, seuil, trail, point):
    """Rend (R obtenu, index de la bougie de sortie)."""
    risque = abs(entree - sl)
    cible = (tp - entree) * sens
    declencheur = entree + sens * (seuil / 100.0) * cible if seuil is not None else None
    stop, arme, sommet = sl, False, entree

    for i, b in enumerate(bougies):
        favorable = b["h"] if sens > 0 else b["l"]
        defavorable = b["l"] if sens > 0 else b["h"]
        if (defavorable - stop) * sens <= 0:
            return (stop - entree) * sens / risque, i
        if (favorable - tp) * sens >= 0:
            return cible / risque, i
        if (favorable - sommet) * sens > 0:
            sommet = favorable
        if declencheur is not None and not arme and (favorable - declencheur) * sens >= 0:
            arme = True
            if (entree - stop) * sens > 0:
                stop = entree
        if arme and trail:
            cand = sommet - sens * trail * point
            if (cand - stop) * sens > 0:
                stop = cand
    return (bougies[-1]["c"] - entree) * sens / risque, len(bougies) - 1


def main() -> int:
    if not URL or not CLE:
        print("bridge demo non configure")
        return 1
    t = sqlite3.connect("/app/data/trades.db")
    t.row_factory = sqlite3.Row
    lignes = t.execute(
        "SELECT mt5_ticket, pair, direction, entry_price, stop_loss, take_profit, "
        "       created_at, closed_at FROM personal_trades "
        " WHERE status='CLOSED' ORDER BY created_at"
    ).fetchall()

    trades = []
    with httpx.Client() as client:
        for r in lignes:
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
                bg = client.get(f"{URL}/rates", params={
                    "pair": r["pair"], "timeframe": "M1",
                    "from": d0.isoformat(), "to": fin.isoformat()},
                    headers={"X-API-Key": CLE}, timeout=60).json().get("bougies", [])
            except Exception:
                continue
            if not bg:
                continue
            trades.append({"pair": r["pair"], "ouvert": d0, "bougies": bg,
                           "e": e, "sl": sl, "tp": tp, "sens": sens})
            if len(trades) % 100 == 0:
                print(f"  ... {len(trades)} trades charges")

    print()
    print(f"trades charges : {len(trades)}")
    print(f"places simultanees : {MAX_PLACES}")
    print()
    print("  %-26s %8s %10s %13s %12s" % (
        "politique", "pris", "refuses", "duree mediane", "R total*"))

    for nom, (seuil, trail) in POLITIQUES.items():
        ouvertes = []      # dates de liberation des places occupees
        pris = refuses = 0
        rs = []
        durees = []
        for tr in trades:
            ouvertes = [f for f in ouvertes if f > tr["ouvert"]]
            if len(ouvertes) >= MAX_PLACES:
                refuses += 1
                continue
            r, idx = _rejouer(tr["bougies"], tr["e"], tr["sl"], tr["tp"],
                              tr["sens"], seuil, trail, _point(tr["pair"]))
            sortie = datetime.fromisoformat(tr["bougies"][idx]["t"])
            ouvertes.append(sortie)
            pris += 1
            durees.append((sortie - tr["ouvert"]).total_seconds() / 60)
            if tr["pair"] in PAIRES_QUI_COMPTENT:
                rs.append(r)
        print("  %-26s %8d %10d %10.0f min %+11.2f R" % (
            nom, pris, refuses, statistics.median(durees) if durees else 0, sum(rs)))

    print()
    print("  * R total cumule sur XAU/USD et WTI/USD uniquement — les cryptos")
    print("    occupaient des places mais ne portaient aucun risque reel.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
