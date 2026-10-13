"""Donner un stop et un objectif aux positions d'or ouvertes À LA MAIN.

Demandé par Xavier le 2026-10-10, après la mesure des chemins du vendredi :
*« la version qui équipe tes trades à la main »*.

## 🔑 LA MESURE QUI MOTIVE CE MODULE, et c'est la seule

Sur les 43 trades qu'il a ouverts dans le terminal MT5 le 2026-10-09 :

```
40 sur 43  n'ont NI stop NI objectif enregistrés chez le courtier
```

⇒ Ni l'échelle de gains, ni la protection des pertes à 5 min, ni les sondes P0
ne les voient. Ses trois pires de la journée — **258 min, 296 min, 19 min** —
font **−41,72 €** à eux seuls ; sans eux la main finissait à **+19,34 €**.

## ⛔ CE MODULE NE PRÉTEND RIEN SUR LA DIRECTION

Mesuré le 2026-10-10 sur 5 jours : la direction du radar est **indiscernable du
hasard** (horizons 1 à 60 min, aucune p-valeur sous 0,27, réussite 42-54 %), et
celle de Xavier n'est mesurable que sur **un** jour — l'adoption des positions
du courtier ne date que du 09/10 — où elle ne bat pas un biais acheteur
constant. Il n'y avait donc aucune base pour qu'un algorithme lui impose un
sens. Ce module **borne le risque de ce qu'il ouvre lui-même**, point.
→ `project_direction_sans_information_2026_10_10`

## Les quatre gardes, et la raison de chacune

1. **Inerte par défaut** (`EQUIPER_TRADES_MAIN=0`). Même choix que
   `XAU_TP_FIXE_EUR` et `LANCEUR_SUR_FERMETURE` : rien ne bouge sans armement.
2. **Il COMBLE, il ne REMPLACE jamais.** Une borne déjà posée n'est pas
   touchée : resserrer la protection que quelqu'un a choisie, sans le lui dire,
   serait pire que de ne rien faire.
3. ⛔ **Jamais de sortie immédiate.** Si la borne calculée est **déjà
   franchie** — la position perd plus que le stop, ou gagne plus que
   l'objectif — on ne la pose pas. Un stop du mauvais côté du cours **ferme**
   la position : fermer n'est pas protéger, et ce n'est pas ce qui a été
   demandé. Le cas est signalé (`alerte`) plutôt que tranché tout seul.
4. **L'or seul, et seulement ce que le radar n'a PAS ouvert.** Les positions du
   radar ont déjà leurs bornes et leur échelle ; les toucher ici créerait deux
   autorités sur le même stop.

## 🔑 Les bornes viennent des RÉGLAGES du radar, pas d'ici

`XAU_SL_FIXE_EUR` et `XAU_TP_FIXE_EUR` — exactement ceux du chemin
automatique. Écrire 20 et 2 dans ce fichier aurait créé une seconde source de
vérité, qui dérive le jour où l'une des deux bouge.

⚠️ **Et quand `XAU_SL_FIXE_EUR` vaut 0, le stop retombe sur `_distance_sl_or`**
— la fonction même du chemin automatique, appelée et non recopiée. Sans ce
repli, passer l'automatique au pourcentage **éteignait** l'équipement des
trades à la main en silence, et le trou était du côté de la PERTE : la
protection exige un stop existant pour le resserrer, donc un trade à la main
restait sans aucun plancher. C'est arrivé le 2026-10-11, et ça a duré une
heure sur l'argent réel.
→ `project_le_neuf_euros_de_xavier_2026_10_11`
→ `feedback_router_une_source_en_laisser_deux`

⛔ Et un réglage **illisible rend le module muet** au lieu de retomber sur une
valeur par défaut : ici le repli serait posé sur de l'argent réel.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# La marque que le pont pose sur ce que le radar ouvre. Partagée avec
# `echelle_stop_or` pour qu'il n'y ait qu'une definition.
MARQUE_RADAR = "scalping-radar"

SYMBOLES_OR = ("XAUUSD", "XAU/USD", "GOLD")

# ⚠️ Marge de securite avant de declarer une borne << deja franchie >>, en
# euros. A zero, un cours pile sur la borne donnerait un ordre que le courtier
# execute immediatement.
MARGE_FRANCHIE_EUR = 0.10


def arme() -> bool:
    """⚠️ Garde n°1 : inerte par défaut."""
    return os.getenv("EQUIPER_TRADES_MAIN", "0").strip().lower() in (
        "1", "true", "on", "yes", "oui")


# Les quatre etats d'un reglage en euros. ⛔ ILLISIBLE et INERTE ne sont PAS
# la meme chose, et les confondre a coute une heure de trades a la main sans
# plancher le 2026-10-11 : vide ou 0 est une DECISION (<< le pourcentage
# gouverne >>), une valeur negative ou non numerique est une ERREUR.
_ABSENT, _INERTE, _ILLISIBLE, _POSE = "absent", "inerte", "illisible", "pose"


def _classer(nom: str) -> tuple[str, float | None]:
    """``(etat, valeur)`` d'un reglage en euros. Voir les quatre etats ci-dessus."""
    brut = (os.getenv(nom) or "").strip()
    if not brut:
        return (_ABSENT, None)
    try:
        v = float(brut.replace(",", "."))
    except (TypeError, ValueError):
        logger.warning("equiper_trades_main: %s illisible (%r) — rien ne sera "
                       "pose, et on ne retombe PAS sur un defaut", nom, brut)
        return (_ILLISIBLE, None)
    if v == 0:
        return (_INERTE, None)
    if v < 0:
        logger.warning("equiper_trades_main: %s = %s, negatif — rien ne sera "
                       "pose, et on ne retombe PAS sur un defaut", nom, v)
        return (_ILLISIBLE, None)
    return (_POSE, v)


