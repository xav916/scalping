#!/usr/bin/env python3
"""Hors echantillon d'une CHAINE du laboratoire — or, argent, n'importe quelle paire.

Deux etapes, dans cet ordre, et la premiere a un droit de veto :

  1. **Est-ce que je reproduis la cellule publiee par le laboratoire ?** Si non,
     le hors-echantillon ne mesure pas la meme chose et ne vaut rien.
  2. **Tient-elle sur les jours 90 a 365**, que les nuits du laboratoire — qui
     rejouent une fenetre glissante de 90 jours — n'ont jamais vus ?

⛔ CE QUI EST REUTILISE, JAMAIS REECRIT
`detections`, `fusionner_chaines`, `rejouer_cellule`, `controle_poole`,
`_stat`, `_welch`, `plafond_hasard`, `_agreger_brut`, `_bougies_et_spread`.

⛔ UNE CHAINE N'EST PAS UN MOTIF SIMPLE. Sans `fusionner_chaines`, le releve ne
la porte pas et `rejouer_cellule` rend ZERO trade — un << pas de resultat >>
qui ressemble a un resultat.

⛔ LE CONTROLE EST TIRE **PAR CELLULE**, au risque et a l'objectif de CETTE
cellule. Un controle au risque median global ne paie pas les memes frais —
`cout = spread / risque` — et l'ecart mesurerait une difference de COUT prise
pour une difference de direction. Faute trouvee dans mon banc du 2026-10-01.

⛔ LA FENETRE EST EPINGLEE a l'instant de la nuit reproduite. Le laboratoire
rejoue `now - 90j -> now` ; lance quelques heures plus tard, le meme code voit
d'autres trades et rend un autre chiffre. Ce n'est pas un defaut d'appareil,
c'est une autre fenetre.
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

MOTIF = os.getenv("OOS_MOTIF", "chaine:sweep_sur_niveau_majeur_haussier")
SENS = os.getenv("OOS_SENS", "buy")
FACTEUR = int(os.getenv("OOS_FACTEUR", "1"))      # 1 = 5 min, pas d'agregation
CHAINE = os.getenv("OOS_CHAINE", "1") == "1"
PAIRE = os.getenv("OOS_PAIRE", "XAU/USD")
JOURS_TOTAL = int(os.getenv("OOS_JOURS_TOTAL", "365"))
JOURS_VUS = int(os.getenv("OOS_JOURS_VUS", "90"))
SPREAD = float(os.getenv("OOS_SPREAD", "0.20"))
GRAINES = int(os.getenv("OOS_GRAINES", str(labo.CONTROLE_GRAINES)))
ATTENDU_VUE = float(os.getenv("OOS_ATTENDU_VUE", "-0.1648"))
OOS_FIN = os.getenv("OOS_FIN", "2026-10-01T03:51:14+00:00")
TOLERANCE = float(os.getenv("OOS_TOLERANCE", "0.08"))
MIN_TRADES = int(os.getenv("OOS_MIN_TRADES", "5"))


# ⛔ LA LECTURE A ETE FAUSSE UNE FOIS, LE 2026-10-01. La version inline testait
# `R_oos > 0` et imprimait << signe tenu >> — correct pour une cellule dont
# l'echantillon est POSITIF (`pin_bar_down`, +0,1550), faux des que
# l'echantillon est NEGATIF. Les chaines `sweep_sur_niveau_majeur` de l'or sont
# passees de -0,17 a +0,43 et ont ete etiquetees CANDIDAT alors que leur signe
# venait de S'INVERSER.
#
# > Un outil de mesure qui se trompe d'etiquette est pire qu'un outil absent :
# > il rend un verdict credible et faux.
#
# 🔑 La regle : le signe se compare A CELUI DE L'ECHANTILLON, jamais a zero.
def _meme_signe(a: float, b: float) -> bool:
    return (a > 0 and b > 0) or (a < 0 and b < 0)


def lecture(vue_r: float, oos_r: float, t_vs: float, barre: float) -> str:
    """L'etiquette a poser, et rien d'autre. Testee unitairement."""
    if not _meme_signe(vue_r, oos_r):
        return ("INSTABLE — le signe S'INVERSE entre deux fenetres disjointes "
                "(%+.4f -> %+.4f). Ni preuve ni refutation : l'estimation ne "
                "porte pas d'information a ce n." % (vue_r, oos_r))
    if vue_r < 0:
        return ("CONFIRME NEGATIF — le signe tient, et il est mauvais "
                "(%+.4f -> %+.4f)" % (vue_r, oos_r))
    if t_vs > barre:
        return "CANDIDAT — signe positif tenu ET barre franchie"
    return ("SIGNE POSITIF TENU, barre NON franchie — pas une preuve, "
            "pas une refutation")


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
    if CHAINE:
        releve = labo.fusionner_chaines(releve, agregees)
    trades = labo.rejouer_cellule(agregees, releve, MOTIF, SENS, SPREAD)
    if len(trades) < MIN_TRADES:
        return None, "seulement %d trades" % len(trades)
    R = [t["R"] for t in trades]
    moyenne, t_brut = labo._stat(R)
    ctrl = labo.controle_poole(
        agregees, SPREAD, len(R),
        st.median(t["risque"] for t in trades),
        st.median(t["objectif_r"] for t in trades),
        graine=0, sens=SENS, graines=GRAINES)
    if len(ctrl) < MIN_TRADES:
        return None, "controle vide"
    t_vs = labo._welch(moyenne, st.pstdev(R), len(R),
                       st.mean(ctrl), st.pstdev(ctrl), len(ctrl))
    print("  %-18s bougies %6d · n=%-4d  R %+.4f  (t brut %+.2f)"
          % (etiquette, len(agregees), len(R), moyenne, t_brut))
    print("  %-18s hasard %+.4f sur %d tirages  ->  delta %+.4f · t_vs %+.3f"
          % ("", st.mean(ctrl), len(ctrl), moyenne - st.mean(ctrl), t_vs))
    return {"n": len(R), "r": moyenne, "ctrl": st.mean(ctrl),
            "delta": moyenne - st.mean(ctrl), "t_vs": t_vs}, None


def main() -> int:
    barre = labo.plafond_hasard(1)
    print("HORS ECHANTILLON — %s / %s / %s en %s"
          % (MOTIF, SENS, PAIRE, labo._horizon(FACTEUR)))
    print("  spread epingle %.2f · %d graines · barre d'un test %.3f\n"
          % (SPREAD, GRAINES, barre))

    bougies, _vivant = reg._bougies_et_spread(JOURS_TOTAL, PAIRE)
    fin_fenetre = _en_date(OOS_FIN)
    bougies = [b for b in bougies if _en_date(_horodatage(b)) <= fin_fenetre]
    coupure = fin_fenetre - timedelta(days=JOURS_VUS)
    vieilles = [b for b in bougies if _en_date(_horodatage(b)) < coupure]
    recentes = [b for b in bougies if _en_date(_horodatage(b)) >= coupure]
    if not vieilles or not recentes:
        print("  decoupage impossible")
        return 1
    fin = _en_date(_horodatage(vieilles[-1]))
    deb = _en_date(_horodatage(recentes[0]))
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
    print("  publie par le labo : %+.4f · mesure ici : %+.4f · ecart %.4f"
          % (ATTENDU_VUE, vue["r"], ecart))
    if ecart > TOLERANCE:
        print("  -> NON REPRODUIT. On s'arrete : mesurer une autre fenetre "
              "avec un appareil qui ne retrouve pas le chiffre publie ne "
              "trancherait rien.")
        return 1
    print("  -> REPRODUIT\n")

    print("=== ETAPE 2 : les jours 90 a 365, jamais rejoues")
    oos, err = mesurer(vieilles, "fenetre OOS")
    if err:
        print("  mesure impossible : %s" % err)
        return 1

    print("\n=== VERDICT")
    print("  R      : vue %+.4f  ->  hors echantillon %+.4f"
          % (vue["r"], oos["r"]))
    print("  delta  : vue %+.4f  ->  hors echantillon %+.4f"
          % (vue["delta"], oos["delta"]))
    print("  t_vs   : vue %+.3f   ->  hors echantillon %+.3f  (barre %.3f)"
          % (vue["t_vs"], oos["t_vs"], barre))
    print("  n      : vue %d  ->  hors echantillon %d" % (vue["n"], oos["n"]))
    print("\n  le signe tient hors echantillon : %s"
          % ("OUI" if _meme_signe(vue["r"], oos["r"]) else "NON — il S'INVERSE"))
    print("  franchit la barre du hasard     : %s"
          % ("OUI" if oos["t_vs"] > barre else "NON"))
    print("\n  lecture : %s" % lecture(vue["r"], oos["r"], oos["t_vs"], barre))
    return 0


if __name__ == "__main__":
    sys.exit(main())
