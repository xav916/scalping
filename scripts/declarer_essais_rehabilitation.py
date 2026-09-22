"""Déclare au banc les deux essais de réhabilitation — l'or et le WTI.

## Pourquoi ces deux essais existent

Xavier a décidé le 2026-09-22 de réhabiliter `XAU/USD` et `WTI/USD`. Ce script ne
réhabilite rien : il **déclare**, pour que la réhabilitation soit jugée sur des
clôtures que personne n'a vues au moment où l'hypothèse a été écrite.

⛔ **Sans déclaration préalable, « l'or va mieux » sera vrai le jour où il ira mieux
par hasard.** C'est exactement ce qui a rendu bonnes les 1 226 variantes
précédentes, et c'est ce que le banc existe pour rendre impossible.

## Ce qui a CHANGÉ, et pourquoi ce n'est pas du cherry-picking

Trois protections sont entrées en service APRÈS que ces instruments ont accumulé
leurs chiffres. Aucune n'a été choisie en regardant leurs résultats — les trois
corrigent des défauts trouvés pour d'autres raisons :

- **2026-08-03** — `NO_FRIDAY_LATE_OPEN_ENERGY` : bloque l'ouverture d'énergie le
  vendredi soir. Motivé par l'incident de gap WTI du 03/08.
- **2026-09-04** — la fermeture du vendredi élargie à **tout ce dont le marché
  ferme** (forex, métaux, pétrole, indices), et plus seulement aux métaux.
- **2026-09-20** — le **blackout news** fonctionne enfin. Il n'avait **jamais
  bloqué un seul ordre** depuis l'existence du code (le producteur émettait
  « 14:30 », le consommateur exigeait de l'ISO). L'or et le WTI n'ont donc jamais
  été tradés avec protection autour des annonces — et la fenêtre qui a fait
  rétrograder l'or contenait CPI, FOMC, BoE et BoJ.

🔑 C'est la seule base légitime pour re-mesurer : les conditions ont changé pour
des raisons indépendantes du résultat qu'on espère.

## Ce que chaque essai ne dit PAS

Il ne dit pas que l'instrument a un edge. Il dit : *à partir d'aujourd'hui, sous ces
protections, voici ce que rendent les clôtures*. Le verdict tombera au
`min_sample`, contre le plafond du hasard à N essais — et N inclut les 1 226 du
dépouillement.

⚠️ **Les priors diffèrent fortement entre les deux**, et les hypothèses le disent :

    XAU/USD   223 trades reels, 38,4 % de reussite, +432,54 USD au gate S8.
              Mais contrefactuel du 21/09 : -0,689 R, 8 clotures sur 9 au stop.
              -> un instrument a edge apparent dont les NIVEAUX perdent.

    WTI/USD   116 trades reels, 6,1 % de reussite. Shadow V2_WTI_OPTIMAL :
              16 setups, WR 11 %, -205 EUR, alors que son backtest annoncait
              PF 1,20-1,78. -> un backtest DEMENTI par le reel.

## Portée : la démo, et elle seule

Les deux sélecteurs visent `admin_legacy`. Le banc ne juge que des clôtures
`is_auto = 1` **postérieures** à la déclaration : un instrument qui ne
s'auto-exécute nulle part n'en produira aucune.

⚠️ **`WTI/USD` doit donc être remis en `AUTO_EXEC` sur la démo** pour que son essai
puisse accumuler. C'est une action à part, volontaire, et elle n'engage pas d'argent
réel. Vérifier son état avant :

    sqlite3 -readonly /opt/scalping/data/trades.db \\
      "SELECT destination, direction, state, state_since FROM pair_admission_state
       WHERE pair='WTI/USD' ORDER BY destination, direction, state_since DESC;"

⛔ Aucun des deux essais ne porte sur `admin_live`. Le passage à l'argent réel
demande, EN PLUS d'un essai passé : le contrôle par comparaison inter-paires, et un
`r_contrefactuel_moyen >= 0` sur une fenêtre postérieure. Trois conditions, pas une.

## Usage

    sudo docker exec scalping-radar python scripts/declarer_essais_rehabilitation.py
    sudo docker exec scalping-radar python scripts/declarer_essais_rehabilitation.py --vraiment
"""
from __future__ import annotations