def _reglage(nom: str) -> float | None:
    """Un réglage en euros, strictement positif, ou ``None``.

    ⛔ Pas de valeur de repli : voir l'en-tête.
    """
    brut = (os.getenv(nom) or "").strip()
    if not brut:
        logger.warning("equiper_trades_main: %s absent — rien ne sera posé", nom)
        return None
    try:
        v = float(brut.replace(",", "."))
    except (TypeError, ValueError):
        logger.warning("equiper_trades_main: %s illisible (%r) — rien ne sera "
                       "posé", nom, brut)
        return None
    if v <= 0:
        logger.warning("equiper_trades_main: %s = %s, non strictement positif "
                       "— rien ne sera posé", nom, v)
        return None
    return v


def stop_eur(prix: float | None = None,
             taux_eur_usd: float | None = None) -> float | None:
    """La distance de stop a poser, en euros, ou ``None``.

    🔑 LE DEFAUT QUE CE REPLI REPARE, et il a vecu une heure sur l'argent reel.
    `XAU_SL_FIXE_EUR` sert DEUX chemins qui lui donnent des sens OPPOSES :

        chemin AUTOMATIQUE   0 = inerte, c'est `XAU_SL_PCT` qui gouverne
        chemin A LA MAIN     0 = ne pose RIEN  (seule source du stop)

    Le 2026-10-11 a 18h33, en le passant de 20 a 0 pour donner a Xavier son
    stop au POURCENTAGE, j'ai eteint l'equipement des trades a la main sans le
    voir. Le journal le disait pourtant mot pour mot :
    << XAU_SL_FIXE_EUR = 0.0, non strictement positif — rien ne sera pose >>.

    ⛔ ET LE TROU ETAIT DANS LE NEGATIF, le plus mauvais cote : un trade a la
    main sans stop restait sans PLANCHER, parce que `protection_perte_or`
    exige un stop EXISTANT pour le resserrer (`sl is None` ⇒ elle s'abstient).
    En profit il etait couvert — le trainage pose le stop des +0,50 EUR — mais
    en perte, rien, jusqu'a l'appel de marge.

    ⇒ On retombe sur `_distance_sl_or`, c'est-a-dire EXACTEMENT la fonction du
    chemin automatique. Pas une copie du calcul : l'appel. Ecrire `prix * 0,35
    / 100` ici creerait la seconde source de verite que l'en-tete de ce module
    interdit explicitement.

    `prix` ou `taux_eur_usd` manquants ⇒ ``None``, donc rien de pose. On ne
    DEVINE pas un stop sur de l'argent reel.
    """
    # 🔑 LE REGLAGE PROPRE A LA MAIN, POSE LE 2026-10-13, ET POURQUOI IL
    # EXISTE. Xavier : << pour les trades lances a la main, je veux que
    # l'objectif soit de base 20 euros et que le stop loss soit a 13 euros >>.
    #
    # ⛔ ON NE PEUT PAS LE FAIRE AVEC `XAU_SL_FIXE_EUR` : ce nom est lu AUSSI
    # par `pattern_detector._distance_sl_or`, donc par le chemin AUTOMATIQUE.
    # Le poser a 13 donnerait au ROBOT un stop fixe de 13 EUR a la place de ses
    # 0,35 % du prix -- en defaisant en silence la decision que Xavier a prise
    # le 11/10. Un reglage partage entre deux chemins qui veulent desormais
    # deux choses differentes doit se DEDOUBLER, pas s'arbitrer au hasard.
    #
    # ⚠️ Et c'est la MEME variable qui a deja coute une heure d'argent reel le
    # 11/10 (0 = inerte d'un cote, 0 = ne pose rien de l'autre). On ne la
    # touche plus.
    etat_m, fixe_m = _classer("MAIN_SL_FIXE_EUR")
    if etat_m == _POSE:
        return fixe_m
    if etat_m == _ILLISIBLE:
        # Illisible ⇒ MUET, comme pour le reglage partage : quelqu'un a voulu
        # poser une valeur et s'est trompe, le masquer serait pire.
        return None

    etat, fixe = _classer("XAU_SL_FIXE_EUR")
    if etat == _POSE:
        return fixe
    if etat == _ILLISIBLE:
        # ⛔ ET LA DISTINCTION COMPTE. `""` et `"0"` sont la convention
        # << inerte >> de ce depot : quelqu'un a DECIDE que le pourcentage
        # gouverne, et le repli est alors exactement ce qu'il veut. Mais
        # `"zero"` ou `"-5"` sont des ERREURS de configuration : quelqu'un a
        # voulu poser une valeur et s'est trompe. Retomber en silence
        # masquerait sa faute, et c'est le contrat que
        # `test_un_reglage_ILLISIBLE_rend_le_module_MUET` protege depuis le
        # 2026-10-10. On reste donc MUET, et on le dit.
        return None

    if not prix or not taux_eur_usd or taux_eur_usd <= 0:
        return None
    try:
        from backend.services.pattern_detector import _distance_sl_or
        distance_usd = _distance_sl_or(float(prix))
    except Exception as e:  # noqa: BLE001
        logger.warning("equiper_trades_main: distance de stop illisible (%s) "
                       "— rien ne sera pose", e)
        return None
    if distance_usd is None or distance_usd <= 0:
        logger.warning("equiper_trades_main: aucune distance de stop pour un "
                       "or a %s — rien ne sera pose", prix)
        return None
    return distance_usd / float(taux_eur_usd)


