#!/usr/bin/env python3
"""Banc de la LARGEUR DU STOP sur l'or — prédiction déclarée dans `47b5c6c`.

Question : élargir le stop (objectif maintenu à 1,8 R) rend-il le résultat
non négatif ? Le coût passé à `_issue` vaut `spread / risque` : le spread étant
une distance de PRIX, le coût en R est inversement proportionnel à la largeur
du stop. Élargir allège donc mécaniquement la charge — reste à savoir si ça
suffit à battre le hasard.

⛔ CE QUI EST RÉUTILISÉ, JAMAIS RÉÉCRIT
`_issue`, `detections`, `controle_aleatoire`, `plafond_hasard`, `_stat`,
`PLACEBO_PCT`, `FENETRE`, `_bougies_et_spread`. Une seconde arithmétique du
risque ou de la sortie produirait des chiffres incomparables à ceux du labo —
c'est exactement ce qui a fait poser quatre fausses pauses sur l'or.

⛔ LE REJEU EST SÉQUENTIEL PAR k
Un stop plus large tient la position plus longtemps et décale toutes les
entrées suivantes. Chaque k a donc SA propre suite d'entrées. C'est voulu : la
question est « que vaut le système avec ce stop-là », pas « que vaut cette
gestion sur les trades de l'autre ».
⚠️ Conséquence à dire : l'écart entre deux k mêle un effet de GESTION et un
effet de POPULATION. C'est pour ça que le verdict ne se lit pas entre k, mais
entre chaque k et SON contrôle aléatoire.

⛔ LE CONTRÔLE PORTE LE MÊME k
Le 15/09, trois défauts emboîtés ont été trouvés dans le contrôle aléatoire,
dont « contrôle non porteur du verdict ». Un contrôle tiré au stop d'origine
pendant qu'on mesure un stop doublé comparerait deux choses différentes. Le
contrôle reçoit donc la médiane des risques DÉJÀ mis à l'échelle — pas le
risque d'origine, et pas une seconde multiplication par k.
"""

from __future__ import annotations

import os
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services import laboratoire_or as labo  # noqa: E402
from backend.services import reglage_or as reg  # noqa: E402

FACTEURS = (0.5, 0.75, 1.0, 1.5, 2.0, 3.0)
PAIRE = os.getenv("BANC_PAIRE", "XAU/USD")
JOURS = int(os.getenv("BANC_JOURS", str(reg.JOURS_ETUDIES)))
GRAINES = int(os.getenv("LABO_OR_CONTROLE_GRAINES", "30"))


def rejeu_cellule_k(bougies, releve, motif, sens, spread, k):
    """`labo.rejouer_cellule`, mais le stop multiplié par k.

    L'objectif reste celui du setup (≈1,8 R) : c'est la distance de stop qui
    change, donc le TP se déplace aussi en PRIX. `PLACEBO_PCT` est appliqué
    APRÈS multiplication — à k=0,5 des cellules disparaissent, et c'est le
    résultat.
    """
    trades = []
    i, n = labo.FENETRE, len(bougies)
    while i < n:
        cands = [s for s in releve.get(i, ())
                 if labo._nom_motif(s) == motif and labo._sens(s) == sens]
        if not cands:
            i += 1
            continue
        s = cands[0]
        entree = float(s.entry_price)
        risque0 = abs(entree - float(s.stop_loss))
        if risque0 <= 0 or entree <= 0:
            i += 1
            continue
        objectif_r = abs(float(s.take_profit_1) - entree) / risque0
        risque = risque0 * k
        if risque / entree < labo.PLACEBO_PCT or objectif_r <= 0:
            i += 1
            continue
        signe = 1 if sens == "buy" else -1
        R, sortie = labo._issue(bougies, i, entree, risque, objectif_r, signe,
                                spread / risque)
        trades.append({"R": R, "risque": risque, "cout": spread / risque,
                       "risque_pct": risque / entree, "objectif_r": objectif_r,
                       "sens": sens})
        i = sortie + 1
    return trades


def controle_pour(bougies, spread, n_par_sens, risque_med_k, objectif_med):
    """Moyennes du contrôle aléatoire, une par graine, SENS RESPECTÉ.

    ⚠️ `risque_med_k` porte DÉJÀ le facteur k : il est la médiane des risques
    des trades rejoués, qui valent `risque0 * k`. Il ne faut donc surtout pas
    le remultiplier ici — le nom le dit pour que personne ne le refasse.
    """
    moyennes = []
    for g in range(GRAINES):
        R = []
        for sens, combien in n_par_sens.items():
            if combien <= 0:
                continue
            tir = labo.controle_aleatoire(bougies, spread, combien,
                                          risque_med_k, objectif_med,
                                          graine=g, sens=sens)
            R.extend(t["R"] for t in tir)
        if R:
            moyennes.append(st.mean(R))
    return moyennes


