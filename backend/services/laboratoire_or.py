"""Le laboratoire de l'or : mesurer chaque nuit ce qui marche, et ce qui ne marche pas.

Demandé par Xavier le 2026-09-08 : « je veux que les bougies sur l'or soient
analysées, agrégées et étudiées pour définir un pattern et un réajustement
automatique et une amélioration continue ».

## ⛔ Ce que ce module ne fera JAMAIS

Il ne choisit pas le meilleur réglage sur les données qui l'ont suggéré. Ce
projet a déjà mesuré où ça mène :

- **DSR 0,35** — la variante gagnante était SOUS le plafond du hasard
- **PBO 0,579** sur l'argent réel — pire que pile ou face
- « elle tient à **3 trades sur 233** »
- Phase 2 ML : des entrées **pires que le hasard**
- 29 000 trades, contrôle aléatoire : **Δ = +0,004 R**

🔑 Un laboratoire qui ne peut pas dire « rien ne dépasse le hasard » n'est pas
un laboratoire, c'est un générateur de justifications.

## Ce qu'il fait

Pour chaque **(échelle, motif, sens)** — une *cellule* — il rejoue les 90
derniers jours et rend quatre nombres qui décident :

1. `n` — combien de trades. Sous `MIN_TRADES`, la cellule est **INSUFFISANTE**,
   quel que soit son résultat.
2. `r_moyen` et `t` — l'écart au zéro.
3. `delta_hasard` — l'écart au **contrôle aléatoire** de la même échelle. C'est
   la seule comparaison qui vaille : un motif qui gagne autant que des entrées
   au hasard n'apporte rien.
4. `plafond` — le |t| maximal attendu **sans aucun effet**, compte tenu du
   nombre de cellules examinées. Une cellule ne peut être RETENUE qu'au-dessus.

## Garde-fous du rejeu

⛔ **Séquentiel** : jamais deux trades ouverts sur la même cellule. Une fenêtre
glissante compterait dix fois le même mouvement.
⛔ Le **stop est testé AVANT** l'objectif dans une bougie qui contient les deux.
⛔ Le **spread est facturé** en R — et c'est un avantage attendu des grandes
échelles, donc l'omettre les flatterait.
⛔ Les stops **placebos** (< 0,1 % du prix) sont écartés : 155 des 181 stops du
réel en étaient, et ils rendent des R de plusieurs centaines.
"""
from __future__ import annotations

import logging
import math
import os
import random
import statistics as st
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

PAIRE = "XAU/USD"

# Échelles étudiées, en nombre de bougies de 5 min agrégées.
# 1 = M5 (le chemin qui trade), 3 = M15, 6 = M30, 12 = M60.
ECHELLES: tuple[int, ...] = tuple(
    int(x) for x in os.getenv("LABO_OR_ECHELLES", "1,3,6,12").split(",")
    if x.strip().isdigit())

# La fenêtre que voient les détecteurs. ⚠️ La MÊME que le chemin de production
# (`CANDLE_COUNT`), sinon on mesurerait un détecteur qui n'existe pas.
FENETRE = int(os.getenv("LABO_OR_FENETRE", "50"))

# Sous ce nombre de trades, une cellule ne peut RIEN conclure.
MIN_TRADES = int(os.getenv("LABO_OR_MIN_TRADES", "20"))

# Un stop plus serré que ça n'est pas un stop, c'est un placebo.
PLACEBO_PCT = 0.001

# Combien de bougies au maximum on laisse courir un trade avant de le solder au
# marché. 3 000 bougies de l'échelle : large, mais borné.
MAX_BOUGIES_TENUE = 3000


# ─────────────────────────────────────────────────────────────────────
# Le plafond du hasard
# ─────────────────────────────────────────────────────────────────────

# |t| maximal attendu quand AUCUNE cellule n'a d'effet, selon leur nombre.
#
# ⛔ SIMULÉ, pas asymptotique. La formule sqrt(2 ln k) se trompe lourdement pour
# les petits k — et c'est exactement le régime où l'on décide ici. Table obtenue
# par 40 000 tirages par valeur, graine 20260908, le 2026-09-08 : elle ne doit
# pas bouger, sinon le seuil bougerait avec elle.
PLAFOND_HASARD: tuple[tuple[int, float], ...] = (
    (1, 0.798), (2, 1.133), (3, 1.328), (4, 1.461), (6, 1.654), (8, 1.789),
    (12, 1.957), (16, 2.077), (24, 2.241), (32, 2.349), (48, 2.496),
    (64, 2.595), (96, 2.730), (128, 2.829), (192, 2.952), (256, 3.043),
)


def plafond_hasard(k: int) -> float:
    """Le |t| qu'il faut DÉPASSER pour que `k` cellules aient dit autre chose
    que du bruit. Interpolation en log(k) entre les points simulés."""
    if k <= 1:
        return PLAFOND_HASARD[0][1]
    if k >= PLAFOND_HASARD[-1][0]:
        # Au-delà de la table, la croissance est en sqrt(2 ln k) : on prolonge
        # en gardant l'écart constaté au dernier point plutôt que de changer de
        # modèle en cours de route.
        kmax, vmax = PLAFOND_HASARD[-1]
        return vmax + (math.sqrt(2 * math.log(k)) - math.sqrt(2 * math.log(kmax)))
    for (k0, v0), (k1, v1) in zip(PLAFOND_HASARD, PLAFOND_HASARD[1:]):
        if k0 <= k <= k1:
            if k1 == k0:
                return v0
            part = (math.log(k) - math.log(k0)) / (math.log(k1) - math.log(k0))
            return v0 + part * (v1 - v0)
    return PLAFOND_HASARD[-1][1]



# ─────────────────────────────────────────────────────────────────────
# La validation croisee : un verdict sur UN instrument ne vaut rien
# ─────────────────────────────────────────────────────────────────────
#
# ⛔ POURQUOI. Le laboratoire mesure toutes ses cellules sur XAU/USD. Sur 120
# tests, une cellule finit par depasser le plafond PAR HASARD ; le plafond
# corrige ce risque, mais il ne dit pas si le resultat SE REPRODUIT ailleurs.
#
# Or c'est exactement ce que la mesure du 25/08 a etabli : `PBO = 0,579` sur
# l'argent reel — selectionner sur la performance mesuree ne generalise pas,
# pire que pile ou face. Un motif valide sur un seul instrument est l'objet meme
# que le PBO condamne.
#
# ⇒ Un motif qui bat le plafond sur 6 instruments sur 20 est une information
# d'une tout autre nature qu'un motif qui le bat sur l'or seul.

# En dessous, une cellule n'est pas un resultat mais un petit echantillon.
CONCORDANCE_MIN_N = int(os.getenv("LABO_CONCORDANCE_MIN_N", "30"))


def plafond_commun(par_paire: dict[str, list]) -> float:
    """Le plafond du hasard calcule sur TOUTES les cellules, tous instruments.

    ⛔ LE PIEGE QUE CETTE FONCTION EXISTE POUR FERMER. `mesurer()` calcule
    `plafond_hasard(len(cellules))` — les cellules de CETTE paire. Lancer la
    mesure sur vingt instruments produirait vingt plafonds calcules chacun comme
    si l'on n'avait fait que 120 tests, alors qu'on en a fait 2 400.

    Ce serait la porte grande ouverte aux fausses decouvertes : plus on ajoute
    d'instruments, plus on tire de billets, et un plafond par instrument ne le
    voit pas.

        120 cellules   -> 2,81
      2 400 cellules   -> 3,66

    ⚠️ Cout assume : la barre monte pour tout le monde. C'est le prix d'une
    preuve qui vaut quelque chose.
    """
    total = sum(len(c or []) for c in (par_paire or {}).values())
    return plafond_hasard(max(total, 1))


def concordance(par_paire: dict[str, list], plafond: float) -> dict[str, dict]:
    """`{motif: {instruments, sur, paires}}` — ou la meme regle tient ailleurs.

    Ne retient qu'une cellule qui bat le plafond ET porte assez de trades :
    un `t` eleve sur n=4 n'est pas une victoire, c'est un petit echantillon.

    ⛔ LE SIGNE COMPTE. Un motif qui gagne sur une paire et PERD sur une autre
    n'est pas « valide sur deux instruments » : c'est du bruit qui change de
    signe. Les compter ensemble fabriquerait une concordance — on ne retient
    donc que le sens MAJORITAIRE, et l'autre est ignore.

    ⚠️ Un motif isole n'est pas ecarte : il ressort avec son « 1 sur 20 », pour
    qu'on LISE l'isolement au lieu de le deviner.
    """
    retenues: dict[str, dict[int, set]] = {}
    total_paires = len(par_paire or {})
    for paire, cellules in (par_paire or {}).items():
        for c in (cellules or []):
            if (c.get("n") or 0) < CONCORDANCE_MIN_N:
                continue
            t = c.get("t") or 0.0
            if abs(t) <= plafond:
                continue
            signe = 1 if t > 0 else -1
            retenues.setdefault(c["motif"], {}).setdefault(signe, set()).add(paire)

    out: dict[str, dict] = {}
    for motif, par_signe in retenues.items():
        # Le sens MAJORITAIRE : compter les deux ensemble fabriquerait une
        # concordance la ou il n'y a qu'un signe qui bascule.
        signe = max(par_signe, key=lambda s: len(par_signe[s]))
        paires = sorted(par_signe[signe])
        out[motif] = {"instruments": len(paires), "sur": total_paires,
                      "paires": paires, "sens": "gagnant" if signe > 0 else "perdant"}
    return out


# ─────────────────────────────────────────────────────────────────────
# Le rejeu
# ─────────────────────────────────────────────────────────────────────

def _nom_motif(setup) -> str:
    """⚠️ `setup.pattern` emballe l'enum dans `.pattern`. Se tromper de niveau
    rend un identifiant unique par trade — un regroupement qui ne regroupe rien."""
    p = getattr(setup, "pattern", None)
    p = getattr(p, "pattern", p)
    return str(getattr(p, "value", p))


def _sens(setup) -> str:
    d = getattr(setup, "direction", None)
    return str(getattr(d, "value", d)).lower()