def objectif_eur() -> float | None:
    """L'objectif a poser sur un trade A LA MAIN, en euros, ou ``None``.

    🔑 `MAIN_TP_FIXE_EUR` PRIME sur `XAU_TP_FIXE_EUR`, pour la meme raison que
    le stop : le nom partage est lu par `pattern_detector`, donc par le chemin
    AUTOMATIQUE. Le poser a 20 rendrait au ROBOT un objectif de 20 EUR alors
    que Xavier a decide le 11/10 << plus d'objectif du tout >>.

    ⛔ Absent ⇒ on retombe sur le reglage partage, donc sur le comportement
    d'avant, a l'identique.
    """
    propre = _reglage("MAIN_TP_FIXE_EUR")
    if propre is not None:
        return propre
    return _reglage("XAU_TP_FIXE_EUR")


def est_de_l_or(position: dict) -> bool:
    sym = str(position.get("symbol") or "").upper().replace(" ", "")
    return any(sym == s.upper().replace("/", "").replace(" ", "")
               or sym == s.upper() for s in SYMBOLES_OR)


def est_du_radar(position: dict) -> bool:
    return MARQUE_RADAR in str(position.get("comment") or "")


def concerne(position: dict) -> bool:
    """Cette position est-elle dans la portée du module ?

    🔑 Partagée avec `echelle_stop_or` : c'est elle qui fait que l'échelle et
    la protection des pertes **adoptent** ces positions une fois équipées.
    Sans cette adoption, le stop serait posé une fois et ne suivrait jamais le
    gain — tout l'intérêt disparaîtrait.
    """
    return arme() and est_de_l_or(position) and not est_du_radar(position)


