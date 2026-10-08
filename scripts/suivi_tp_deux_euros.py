#!/usr/bin/env python3
"""Suivi de l'experience << TP de l'or a 2 EUR >> contre la prediction posee.

Xavier a demande cette configuration le 2026-10-08 CONTRE la mesure, et la
prediction a ete ecrite AVANT que ca tourne. Ce script la confronte au reel.

## 🔑 POURQUOI UN SCRIPT ET PAS UN COUP D'OEIL

Regarder la courbe quand elle plait est exactement ce qu'un banc existe pour
empecher. La prediction est figee ici en dur :

    esperance   -0,68 EUR / trade
    taux au TP   81,9 %   (requis 85,7 %)

⇒ Le script dit **de combien d'erreurs-types** le reel s'ecarte de la
prediction, et combien de trades il faudrait pour trancher. Il ne dit jamais
<< ca marche >> sur trois trades.

## ⚠️ L'ENTREE DU SIGNAL, ET LE PIEGE QUI A DEJA MORDU 4 FOIS

`entry_price` est le prix **EXECUTE**, `stop_loss` le niveau du **SIGNAL**, et
`slippage_pips` est stocke **SANS SIGNE**. Des deux candidats `fill ± slip`, on
retient celui qui rend 0,350 % de stop — la REGLE est l'arbitre, pas le signe
suppose.
"""
from __future__ import annotations

import math
import os
import sqlite3
import sys

DB = os.environ.get("TRADES_DB", "/app/data/trades.db")
# Borne : l'armement de l'experience. Aucun trade anterieur ne compte.
DEPUIS = os.environ.get("TP2_DEPUIS", "2026-10-08T12:34:15")
CIBLE_EUR = 2.0
PREDIT_EUR_PAR_TRADE = -0.68
PREDIT_TAUX_TP = 0.819
REQUIS_TAUX_TP = 0.857


def _entree_signal(fill: float, slip_pips: float, stop: float) -> float:
    """🔑 La REGLE arbitre, pas le signe du slippage (stocke sans signe)."""
    candidats = (fill + slip_pips / 100.0, fill - slip_pips / 100.0)
    return min(candidats, key=lambda e: abs(abs(stop - e) / e * 100 - 0.35))


def main() -> int:
    c = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    lignes = list(c.execute(
        "SELECT id,direction,entry_price,stop_loss,take_profit,slippage_pips,"
        "       signal_pattern,horizon,status,pnl,close_reason,created_at "
        "FROM personal_trades WHERE pair LIKE '%XAU%' AND created_at > ? "
        "  AND is_auto = 1 ORDER BY id", (DEPUIS,)))

    print("=== EXPERIENCE : TP DE L'OR A 2 EUR ===")
    print("    borne : %s   (trades AUTOMATIQUES de l'or uniquement)" % DEPUIS)
    print("")
    if not lignes:
        print("    aucun trade encore. Rien a lire — et c'est normal.")
        return 0

    armes, hors, fermes, exclus, pnl = 0, [], [], [], 0.0
    print("    %-6s %-5s %-22s %-7s %8s %8s  %-10s %9s"
          % ("id", "sens", "motif", "horizon", "stop $", "cible $", "etat", "pnl EUR"))
    for (i, d, ent, sl, tp, slip, mot, hz, st, p, cr, qd) in lignes:
        ent, sl, tp, slip = float(ent or 0), float(sl or 0), float(tp or 0), float(slip or 0)
        if not (ent and sl and tp):
            continue
        e = _entree_signal(ent, slip, sl)
        dsl, dtp = abs(sl - e), abs(tp - e)
        arme = 2.0 < dtp < 2.6          # la cible en euros, au taux du jour
        armes += arme
        if not arme:
            hors.append((i, dtp, dtp / dsl if dsl else 0))
        # ⛔ Un trade HORS CIBLE n'est PAS l'experience : le compter
        # contaminerait l'EUR/trade par un gain a 1,8 R. Il est affiche, et
        # signale, mais il ne pese pas dans le verdict.
        if st == "CLOSED" and arme:
            fermes.append((i, float(p or 0), cr))
            pnl += float(p or 0)
        elif st == "CLOSED":
            exclus.append((i, float(p or 0)))
        print("    %-6s %-5s %-22s %-7s %8.3f %8.3f  %-10s %9.2f%s"
              % (i, d, str(mot)[:22], hz, dsl, dtp, st, float(p or 0),
                 "" if arme else "   <- PAS la cible de 2 EUR"))

    print("")
    print("    trades             %d   dont %d a la cible de 2 EUR" % (len(lignes), armes))
    if hors:
        print("    ⛔ %d HORS CIBLE : %s" % (
            len(hors), ", ".join("#%s %.2f $ (%.2f R)" % h for h in hors[:5])))
        print("       -> verifier si un motif passe par une branche qui garde 1,8 R")

    n = len(fermes)
    if exclus:
        print("    ⛔ %d trade(s) ferme(s) EXCLU(S) du verdict (hors cible) : %s"
              % (len(exclus), ", ".join("#%s %+.2f EUR" % e for e in exclus[:5])))
    print("")
    print("=== LE REEL CONTRE LA PREDICTION ===")
    if n == 0:
        print("    aucun trade FERME : rien a trancher.")
        return 0
    gagnants = sum(1 for _, p, _ in fermes if p > 0)
    taux = gagnants / n
    moy = pnl / n
    print("    fermes             %d" % n)
    print("    au TP              %d / %d = %.1f %%   (predit %.1f %%, requis %.1f %%)"
          % (gagnants, n, taux * 100, PREDIT_TAUX_TP * 100, REQUIS_TAUX_TP * 100))
    print("    EUR / trade        %+.2f              (predit %+.2f)"
          % (moy, PREDIT_EUR_PAR_TRADE))
    print("    cumul              %+.2f EUR" % pnl)
    print("")
    # ⛔ L'erreur-type, pour ne PAS lire un ecart qui n'existe pas.
    se = math.sqrt(PREDIT_TAUX_TP * (1 - PREDIT_TAUX_TP) / n)
    z = (taux - PREDIT_TAUX_TP) / se if se else 0.0
    print("    ecart au taux predit : z = %+.2f  (erreur-type %.1f points)"
          % (z, se * 100))
    if abs(z) < 2:
        # ⚠️ Projeter << combien de trades de plus >> depuis un ecart quasi nul
        # rend un nombre absurde (900 000 trades pour trancher 0,1 point). Le
        # dire ainsi serait du bruit : a ce stade, le reel est simplement
        # CONFONDU avec la prediction.
        ecart = abs(taux - PREDIT_TAUX_TP)
        if ecart < 0.5 * se:
            print("    ⇒ INDECIDABLE : le reel est CONFONDU avec la prediction")
            print("       (ecart %.1f point contre une erreur-type de %.1f)."
                  % (ecart * 100, se * 100))
        else:
            besoin = max(0, int(math.ceil(
                PREDIT_TAUX_TP * (1 - PREDIT_TAUX_TP) * (2 / ecart) ** 2)) - n)
            print("    ⇒ INDECIDABLE. A cet ecart il faudrait ~%d trades de plus."
                  % besoin)
    elif z > 0:
        print("    ⇒ le reel fait MIEUX que ma prediction : c'est ma mesure a revoir.")
    else:
        print("    ⇒ le reel fait PIRE que ma prediction.")
    print("")
    print("    ⚠️ Moins de 30 trades fermes ne tranche rien, quel que soit le signe.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