import argparse
import sys

PROTECTIONS = (
    "protections entrees en service APRES les chiffres qui ont sorti cet "
    "instrument : NO_FRIDAY_LATE_OPEN_ENERGY (2026-08-03), fermeture du vendredi "
    "elargie a tout marche qui ferme (2026-09-04), et blackout news REPARE le "
    "2026-09-20 apres n'avoir jamais bloque un seul ordre depuis l'existence du "
    "code. Aucune de ces trois n'a ete choisie en regardant les resultats de "
    "l'instrument."
)

ESSAIS = [
    {
        "slug": "rehabilitation-or-2026-09-22",
        "hypothesis": (
            "Sous les protections citees, les niveaux SL/TP de XAU/USD rendent une "
            "esperance POSITIVE en auto-execution sur admin_legacy. Prior contraire : "
            "le contrefactuel du 2026-09-21 rend -0,689 R sur n=9, avec 8 clotures "
            "sur 9 qui seraient allees au stop, et le regulateur a retrograde la "
            "paire le 2026-09-18 sur dd_R=5,168. L'instrument porte par ailleurs "
            "87,6 % du resultat et affiche 38,4 % de reussite sur 223 trades reels : "
            "edge apparent, niveaux perdants. " + PROTECTIONS
        ),
        "selector": {"pairs": ["XAU/USD"], "destinations": ["admin_legacy"]},
        "min_sample": 30,
    },
    {
        "slug": "rehabilitation-wti-2026-09-22",
        "hypothesis": (
            "Sous les protections citees, WTI/USD rend une esperance POSITIVE en "
            "auto-execution sur admin_legacy. Prior FORTEMENT contraire : 116 trades "
            "reels a 6,1 % de reussite, et un shadow V2_WTI_OPTIMAL de 16 setups a "
            "WR 11 % pour -205 EUR, alors que son backtest annoncait PF 1,20-1,78 sur "
            "4 fenetres sur 4 — un backtest DEMENTI par le reel. L'instrument a ete "
            "retire de la whitelist Live au gate S8 du 2026-07-04 sur ce motif. "
            + PROTECTIONS
        ),
        "selector": {"pairs": ["WTI/USD"], "destinations": ["admin_legacy"]},
        "min_sample": 30,
    },
]

AUTEUR = "xavier"
VARIANTES = 1


def main() -> int:
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument("--vraiment", action="store_true",
                   help="declare pour de bon (sinon : simulation)")
    args = a.parse_args()

    from backend.services import research_bench as banc

    deja = [e["slug"] for e in ESSAIS if banc.get_trial(e["slug"]) is not None]
    if deja:
        print("Deja declare(s), un slug ne se redeclare pas :")
        for s in deja:
            print(f"  - {s}")
        return 1

    n = banc.counter()
    print(f"N actuel : {n}  ->  {n + VARIANTES * len(ESSAIS)} apres declaration")
    print()
    for e in ESSAIS:
        print(f"  {e['slug']}")
        print(f"     selecteur : {e['selector']}")
        print(f"     echantillon minimum : {e['min_sample']} clotures posterieures")
    print()

    if not args.vraiment:
        print("SIMULATION — rien n'a ete ecrit. Relancer avec --vraiment.")
        return 0

    for e in ESSAIS:
        banc.declare(slug=e["slug"], hypothesis=e["hypothesis"],
                     selector=e["selector"], variants_declared=VARIANTES,
                     author=AUTEUR, min_sample=e["min_sample"])
        t = banc.get_trial(e["slug"])
        print(f"{e['slug']} : declare le {t['declared_at']}, "
              f"empreinte {t['declaration_hash'][:16]}...")
    print()
    print(f"N est desormais {banc.counter()}.")
    print("La frontiere est posee : seules les clotures POSTERIEURES comptent.")
    print()
    print("⚠️ WTI doit etre en AUTO_EXEC sur admin_legacy pour produire des")
    print("   clotures. Verifier pair_admission_state (cf. docstring).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