def main() -> int:
    print("banc largeur du stop — %s, %d jours, %d graines de controle"
          % (PAIRE, JOURS, GRAINES))
    bougies, spread = reg._bougies_et_spread(JOURS, PAIRE)
    # ⛔ `_bougies_et_spread` rend `ask - bid` du tick VIVANT : 90 jours de
    # rejeu sont donc factures au spread d'un SEUL instant. Mesure du 30/09 :
    # 0,50 a 21h45 Paris contre 0,20 dans le banc du 15/09 — un facteur 2,5 qui
    # deplace tous les couts et rend deux bancs incomparables. `BANC_SPREAD`
    # permet d'epingler la valeur de reference pour comparer a l'identique.
    epingle = os.getenv("BANC_SPREAD")
    if epingle:
        spread = float(epingle)
        print("  spread EPINGLE a %.4f (vivant ignore)" % spread)
    print("  %d bougies M5, spread %.4f" % (len(bougies), spread))
    if len(bougies) < 500:
        print("  ⛔ pas assez de bougies, on arrete")
        return 1
    releve = labo.detections(bougies, PAIRE)
    cellules = sorted({(labo._nom_motif(s), labo._sens(s))
                       for lot in releve.values() for s in lot})
    print("  %d cellules motif x sens" % len(cellules))
    plafond = labo.plafond_hasard(len(FACTEURS))
    print("  plafond du hasard pour %d variantes : %.3f\n" % (len(FACTEURS), plafond))

    print("%-6s %6s %10s %10s %10s %10s %9s %9s"
          % ("k", "n", "stop %", "cout R", "R moyen", "t", "ctrl moy", "z"))
    lignes = []
    for k in FACTEURS:
        tous, n_sens = [], {"buy": 0, "sell": 0}
        for motif, sens in cellules:
            tr = rejeu_cellule_k(bougies, releve, motif, sens, spread, k)
            tous.extend(tr)
            n_sens[sens] = n_sens.get(sens, 0) + len(tr)
        if not tous:
            print("%-6.2f %6d   (aucun trade — tout sous le seuil placebo)" % (k, 0))
            lignes.append({"k": k, "n": 0})
            continue
        R = [t["R"] for t in tous]
        moyenne, t_stat = labo._stat(R)
        risque_med = st.median(t["risque"] for t in tous)
        objectif_med = st.median(t["objectif_r"] for t in tous)
        ctrl = controle_pour(bougies, spread, n_sens, risque_med, objectif_med)
        z = 0.0
        if len(ctrl) > 1 and st.pstdev(ctrl) > 0:
            z = (moyenne - st.mean(ctrl)) / st.pstdev(ctrl)
        print("%-6.2f %6d %9.3f%% %10.4f %+10.4f %+10.2f %+9.4f %+9.2f"
              % (k, len(R), st.median(t["risque_pct"] for t in tous) * 100,
                 st.median(t["cout"] for t in tous), moyenne, t_stat,
                 st.mean(ctrl) if ctrl else 0.0, z))
        lignes.append({"k": k, "n": len(R), "r_moyen": moyenne, "t": t_stat,
                       "z": z, "cout": st.median(t["cout"] for t in tous)})

    print("\n=== VERDICT contre les predictions de 47b5c6c")
    ref = next((x for x in lignes if x["k"] == 1.0 and x["n"]), None)
    if ref:
        print("  P1 reproduction a k=1 : r_moyen %+.4f (publie -0,0306), "
              "cout %.4f (publie 0,0207)" % (ref["r_moyen"], ref["cout"]))
    mesures = [x for x in lignes if x.get("n")]
    croissant = all(a["r_moyen"] <= b["r_moyen"] + 1e-9
                    for a, b in zip(mesures, mesures[1:]))
    print("  P2 monotonie croissante en k : %s" % ("VRAIE" if croissant else "FAUSSE"))
    franchis = [x for x in mesures if abs(x["t"]) > plafond and x["r_moyen"] > 0]
    print("  P3 aucun k ne franchit le plafond (%.3f) : %s"
          % (plafond, "VRAIE" if not franchis else
             "FAUSSE — %s" % [x["k"] for x in franchis]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