# ─── Politiques de sortie ───────────────────────────────────────────
#
# ⛔ CE QUI MANQUAIT (comble le 2026-09-12). `_issue` ne connaissait qu'une
# sortie : stop a -1 R, cible fixe, expiration. Donc rien de ce que « sortir
# et refermer » veut dire — paliers, mise a zero du risque, stop suiveur.
#
# 🔑 COMPARAISON APPARIEE, PAS UN CROISEMENT DE CELLULES. Croiser 4 politiques
# avec les cellules ferait passer 2 356 cellules a ~9 400, et le plafond du
# hasard de 3,66 a 4,28 : on paierait en exigence une question qu'on peut
# poser autrement. La vraie question n'est pas « quelle cellule gagne avec
# quelle sortie », c'est « la gestion de sortie ajoute-t-elle quelque chose a
# la sortie simple ? ». Memes trades, memes stops, seule la sortie change.
#
# ⛔ LE PRIOR A RESPECTER. Mesure du 2026-08-11 : la gestion de sortie a
# DETRUIT de la performance sur l'or, -0,329 R. Ce banc existe pour reproduire
# ou refuter ce chiffre, pas pour justifier une gestion decidee d'avance.
#
# ⚠️ Une politique qui ne se distingue pas de la sortie simple n'est pas
# « neutre, donc on la prend » : c'est un degre de liberte de plus pour rien.
POLITIQUES_SORTIE: tuple[str, ...] = (
    "cible_unique",         # la reference — tout le passe a ete mesure avec
    "equilibre_a_1R",       # stop a l'entree des que +1 R est touche
    "moitie_a_mi_chemin",   # la moitie sort a mi-objectif, le reste court
)


def _issue(bougies, depart: int, entree: float, risque: float, objectif_r: float,
           sens: int, cout: float, politique: str = "cible_unique"
           ) -> tuple[float, int]:
    """Ce que le trade aurait donné, en R, et l'indice de sa sortie.

    ⛔ Le stop est testé AVANT l'objectif, dans TOUTE politique : dans une
    bougie qui contient les deux, on ne sait pas lequel est venu en premier, et
    supposer l'objectif fabriquerait une performance.

    ⛔ Une politique inconnue LÈVE. Retomber en silence sur la sortie simple
    ferait lire « cette gestion ne change rien » alors qu'elle n'a jamais
    tourné — la forme de silence déjà payée quatre fois ici.

    ⚠️ Le coût se paie à CHAQUE fermeture, au prorata de la part fermée. Une
    sortie gratuite ferait gagner toutes les politiques qui coupent souvent.
    """
    if politique not in POLITIQUES_SORTIE:
        raise KeyError(f"politique de sortie inconnue : {politique!r} — "
                       f"connues : {POLITIQUES_SORTIE}")
    j = depart
    fin = min(len(bougies), depart + MAX_BOUGIES_TENUE)
    stop_r = -1.0              # le stop courant, en R
    part = 1.0                 # la part encore ouverte
    acquis = 0.0               # ce qui est deja encaisse, coût déduit
    mi = objectif_r / 2.0

    while j < fin:
        b = bougies[j]
        haut, bas = float(b["h"]), float(b["l"])
        pire = min(sens * (haut - entree), sens * (bas - entree)) / risque
        mieux = max(sens * (haut - entree), sens * (bas - entree)) / risque
        if pire <= stop_r:
            return acquis + part * (stop_r - cout), j
        if mieux >= objectif_r:
            return acquis + part * (objectif_r - cout), j
        # ⚠️ Les deux gestes ci-dessous s'arment APRÈS les sorties : s'armer
        # avant laisserait une bougie déclencher sa propre protection, ce qui
        # est du futur lu à l'envers.
        if politique == "equilibre_a_1R" and mieux >= 1.0 and stop_r < 0.0:
            stop_r = 0.0
        if politique == "moitie_a_mi_chemin" and mieux >= mi and part > 0.5:
            acquis += 0.5 * (mi - cout)
            part = 0.5
        j += 1

    dernier = bougies[min(j, len(bougies) - 1)]
    reste = sens * (float(dernier["c"]) - entree) / risque
    return acquis + part * (reste - cout), j


def comparer_sorties(bougies, releve: dict[int, list], motif: str, sens: str,
                     spread: float,
                     politiques: tuple[str, ...] | None = None) -> dict:
    """Chaque politique, sur EXACTEMENT les mêmes entrées.

    ⛔ L'INVARIANT. Le rejeu est séquentiel (`i = sortie + 1`) : une sortie
    différente décale les entrées suivantes. Si chaque politique rejouait
    seule, elles ne verraient pas les mêmes trades, et l'écart mesurerait une
    différence de POPULATION au lieu d'une différence de GESTION.

    ⇒ La suite des entrées est fixée par la politique de RÉFÉRENCE, puis
    chaque politique est rejouée sur ces indices-là.
    """
    res = _R_par_politique(bougies, releve, motif, sens, spread, politiques)
    if not res:
        return {}
    out: dict[str, dict] = {}
    for p, R in res.items():
        moyenne, t = _stat(R)
        out[p] = {"n": len(R), "r_moyen": moyenne, "t": t, "r_total": sum(R)}
    # ⚠️ L'écart à la référence est le seul chiffre qui réponde à la question.
    ref = out.get(POLITIQUES_SORTIE[0], {}).get("r_moyen", 0.0)
    for p, d in out.items():
        d["delta_reference"] = d["r_moyen"] - ref
    return out


def _R_par_politique(bougies, releve: dict[int, list], motif: str, sens: str,
                     spread: float,
                     politiques: tuple[str, ...] | None = None
                     ) -> dict[str, list[float]]:
    """Les R bruts de chaque politique, sur EXACTEMENT les memes entrees.

    ⛔ Extrait de `comparer_sorties` le 2026-09-14, parce que la mise en commun
    entre motifs a besoin des R **un par un**. Ma premiere version les
    reconstituait a partir des moyennes (`[moyenne] * n`) : la moyenne
    restait juste, mais la variance intra-bloc devenait NULLE et le `t` etait
    fabrique. Un `t` gonfle est pire qu'un `t` absent — il a l'air d'un
    resultat.
    """
    politiques = politiques or POLITIQUES_SORTIE
    entrees: list[tuple[int, float, float, float]] = []
    i, n = FENETRE, len(bougies)
    while i < n:
        candidats = [s for s in releve.get(i, ())
                     if _nom_motif(s) == motif and _sens(s) == sens]
        if not candidats:
            i += 1
            continue
        s = candidats[0]
        entree = float(s.entry_price)
        risque = abs(entree - float(s.stop_loss))
        if risque <= 0 or entree <= 0 or risque / entree < PLACEBO_PCT:
            i += 1
            continue
        objectif_r = abs(float(s.take_profit_1) - entree) / risque
        if objectif_r <= 0:
            i += 1
            continue
        signe = 1 if sens == "buy" else -1
        _, sortie = _issue(bougies, i, entree, risque, objectif_r, signe,
                           spread / risque, politique=POLITIQUES_SORTIE[0])
        entrees.append((i, entree, risque, objectif_r))
        i = sortie + 1

    if not entrees:
        return {}
    signe = 1 if sens == "buy" else -1
    return {p: [_issue(bougies, i, e, r, o, signe, spread / r, politique=p)[0]
                for i, e, r, o in entrees] for p in politiques}


def comparer_sorties_global(bougies, releve: dict[int, list], spread: float,
                            politiques: tuple[str, ...] | None = None) -> dict:
    """La MEME question, posee sur tous les motifs a la fois.

    ⛔ **Pourquoi elle existe** (2026-09-14). `comparer_sorties` repond par
    (motif, sens) : trente reponses par instrument, dont aucune ne dit si la
    gestion de sortie aide **globalement**. Or c'est la seule question que le
    prior pose — « la gestion de sortie a detruit 0,329 R sur l'or ».

    🔑 On MET EN COMMUN les R, on ne moyenne pas des moyennes : une cellule de
    trois trades peserait alors autant qu'une de trois cents.

    ⚠️ L'appariement est preserve : chaque motif garde ses propres entrees,
    fixees par la politique de reference, et toutes les politiques rejouent
    exactement celles-la. Les `n` doivent donc etre IDENTIQUES d'une politique
    a l'autre — un test le verifie, parce qu'un `n` qui differe signifierait
    qu'on compare deux populations.

    ⛔ Ne cree AUCUNE cellule : croiser les politiques avec les cellules
    ferait passer 2 356 cellules a ~9 400 et le plafond du hasard de 3,66 a
    4,28. On paierait en exigence une question qu'on peut poser a part.
    """
    politiques = politiques or POLITIQUES_SORTIE
    paires_motif_sens = sorted({(_nom_motif(s), _sens(s))
                                for liste in releve.values() for s in liste})
    commun: dict[str, list[float]] = {p: [] for p in politiques}
    for motif, sens in paires_motif_sens:
        res = _R_par_politique(bougies, releve, motif, sens, spread, politiques)
        if not res:
            continue
        for p in politiques:
            commun[p] += res.get(p, [])
    if not any(commun.values()):
        return {}
    out: dict[str, dict] = {}
    for p in politiques:
        moyenne, t = _stat(commun[p]) if commun[p] else (0.0, 0.0)
        out[p] = {"n": len(commun[p]), "r_moyen": moyenne, "t": t}
    ref = out.get(POLITIQUES_SORTIE[0], {}).get("r_moyen", 0.0)
    for d in out.values():
        d["delta_reference"] = round(d["r_moyen"] - ref, 6)
    return out


