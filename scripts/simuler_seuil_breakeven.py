#!/usr/bin/env python3
"""A quel seuil faut-il ramener le stop a l'entree ?

`BREAKEVEN_TRIGGER_PCT = 50` : des qu'un trade a parcouru la moitie du chemin
vers son objectif, le stop remonte au prix d'entree. Mesure le 2026-08-11, ce
reglage **aplatit tout** — il efface la perte sur les trades perdants
(−1,00 → −0,03 R) mais rabote les gagnants dans la meme proportion
(+3,00 → +0,06 R). Les deux effets s'annulent.

Ce script rejoue les memes trades a differents seuils, a partir de `mfe_pct`
(plus forte avancee favorable) et `mae_pct` (pire recul), pour trouver ou placer
le curseur.

## Ce que la donnee permet — et ce qu'elle ne permet PAS

⚠️ `mfe_pct` et `mae_pct` sont des MAXIMA, sans ordre chronologique entre eux.
   On ne sait donc pas si le recul est survenu avant ou apres l'avancee.

Consequence, et c'est la seule facon honnete de traiter ce trou :

- **Trades PERDANTS : l'ordre est force.** Le stop est touche a la FIN (c'est ce
  qui clot le trade), donc l'avancee favorable lui est forcement anterieure. Si
  elle atteint le seuil, la mise a zero du risque etait armee et le trade sort a
  0 au lieu de −1 R. **Aucune ambiguite.**

- **Trades GAGNANTS : l'ordre est inconnu.** Si le recul precede le declenchement
  du seuil, le gain est preserve ; s'il le suit, le trade sort a 0. On calcule
  donc les DEUX bornes et on les affiche. La verite est entre les deux.

Un resultat qui ne tient que dans la borne favorable n'est pas un resultat.

Usage :
    python3 scripts/simuler_seuil_breakeven.py
"""
import re
import sqlite3
import statistics
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.telegram_service import destination_for_ticket  # noqa: E402

FENETRE_AVANT = timedelta(minutes=90)
FENETRE_APRES = timedelta(minutes=30)
TOLERANCE_PRIX = 0.002
SEUILS = [0, 25, 40, 50, 60, 75, 90, None]  # None = jamais de mise a zero


