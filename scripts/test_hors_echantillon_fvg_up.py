#!/usr/bin/env python3
"""Test HORS ÉCHANTILLON de `fvg_up` acheteur sur l'or — déclaré dans `641df08`.

Les dix nuits qui donnent cette cellule positive rejouent une fenêtre
GLISSANTE de 90 jours : elles partagent 89 jours sur 90. Ce test prend les
jours **90 à 365**, que aucune d'elles n'a vus.

⛔ CE QUI EST RÉUTILISÉ, JAMAIS RÉÉCRIT
`detections`, `rejouer_cellule`, `controle_aleatoire`, `_welch`,
`plafond_hasard`, `PLACEBO_PCT`. En particulier `_welch` : le `t_vs_hasard`
publié est un t de Welch entre la cellule et son contrôle de MÊME SENS, et
recalculer cet écart autrement rendrait un nombre incomparable au +2,47 qu'on
cherche à réfuter.

⛔ LE TEST S'ARRÊTE SI LE RECOUVREMENT N'EST PAS NUL. Un test « hors
échantillon » qui partagerait ne serait-ce qu'un jour avec la fenêtre de
sélection ne mesurerait rien — et aurait l'air d'un résultat.
"""

from __future__ import annotations

import os
import statistics as st
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services import laboratoire_or as labo  # noqa: E402
from backend.services import reglage_or as reg  # noqa: E402

MOTIF, SENS = "fvg_up", "buy"
JOURS_TOTAL = int(os.getenv("OOS_JOURS_TOTAL", "365"))
JOURS_VUS = int(os.getenv("OOS_JOURS_VUS", "90"))
SPREAD = float(os.getenv("OOS_SPREAD", "0.20"))
GRAINES = int(os.getenv("OOS_GRAINES", "30"))

# ⛔ LE GARDE-FOU QUI MANQUAIT. Le 30/09, la validation croisee a rendu des R de
# -127 a -184 : j'avais epingle le spread de l'OR (0,20) puis l'applique a des
# paires cotees 1,08, ou il vaut ~200 R par trade. Un R normalise au stop
# plafonne a ≈ -1 ; -127 est impossible par construction.
#
# 🔑 La lecon n'est pas « faire attention » : c'est qu'une mesure doit REFUSER
# de publier un chiffre absurde. Au-dela de ce cout, aucun edge plausible ne
# survit et la cellule n'est pas mesurable — on le DIT au lieu de rendre un `t`
# calcule sur deux distributions ruinees.
COUT_MAX_R = float(os.getenv("OOS_COUT_MAX_R", "0.25"))
R_MAX_PLAUSIBLE = 3.0


def _horodatage(b):
    """Le temps d'une bougie, quel que soit le nom du champ dans cette source."""
    for cle in ("t", "time", "ts", "date", "datetime"):
        if cle in b:
            return b[cle]
    raise KeyError("aucun champ de temps dans la bougie : %s" % list(b)[:8])


def _en_date(v):
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v, tz=timezone.utc)
    s = str(v).replace("Z", "+00:00")
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def mesurer_cellule(bougies, pair, spread):
    """R de la cellule + son contrôle, et le t de Welch entre les deux."""
    releve = labo.detections(bougies, pair)
    trades = labo.rejouer_cellule(bougies, releve, MOTIF, SENS, spread)
    if len(trades) < 10:
        return None, "seulement %d trades" % len(trades)
    R = [t["R"] for t in trades]
    moyenne, t_brut = labo._stat(R)
    ecart = st.pstdev(R) if len(R) > 1 else 0.0
    risque_med = st.median(t["risque"] for t in trades)
    objectif_med = st.median(t["objectif_r"] for t in trades)

    cout_r = spread / risque_med if risque_med > 0 else float("inf")
    if cout_r > COUT_MAX_R:
        return None, ("cout %.2f R/trade > %.2f — spread %.5f contre stop %.5f : "
                      "NON MESURABLE" % (cout_r, COUT_MAX_R, spread, risque_med))
    if abs(moyenne) > R_MAX_PLAUSIBLE:
        return None, ("R moyen %+.1f impossible (plafonne a ≈1 par construction)"
                      % moyenne)

    # Contrôle : MÊME sens, MÊME nombre, MÊME risque médian, 30 graines mises
    # en commun — un tirage unique saute de ±0,10 R d'une graine à l'autre.
    Rc: list[float] = []
    for g in range(GRAINES):
        Rc.extend(x["R"] for x in labo.controle_aleatoire(
            bougies, spread, len(R), risque_med, objectif_med,
            graine=g, sens=SENS))
    if len(Rc) < 10:
        return None, "controle vide"
    moy_c = st.mean(Rc)
    ecart_c = st.pstdev(Rc)
    t_vs = labo._welch(moyenne, ecart, len(R), moy_c, ecart_c, len(Rc))
    return {"n": len(R), "r_moyen": moyenne, "t_brut": t_brut,
            "r_hasard": moy_c, "n_hasard": len(Rc),
            "delta": moyenne - moy_c, "t_vs_hasard": t_vs,
            "cout": spread / risque_med}, None


