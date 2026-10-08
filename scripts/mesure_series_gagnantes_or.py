#!/usr/bin/env python3
"""Les gains de l'or se SUIVENT-ils ? Et que ferait le compteur N de Xavier ?

    docker exec scalping-radar python /tmp/mesure_series_gagnantes_or.py

Xavier, 2026-10-08 : TP et SL evolutifs, indexes sur un compteur `N` de serie
gagnante. Depart SL 5 EUR / TP 10 EUR ; un gain fait `N+1` (TP x1,5, SL x1,1),
une perte fait `N-1`.

⛔ CE QUE CETTE MESURE EPROUVE, ET RIEN D'AUTRE.

L'echelle suppose que `N` porte de l'information : qu'apres un gain, le gain
suivant soit plus probable. Si les issues sont INDEPENDANTES, `N` est une
marche au hasard et l'echelle n'est que du bruit habille en regle.

Trois questions, dans cet ordre :

1. **Dependance** — P(gain | gain precedent) contre P(gain | perte precedente),
   sur les trades REELS puis sur la population du laboratoire.
2. **Mecanique** — a quelle valeur `N` vit-il vraiment, au taux de reussite
   MESURE ? Une marche a derive negative reste collee a zero, et l'echelle ne
   s'armerait jamais.
3. **Geometrie** — ou mene `TP x1,5^N` et `SL x1,1^N` en euros et en R.

⚠️ Elle ne dit RIEN de la rentabilite de l'echelle. Elle dit si sa premisse
tient. Une premisse fausse suffit a l'ecarter ; une premisse vraie demanderait
un banc pre-inscrit.
"""
from __future__ import annotations

import math
import sqlite3
import statistics
import sys
from pathlib import Path

sys.path.insert(0, "/app")

DB_REEL = "/app/data/trades.db"