def _dt(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def _sens(direction: str) -> int:
    return 1 if str(direction).strip().lower().startswith("b") else -1


def _collecter():
    t = sqlite3.connect("/app/data/trades.db")
    t.row_factory = sqlite3.Row
    b = sqlite3.connect("/app/data/backtest.db")
    b.row_factory = sqlite3.Row

    lignes = t.execute(
        "SELECT mt5_ticket, pnl, notes, pair, direction, entry_price, stop_loss, "
        "       take_profit, created_at "
        "  FROM personal_trades WHERE status = 'CLOSED'"
    ).fetchall()

    out = []
    for r in lignes:
        if not str(r["mt5_ticket"]).isdigit():
            continue
        if destination_for_ticket(int(r["mt5_ticket"])) != "admin_legacy":
            continue
        d0 = _dt(r["created_at"])
        e, sl, tp = r["entry_price"], r["stop_loss"], r["take_profit"]
        if not d0 or not e or not sl or not tp:
            continue
        s = _sens(r["direction"])
        risque = abs(e - sl)
        cible = (tp - e) * s
        if risque <= 0 or cible <= 0:
            continue
        m = re.search(r"risk_money=([0-9.]+)", r["notes"] or "")
        if not m or float(m.group(1)) <= 0:
            continue

        cands = b.execute(
            "SELECT outcome, rr_realized, mfe_pct, mae_pct, entry_price FROM trades "
            " WHERE pair = ? AND direction = ? AND outcome != 'OPEN' "
            "   AND emitted_at BETWEEN ? AND ?",
            (r["pair"], r["direction"],
             (d0 - FENETRE_AVANT).isoformat(), (d0 + FENETRE_APRES).isoformat()),
        ).fetchall()
        proches = [c for c in cands
                   if abs(c["entry_price"] - e) <= abs(e) * TOLERANCE_PRIX]
        if not proches or len({c["outcome"] for c in proches}) > 1:
            continue

        # ⛔ Un zero d'excursion n'est PAS une mesure. Preuve logique : 9 055
        # trades etiquetes WIN_TP1 portent mfe_pct = 0, alors qu'atteindre son
        # objectif impose une avancee au moins egale a la distance du TP. Ces
        # zeros veulent dire << non mesure >>. 31 % des mfe_pct et 25 % des
        # mae_pct sont dans ce cas.
        #
        # Les garder faisait conclure qu'un seuil de 0 % dominait : ses
        # << gagnants sans recul >> etaient des mae_pct non mesures.
        #
        # ⚠️ Ce filtre ecarte aussi de vrais zeros (un trade qui n'est
        # effectivement jamais parti a contresens). On ne sait pas les
        # distinguer — on prefere un echantillon plus petit a un resultat faux.
        proches = [c for c in proches if c["mfe_pct"] and c["mae_pct"]]
        if not proches:
            continue

        out.append({
            "issue": proches[0]["outcome"],
            "r_fixe": statistics.median([c["rr_realized"] for c in proches]),
            # MFE/MAE sont en % du prix ; on les convertit en multiples de R.
            "mfe_r": (statistics.median([c["mfe_pct"] for c in proches]) / 100.0) * e / risque,
            "mae_r": (statistics.median([c["mae_pct"] for c in proches]) / 100.0) * e / risque,
            "cible_r": cible / risque,
        })
    return out


def _simuler(trades, seuil):
    """Retourne (R_borne_basse, R_borne_haute, nb_sauves, nb_rabotes)."""
    bas, haut = [], []
    sauves = rabotes = 0
    for t in trades:
        perdant = t["issue"] == "LOSS"
        if seuil is None:
            bas.append(t["r_fixe"]); haut.append(t["r_fixe"])
            continue
        declencheur_r = (seuil / 100.0) * t["cible_r"]
        arme = t["mfe_r"] >= declencheur_r

        if perdant:
            # Ordre FORCE : l'avancee precede le stop final.
            if arme:
                bas.append(0.0); haut.append(0.0); sauves += 1
            else:
                bas.append(t["r_fixe"]); haut.append(t["r_fixe"])
        else:
            # Ordre INCONNU. Le trade est rabote seulement si, une fois arme, le
            # prix est revenu a l'entree — donc si le recul atteint l'entree.
            revient = arme and t["mae_r"] > 0
            haut.append(t["r_fixe"])                      # recul AVANT l'armement
            bas.append(0.0 if revient else t["r_fixe"])   # recul APRES l'armement
            if revient:
                rabotes += 1
    return statistics.mean(bas), statistics.mean(haut), sauves, rabotes


def main() -> int:
    trades = _collecter()
    print(f"trades exploitables : {len(trades)}")
    print("  (excursions NON mesurees ecartees : voir le commentaire du code)")
    if not trades:
        return 1
    perdants = sum(1 for t in trades if t["issue"] == "LOSS")
    print(f"  dont perdants sans gestion : {perdants}")
    print(f"  reel mesure aujourd'hui (seuil 50) : +0.0455 R")
    print()
    print("  %-10s %12s %12s %10s %10s" % (
        "seuil", "borne basse", "borne haute", "sauves", "rabotes"))
    for s in SEUILS:
        bas, haut, sv, rb = _simuler(trades, s)
        nom = "jamais" if s is None else f"{s} %"
        print("  %-10s %+11.4f %+12.4f %10d %10d" % (nom, bas, haut, sv, rb))
    print()
    print("⚠️ La verite est ENTRE les deux bornes : `mfe_pct` et `mae_pct` sont")
    print("   des maxima sans ordre chronologique. Un seuil qui ne gagne que")
    print("   dans la borne haute n'est pas un resultat.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