def detections(bougies, pair: str = PAIRE,
               depuis: int | None = None) -> dict[int, list]:
    """Tous les setups détectables, indice par indice. Calculé UNE fois.

    🔑 Sans cette mise en commun, mesurer 10 motifs × 4 échelles demanderait 40
    passages de détection sur 26 000 bougies. On détecte une fois, on rejoue
    ensuite chaque cellule à partir du même relevé.
    """
    from backend.models.schemas import Candle
    from backend.services.pattern_detector import (calculate_trade_setup,
                                                   detect_patterns)
    from datetime import datetime

    def _obj(x):
        d = x["t"]
        if not isinstance(d, datetime):
            d = datetime.fromisoformat(str(d).replace("Z", "+00:00"))
        # ⛔ 2026-09-12 : le volume etait ECRASE PAR UN ZERO LITTERAL ici.
        #
        # C'etait juste tant que la seule source etait Twelve Data, qui rend
        # zero partout (verifie le meme jour : 0 bougie a volume > 0 sur
        # XAU/USD, XAG/USD, EUR/USD). Mais le laboratoire ne lit PAS Twelve
        # Data — `_bougies_et_spread` interroge `/rates` du pont MT5, qui
        # transporte desormais `tv`. Sans cette ligne, le volume traversait le
        # reseau pour mourir a la frontiere.
        #
        # 🔑 `tv`, pas `rv` : `tick_volume` compte les CHANGEMENTS DE PRIX,
        # `real_volume` compte les contrats et vaut zero chez les courtiers
        # CFD. Prendre `rv` rendrait un profil vide en croyant mesurer le
        # marche. Et `tv` doit rester nomme pour ce qu'il est : un compte de
        # ticks, pas un volume negocie — le vrai volume n'existe que sur les
        # futures (COMEX GC/SI).
        #
        # ⚠️ Un pont pas encore redeploye ne rend pas `tv` : on retombe sur
        # zero plutot que de perdre la nuit. Verifie avant d'ecrire : AUCUN
        # detecteur ne lit `volume`, donc ce cablage ne deplace aucun des 30
        # verdicts existants.
        return Candle(timestamp=d, open=float(x["o"]), high=float(x["h"]),
                      low=float(x["l"]), close=float(x["c"]),
                      volume=float(x.get("tv") or 0.0))

    # ⚠️ `depuis` existe pour la PRODUCTION : relever toute la serie
    # demanderait un passage de detection par bougie, soit des centaines par
    # cycle de cinq minutes. Le laboratoire, lui, releve tout — il en a le
    # temps, et il en a besoin.
    out: dict[int, list] = {}
    debut = FENETRE if depuis is None else max(FENETRE, int(depuis))
    for i in range(debut, len(bougies) + (0 if depuis is None else 1)):
        fen = [_obj(x) for x in bougies[i - FENETRE:i]]
        trouves = []
        for motif in detect_patterns(fen, pair):
            s = calculate_trade_setup(pair, motif, fen, is_simulated=False)
            if s is None:
                continue
            trouves.append(s)
        if trouves:
            out[i] = trouves
    return out


# ─── Confluence : mesurer une CHAINE et non un maillon ──────────────
#
# ⛔ LE MANQUE, comble le 2026-09-12. Une cellule valait
# `paire × echelle × UN motif × sens`. Or les methodes qu'on veut eprouver ne
# sont pas des motifs isoles, ce sont des chaines :
#
#     contexte -> niveau majeur -> liquidite -> prise de liquidite
#              -> retest -> confirmation volume -> BUY/SELL
#
# Mesurer les maillons separement ne dit rien de la chaine montee.
#
# 🔑 LE CHOIX DE CONCEPTION qui rend tout le reste gratuit : une chaine produit
# un setup SYNTHETIQUE nomme `chaine:<nom>`, injecte dans le meme releve. Elle
# herite alors, sans une ligne de plus, du stockage, du controle aleatoire de
# son echelle, et surtout du PLAFOND DU HASARD COMMUN. Ajouter des chaines
# releve donc la barre pour tout le monde — c'est voulu : plus de tests,
# exigence plus haute.
#
# ⛔ UNE CHAINE NE PEUT JAMAIS ETRE ARMEE. `chaine:...` n'est pas un
# `PatternType`, donc la liste blanche fail-closed du pont la refuse
# (`pattern_not_allowed`). Le laboratoire mesure ; il n'ouvre aucune porte.

# ⛔ DECLAREES, JAMAIS CHERCHEES. Six conditions librement combinables font des
# dizaines de milliers de chaines. Les essayer toutes garantirait d'en
# « trouver » une qui gagne, et ce serait exactement le geste que l'audit du
# 25/08 condamne : PBO = 0,579 sur l'argent reel — selectionner sur la
# performance mesuree ne generalise pas, pire que pile ou face.
#
# ⚠️ CE QUE CES CHAINES SONT. Notre FORMALISATION d'un vocabulaire (liquidite,
# niveau, structure, confirmation par les volumes). Elles ne sont la methode de
# personne : personne n'a publie ces seuils. Garder la distinction « ce qui est
# dit » / « ce qui est deduit » lisible, sinon on croira avoir reproduit une
# methode qu'on a en realite inventee.
# ⛔ LA FENETRE DE SEQUENCE — « PUIS », pas « ET » (corrige le 2026-09-12).
#
# Premiere version : co-occurrence au MEME indice. Mesure sur 4 111 bougies
# d'or reelles, elle ne s'est jamais declenchee :
#
#     liquidity_sweep_up   194 occurrences
#     bos_up               131 occurrences
#     au MEME indice                       0
#     a 1, 2, 3, 5, 10 bougies d'ecart     0
#     a 20 bougies d'ecart                10
#
# Deux erreurs empilees. J'avais code « ET » quand le vocabulaire dit
# « PUIS ». Et les deux detecteurs sont STRUCTURELLEMENT exclusifs : ils
# lisent la meme fenetre de 30 bougies et disent l'inverse l'un de l'autre —
# un balayage REJETTE un extreme, une cassure CLOTURE au-dela du meme extreme.
# La meme fenetre ne peut pas etre les deux.
#
# 🔑 Le decompte des chaines muettes a revele ce defaut. Sans lui, la chaine
# aurait disparu du releve et on aurait lu « elle ne marche pas » au lieu de
# « elle n'a jamais ete mesuree ».
#
# ⛔ POURQUOI 30, ET PAS LA VALEUR QUI MARCHE. 30 est le `lookback` de
# `_detect_breakout` (`candles[-30:]`), deja partage par le balayage, le BOS
# et le CHoCH. C'est une geometrie EXISTANTE, pas un reglage. Choisir 20 parce
# que c'est la premiere valeur qui donne des resultats serait du reglage sur
# la donnee — de l'edge fabrique, et le PBO de 0,579 dit ou ca mene.
#
# ⚠️ Consequence assumee : si une chaine ne produit qu'une dizaine de trades a
# 30 bougies, le verdict honnete est INSUFFISANT. Une chaine peut etre vraie
# et non mesurable — ce n'est pas la meme chose que fausse.
FENETRE_SEQUENCE = 30