def _t_proportions(k1, n1, k2, n2):
    """`z` de la difference de deux proportions. `None` si indecidable."""
    if n1 < 5 or n2 < 5:
        return None
    p1, p2 = k1 / n1, k2 / n2
    p = (k1 + k2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se <= 0:
        return None
    return (p1 - p2) / se


def dependance(issues: list[bool], titre: str) -> None:
    """P(gain | gain) contre P(gain | perte), sur une suite CHRONOLOGIQUE."""
    print(f"\n=== {titre} — n={len(issues)} ===")
    if len(issues) < 10:
        print("  trop court")
        return
    taux = sum(issues) / len(issues)
    apres_gain = [issues[i] for i in range(1, len(issues)) if issues[i - 1]]
    apres_perte = [issues[i] for i in range(1, len(issues)) if not issues[i - 1]]
    kg, ng = sum(apres_gain), len(apres_gain)
    kp, np_ = sum(apres_perte), len(apres_perte)
    print(f"  taux de reussite global      : {taux * 100:5.1f} %")
    if ng:
        print(f"  P(gain | gain precedent)     : {kg / ng * 100:5.1f} %  "
              f"(n={ng})")
    if np_:
        print(f"  P(gain | perte precedente)   : {kp / np_ * 100:5.1f} %  "
              f"(n={np_})")
    z = _t_proportions(kg, ng, kp, np_)
    if z is None:
        print("  ecart : indecidable (echantillon trop mince)")
    else:
        verdict = "DEPENDANCE" if abs(z) >= 2.0 else "rien (|z| < 2)"
        print(f"  ecart : z = {z:+.2f}   -> {verdict}")

    # Longueur de la plus longue serie, contre ce que le hasard donnerait.
    serie = best = 0
    for x in issues:
        serie = serie + 1 if x else 0
        best = max(best, serie)
    attendu = (math.log(len(issues) * (1 - taux)) / math.log(1 / taux)
               if 0 < taux < 1 else float("nan"))
    print(f"  plus longue serie gagnante   : {best}  "
          f"(hasard en attendrait ~{attendu:.1f})")


def marche_de_N(taux: float, n_trades: int, plancher: int = 0,
                plafond: int = 20) -> dict:
    """Ou vit `N` sous la regle de Xavier, au taux donne. Deterministe.

    Chaine de Markov : +1 avec probabilite `taux`, -1 sinon, bornee.
    On itere la distribution plutot que de simuler — pas de hasard, donc
    rejouable.
    """
    etats = list(range(plancher, plafond + 1))
    d = {e: 0.0 for e in etats}
    d[plancher] = 1.0
    for _ in range(n_trades):
        nd = {e: 0.0 for e in etats}
        for e, masse in d.items():
            if masse <= 0:
                continue
            haut = min(e + 1, plafond)
            bas = max(e - 1, plancher)
            nd[haut] += masse * taux
            nd[bas] += masse * (1 - taux)
        d = nd
    return d


def geometrie(n_max: int = 8, sl0: float = 5.0, tp0: float = 10.0) -> None:
    print(f"\n=== Geometrie : SL {sl0:.0f} EUR x1,1^N, "
          f"TP {tp0:.0f} EUR x1,5^N ===")
    print(f"  {'N':>2s} {'SL EUR':>8s} {'TP EUR':>9s} {'TP/SL':>7s} "
          f"{'SL en $ (1 oz)':>15s} {'TP en $':>9s} "
          f"{'% gagnants pour etre a 0':>25s}")
    for n in range(0, n_max + 1):
        sl = sl0 * 1.1 ** n
        tp = tp0 * 1.5 ** n
        ratio = tp / sl
        # EUR -> $ au taux courtier 1,1250
        print(f"  {n:2d} {sl:8.2f} {tp:9.2f} {ratio:7.2f} "
              f"{sl * 1.125:15.1f} {tp * 1.125:9.1f} "
              f"{100 / (1 + ratio):24.1f} %")


def main() -> int:
    # ── 1. Les trades REELS de l'or, dans l'ordre ────────────────────────
    with sqlite3.connect(f"file:{Path(DB_REEL)}?mode=ro", uri=True) as c:
        lignes = c.execute(
            "SELECT pnl, close_reason FROM personal_trades "
            "WHERE pair = 'XAU/USD' AND destination_id = 'admin_live' "
            "AND status = 'CLOSED' AND pnl IS NOT NULL "
            "AND created_at >= '2026-09-01' ORDER BY created_at"
        ).fetchall()
    dependance([p > 0 for p, _cr in lignes], "OR REEL, toutes sorties")
    dependance([p > 0 for p, cr in lignes if cr != "MANUAL"],
               "OR REEL, fermetures AUTOMATIQUES seules")

    # ── 2. La population du laboratoire, bien plus large ────────────────
    try:
        sys.path.insert(0, "/tmp")
        import banc_contre_fil_or as banc
        from backend.services import laboratoire_or as labo
        bgs = banc.bougies("2023-08-01", "2026-01-01")
        releve = labo.detections(bgs)
        ent = banc._entrees(bgs, releve, 0.20)
        rs = [banc._issue(bgs, i, e, r, o, s, 0.20 / r)[0]
              for i, e, r, o, s, _sortie in ent]
        dependance([x > 0 for x in rs],
                   "LABORATOIRE, or 5 min 2023-08 -> 2026-01")
        taux_labo = sum(1 for x in rs if x > 0) / len(rs) if rs else 0.0
        print(f"  R moyen de cette population : {statistics.fmean(rs):+.4f}")
    except Exception as e:  # noqa: BLE001
        print(f"\n(laboratoire indisponible : {type(e).__name__}: {e})")
        taux_labo = None

    # ── 3. Ou vit N, aux taux mesures ───────────────────────────────────
    auto = [p > 0 for p, cr in lignes if cr != "MANUAL"]
    taux_auto = sum(auto) / len(auto) if auto else 0.0
    print("\n=== Ou vit le compteur N, apres 200 trades ===")
    for nom, taux in (("or REEL, automatique", taux_auto),
                      ("laboratoire", taux_labo),
                      ("pile ou face", 0.50),
                      ("il faudrait", 0.60)):
        if taux is None:
            continue
        d = marche_de_N(taux, 200)
        esp = sum(e * m for e, m in d.items())
        p0 = d.get(0, 0.0) + d.get(1, 0.0)
        print(f"  {nom:22s} taux {taux * 100:4.1f} %  "
              f"N moyen {esp:5.2f}   P(N <= 1) = {p0 * 100:5.1f} %")

    geometrie()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
