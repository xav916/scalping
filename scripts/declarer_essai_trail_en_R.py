"""Déclare au banc l'essai « stop suiveur exprimé en R » — AVANT toute modification.

## Pourquoi ce script existe, et pourquoi il ne change rien

Le 2026-09-21, l'enquête sur une absence de trade sur l'or a établi que
``TRAIL_DISTANCE_POINTS`` est un entier **global**, appliqué tel quel à tous les
instruments :

    trail_distance = TRAIL_DISTANCE_POINTS * info.point   # 150 × point du symbole

Sur l'or (`info.point` = 0,01) cela vaut **1,50 USD**, quand la distance
entrée→stop des trades mesurés va de 12,08 à 27,13 USD — soit un stop suiveur à
**0,074 R** face à un stop initial à 1 R. Mesuré sur les 14 clôtures de la
fenêtre : gain moyen **+0,298 R** (8 sorties au suiveur), perte moyenne
**−1,00 R** (6 sorties au stop). Espérance **−0,26 R par trade** ; il faudrait
**77 %** de réussite pour l'équilibre, le taux observé était de **57 %**.

⛔ **C'est précisément parce que le diagnostic est convaincant qu'il faut passer
par le banc.** Choisir maintenant une valeur de suivi « qui aurait marché » sur
ces quatorze trades, c'est refaire ce que soixante-cinq expériences ont déjà
fait : retenir la meilleure variante sur les données qui l'ont suggérée. Le banc
est là pour que la soixante-seizième ne paraisse pas bonne pour la même raison.

Ce script **déclare**. Il ne modifie ni le bridge, ni la configuration, ni
l'admission. La modification vient APRÈS, et son verdict ne portera que sur des
clôtures postérieures à cette déclaration — la borne est en SQL.

## Le choix de la valeur, et pourquoi il n'est pas tiré des données

⚠️ La correction de principe — exprimer la distance en **fraction du risque du
trade** plutôt qu'en points — ne dépend pas de ces quatorze trades. C'est le même
argument qui a fait passer le drawdown de démotion des euros au R le 2026-09-08 :
une unité dépendante de l'instrument mesure la taille, pas le comportement.

Pour la valeur, on **réemploie le 0,5 qui existe déjà** dans
``BREAKEVEN_TRIGGER_PCT = 50``, au lieu d'introduire un nombre neuf. C'est la
doctrine du projet — « aucun réglage neuf », les 30 bougies de `_detect_breakout`
reprises par le balayage, le 0,5 × ATR du détecteur de gap repris par l'order
block. Un degré de liberté de plus, ici, serait un essai de plus à compter.

D'où **une seule variante déclarée**. Si vous voulez en balayer plusieurs,
changez `VARIANTES` — mais le plafond du hasard monte avec, et c'est le but.

## Usage

    # declarer
    sudo docker exec scalping-radar python scripts/declarer_essai_trail_en_R.py --vraiment
    # abandonner (cf. MOTIF_ABANDON — l'essai s'est revele mal specifie)
    sudo docker exec scalping-radar python scripts/declarer_essai_trail_en_R.py \
        --abandonner --vraiment

Sans `--vraiment`, le script affiche ce qu'il ferait et ne touche à rien.
"""
from __future__ import annotations

import argparse
import sys

SLUG = "trail-en-R-or-2026-09-21"

FRACTION_R = 0.5
VARIANTES = 1
MIN_ECHANTILLON = 30

HYPOTHESE = (
    "Exprimer la distance du stop suiveur en fraction du risque du trade "
    f"(|entree - stop| x {FRACTION_R}) au lieu d'un nombre de points global "
    "(TRAIL_DISTANCE_POINTS=150, soit 0,074 R sur l'or) rend l'esperance par "
    "trade positive sur XAU/USD en auto-execution. Mesure du 2026-09-21 sur "
    "14 cloture s: gain moyen +0,298 R au suiveur contre perte moyenne -1,00 R "
    "au stop, esperance -0,26 R/trade, 77 % de reussite requis pour l'equilibre "
    "contre 57 % observe. La fraction 0,5 reprend BREAKEVEN_TRIGGER_PCT=50 et "
    "n'introduit aucun reglage neuf."
)

# ⛔ `admin_legacy` et NON `admin_live`. Le banc ne juge que des clotures
# `is_auto = 1` posterieures a la declaration : `admin_live sell` etant
# retrograde en TELEGRAM depuis le 18/09, il n'en produira aucune. L'or
# auto-execute encore sur `admin_legacy` (AUTO_EXEC depuis le 25/08), et c'est
# le MEME pont MT5, donc le meme stop suiveur. C'est la ou la mesure est
# possible.
#
# ⚠️ Les deux sens sont inclus : le suiveur ne distingue pas l'achat de la vente.
SELECTEUR = {
    "pairs": ["XAU/USD"],
    "destinations": ["admin_legacy"],
}

AUTEUR = "xavier"