CHAINES: tuple[dict, ...] = (
    # Prise de liquidite PUIS cassure de structure — le balayage seul est un
    # piege, c'est la cassure qui le transforme en direction.
    {"nom": "sweep_puis_structure_haussier",
     "motifs": ("liquidity_sweep_up", "bos_up"),
     "declencheur": "bos_up", "predicats": (), "fenetre": FENETRE_SEQUENCE,
     "invalidants": ("bos_down",)},
    {"nom": "sweep_puis_structure_baissier",
     "motifs": ("liquidity_sweep_down", "bos_down"),
     "declencheur": "bos_down", "predicats": (), "fenetre": FENETRE_SEQUENCE,
     "invalidants": ("bos_up",)},
    # Prise de liquidite sur une zone d'accumulation.
    {"nom": "sweep_sur_order_block_haussier",
     "motifs": ("liquidity_sweep_up", "order_block_up"),
     "declencheur": "order_block_up", "predicats": (),
     "fenetre": FENETRE_SEQUENCE, "invalidants": ("bos_down",)},
    {"nom": "sweep_sur_order_block_baissier",
     "motifs": ("liquidity_sweep_down", "order_block_down"),
     "declencheur": "order_block_down", "predicats": (),
     "fenetre": FENETRE_SEQUENCE, "invalidants": ("bos_up",)},
    # Changement de caractere PUIS desequilibre — le retournement laisse un
    # trou que le prix revient combler.
    {"nom": "choch_puis_fvg_haussier",
     "motifs": ("choch_up", "fvg_up"),
     "declencheur": "fvg_up", "predicats": (), "fenetre": FENETRE_SEQUENCE,
     "invalidants": ("choch_down",)},
    {"nom": "choch_puis_fvg_baissier",
     "motifs": ("choch_down", "fvg_down"),
     "declencheur": "fvg_down", "predicats": (), "fenetre": FENETRE_SEQUENCE,
     "invalidants": ("choch_up",)},
    # ⚠️ Fenetre ZERO ci-dessous : une confirmation par les volumes est
    # SIMULTANEE par definition. Le volume confirme la bougie du signal, pas
    # une bougie d'il y a deux heures.
    {"nom": "niveau_confirme_volume_haussier",
     "motifs": ("range_bounce_up",),
     "declencheur": "range_bounce_up", "predicats": ("volume_fort",),
     "fenetre": 0},
    {"nom": "niveau_confirme_volume_baissier",
     "motifs": ("range_bounce_down",),
     "declencheur": "range_bounce_down", "predicats": ("volume_fort",),
     "fenetre": 0},
    # Cassure CONFIRMEE par les volumes — la fausse cassure est le defaut
    # nomme du motif ; le volume est la confirmation qu'on lui oppose.
    {"nom": "cassure_confirmee_volume_haussier",
     "motifs": ("breakout_up",),
     "declencheur": "breakout_up", "predicats": ("volume_fort",),
     "fenetre": 0},
    {"nom": "cassure_confirmee_volume_baissier",
     "motifs": ("breakout_down",),
     "declencheur": "breakout_down", "predicats": ("volume_fort",),
     "fenetre": 0},
    # ⚠️ HYPOTHESE DE SESSION, declaree le 2026-09-12 : les vraies cassures se
    # font a l'ouverture de Londres, pas a n'importe quelle heure. C'est une
    # hypothese DISTINCTE, pas une variante de la precedente qu'on essaierait
    # en plus — l'essayer « aussi » serait tester deux fois la meme idee.
    {"nom": "cassure_killzone_londres_haussier",
     "motifs": ("breakout_up",),
     "declencheur": "breakout_up", "predicats": ("killzone_londres",),
     "fenetre": 0},
    {"nom": "cassure_killzone_londres_baissier",
     "motifs": ("breakout_down",),
     "declencheur": "breakout_down", "predicats": ("killzone_londres",),
     "fenetre": 0},
    # ⛔ NOTRE lecture des etapes 2 + 4 des cinq de Vivien (declaree le
    # 2026-09-14 dans docs/concepts-trading.md, commit 720fcd3, avant le code).
    # L'etape 3 — « tracer le Volume Profile sur cette zone » — est un geste de
    # LECTURE : elle produit des niveaux, pas une condition d'entree. Elle
    # n'entre donc pas dans la chaine.
    #
    # 🔑 UN SEUL motif, et c'est voulu : la chaine est un SOUS-ENSEMBLE STRICT
    # du balayage. La comparaison avec `liquidity_sweep` seul est donc
    # APPARIEE — la forme la plus lisible, celle de la double prise, et non la
    # forme chevauchante des trois maillons.
    {"nom": "prise_en_accumulation_haussier",
     "motifs": ("liquidity_sweep_up",),
     "declencheur": "liquidity_sweep_up", "predicats": ("dans_accumulation",),
     "fenetre": 0},
    {"nom": "prise_en_accumulation_baissier",
     "motifs": ("liquidity_sweep_down",),
     "declencheur": "liquidity_sweep_down",
     "predicats": ("dans_accumulation",), "fenetre": 0},
    # ⛔ LE PREMIER MAILLON DE LA CHAINE : le contexte (declare le 2026-09-14
    # dans docs/concepts-trading.md, b9aa1cc, avant le code). Un balayage pris
    # a contre-courant de la structure large n'est pas le meme trade.
    #
    # 🔑 Un seul motif : sous-ensemble STRICT du balayage, donc comparaison
    # APPARIEE avec `liquidity_sweep` seul.
    {"nom": "sweep_avec_biais_haussier",
     "motifs": ("liquidity_sweep_up",),
     "declencheur": "liquidity_sweep_up",
     "predicats": ("biais_haussier",), "fenetre": 0},
    {"nom": "sweep_avec_biais_baissier",
     "motifs": ("liquidity_sweep_down",),
     "declencheur": "liquidity_sweep_down",
     "predicats": ("biais_baissier",), "fenetre": 0},
    # ⚠️ ICT / Smart Money — PAS le corpus rapporte le 12/09. Ajoute a la
    # demande explicite de Xavier le 14/09, apres signalement. Declare dans
    # docs/concepts-trading.md (55959f8) avant le code.
    #
    # ⚠️ Recouvrement attendu avec le balayage lui-meme : un balayage des bas a
    # de bonnes chances d'etre deja sous l'equilibre. A MESURER, pas a deduire.
    # ⛔ MONTAGE CORRIGE APRES MESURE (2026-09-14). Ma premiere version
    # accrochait le contexte au BALAYAGE. Mesure sur 15 jours, XAU/USD :
    #
    #     liquidity_sweep_up    en discount  91,8 %      bos_up      0,0 %
    #     liquidity_sweep_down  en discount   7,8 %      breakout_up 2,0 %
    #
    # Un balayage des bas EST deja en discount — par construction, puisqu'il
    # fait un nouveau plus-bas. Le filtre n'ecartait que 8 % des cas : 160
    # cellules pour presque aucune information, et le plafond du hasard monte
    # pour TOUT LE MONDE.
    #
    # 🔑 Accroche a un motif dont la position n'est PAS determinee par sa
    # definition, le meme filtre discrimine vraiment :
    #
    #     engulfing_bullish     en discount  45,5 %
    #     engulfing_bearish     en discount  61,0 %  (donc 39 % en premium)
    #
    # C'est aussi la lecture ICT fidele : « n'achete un signal haussier qu'en
    # discount » — un avalement haussier peut survenir n'importe ou dans la
    # fourchette, un balayage des bas non.
    {"nom": "avalement_en_discount_haussier",
     "motifs": ("engulfing_bullish",),
     "declencheur": "engulfing_bullish",
     "predicats": ("en_discount",), "fenetre": 0},
    {"nom": "avalement_en_premium_baissier",
     "motifs": ("engulfing_bearish",),
     "declencheur": "engulfing_bearish",
     "predicats": ("en_premium",), "fenetre": 0},
    # ⛔ LE MAILLON 3 : le niveau majeur (declare le 2026-09-20 dans
    # docs/concepts-trading.md, avant le code). Un balayage pris n'importe ou
    # n'est pas un balayage pris sur un niveau que le marche a defendu a
    # l'echelle que tout le monde regarde.
    #
    # 🔑 Un seul motif : sous-ensemble STRICT du balayage, donc comparaison
    # APPARIEE avec `liquidity_sweep` seul.
    #
    # ⚠️ Balayer les HAUTS fait VENDRE : la chaine baissiere porte le predicat
    # du cote `haut`. L'inverser mesurerait la chaine sans sa condition.
    {"nom": "sweep_sur_niveau_majeur_haussier",
     "motifs": ("liquidity_sweep_up",),
     "declencheur": "liquidity_sweep_up",
     "predicats": ("sur_niveau_majeur_bas",), "fenetre": 0},
    {"nom": "sweep_sur_niveau_majeur_baissier",
     "motifs": ("liquidity_sweep_down",),
     "declencheur": "liquidity_sweep_down",
     "predicats": ("sur_niveau_majeur_haut",), "fenetre": 0},
    # ⛔ LE MAILLON « M15 = setup, M5 = trigger » (declare le 2026-09-20 dans
    # docs/concepts-trading.md, avant le code). La structure d'une echelle
    # AGREGEE devient un contexte pour un declencheur d'une autre echelle :
    # jusqu'ici chaque cellule vivait entierement dans un seul horizon.
    #
    # 🔑 Recouvrement avec le BIAIS mesure AVANT de declarer, fixture figee,
    # 230 observations par sens : 29,3 % / 41,5 % en haussier, 46,4 % / 47,1 %
    # en baissier. Ni inclusion, ni redondance — les deux echelles disent autre
    # chose plus d'une fois sur deux. C'est ce chiffre qui justifie ces deux
    # chaines ; sans lui, elles auraient double le biais en silence.
    #
    # ⚠️ Un seul motif : sous-ensemble STRICT du balayage, comparaison APPARIEE.
    {"nom": "sweep_avec_structure_m15_haussier",
     "motifs": ("liquidity_sweep_up",),
     "declencheur": "liquidity_sweep_up",
     "predicats": ("structure_m15_haussiere",), "fenetre": 0},
    {"nom": "sweep_avec_structure_m15_baissier",
     "motifs": ("liquidity_sweep_down",),
     "declencheur": "liquidity_sweep_down",
     "predicats": ("structure_m15_baissiere",), "fenetre": 0},
)

# Un pic de volume : la bougie que le detecteur vient de voir porte au moins
# 1,5 fois le volume median des 20 precedentes. AUCUN REGLAGE NEUF ailleurs —
# ce seuil est le seul de la confluence, et il est ecrit ici, pas disperse.
VOLUME_FORT_MULT = float(os.getenv("LABO_VOLUME_FORT_MULT", "1.5"))
VOLUME_FENETRE = 20


def _volume_fort(bougies, i: int) -> bool:
    """⚠️ Rend False quand le volume est ABSENT ou nul.

    Un pont pas encore redeploye ne rend pas `tv`. Repondre True par defaut
    ferait declencher la chaine partout en pretendant avoir vu un volume —
    la chaine mesurerait alors autre chose que ce que son nom annonce.
    """
    j = i - 1                      # la derniere bougie vue par le detecteur
    if j < VOLUME_FENETRE:
        return False
    fenetre = [float(b.get("tv") or 0.0)
               for b in bougies[j - VOLUME_FENETRE:j]]
    ref = st.median(fenetre) if fenetre else 0.0
    if ref <= 0:
        return False               # pas de donnee : on ne valide pas
    return float(bougies[j].get("tv") or 0.0) >= ref * VOLUME_FORT_MULT


# ─── Les sessions ───────────────────────────────────────────────────
#
# ⛔ HEURES LOCALES DE CHAQUE PLACE, JAMAIS UTC FIXE. Londres et New York
# changent d'heure, et a des dates differentes. Des bornes en UTC fixe
# decaleraient les sessions d'une heure LA MOITIE DE L'ANNEE — et la mesure
# dirait « ce motif marche le matin » en ayant regarde deux fenetres
# differentes selon la saison.
#
# ⚠️ Ces bornes sont une CONVENTION DECLAREE, pas une mesure : ce sont les
# horaires d'ouverture publics des places. Les deplacer serait un choix a
# ecrire, jamais un reglage a optimiser.
# ⛔ DECLAREES UNE SEULE FOIS, dans `sessions_marche` : l'opening range
# en a besoin cote detecteur. Deux tables finiraient par diverger, et deux
# mesures porteraient le meme nom en decrivant deux fenetres.
from backend.services.sessions_marche import SESSIONS as _SESSIONS


def _instant(bougies, i: int):
    """L'horodatage de la bougie `i`, en datetime conscient — ou `None`.

    ⛔ `t` est une CHAINE dans les bougies brutes et un `datetime` apres
    `_agreger_brut`. Ne gerer qu'une forme rendrait les sessions muettes sur
    M15, M30 et H1 — en silence, exactement comme le volume l'a ete.
    """
    # ⛔ L'INDICE D'ENTREE PEUT NE PAS ENCORE EXISTER (2026-09-14). Le
    # laboratoire lit `bougies[i]` : la bougie sur laquelle on ENTRE, une de
    # plus que ce que le detecteur a vu. Elle existe toujours dans un rejeu.
    # En PRODUCTION elle n'est pas encore formee — et `None` rendait alors
    # toutes les chaines de session muettes, en silence. Mesure du jour : le
    # labo voyait `cassure_killzone_londres_haussier`, la production rien.
    #
    # 🔑 On EXTRAPOLE l'horodatage de la bougie a venir depuis le pas de la
    # serie. Le laboratoire, lui, ne passe jamais par ce chemin : sa boucle
    # s'arrete a `len - 1`. Aucune mesure existante ne bouge.
    if i == len(bougies) >= 2:
        avant, dernier = _instant(bougies, i - 2), _instant(bougies, i - 1)
        if avant is None or dernier is None:
            return None
        return dernier + (dernier - avant)
    if not (0 <= i < len(bougies)):
        return None
    t = bougies[i].get("t")
    if isinstance(t, datetime):
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(t).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None            # fail-closed : une date illisible ne valide rien
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _dans_session(nom: str):
    """Fabrique le prédicat de la session `nom`. Lu sur la bougie du SIGNAL."""
    zone, debut, fin = _SESSIONS[nom]

    def _predicat(bougies, i: int) -> bool:
        d = _instant(bougies, i)
        if d is None:
            return False
        try:
            from zoneinfo import ZoneInfo
            local = d.astimezone(ZoneInfo(zone))
        except Exception:      # noqa: BLE001 — base tz absente
            # ⛔ On rend NON, jamais un repli en UTC fixe : un repli
            # silencieux mesurerait une autre fenetre sous le meme nom.
            logger.warning("labo_or: zone horaire %s indisponible — session "
                           "%s repond NON", zone, nom)
            return False
        mn = local.hour * 60 + local.minute
        return debut[0] * 60 + debut[1] <= mn < fin[0] * 60 + fin[1]

    return _predicat


