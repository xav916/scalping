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
    out: dict[str, dict] = {}
    for p in politiques:
        R = [_issue(bougies, i, e, r, o, signe, spread / r, politique=p)[0]
             for i, e, r, o in entrees]
        moyenne, t = _stat(R)
        out[p] = {"n": len(R), "r_moyen": moyenne, "t": t, "r_total": sum(R)}
    # ⚠️ L'écart à la référence est le seul chiffre qui réponde à la question.
    ref = out.get(POLITIQUES_SORTIE[0], {}).get("r_moyen", 0.0)
    for p, d in out.items():
        d["delta_reference"] = d["r_moyen"] - ref
    return out


def detections(bougies, pair: str = PAIRE) -> dict[int, list]:
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

    out: dict[int, list] = {}
    for i in range(FENETRE, len(bougies)):
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
     "declencheur": "bos_up", "predicats": (), "fenetre": FENETRE_SEQUENCE},
    {"nom": "sweep_puis_structure_baissier",
     "motifs": ("liquidity_sweep_down", "bos_down"),
     "declencheur": "bos_down", "predicats": (), "fenetre": FENETRE_SEQUENCE},
    # Prise de liquidite sur une zone d'accumulation.
    {"nom": "sweep_sur_order_block_haussier",
     "motifs": ("liquidity_sweep_up", "order_block_up"),
     "declencheur": "order_block_up", "predicats": (),
     "fenetre": FENETRE_SEQUENCE},
    {"nom": "sweep_sur_order_block_baissier",
     "motifs": ("liquidity_sweep_down", "order_block_down"),
     "declencheur": "order_block_down", "predicats": (),
     "fenetre": FENETRE_SEQUENCE},
    # Changement de caractere PUIS desequilibre — le retournement laisse un
    # trou que le prix revient combler.
    {"nom": "choch_puis_fvg_haussier",
     "motifs": ("choch_up", "fvg_up"),
     "declencheur": "fvg_up", "predicats": (), "fenetre": FENETRE_SEQUENCE},
    {"nom": "choch_puis_fvg_baissier",
     "motifs": ("choch_down", "fvg_down"),
     "declencheur": "fvg_down", "predicats": (), "fenetre": FENETRE_SEQUENCE},
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


# ⛔ Fail-closed : un predicat mal orthographie doit LEVER. S'il rendait True,
# la chaine serait mesuree sans sa condition et le verdict serait faux sans
# que rien ne le dise.
_PREDICATS = {"volume_fort": _volume_fort}


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
    chaines = chaines if chaines is not None else CHAINES
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
                if not all(any((i - d) in ou.get((m, sens), ())
                               for d in range(0, fen + 1)) for m in autres):
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


def controle_aleatoire(bougies, spread: float, combien: int, risque_median: float,
                       objectif_r: float, graine: int) -> list[dict]:
    """Les mêmes trades, mais déclenchés AU HASARD.

    🔑 La seule comparaison qui vaille. « Aucun système ne bat le hasard » a été
    établi comme ça : Δ = +0,004 R sur 29 000 trades. Une cellule qui gagne
    autant que le hasard n'apporte rien, même si son R moyen est positif.

    ⚠️ Même population : même nombre de trades, même distance de stop médiane,
    même objectif, même contrainte séquentielle.
    """
    if combien <= 0 or risque_median <= 0:
        return []
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
        signe = 1 if tirage.random() < 0.5 else -1
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
    controles: dict[int, dict] = {}

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
        risques, objectifs = [], []
        for motif, sens in paires_motif_sens:
            trades = rejouer_cellule(agregees, releve, motif, sens, spread)
            if not trades:
                continue
            risques += [t["risque"] for t in trades]
            objectifs += [t["objectif_r"] for t in trades]
            R = [t["R"] for t in trades]
            moyenne, t = _stat(R)
            cellules.append({
                "echelle": facteur, "horizon": _horizon(facteur),
                "motif": motif, "sens": sens, "n": len(R),
                "r_moyen": moyenne, "t": t, "r_total": sum(R),
                "spread_r": st.median(x["cout"] for x in trades),
            })
        if risques:
            # ⚠️ Le contrôle a la MÊME population : autant de trades que la
            # cellule médiane, même distance de stop, même objectif.
            n_median = int(st.median(
                [c["n"] for c in cellules if c["echelle"] == facteur] or [0]))
            alea = controle_aleatoire(
                agregees, spread, max(n_median, MIN_TRADES),
                st.median(risques), st.median(objectifs), graine=facteur * 101)
            m_alea, _ = _stat([x["R"] for x in alea])
            controles[facteur] = {"n": len(alea), "r_moyen": m_alea}

    for c in cellules:
        ref = controles.get(c["echelle"], {})
        c["r_hasard"] = ref.get("r_moyen", 0.0)
        c["delta_hasard"] = c["r_moyen"] - c["r_hasard"]

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


def _verdict(cellule: dict, plafond: float) -> str:
    """Trois issues, et l'insuffisance n'est PAS un refus.

    ⛔ Confondre « pas assez de données » et « ça ne marche pas » ferait fermer
    des motifs qui n'ont simplement pas encore parlé.
    """
    if cellule["n"] < MIN_TRADES:
        return INSUFFISANT
    if abs(cellule["t"]) < plafond:
        # Sous le plafond du hasard : indistinguable du bruit, dans les DEUX
        # sens. On ne retient pas, mais on ne réfute pas non plus.
        return INSUFFISANT
    if cellule["t"] > 0 and cellule["delta_hasard"] > 0:
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