def main() -> int:
    print("TEST HORS ECHANTILLON — %s / %s / or 5 min" % (MOTIF, SENS))
    print("  declaration : 641df08 · spread epingle %.2f · %d graines\n"
          % (SPREAD, GRAINES))

    bougies, _vivant = reg._bougies_et_spread(JOURS_TOTAL, "XAU/USD")
    print("  %d bougies sur %d jours demandes" % (len(bougies), JOURS_TOTAL))
    if len(bougies) < 2000:
        print("  ⛔ pas assez de bougies pour une fenetre disjointe")
        return 1

    coupure = datetime.now(timezone.utc) - timedelta(days=JOURS_VUS)
    vieilles = [b for b in bougies if _en_date(_horodatage(b)) < coupure]
    recentes = [b for b in bougies if _en_date(_horodatage(b)) >= coupure]
    if not vieilles or not recentes:
        print("  ⛔ decoupage impossible")
        return 1

    fin_oos = _en_date(_horodatage(vieilles[-1]))
    deb_vues = _en_date(_horodatage(recentes[0]))
    print("  fenetre DISJOINTE : %s -> %s  (%d bougies)"
          % (_en_date(_horodatage(vieilles[0])).date(), fin_oos.date(),
             len(vieilles)))
    print("  fenetre VUE       : %s -> %s  (%d bougies)"
          % (deb_vues.date(), _en_date(_horodatage(recentes[-1])).date(),
             len(recentes)))
    if fin_oos >= deb_vues:
        print("  ⛔ RECOUVREMENT NON NUL — test invalide, aucun verdict")
        return 1
    print("  recouvrement : NUL (%.1f h d'ecart)\n"
          % ((deb_vues - fin_oos).total_seconds() / 3600))

    res, err = mesurer_cellule(vieilles, "XAU/USD", SPREAD)
    barre1 = labo.plafond_hasard(1)
    if err:
        print("  ⛔ mesure impossible : %s" % err)
        return 1
    print("=== L'OR, sur la fenetre JAMAIS VUE")
    print("  n=%d  R moyen %+.4f  (t brut %+.2f)" % (res["n"], res["r_moyen"], res["t_brut"]))
    print("  hasard %+.4f sur %d tirages  ->  delta %+.4f"
          % (res["r_hasard"], res["n_hasard"], res["delta"]))
    print("  t_vs_hasard = %+.3f   contre une barre de %.3f  ->  %s"
          % (res["t_vs_hasard"], barre1,
             "FRANCHIT" if res["t_vs_hasard"] > barre1 else "ne franchit pas"))
    print("  (les fenetres glissantes donnaient une mediane de +2,47)")

    print("\n=== VALIDATION CROISEE sur les instruments servis")
    paires = reg.instruments_servis()
    resultats = []
    for p in paires:
        if p == "XAU/USD":
            continue
        try:
            b, spread_p = reg._bougies_et_spread(JOURS_TOTAL, p)
        except Exception as e:  # noqa: BLE001
            print("  %-12s bougies indisponibles (%s)" % (p, str(e)[:40]))
            continue
        # ⛔ LE SPREAD DE CHAQUE INSTRUMENT, jamais celui de l'or.
        if not spread_p or spread_p <= 0:
            print("  %-12s spread illisible — ecarte" % p)
            continue
        v = [x for x in b if _en_date(_horodatage(x)) < coupure]
        if len(v) < 2000:
            print("  %-12s %d bougies disjointes seulement" % (p, len(v)))
            continue
        r, e = mesurer_cellule(v, p, spread_p)
        if e:
            print("  %-12s %s" % (p, e))
            continue
        resultats.append((p, r))
        print("  %-12s spread %-9.5f n=%-5d R=%+8.4f  cout %.4f R  t_vs_hasard=%+6.2f"
              % (p, spread_p, r["n"], r["r_moyen"], r["cout"], r["t_vs_hasard"]))

    barre_n = labo.plafond_hasard(max(len(resultats) + 1, 1))
    pos = sum(1 for _, r in resultats if r["r_moyen"] > 0)
    franchissent = [p for p, r in resultats if r["t_vs_hasard"] > barre_n]
    print("\n=== VERDICT contre les predictions de 641df08")
    print("  P1 effondrement (t_vs_hasard < +2,47) : %s  [%.3f]"
          % ("VRAIE" if res["t_vs_hasard"] < 2.47 else "FAUSSE", res["t_vs_hasard"]))
    if resultats:
        print("  P2 concordance absente (< moitie positifs, aucun > %.3f) : %s"
              % (barre_n, "VRAIE" if (pos * 2 < len(resultats) and not franchissent)
                 else "FAUSSE"))
        print("     %d/%d instruments positifs, %d franchissent : %s"
              % (pos, len(resultats), len(franchissent), franchissent or "aucun"))
    print("  decision : %s" % (
        "🔬 CANDIDAT — or franchit ET concordance"
        if res["t_vs_hasard"] > barre1 and franchissent
        else "⛔ NON RETENU — or franchit mais concordance absente"
        if res["t_vs_hasard"] > barre1
        else "⛔ REFUTE — l'or ne franchit pas sa barre"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