# ⛔ Fail-closed : un predicat mal orthographie doit LEVER. S'il rendait True,
# la chaine serait mesuree sans sa condition et le verdict serait faux sans
# que rien ne le dise.
def _dans_accumulation(bougies, i: int) -> bool:
    """Le balayage se produit-il DANS une zone d'accumulation ?

    C'est notre lecture des etapes 2 et 4 des cinq de Vivien : trouver une
    zone d'accumulation, puis y attendre une prise de liquidite.

    ⛔ Les seuils sont les NOTRES (`market_profile.ACCU_*`), declares dans
    `docs/concepts-trading.md` avant d'etre codes. Aucun seuil n'a ete publie
    par Vivien : presenter les notres comme sa definition fabriquerait « un
    robot inspire de Vivien » qu'on croirait fidele.

    ⚠️ Lit `bougies[:i]` — ce que le detecteur a vu, pas une bougie de plus.
    Meme discipline que `_volume_fort` : un predicat qui regarde au-dela du
    signal mesure l'avenir.
    """
    from datetime import datetime

    from backend.models.schemas import Candle
    from backend.services import market_profile as mp

    vues = bougies[:i]
    besoin = mp.ACCU_RECENTES + mp.ACCU_AVANT
    if len(vues) < besoin:
        return False
    fen = vues[-besoin:]
    try:
        objets = [Candle(
            timestamp=(x["t"] if isinstance(x["t"], datetime)
                       else datetime.fromisoformat(str(x["t"]).replace("Z", "+00:00"))),
            open=float(x["o"]), high=float(x["h"]), low=float(x["l"]),
            close=float(x["c"]), volume=float(x.get("tv") or 0.0)) for x in fen]
    except Exception:  # noqa: BLE001 — bougie malformee : on ne valide pas
        return False
    return mp.zone_accumulation(objets, source=mp.VOLUME) is not None


# ─── Le biais de l'echelle superieure ───────────────────────────────
#
# ⛔ AGREGER EN H4 FIXE SERAIT FAUX. Le laboratoire mesure chaque motif a
# quatre echelles ; un « biais H4 » calcule sur des bougies d'une heure serait
# un biais de HUIT JOURS sous le meme nom. Deux fenetres, un seul nom — le
# defaut que `sessions_marche` existe pour empecher ailleurs.
#
# 🔑 Le biais est donc RELATIF a l'echelle mesuree : la meme
# `_tendance_de_structure` — qui coupe une fenetre en deux et exige A LA FOIS
# un plus-haut ET un plus-bas superieurs — sur une fenetre 8 x plus longue.
# A l'echelle 5 min cela regarde 20 h de marche : l'ordre de grandeur du H4.
#
# ⚠️ UN SEUL reglage neuf : le facteur. Chaque seuil supplementaire est un
# degre de liberte, donc de l'edge fabrique.
BIAIS_FACTEUR = 8
BIAIS_FENETRE = BIAIS_FACTEUR * FENETRE


def _biais(attendu: str):
    """Fabrique le predicat « la structure large est `attendu` »."""

    def _predicat(bougies, i: int) -> bool:
        from datetime import datetime

        from backend.models.schemas import Candle
        from backend.services.pattern_detector import _tendance_de_structure

        # ⚠️ `bougies[:i]` — ce que le detecteur a vu, pas une bougie de plus.
        vues = bougies[:i]
        if len(vues) < BIAIS_FENETRE:
            return False            # fail-closed : pas d'histoire, pas de biais
        fen = vues[-BIAIS_FENETRE:]
        try:
            objets = [Candle(
                timestamp=(x["t"] if isinstance(x["t"], datetime)
                           else datetime.fromisoformat(
                               str(x["t"]).replace("Z", "+00:00"))),
                open=float(x["o"]), high=float(x["h"]), low=float(x["l"]),
                close=float(x["c"]), volume=float(x.get("tv") or 0.0))
                for x in fen]
        except Exception:  # noqa: BLE001 — bougie malformee : on ne valide pas
            return False
        return _tendance_de_structure(objets) == attendu

    return _predicat


def _cote_de_l_equilibre(veut_discount: bool):
    """Fabrique le predicat « le prix est du bon cote de l'equilibre ».

    ⚠️ Concept ICT, PAS du corpus rapporte le 12/09 — ajoute a la demande
    explicite de Xavier le 14/09. Cf. `market_profile.zone_premium_discount`.
    """

    def _predicat(bougies, i: int) -> bool:
        from datetime import datetime

        from backend.models.schemas import Candle
        from backend.services import market_profile as mp

        vues = bougies[:i]          # ce que le detecteur a vu, pas une de plus
        if len(vues) < FENETRE:
            return False            # fail-closed : pas de fourchette, pas d'avis
        fen = vues[-FENETRE:]
        try:
            objets = [Candle(
                timestamp=(x["t"] if isinstance(x["t"], datetime)
                           else datetime.fromisoformat(
                               str(x["t"]).replace("Z", "+00:00"))),
                open=float(x["o"]), high=float(x["h"]), low=float(x["l"]),
                close=float(x["c"]), volume=float(x.get("tv") or 0.0))
                for x in fen]
        except Exception:  # noqa: BLE001 — bougie malformee : on ne valide pas
            return False
        z = mp.zone_premium_discount(objets)
        if z is None:
            return False
        return bool(z["discount"]) if veut_discount else bool(z["premium"])

    return _predicat


# ─── LE NIVEAU MAJEUR (2026-09-20) ──────────────────────────────────
#
# Declare dans `docs/concepts-trading.md` AVANT d'etre code. Le maillon 3 de la
# chaine rapportee le 12/09 decide OU on attend la liquidite ; sans lui, le
# balayage se declenche sur le max glissant des 30 dernieres bougies — donc
# n'importe ou. `_find_level` ne le comble pas : il moyenne les cinq extremes
# de la fenetre courante, une seule echelle.
#
# ⛔ AUCUN REGLAGE NEUF. La fenetre est celle du BIAIS (`BIAIS_FENETRE` = 400),
# la tolerance est le `0,5 x ATR(14)` de `_IMPULSION_MIN_ATR`.
# ⚠️ C'est une REUTILISATION, pas une derivation : rien ne prouve que la bonne
# tolerance soit celle de l'impulsion. Posee une fois, jamais ajustee.
#
# ⛔ LE NIVEAU DOIT PREEXISTER — la bougie courante est EXCLUE de la fenetre.
# Sans cette exclusion, toute bougie faisant un nouvel extreme de 400 serait a
# distance ZERO de « son » niveau, et le predicat serait vrai par construction.
# C'est l'objection declaree dans le carnet, et elle est traitee ICI, pas plus
# tard.
#
# ⚠️ CE QUI EST COMPARE, et le choix est assume. On compare l'extreme que la
# bougie a ATTEINT (son propre haut, ou son propre bas) au niveau, pas le max
# des 30 qu'elle a franchi. Raison : le `30` du balayage est un litteral dans
# `_detect_liquidity_sweep`, non exporte ; le recopier ici en ferait une
# SECONDE source du meme chiffre — le defaut que ce depot paie en boucle. Les
# deux grandeurs ne sont pas identiques (le haut de la bougie est au-dessus du
# max des 30) : l'ecart vaut le depassement de la meche, et il est assume.
NIVEAU_TOLERANCE_ATR = 0.5


def _sur_niveau_majeur(cote: str):
    """Fabrique le predicat « l'extreme atteint est a portee du niveau de 400 ».

    `cote` vaut "haut" (balayage des hauts, donc une VENTE) ou "bas".
    """

    def _predicat(bougies, i: int) -> bool:
        from datetime import datetime

        from backend.models.schemas import Candle
        from backend.services.pattern_detector import _calculate_atr

        # ⚠️ `bougies[:i]` — ce que le detecteur a vu ; sa DERNIERE bougie est
        # `vues[-1]`, celle qui porte le balayage. Pas `bougies[i]`, que le
        # detecteur n'a jamais vue.
        vues = bougies[:i]
        avant = vues[:-1]
        if len(avant) < BIAIS_FENETRE:
            return False            # fail-closed : pas d'histoire, pas de niveau
        fen = avant[-BIAIS_FENETRE:]
        try:
            if cote == "haut":
                niveau = max(float(x["h"]) for x in fen)
                atteint = float(vues[-1]["h"])
            else:
                niveau = min(float(x["l"]) for x in fen)
                atteint = float(vues[-1]["l"])
            objets = [Candle(
                timestamp=(x["t"] if isinstance(x["t"], datetime)
                           else datetime.fromisoformat(
                               str(x["t"]).replace("Z", "+00:00"))),
                open=float(x["o"]), high=float(x["h"]), low=float(x["l"]),
                close=float(x["c"]), volume=float(x.get("tv") or 0.0))
                for x in vues[-15:]]
        except Exception:  # noqa: BLE001 — bougie malformee : on ne valide pas
            return False
        atr = _calculate_atr(objets, period=14)
        if atr <= 0:
            return False            # sans echelle, pas de tolerance
        # ⛔ LE NIVEAU NE DOIT PAS ETRE DEPASSE — correction du 2026-09-20,
        # imposee par la mesure de recouvrement et PREVUE par la declaration.
        # Sans cette ligne, mesure sur la fixture figee (4 598 fenetres) :
        #   balayage des HAUTS : 31 declenchements, dont 80,6 % DEPASSENT ;
        #   balayage des BAS   : 53 declenchements, dont 94,3 % DEPASSENT.
        # La regle mesurait donc une CASSURE de la grande fourchette, pas un
        # niveau retesté — deux populations opposees sous un seul nom. La
        # version large etait la plus fournie ET la moins fidele : c'est la
        # forme exacte du reglage sur la donnee que ce laboratoire refuse.
        if (atteint > niveau) if cote == "haut" else (atteint < niveau):
            return False
        return abs(atteint - niveau) <= NIVEAU_TOLERANCE_ATR * atr

    return _predicat


