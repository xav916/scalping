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


def _issue(bougies, depart: int, entree: float, risque: float, objectif_r: float,
           sens: int, cout: float) -> tuple[float, int]:
    """Ce que le trade aurait donné, en R, et l'indice de sa sortie.

    ⛔ Le stop est testé AVANT l'objectif : dans une bougie qui contient les
    deux, on ne sait pas lequel est venu en premier, et supposer l'objectif
    fabriquerait une performance."""
    j = depart
    fin = min(len(bougies), depart + MAX_BOUGIES_TENUE)
    while j < fin:
        b = bougies[j]
        haut, bas = float(b["h"]), float(b["l"])
        pire = min(sens * (haut - entree), sens * (bas - entree)) / risque
        mieux = max(sens * (haut - entree), sens * (bas - entree)) / risque
        if pire <= -1.0:
            return -1.0 - cout, j
        if mieux >= objectif_r:
            return objectif_r - cout, j
        j += 1
    dernier = bougies[min(j, len(bougies) - 1)]
    return sens * (float(dernier["c"]) - entree) / risque - cout, j


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
        return Candle(timestamp=d, open=float(x["o"]), high=float(x["h"]),
                      low=float(x["l"]), close=float(x["c"]), volume=0.0)

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
        releve = detections(agregees, pair)
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
        out.append({"t": cle, "o": float(g[0]["o"]), "c": float(g[-1]["c"]),
                    "h": max(float(y["h"]) for y in g),
                    "l": min(float(y["l"]) for y in g)})
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