def suivi_arme() -> bool:
    """Les trades A LA MAIN doivent-ils etre SUIVIS apres avoir ete equipes ?

    Demande de Xavier le 2026-10-13 : << pour les trades lances a la main, je
    ne veux pas avoir le SL qui va s'updater >>.

    🔑 DEUX CHOSES ETAIENT CONFONDUES DANS `concerne()`, et c'est ce que ce
    reglage separe :
      - POSER un stop sur une position qui n'en a pas (ce module) ;
      - le SUIVRE ensuite (l'echelle cote gain, la protection cote perte).
    Il voulait couper le second sans perdre le premier. Sans cette separation
    il aurait fallu `EQUIPER_TRADES_MAIN=0`, qui laisse NUE une position
    ouverte sans stop -- et le 09/10, 40 de ses 43 trades du terminal
    n'avaient NI stop NI objectif, ses trois pires faisant -41,72 EUR a eux
    seuls.

    ⛔ Defaut `1` : le comportement d'avant, a l'identique. Un reglage absent
    ne doit jamais changer la facon dont l'argent reel est protege.
    """
    return os.getenv("EQUIPER_TRADES_MAIN_SUIVI", "1").strip().lower() in (
        "1", "true", "yes", "on", "oui")


def concerne_suivi(position: dict) -> bool:
    """Cette position peut-elle etre SUIVIE (stop deplace) ?

    🔑 A lire par l'echelle et la protection. `concerne()` reste la porte du
    seul EQUIPEMENT INITIAL : les deux ne doivent plus etre confondues.
    """
    return suivi_arme() and concerne(position)


def decision(position: dict, taux_eur_usd: float) -> dict | None:
    """Ce qu'il faut poser sur cette position, ou ``None``.

    Rend ``{"ticket", "sl", "tp", "motif", "alerte"}`` où ``sl``/``tp`` valent
    ``None`` quand il n'y a rien à poser de ce côté.
    """
    if not concerne(position):
        return None
    try:
        taux = float(taux_eur_usd or 0)
        entree = float(position.get("price_open") or 0)
        courant = float(position.get("price_current") or 0)
    except (TypeError, ValueError):
        return None
    if taux <= 0 or entree <= 0 or courant <= 0:
        return None

    sens = str(position.get("type") or "").lower()
    if sens not in ("buy", "sell"):
        return None
    signe = 1 if sens == "buy" else -1

    sl_pose = float(position.get("sl") or 0) > 0
    tp_pose = float(position.get("tp") or 0) > 0
    if sl_pose and tp_pose:
        return None                      # ⚠️ Garde n°2 : rien a combler.

    # Le profit courant, en euros, du point de vue de la position.
    profit_eur = signe * (courant - entree) / taux

    # 🔑 `entree`, pas `courant` : le stop se mesure depuis le PRIX
    # D'ENTREE, comme sur le chemin automatique. Le mesurer depuis le
    # cours courant ferait un stop qui bouge avec le marche avant meme
    # d'etre pose.
    d_sl, d_tp = stop_eur(entree, taux), objectif_eur()
    sl = tp = None
    alerte = None

    if not sl_pose and d_sl is not None:
        # ⛔ Garde n°3 : un stop deja franchi FERMERAIT la position.
        if profit_eur <= -(d_sl - MARGE_FRANCHIE_EUR):
            alerte = (f"stop de {d_sl:.2f} € deja franchi "
                      f"(position a {profit_eur:+.2f} €) — RIEN pose, "
                      f"a trancher a la main")
            logger.warning("equiper_trades_main: ticket %s — %s",
                           position.get("ticket"), alerte)
        else:
            sl = round(entree - signe * d_sl * taux, 2)

    if not tp_pose and d_tp is not None:
        # ⛔ Meme raison dans l'autre sens : un objectif derriere le cours
        # encaisse immediatement. C'est une sortie, pas une protection.
        if profit_eur >= (d_tp - MARGE_FRANCHIE_EUR):
            msg = (f"objectif de {d_tp:.2f} € deja depasse "
                   f"(position a {profit_eur:+.2f} €) — RIEN pose")
            alerte = f"{alerte} ; {msg}" if alerte else msg
            logger.warning("equiper_trades_main: ticket %s — %s",
                           position.get("ticket"), msg)
        else:
            tp = round(entree + signe * d_tp * taux, 2)

    if sl is None and tp is None:
        # On rend quand meme la decision quand il y a une ALERTE : un cas
        # non traitable doit se LIRE, pas disparaitre.
        if alerte:
            return {"ticket": position.get("ticket"), "sl": None, "tp": None,
                    "motif": "borne_deja_franchie", "alerte": alerte,
                    "profit_eur": round(profit_eur, 2)}
        return None

    return {"ticket": position.get("ticket"), "sl": sl, "tp": tp,
            "motif": "nue" if (not sl_pose and not tp_pose) else "partielle",
            "alerte": alerte, "profit_eur": round(profit_eur, 2)}