# ─── LA STRUCTURE DE L'ECHELLE AGREGEE — M15 (2026-09-20) ───────────
#
# Declare dans `docs/concepts-trading.md` AVANT d'etre code. Le critere
# rapporte : casser le high M15 fait repasser la structure M15 haussiere.
#
# 🔑 CE QUI EST NEUF n'est pas la cassure de structure — `bos_up` / `bos_down`
# existent depuis le 09/09. C'est que la structure d'une ECHELLE AGREGEE
# devienne un PREDICAT disponible pour un declencheur d'une autre echelle.
# Aujourd'hui chaque cellule vit entierement dans un seul horizon : un balayage
# 5 min ne sait rien de l'etat du M15.
#
# ⛔ AUCUN REGLAGE NEUF. `echelle_agregee.agreger` existe depuis le 2026-09-08
# et a ete mesure AVANT d'etre construit ; `_tendance_de_structure` n'a aucun
# seuil propre ; la fenetre est `FENETRE`, celle des detecteurs, appliquee a
# l'echelle agregee. Le `+ 2` ci-dessous est une marge d'alignement sur
# l'horloge — `agreger` ecarte le groupe incomplet — pas un reglage de
# strategie.
#
# ⚠️ CE QUE NOUS REDUISONS, et c'est ecrit dans le carnet : le critere rapporte
# decrit une BASCULE (« casser le high FAIT REPASSER la structure haussiere ») ;
# `_tendance_de_structure` rend un ETAT. Nous mesurons donc « la structure M15
# EST haussiere », pas « elle VIENT DE basculer ». Un etat dure des heures la ou
# une bascule est instantanee : ce ne sont pas les memes trades. Reduction
# assumee, pas implementation fidele.
M15_FACTEUR = 3      # 3 x 5 min : l'agregation, pas un reglage


def _structure_agregee(attendu: str, facteur: int = M15_FACTEUR):
    """Fabrique le predicat « la structure de l'echelle agregee est `attendu` »."""

    def _predicat(bougies, i: int) -> bool:
        from datetime import datetime

        from backend.models.schemas import Candle
        from backend.services.echelle_agregee import agreger
        from backend.services.pattern_detector import _tendance_de_structure

        # ⚠️ `bougies[:i]` — ce que le detecteur a vu, pas une bougie de plus.
        vues = bougies[:i]
        besoin = (FENETRE + 2) * facteur
        if len(vues) < besoin:
            return False        # fail-closed : pas d'histoire, pas de structure
        fen = vues[-besoin:]
        try:
            objets = [Candle(
                timestamp=(x["t"] if isinstance(x["t"], datetime)
                           else datetime.fromisoformat(
                               str(x["t"]).replace("Z", "+00:00"))),
                open=float(x["o"]), high=float(x["h"]), low=float(x["l"]),
                close=float(x["c"]), volume=float(x.get("tv") or 0.0))
                for x in fen]
            agregees = agreger(objets, facteur)
        except Exception:  # noqa: BLE001 — bougie malformee : on ne valide pas
            return False
        # L'agregation ecarte les groupes incomplets : elle peut rendre moins
        # que `FENETRE`. Dans ce cas on ne se prononce pas.
        if len(agregees) < FENETRE:
            return False
        return _tendance_de_structure(agregees[-FENETRE:]) == attendu

    return _predicat


_PREDICATS = {"volume_fort": _volume_fort,
              "dans_accumulation": _dans_accumulation,
              "biais_haussier": _biais("haussiere"),
              "biais_baissier": _biais("baissiere"),
              "en_discount": _cote_de_l_equilibre(True),
              "en_premium": _cote_de_l_equilibre(False),
              "sur_niveau_majeur_haut": _sur_niveau_majeur("haut"),
              "sur_niveau_majeur_bas": _sur_niveau_majeur("bas"),
              "structure_m15_haussiere": _structure_agregee("haussiere"),
              "structure_m15_baissiere": _structure_agregee("baissiere")}
_PREDICATS.update({nom: _dans_session(nom) for nom in _SESSIONS})


class _SetupChaine:
    """Le setup du DECLENCHEUR, renomme au nom de la chaine.

    🔑 SL et TP viennent du chemin deja eprouve. En inventer de nouveaux
    ajouterait des degres de liberte — donc de l'edge fabrique.

    `_nom_motif` deroule `setup.pattern` puis `.pattern` puis `.value` : une
    chaine de caracteres traverse les trois et ressort telle quelle.
    """

    __slots__ = ("pattern", "_base")

    def __init__(self, nom: str, base):
        self.pattern = f"chaine:{nom}"
        self._base = base

    def __getattr__(self, nom):
        return getattr(self._base, nom)


def chaines_detectees(releve: dict[int, list], bougies,
                      chaines: tuple[dict, ...] | None = None
                      ) -> tuple[dict[int, list], dict[str, int]]:
    """`({indice: [setups de chaine]}, {nom: nombre de declenchements})`.

    ⛔ Le DECOMPTE fait partie du contrat. Sans trade, aucune cellule n'est
    creee : la chaine disparait du releve et devient indiscernable d'une
    chaine qui ne marche pas. C'est la forme de silence deja payee quatre fois
    ici — on rend donc les zeros.
    """
    # ⛔ Les notions DECLAREES entrent ici, au meme titre que les chaines
    # ecrites a la main : une notion completee par Xavier doit se mesurer sans
    # une ligne de code. Tant qu'il manque une des six lignes, elle ne produit
    # rien — cf. `notions_vivien`, qui LEVE sur un nom inconnu plutot que de
    # mesurer une chaine amputee de sa condition.
    if chaines is None:
        from backend.services.notions_vivien import chaines as _declarees
        chaines = CHAINES + _declarees()
    sortie: dict[int, list] = {}
    compte: dict[str, int] = {c["nom"]: 0 for c in chaines}

    # ⚠️ Indexe par (motif, SENS), pas par motif seul. Un balayage haussier
    # plus une cassure baissiere n'est pas une confluence, c'est une
    # contradiction — la mesurer melangerait deux paris opposes.
    ou: dict[tuple[str, str], set[int]] = {}
    for i, liste in releve.items():
        for s in liste:
            ou.setdefault((_nom_motif(s), _sens(s)), set()).add(i)

    for c in chaines:
        decl = c["declencheur"]
        fen = int(c.get("fenetre", 0) or 0)
        autres = [m for m in c["motifs"] if m != decl]
        for sens in ("buy", "sell"):
            for i in sorted(ou.get((decl, sens), ())):
                # ⛔ « PUIS » : le maillon precede le declencheur, ou tombe sur
                # la meme bougie. Accepter l'ordre inverse mesurerait une autre
                # chaine sous le meme nom.
                # `ou_maillon` retient la position REELLE de chaque maillon :
                # elle borne la zone ou un dementi compte.
                ou_maillon = []
                for m in autres:
                    trouve = next((i - d for d in range(0, fen + 1)
                                   if (i - d) in ou.get((m, sens), ())), None)
                    if trouve is None:
                        break
                    ou_maillon.append(trouve)
                if len(ou_maillon) != len(autres):
                    continue
                # ⛔ L'INVALIDATION (2026-09-12). Une chaine acceptait un
                # maillon jusqu'a 30 bougies avant son declencheur, et rien
                # n'interdisait qu'entre les deux le marche ait fait
                # EXACTEMENT LE CONTRAIRE : balayage haussier, puis cassure
                # baissiere, puis cassure haussiere du declencheur. La chaine
                # se declenchait quand meme, sur un maillon que les faits
                # avaient deja dementi. La fenetre de 30 etait une passoire.
                #
                # ⚠️ Un dementi ANTERIEUR au maillon ne compte pas : il
                # appartient a une histoire precedente, et l'inclure
                # reviendrait a remonter indefiniment dans le passe.
                invalidants = c.get("invalidants", ())
                if invalidants and ou_maillon:
                    depuis = min(ou_maillon)
                    if any(k in ou.get((m, s2), ())
                           for m in invalidants
                           for s2 in ("buy", "sell")
                           for k in range(depuis + 1, i)):
                        continue
                if not all(_PREDICATS[p](bougies, i) for p in c["predicats"]):
                    continue
                # 🔑 Le setup vient du DECLENCHEUR, a SON indice : les niveaux
                # d'un maillon vieux de 30 bougies seraient perimes.
                base = next((s for s in releve.get(i, ())
                             if _nom_motif(s) == decl and _sens(s) == sens),
                            None)
                if base is None:
                    continue
                sortie.setdefault(i, []).append(_SetupChaine(c["nom"], base))
                compte[c["nom"]] += 1
    return sortie, compte


def fusionner_chaines(releve: dict[int, list], bougies,
                      chaines: tuple[dict, ...] | None = None
                      ) -> dict[int, list]:
    """Le releve enrichi des chaines — les motifs simples restent intacts."""
    trouvees, compte = chaines_detectees(releve, bougies, chaines)
    muettes = [n for n, k in compte.items() if k == 0]
    if muettes:
        # ⚠️ Une chaine qui ne se declenche jamais n'est pas « sans resultat » :
        # c'est une mesure qui n'a pas eu lieu, et il faut pouvoir le lire.
        logger.info("labo_or: chaines jamais declenchees : %s",
                    ", ".join(sorted(muettes)))
    if not trouvees:
        return releve
    fusion = {i: list(liste) for i, liste in releve.items()}
    for i, liste in trouvees.items():
        fusion.setdefault(i, []).extend(liste)
    return fusion


