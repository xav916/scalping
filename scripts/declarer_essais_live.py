"""Déclare au banc les deux essais qui peuvent ouvrir `admin_live` — l'or et le WTI.

Décision de Xavier du 2026-09-22 : rouvrir les deux instruments sur IC Markets,
**par la voie rigoureuse**. Ce script déclare ; il ne promeut rien.

## Pourquoi les essais du 2026-09-22 ne suffisaient pas

`rehabilitation-or-2026-09-22` et `rehabilitation-wti-2026-09-22` ont un sélecteur
`destinations: ["admin_legacy"]`. Or `gate_promotion` exige que la portée de l'essai
**couvre** la destination demandée, et `_couvre` est explicite :

> ⛔ *Une couverture étroite ne couvre JAMAIS une demande large.*

Un essai borné à la démo ne pourra donc jamais ouvrir l'argent réel, quel que soit
son verdict. Ces deux essais gardent leur valeur — ils répondent à une question plus
étroite et plus propre — mais ils ne sont pas la clé de cette porte-ci.

## Le sélecteur retenu, et pourquoi il nomme les deux destinations

    destinations : ["admin_legacy", "admin_live"]

⛔ **Et non pas « aucune restriction ».** Omettre la clé rendrait la portée illimitée
— l'essai couvrirait alors `admin_kraken` et `user:2`, le compte d'un client. Une
porte qu'on ouvre doit nommer ce qu'elle ouvre.

🔑 **Le fait que la démo alimente une mesure qui ouvrira le réel est assumé, et
biaisé dans le sens FLATTEUR.** Mesuré le 2026-09-22 (constat R-15 du rapport) : sur
l'or vendeur, le dépassement de stop vaut −0,040 R en démo contre +0,127 R en réel.
Les fills simulés honorent le stop ; le courtier prend environ 13 % de plus. Un
verdict nourri majoritairement de démo surestime donc légèrement le réel. C'est
écrit ici pour que personne n'ait à le redécouvrir au moment du verdict.

## Ce qu'il faut EN PLUS de ces essais

1. **Armer le banc.** `RESEARCH_BENCH_GATE_ENABLED=true` dans `/opt/scalping/.env`,
   puis redémarrage du service. Sans ça la porte est désarmée (constat R-2) et
   laisse tout passer — déclarer des essais devient un rituel sans effet.
2. **Ouvrir la classe `energy`** pour le WTI : `MT5_BRIDGE_ALLOWED_ASSET_CLASSES`
   vaut aujourd'hui `forex,metal`. Cette porte vit dans `.env`, aucun script ne
   l'ouvre.
3. **Attendre l'échantillon**, puis évaluer. Le verdict se calcule contre le plafond
   du hasard à N essais, et N vaut 1 235 avant ce script.

⚠️ Armer le banc refusera aussi les promotions AUTOMATIQUES vers `AUTO_EXEC` sur
l'argent réel tant qu'aucun essai ne les couvre. Le planificateur le gère
proprement — `refused_by_bench`, journalisé comme décision et non comme panne — mais
c'est un changement de comportement réel, et il vaut pour toutes les paires.

## Usage

    sudo docker exec scalping-radar python scripts/declarer_essais_live.py
    sudo docker exec scalping-radar python scripts/declarer_essais_live.py --vraiment
"""
from __future__ import annotations

import argparse
import pathlib
import sys

_RACINE = str(pathlib.Path(__file__).resolve().parent.parent)
if _RACINE not in sys.path:
    sys.path.insert(0, _RACINE)

DESTINATIONS = ["admin_legacy", "admin_live"]
AUTEUR = "xavier"
VARIANTES = 1
MIN_ECHANTILLON = 30

_BIAIS = (
    "Biais connu et assume : la demo alimentera l'essentiel de l'echantillon, et "
    "elle FLATTE — depassement de stop -0,040 R en demo contre +0,127 R en reel sur "
    "l'or vendeur (constat R-15, mesure du 2026-09-22)."
)

ESSAIS = [
    {
        "slug": "live-or-2026-09-22",
        "hypothesis": (
            "XAU/USD en auto-execution rend une esperance POSITIVE sur admin_legacy "
            "et admin_live reunis, sous les protections entrees en service depuis "
            "ses mauvais chiffres (NO_FRIDAY_LATE_OPEN_ENERGY 03/08, fermeture du "
            "vendredi elargie 04/09, blackout news repare 20/09 apres n'avoir jamais "
            "bloque un seul ordre). Prior CONTRAIRE : contrefactuel du 21/09 a "
            "-0,689 R avec 8 clotures sur 9 au stop, retrogradation du 18/09 sur "
            "dd_R=5,168. " + _BIAIS
        ),
        "selector": {"pairs": ["XAU/USD"], "destinations": DESTINATIONS},
    },
    {
        "slug": "live-wti-2026-09-22",
        "hypothesis": (
            "WTI/USD en auto-execution rend une esperance POSITIVE sur admin_legacy "
            "et admin_live reunis, sous les memes protections. Prior FORTEMENT "
            "CONTRAIRE : 116 trades reels a 6,1 % de reussite, shadow "
            "V2_WTI_OPTIMAL a WR 11 % pour -205 EUR quand son backtest annoncait "
            "PF 1,20-1,78, et retrait de la whitelist Live au gate S8 du 04/07. "
            + _BIAIS
        ),
        "selector": {"pairs": ["WTI/USD"], "destinations": DESTINATIONS},
    },
]


def main() -> int:
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument("--vraiment", action="store_true",
                   help="declare pour de bon (sinon : simulation)")
    args = a.parse_args()

    from config import settings
    from backend.services import research_bench as banc

    arme = bool(getattr(settings, "RESEARCH_BENCH_GATE_ENABLED", False))
    print(f"banc d'essai : {'ARME' if arme else 'DESARME'}")
    if not arme:
        print("  ⚠️ Desarme, ces essais ne garderont AUCUNE porte. Poser")
        print("     RESEARCH_BENCH_GATE_ENABLED=true dans /opt/scalping/.env,")
        print("     puis redemarrer le service.")
    print()

    deja = [e["slug"] for e in ESSAIS if banc.get_trial(e["slug"]) is not None]
    if deja:
        print("Deja declare(s), un slug ne se redeclare pas :")
        for s in deja:
            print(f"  - {s}")
        return 1

    n = banc.counter()
    print(f"N : {n}  ->  {n + VARIANTES * len(ESSAIS)}")
    for e in ESSAIS:
        print(f"  {e['slug']}  {e['selector']}")
    print()

    if not args.vraiment:
        print("SIMULATION — rien n'a ete ecrit. Relancer avec --vraiment.")
        return 0

    for e in ESSAIS:
        banc.declare(slug=e["slug"], hypothesis=e["hypothesis"],
                     selector=e["selector"], variants_declared=VARIANTES,
                     author=AUTEUR, min_sample=MIN_ECHANTILLON)
        t = banc.get_trial(e["slug"])
        print(f"{e['slug']} : {t['declared_at']}  empreinte {t['declaration_hash'][:16]}...")

    print(f"\nN est desormais {banc.counter()}.")
    print("Ces essais COUVRENT admin_live : une fois passes, gate_promotion")
    print("laissera la promotion en AUTO_EXEC sur l'argent reel.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