# ⛔ MOTIF D'ABANDON (2026-09-21, le soir meme de la declaration).
#
# Deux defauts, chacun suffisant :
#
# 1. L'hypothese nomme le stop suiveur. Or `TRAIL_DISTANCE_POINTS` vaut **0**
#    en production — le suiveur a ete desarme le 2026-08-11 apres avoir ete
#    mesure a -0,329 R/trade sur l'or. L'essai portait donc sur un mecanisme
#    deja eteint : il n'aurait jamais rien pu mesurer.
#
# 2. Le contrefactuel de sortie, lance le meme soir, a renverse le diagnostic
#    qui a motive cette declaration. Sur XAU/USD / admin_live depuis le 11/09 :
#    R obtenu +0,175 contre R contrefactuel **-0,689**, soit +0,864 R par trade
#    APPORTES par les sorties discretionnaires, et 8 clotures sur 9 qui seraient
#    allees au stop. La destruction de valeur n'est pas dans la sortie, elle est
#    dans les NIVEAUX.
#
# 🔑 Ses variantes restent comptees dans N. C'est le cout correct d'une
# declaration faite sur une deduction plutot que sur une mesure, et le banc est
# concu pour que ce cout ne s'efface pas.
MOTIF_ABANDON = (
    "hypothese doublement mal specifiee : (1) elle nomme le stop suiveur, "
    "desarme depuis le 2026-08-11 (TRAIL_DISTANCE_POINTS=0 en production), donc "
    "elle portait sur un mecanisme eteint ; (2) le contrefactuel de sortie du "
    "2026-09-21 a renverse le diagnostic — sur XAU/USD admin_live depuis le "
    "11/09, les sorties discretionnaires APPORTENT +0,864 R par trade "
    "(+0,175 obtenu contre -0,689 contrefactuel, 8 clotures sur 9 au stop). La "
    "cause est dans les niveaux SL/TP, pas dans la gestion de sortie."
)


def _abandonner(banc, vraiment: bool) -> int:
    """Ferme l'essai sans verdict. N ne redescend pas."""
    essai = banc.get_trial(SLUG)
    if essai is None:
        print(f"L'essai « {SLUG} » n'existe pas — rien a abandonner.")
        return 1
    if essai["status"] != "open":
        print(f"L'essai « {SLUG} » est deja en etat « {essai['status']} ».")
        print("Un essai clos ne se rejoue pas.")
        return 1

    print(f"slug   : {SLUG}")
    print(f"declare: {essai['declared_at']}")
    print(f"motif  : {MOTIF_ABANDON}")
    print(f"N reste a {banc.counter()} — les variantes ne sont PAS rendues.")
    print()
    if not vraiment:
        print("SIMULATION — rien n'a ete ecrit. Ajouter --vraiment.")
        return 0

    if not banc.abandon(SLUG, MOTIF_ABANDON):
        print("Abandon refuse par le banc.")
        return 1
    final = banc.get_trial(SLUG)
    print(f"Abandonne. Etat : {final['status']}, N toujours a {banc.counter()}.")
    return 0


def main() -> int:
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument("--vraiment", action="store_true",
                   help="declare pour de bon (sinon : simulation)")
    a.add_argument("--abandonner", action="store_true",
                   help="ferme l'essai sans verdict (cf. MOTIF_ABANDON). "
                        "⛔ Ses variantes restent comptees dans N.")
    args = a.parse_args()

    from backend.services import research_bench as banc

    if args.abandonner:
        return _abandonner(banc, vraiment=args.vraiment)

    existant = banc.get_trial(SLUG)
    if existant is not None:
        print(f"L'essai « {SLUG} » existe deja "
              f"(declare le {existant['declared_at']}, etat {existant['status']}).")
        print("Un slug ne se redeclare pas — c'est ce qui empeche d'ajuster")
        print("le selecteur apres avoir vu les donnees.")
        return 1

    n_avant = banc.counter()
    print(f"slug          : {SLUG}")
    print(f"selecteur     : {SELECTEUR}")
    print(f"variantes     : {VARIANTES}")
    print(f"min_echantill.: {MIN_ECHANTILLON} clotures")
    print(f"N actuel      : {n_avant}  ->  {n_avant + VARIANTES} apres declaration")
    print()

    if not args.vraiment:
        print("SIMULATION — rien n'a ete ecrit. Relancer avec --vraiment.")
        return 0

    banc.declare(slug=SLUG, hypothesis=HYPOTHESE, selector=SELECTEUR,
                 variants_declared=VARIANTES, author=AUTEUR,
                 min_sample=MIN_ECHANTILLON)
    essai = banc.get_trial(SLUG)
    print(f"Declare le {essai['declared_at']}.")
    print(f"empreinte  : {essai['declaration_hash'][:16]}...")
    print(f"N est desormais {banc.counter()}.")
    print()
    print("La frontiere est posee : seules les clotures POSTERIEURES a cet")
    print("instant compteront. Le stop suiveur peut maintenant etre modifie.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