def rejouer_cellule(bougies, releve: dict[int, list], motif: str, sens: str,
                    spread: float) -> list[dict]:
    """Rejeu SÉQUENTIEL d'une cellule : jamais deux trades ouverts à la fois."""
    trades: list[dict] = []
    i = FENETRE
    n = len(bougies)
    while i < n:
        candidats = [s for s in releve.get(i, ())
                     if _nom_motif(s) == motif and _sens(s) == sens]
        if not candidats:
            i += 1
            continue
        s = candidats[0]
        entree = float(s.entry_price)
        risque = abs(entree - float(s.stop_loss))
        # ⛔ Un stop sous 0,1 % du prix n'est pas un stop : il rend des R de
        # plusieurs centaines et ferait exploser toute moyenne.
        if risque <= 0 or entree <= 0 or risque / entree < PLACEBO_PCT:
            i += 1
            continue
        objectif_r = abs(float(s.take_profit_1) - entree) / risque
        if objectif_r <= 0:
            i += 1
            continue
        signe = 1 if sens == "buy" else -1
        R, sortie = _issue(bougies, i, entree, risque, objectif_r, signe,
                           spread / risque)
        trades.append({"R": R, "risque": risque, "cout": spread / risque,
                       "objectif_r": objectif_r})
        i = sortie + 1
    return trades


# ⛔ UN SEUL TIRAGE NE SUFFIT PAS. Mesuré le 2026-09-15 sur l'or, 365 jours :
# la moyenne d'un tirage de 300 trades saute de **±0,10 R** d'une graine à
# l'autre — soit plus du DOUBLE de l'effet qu'on cherche à corriger (la dérive
# directionnelle, ≈ 0,045 R). Le signe d'un contrôle acheteur contre un
# contrôle vendeur s'inversait d'une graine à l'autre dans 2 cas sur 6.
#
# 🔑 Tant que le contrôle ne servait qu'à donner le SIGNE du delta, sa
# dispersion passait inaperçue. Depuis que le verdict s'appuie sur l'écart au
# contrôle, elle entrerait DIRECTEMENT dans les verdicts. On met donc en commun
# plusieurs tirages : la référence doit être stable, sinon elle n'est pas une
# référence.
CONTROLE_GRAINES = int(os.getenv("LABO_OR_CONTROLE_GRAINES", "20"))


def controle_poole(bougies, spread: float, combien: int, risque_median: float,
                   objectif_r: float, graine: int, sens: str | None = None,
                   graines: int | None = None) -> list[float]:
    """Les R de `graines` tirages successifs, mis en commun.

    ⚠️ On met en commun les R **un par un**, jamais les moyennes : moyenner des
    moyennes rendrait une dispersion artificiellement petite et un t de Welch
    gonflé. Même piège que `_R_par_politique` a payé le 2026-09-14.
    """
    out: list[float] = []
    for k in range(graines or CONTROLE_GRAINES):
        out += [x["R"] for x in controle_aleatoire(
            bougies, spread, combien, risque_median, objectif_r,
            graine + k, sens=sens)]
    return out


