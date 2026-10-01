#!/usr/bin/env python3
"""`pin_bar_down` vendeur sur l'or en 30 min — hors echantillon.

La cellule rend **+0,1556 R sur 84 trades** dans la nuit du 2026-10-01, la
meilleure de l'or ce jour-la. Elle reste `INSUFFISANT` : t_vs_hasard 1,30 contre
une barre de 3,67. Avant de l'armer sur l'argent reel, deux questions, dans cet
ordre :

  1. **Est-ce que je reproduis le +0,1556 ?** Si non, le hors-echantillon ne
     mesure pas la meme chose et ne vaut rien. Cette etape passe AVANT.
  2. **Tient-elle sur les jours 90 a 365**, que les nuits du laboratoire — qui
     rejouent une fenetre glissante de 90 jours — n'ont jamais vus ?

⛔ CE QUI EST REUTILISE, JAMAIS REECRIT
`_agreger_brut` (meme alignement sur l'horloge que la production), `detections`,
`rejouer_cellule`, `controle_poole`, `_stat`, `_welch`, `plafond_hasard`,
`_bougies_et_spread`.

⛔ LE CONTROLE EST TIRE **PAR CELLULE**, au risque et a l'objectif de CETTE
cellule. Un controle au risque median global ne paie pas les memes frais —
`cout = spread / risque` — et l'ecart mesure alors une difference de COUT prise
pour une difference de direction. C'est la faute exacte trouvee dans mon banc
du matin le 2026-10-01, et retiree de `docs/concepts-trading.md`.

⚠️ `pin_bar_up` ACHETEUR en 5 min est l'une des PIRES cellules de l'or
(-0,1560 R sur 436 trades, delta -0,0803). La famille `pin_bar` n'est donc pas
bonne en soi : c'est bien cette cellule-la, a cette echelle-la, qui est en
question.
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

MOTIF = os.getenv("OOS_MOTIF", "pin_bar_down")
SENS = os.getenv("OOS_SENS", "sell")
FACTEUR = int(os.getenv("OOS_FACTEUR", "6"))          # 6 x 5 min = 30 min
PAIRE = os.getenv("OOS_PAIRE", "XAU/USD")
JOURS_TOTAL = int(os.getenv("OOS_JOURS_TOTAL", "365"))
JOURS_VUS = int(os.getenv("OOS_JOURS_VUS", "90"))
SPREAD = float(os.getenv("OOS_SPREAD", "0.20"))
GRAINES = int(os.getenv("OOS_GRAINES", str(labo.CONTROLE_GRAINES)))
ATTENDU_VUE = float(os.getenv("OOS_ATTENDU_VUE", "0.1556"))

# ⛔ LA FENETRE DOIT ETRE EPINGLEE A L'INSTANT DE LA NUIT QU'ON REPRODUIT.
# Le laboratoire rejoue `now - 90j -> now`. Lance 15 h plus tard, le meme code
# voit 3 trades de plus (n=87 contre 84) et rend +0,1868 au lieu de +0,1556.
# Ce n'etait pas un defaut d'appareil, c'etait une autre fenetre.
OOS_FIN = os.getenv("OOS_FIN", "2026-10-01T03:51:14+00:00")

# ⚠️ TOLERANCE CALEE SUR LE BRUIT MESURE, pas choisie. Deux nuits
# CONSECUTIVES du laboratoire, qui partagent 89 jours sur 90, rendent n=84 les
# deux fois et R +0,1885 (30/09) puis +0,1556 (01/10) : la cellule bouge de
# **0,033 R par jour** sur une fenetre quasi identique. Exiger mieux que ce
# bruit serait exiger de l'appareil une stabilite que la QUANTITE n'a pas.
TOLERANCE = float(os.getenv("OOS_TOLERANCE", "0.035"))


def _horodatage(b):
    for cle in ("t", "time", "ts", "date", "datetime"):
        if cle in b:
            return b[cle]
    raise KeyError("aucun champ de temps : %s" % list(b)[:8])


def _en_date(v):
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v, tz=timezone.utc)
    d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def mesurer(bougies_m5, etiquette):
    """`(resultat, motif d'echec)` pour la cellule sur cette fenetre."""
    agregees = labo._agreger_brut(bougies_m5, FACTEUR, None)
    if len(agregees) < labo.FENETRE + 50:
        return None, "seulement %d bougies agregees" % len(agregees)
    releve = labo.detections(agregees, PAIRE)
    trades = labo.rejouer_cellule(agregees, releve, MOTIF, SENS, SPREAD)
    if len(trades) < 10:
        return None, "seulement %d trades" % len(trades)
    R = [t["R"] for t in trades]
    moyenne, t_brut = labo._stat(R)
    risque_med = st.median(t["risque"] for t in trades)
    objectif_med = st.median(t["objectif_r"] for t in trades)
    ctrl = labo.controle_poole(agregees, SPREAD, len(R), risque_med,
                               objectif_med, graine=0, sens=SENS,
                               graines=GRAINES)
    if len(ctrl) < 10:
        return None, "controle vide"
    t_vs = labo._welch(moyenne, st.pstdev(R), len(R),
                       st.mean(ctrl), st.pstdev(ctrl), len(ctrl))
    print("  %-18s bougies agregees %5d · n=%-4d  R %+.4f  (t brut %+.2f)"
          % (etiquette, len(agregees), len(R), moyenne, t_brut))
    print("  %-18s hasard %+.4f sur %d tirages  ->  delta %+.4f  ·  t_vs %+.3f"
          % ("", st.mean(ctrl), len(ctrl), moyenne - st.mean(ctrl), t_vs))
    return {"n": len(R), "r": moyenne, "t_brut": t_brut,
            "ctrl": st.mean(ctrl), "delta": moyenne - st.mean(ctrl),
            "t_vs": t_vs, "cout": SPREAD / risque_med}, None


def main() -> int:
    barre = labo.plafond_hasard(1)
    print("HORS ECHANTILLON — %s / %s / %s en %s"
          % (MOTIF, SENS, PAIRE, labo._horizon(FACTEUR)))
    print("  spread epingle %.2f · %d graines · barre du hasard %.3f\n"
          % (SPREAD, GRAINES, barre))

    bougies, _vivant = reg._bougies_et_spread(JOURS_TOTAL, PAIRE)
    print("  %d bougies M5 sur %d jours demandes" % (len(bougies), JOURS_TOTAL))
    fin_fenetre = _en_date(OOS_FIN)
    avant = len(bougies)
    bougies = [b for b in bougies if _en_date(_horodatage(b)) <= fin_fenetre]
    print("  fenetre epinglee a %s -> %d bougies ecartees (apres la nuit)"
          % (fin_fenetre.isoformat(), avant - len(bougies)))
    coupure = fin_fenetre - timedelta(days=JOURS_VUS)
    vieilles = [b for b in bougies if _en_date(_horodatage(b)) < coupure]
    recentes = [b for b in bougies if _en_date(_horodatage(b)) >= coupure]
    if not vieilles or not recentes:
        print("  decoupage impossible")
        return 1
    fin, deb = _en_date(_horodatage(vieilles[-1])), _en_date(_horodatage(recentes[0]))
    if fin >= deb:
        print("  RECOUVREMENT NON NUL — aucun verdict")
        return 1
    print("  fenetre VUE : %s -> %s · OOS : %s -> %s · recouvrement NUL\n"
          % (deb.date(), _en_date(_horodatage(recentes[-1])).date(),
             _en_date(_horodatage(vieilles[0])).date(), fin.date()))

    print("=== ETAPE 1 : est-ce que je REPRODUIS la cellule du laboratoire ?")
    vue, err = mesurer(recentes, "fenetre VUE")
    if err:
        print("  mesure impossible : %s" % err)
        return 1
    ecart = abs(vue["r"] - ATTENDU_VUE)
    reproduit = ecart <= TOLERANCE
    print("  publie par le labo : %+.4f  ·  mesure ici : %+.4f  ·  ecart %.4f"
          % (ATTENDU_VUE, vue["r"], ecart))
    print("  -> %s\n" % ("REPRODUIT" if reproduit
                         else "NON REPRODUIT — le hors echantillon ne vaut rien"))
    if not reproduit:
        print("  ⛔ On s'arrete ici. Mesurer une autre fenetre avec un appareil")
        print("     qui ne retrouve pas le chiffre publie ne trancherait rien.")
        return 1

    print("=== ETAPE 2 : les jours 90 a 365, jamais rejoues")
    oos, err = mesurer(vieilles, "fenetre OOS")
    if err:
        print("  mesure impossible : %s" % err)
        return 1

    print("\n=== VERDICT")
    print("  R      : vue %+.4f   ->   hors echantillon %+.4f" % (vue["r"], oos["r"]))
    print("  delta  : vue %+.4f   ->   hors echantillon %+.4f"
          % (vue["delta"], oos["delta"]))
    print("  t_vs   : vue %+.3f    ->   hors echantillon %+.3f   (barre %.3f)"
          % (vue["t_vs"], oos["t_vs"], barre))
    tient_signe = oos["r"] > 0
    franchit = oos["t_vs"] > barre
    print("\n  le signe tient hors echantillon : %s" % ("OUI" if tient_signe else "NON"))
    print("  franchit la barre du hasard     : %s" % ("OUI" if franchit else "NON"))
    print("\n  lecture : %s" % (
        "🔬 CANDIDAT — signe tenu ET barre franchie"
        if tient_signe and franchit else
        "⚠️ SIGNE TENU, barre NON franchie — pas une preuve, pas une refutation"
        if tient_signe else
        "⛔ REFUTE — le signe s'inverse sur les jours jamais vus"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