def controle_aleatoire(bougies, spread: float, combien: int, risque_median: float,
                       objectif_r: float, graine: int,
                       sens: str | None = None) -> list[dict]:
    """Les mêmes trades, mais déclenchés AU HASARD.

    🔑 La seule comparaison qui vaille. « Aucun système ne bat le hasard » a été
    établi comme ça : Δ = +0,004 R sur 29 000 trades. Une cellule qui gagne
    autant que le hasard n'apporte rien, même si son R moyen est positif.

    ⚠️ Même population : même nombre de trades, même distance de stop médiane,
    même objectif, même contrainte séquentielle — et depuis le 2026-09-15,
    **le même SENS**.

    ⛔ LE DÉFAUT QUE `sens` FERME. Sans lui, le tirage prenait le sens à pile ou
    face. Sur un marché qui dérive, il moyenne donc les deux sens à zéro
    pendant qu'une cellule à sens unique encaisse la dérive entière : son
    `delta_hasard` est gonflé de toute la tendance. Mesuré sur l'or, 365 jours
    à +16,6 % : ≈ +0,045 R par trade pour un achat, soit la MOITIÉ du `r_moyen`
    de la meilleure cellule acheteuse. On croyait mesurer un motif, on mesurait
    le marché.

    `sens=None` garde le tirage à pile ou face — la référence d'une population
    sans direction propre. Un sens inconnu **LÈVE** : retomber en silence sur
    pile ou face rendrait un chiffre faux qui a l'air d'un résultat.
    """
    if sens is not None and sens not in ("buy", "sell"):
        raise ValueError(f"sens de contrôle inconnu : {sens!r} — "
                         "attendu 'buy', 'sell' ou None")
    if combien <= 0 or risque_median <= 0:
        return []
    fixe = None if sens is None else (1 if sens == "buy" else -1)
    tirage = random.Random(graine)          # ⛔ reproductible
    trades: list[dict] = []
    i = FENETRE
    n = len(bougies)
    # Une entrée toutes les `pas` bougies en moyenne, pour couvrir la période
    # entière plutôt que d'agglomérer les tirages au début.
    pas = max(1, (n - FENETRE) // max(1, combien))
    while i < n and len(trades) < combien:
        b = bougies[i]
        entree = float(b["c"])
        # ⚠️ Le tirage est consommé même quand le sens est imposé : sans ça,
        # les flux aléatoires des contrôles acheteur et vendeur divergeraient
        # dès la première entrée et ne seraient plus comparables entre eux.
        pile = 1 if tirage.random() < 0.5 else -1
        signe = pile if fixe is None else fixe
        R, sortie = _issue(bougies, i, entree, risque_median, objectif_r, signe,
                           spread / risque_median)
        trades.append({"R": R})
        i = max(sortie + 1, i + tirage.randint(1, max(2, pas * 2)))
    return trades


# ⛔ En dessous de cette dispersion, le t n'a plus de sens.
#
# Vu à la première passe : `60min mean_reversion_down` a rendu **t = −685**
# sur 8 trades. Cause : les 8 avaient tous touché le stop, donc des R quasi
# identiques (−1,013), un écart-type proche de zéro, et un t qui explose. Ce
# n'est pas un signal fort, c'est une division par presque rien.
#
# ⚠️ Là, la cellule était écartée par `MIN_TRADES`. Avec 20 trades tous perdants
# elle serait passée pour la découverte du siècle.
ECART_MINIMAL_R = float(os.getenv("LABO_OR_ECART_MINIMAL_R", "0.05"))


def _stat(valeurs: list[float]) -> tuple[float, float]:
    """Moyenne et t de Student. `t = 0` quand l'échantillon ne permet rien.

    ⛔ Une dispersion quasi nulle rend `t = 0`, pas l'infini : quand tous les
    trades finissent pareil, on n'a pas mesuré une régularité, on a mesuré une
    absence de variété.
    """
    if len(valeurs) < 2:
        return (valeurs[0] if valeurs else 0.0), 0.0
    m = st.mean(valeurs)
    ecart = st.stdev(valeurs)
    if ecart < ECART_MINIMAL_R:
        return m, 0.0
    return m, m / (ecart / math.sqrt(len(valeurs)))


# ─────────────────────────────────────────────────────────────────────
# La mesure
# ─────────────────────────────────────────────────────────────────────

RETENU = "RETENU"
INSUFFISANT = "INSUFFISANT"
REFUTE = "REFUTE"


def mesurer(bougies_m5: list, spread: float, pair: str = PAIRE,
            echelles: tuple[int, ...] | None = None) -> dict:
    """Mesure toutes les cellules (échelle × motif × sens). Fonction PURE :
    elle ne lit ni n'écrit rien, elle ne décide rien — elle mesure."""
    from backend.services.echelle_agregee import agreger

    echelles = echelles or ECHELLES
    cellules: list[dict] = []
    controles: dict[str, dict] = {}

    for facteur in echelles:
        agregees = _agreger_brut(bougies_m5, facteur, agreger)
        if len(agregees) < FENETRE + 10:
            logger.info("labo_or: echelle x%d ecartee — %d bougies seulement",
                        facteur, len(agregees))
            continue
        # ⛔ Les chaines entrent ICI, dans le meme releve que les motifs
        # simples. Elles deviennent alors des cellules comme les autres — donc
        # soumises au MEME controle aleatoire et au MEME plafond du hasard.
        #
        # 🔑 Consequence voulue : ajouter des chaines RELEVE la barre pour tout
        # le monde. `plafond_hasard(len(cellules))` compte tout. Mesurer plus
        # de choses doit couter plus cher a prouver, sinon on achete des
        # decouvertes avec des tests supplementaires.
        releve = fusionner_chaines(detections(agregees, pair), agregees)
        paires_motif_sens = sorted({(_nom_motif(s), _sens(s))
                                    for liste in releve.values() for s in liste})
        # ⛔ Par SENS depuis le 2026-09-15 : un contrôle commun aux achats et
        # aux ventes mesure la tendance du marché, pas le motif. Voir
        # `controle_aleatoire`.
        par_sens: dict[str, dict[str, list]] = {}
        for motif, sens in paires_motif_sens:
            trades = rejouer_cellule(agregees, releve, motif, sens, spread)
            if not trades:
                continue
            d = par_sens.setdefault(sens, {"risques": [], "objectifs": [], "n": []})
            d["risques"] += [t["risque"] for t in trades]
            d["objectifs"] += [t["objectif_r"] for t in trades]
            d["n"].append(len(trades))
            R = [t["R"] for t in trades]
            moyenne, t = _stat(R)
            cellules.append({
                "echelle": facteur, "horizon": _horizon(facteur),
                "motif": motif, "sens": sens, "n": len(R),
                "r_moyen": moyenne, "t": t, "r_total": sum(R),
                "ecart_type": st.stdev(R) if len(R) > 2 else 0.0,
                "spread_r": st.median(x["cout"] for x in trades),
            })
        for sens, d in par_sens.items():
            # ⚠️ Le contrôle a la MÊME population : autant de trades que la
            # cellule médiane DE CE SENS, même distance de stop, même objectif,
            # et le même sens. La graine ne dépend pas du sens : les deux
            # contrôles partent donc des mêmes entrées, ce qui les rend
            # comparables entre eux.
            n_median = int(st.median(d["n"] or [0]))
            R_alea = controle_poole(
                agregees, spread, max(n_median, MIN_TRADES),
                st.median(d["risques"]), st.median(d["objectifs"]),
                graine=facteur * 101, sens=sens)
            if not R_alea:
                continue
            m_alea, _ = _stat(R_alea)
            controles[f"{facteur}:{sens}"] = {
                "echelle": facteur, "sens": sens,
                "n": len(R_alea), "graines": CONTROLE_GRAINES,
                "r_moyen": m_alea,
                # Gardé pour le t de Welch : comparer une cellule au hasard
                # demande la dispersion du hasard, pas seulement sa moyenne.
                "ecart_type": st.stdev(R_alea) if len(R_alea) > 2 else 0.0}

    for c in cellules:
        # ⛔ Chaque cellule lit le contrôle de SON sens. Un `.get` muet sur une
        # clé absente rendrait 0,0 et gonflerait le delta — on veut le savoir.
        ref = controles.get(f"{c['echelle']}:{c['sens']}")
        if ref is None:
            logger.warning("labo_or: aucun controle pour %s/%s — cellule ecartee",
                           c["echelle"], c["sens"])
            c["r_hasard"] = None
            c["delta_hasard"] = None
            continue
        c["r_hasard"] = ref["r_moyen"]
        c["delta_hasard"] = c["r_moyen"] - c["r_hasard"]
        # ⛔ LE SECOND DÉFAUT, fermé le 2026-09-15. Le verdict comparait le `t`
        # BRUT de la cellule (son R contre zéro) au plafond du hasard, et ne
        # demandait au contrôle que le SIGNE du delta. Sur une série qui
        # dérive, une cellule acheteuse a donc un `t` énorme — celui de la
        # tendance — et un delta à peine positif : elle passait RETENU.
        #
        # 🔑 La question n'est pas « ce motif gagne-t-il ? » mais « gagne-t-il
        # PLUS QUE LE HASARD DE SON SENS ? ». On teste donc l'écart, par un t
        # de Welch qui tient compte de la dispersion des DEUX côtés.
        c["t_vs_hasard"] = _welch(c["r_moyen"], c["ecart_type"], c["n"],
                                  ref["r_moyen"], ref["ecart_type"], ref["n"])

    plafond = plafond_hasard(len(cellules))
    for c in cellules:
        c["plafond"] = plafond
        c["verdict"] = _verdict(c, plafond)

    return {"pair": pair, "spread": spread, "cellules": cellules,
            "controles": controles, "k": len(cellules), "plafond": plafond,
            "bougies_m5": len(bougies_m5)}


def _agreger_brut(bougies_m5: list, facteur: int, agreger) -> list:
    """Agrège des dicts `{t,o,h,l,c}` — le format que rend le pont.

    ⚠️ `echelle_agregee.agreger` travaille sur des objets `Candle`. Plutôt que
    de convertir 26 000 bougies deux fois, on agrège ici sur les dicts, avec la
    MÊME règle d'alignement sur l'horloge. ⛔ Une règle qui divergerait de la
    production ferait mesurer un instrument que le système ne trade pas.
    """
    from datetime import datetime
    if facteur <= 1:
        return list(bougies_m5)
    pas = 5 * facteur
    groupes: dict = {}
    for x in bougies_m5:
        d = x["t"]
        if not isinstance(d, datetime):
            d = datetime.fromisoformat(str(d).replace("Z", "+00:00"))
        cle = d.replace(minute=(d.minute // pas) * pas, second=0, microsecond=0)
        groupes.setdefault(cle, []).append(x)
    out = []
    for cle in sorted(groupes):
        g = groupes[cle]
        if len(g) < facteur:            # ⛔ bougie en cours : on ne la sert pas
            continue
        # ⛔ LE VOLUME ETAIT JETE ICI (trouve le 2026-09-12 en cablant la
        # confluence). Cette fonction ne rendait que `t o c h l`. Sur M15, M30
        # et H1, `tv` disparaissait donc, `_volume_fort` repondait NON partout,
        # et les chaines a confirmation par volume ne pouvaient se declencher
        # QU'EN 5 MIN — sans qu'aucune erreur ne soit levee.
        #
        # 🔑 Le volume se SOMME, il ne se moyenne pas : trois bougies de 5 min
        # a 10 ticks font une bougie de 15 min a 30 ticks. Une moyenne aurait
        # rendu toutes les echelles comparables entre elles et fausses chacune.
        #
        # ⚠️ Somme des presents, `None` si AUCUN n'a la donnee : « pas de
        # volume mesure » doit rester discernable de « aucune activite », la
        # meme regle qu'a la frontiere du pont.
        vols = [y.get("tv") for y in g if y.get("tv") is not None]
        rvols = [y.get("rv") for y in g if y.get("rv") is not None]
        out.append({"t": cle, "o": float(g[0]["o"]), "c": float(g[-1]["c"]),
                    "h": max(float(y["h"]) for y in g),
                    "l": min(float(y["l"]) for y in g),
                    "tv": sum(float(v) for v in vols) if vols else None,
                    "rv": sum(float(v) for v in rvols) if rvols else None})
    return out


def _horizon(facteur: int) -> str:
    return "5min" if facteur == 1 else f"{5 * facteur}min"


def _welch(m1: float, s1: float, n1: int, m2: float, s2: float, n2: int) -> float:
    """t de Welch entre deux échantillons de variances et tailles différentes.

    ⛔ Rend `0.0` quand une dispersion passe sous `ECART_MINIMAL_R`, **comme
    `_stat`**. Une division par presque rien fabrique un t énorme qui a l'air
    d'un résultat — c'est le `t = −685` sur 8 trades tous stoppés.

    ⚠️ Le garde-fou manquait ici à ma première version, et le contrôle de
    dérive l'a attrapé : sur une série qui monte franchement, TOUS les achats
    touchent l'objectif, les deux dispersions tombent à presque rien, et un
    écart de 0,09 R sortait à un `t` au-dessus du plafond. Quatre cellules
    étaient RETENUES sur une simple tendance. Deux mesures de dispersion dans
    le même fichier doivent appliquer la même règle, sinon l'une dément
    l'autre.
    """
    if n1 < 3 or n2 < 3:
        return 0.0
    if s1 < ECART_MINIMAL_R or s2 < ECART_MINIMAL_R:
        return 0.0
    err = math.sqrt(s1 * s1 / n1 + s2 * s2 / n2)
    if err <= 0:
        return 0.0
    return (m1 - m2) / err


def _verdict(cellule: dict, plafond: float) -> str:
    """Trois issues, et l'insuffisance n'est PAS un refus.

    ⛔ Confondre « pas assez de données » et « ça ne marche pas » ferait fermer
    des motifs qui n'ont simplement pas encore parlé.
    """
    if cellule["n"] < MIN_TRADES:
        return INSUFFISANT
    # ⛔ Sans contrôle de son sens, une cellule n'est comparable à rien : elle
    # ne peut donc être ni retenue ni réfutée. Ce n'est pas un refus, c'est une
    # mesure qui manque — même distinction que `MIN_TRADES` ci-dessus.
    ecart = cellule.get("t_vs_hasard")
    if ecart is None or cellule.get("delta_hasard") is None:
        return INSUFFISANT
    # ⚠️ C'est l'écart AU HASARD DE SON SENS qui est confronté au plafond, pas
    # le `t` brut de la cellule. Le `t` brut répond à « ce motif gagne-t-il ? »,
    # et sur un marché qui dérive la réponse est oui pour TOUT achat. Seule la
    # question « gagne-t-il plus que le hasard de son sens ? » a un sens ici.
    if abs(ecart) < plafond:
        # Sous le plafond du hasard : indistinguable du bruit, dans les DEUX
        # sens. On ne retient pas, mais on ne réfute pas non plus.
        return INSUFFISANT
    # Deux conditions, et les deux sont nécessaires : battre le hasard NE SUFFIT
    # PAS si la cellule perd quand même de l'argent (`r_moyen <= 0`). Perdre
    # moins que le hasard n'est pas une méthode de trading.
    if ecart > 0 and cellule["r_moyen"] > 0:
        return RETENU
    return REFUTE


# ─────────────────────────────────────────────────────────────────────
# Le rendu
# ─────────────────────────────────────────────────────────────────────

def lignes(mesure: dict, maxi: int = 8) -> list[str]:
    """Le bloc lisible. Fonction PURE."""
    cellules = mesure.get("cellules") or []
    if not cellules:
        return ["🔬 Labo de l'or — aucune mesure exploitable cette nuit."]

    retenues = [c for c in cellules if c["verdict"] == RETENU]
    refutees = [c for c in cellules if c["verdict"] == REFUTE]
    out = [
        "🔬 <b>Labo de l'or</b> — ce que disent les 90 derniers jours",
        f"  ({mesure['k']} combinaisons examinées · "
        f"il faut dépasser t={mesure['plafond']:.2f} pour dire autre chose "
        f"que du hasard)",
    ]

    if retenues:
        out.append("✅ <b>Au-dessus du hasard</b> :")
        for c in sorted(retenues, key=lambda x: -abs(x["t"]))[:maxi]:
            out.append(
                f"• {c['horizon']} {c['motif']} {c['sens']} — "
                f"{c['r_moyen']:+.2f} R sur {c['n']} trades (t={c['t']:+.2f}) · "
                f"écart au hasard {c['delta_hasard']:+.2f} R")
    else:
        out.append("⚪ <b>Rien ne dépasse le hasard</b> ce soir — et c'est un "
                   "résultat, pas une panne.")

    if refutees:
        out.append("⛔ <b>Perd de l'argent de façon nette</b> :")
        for c in sorted(refutees, key=lambda x: x["r_moyen"])[:maxi]:
            out.append(
                f"• {c['horizon']} {c['motif']} {c['sens']} — "
                f"{c['r_moyen']:+.2f} R sur {c['n']} trades (t={c['t']:+.2f})")

    attente = [c for c in cellules if c["verdict"] == INSUFFISANT]
    if attente:
        out.append(f"⏳ {len(attente)} combinaisons sans assez de recul "
                   f"(moins de {MIN_TRADES} trades, ou sous le plafond).")
    return out
