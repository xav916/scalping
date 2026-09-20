#!/usr/bin/env python3
"""LES DEUX mesures qui doivent preceder toute lecture de R sur l'extreme
d'accumulation — declarees dans `docs/concepts-trading.md` le 2026-09-20.

⛔ POURQUOI ELLES PASSENT AVANT LE CODE DU PREDICAT. Le carnet declare deux
objections, et c'est le `n` qui inquiete cette fois, pas le recouvrement :

  1. parmi les balayages DEJA en accumulation, quelle part prend deja, de fait,
     le BORD de la zone ? Si c'est ~100 %, la regle ne filtre rien : elle
     duplique `chaine:prise_en_accumulation` et se paie sur le plafond du
     hasard de TOUTES les autres cellules ;
  2. combien de declenchements reste-t-il en valeur absolue ? Sous
     `MIN_TRADES`, la cellule sortira `INSUFFISANT` indefiniment : elle
     coutera du plafond sans jamais pouvoir conclure.

⚠️ RIEN N'EST RECODE ICI. Le detecteur vient de `pattern_detector`, le
predicat d'accumulation de `laboratoire_or._dans_accumulation`, la zone de
`market_profile.zone_accumulation`. Une deuxieme implementation mesurerait
autre chose que ce que le laboratoire mesurera.

🔑 LA GEOMETRIE, et elle a deja ete corrigee une fois. La zone se lit sur
`bougies[:i-1]` — SANS la bougie du signal. Avec elle, `bas` = min(low) des dix
dernieres bougies INCLUT le plus-bas de la bougie qui perce : « low < bas »
serait faux par construction. Le percage se lit sur `bougies[i-1]`, parce que
`detections()` detecte a l'indice `i` sur `bougies[i - FENETRE:i]` : la bougie
`i` n'est pas vue par le detecteur, c'est la bougie d'entree.

Bougies : la fixture FIGEE de vraies bougies XAU/USD 5 min. Aucun appel reseau.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.models.schemas import PatternType                         # noqa: E402
from backend.services import laboratoire_or as labo                    # noqa: E402
from backend.services import market_profile as mp                      # noqa: E402
from backend.services.pattern_detector import Candle, detect_patterns   # noqa: E402

FIXTURE = (Path(__file__).resolve().parents[1] / "backend" / "tests"
           / "fixtures" / "bougies_xauusd_5min.json")

# (motif, bord de la zone pris, libelle)
# ⚠️ Dans ce depot LIQUIDITY_SWEEP_UP est un ACHAT : il balaie les BAS.
CAS = (
    (PatternType.LIQUIDITY_SWEEP_UP.value, "bas", "balayage des BAS (achat)"),
    (PatternType.LIQUIDITY_SWEEP_DOWN.value, "haut", "balayage des HAUTS (vente)"),
)


def _zone_avant(bougies, i: int) -> dict | None:
    """La zone d'accumulation telle qu'elle existait AVANT la bougie du signal.

    ⛔ `bougies[:i-1]` et pas `bougies[:i]` : voir l'en-tete. Meme fenetre que
    `_dans_accumulation` sinon — on ne change qu'un cran d'indice.
    """
    vues = bougies[: i - 1]
    besoin = mp.ACCU_RECENTES + mp.ACCU_AVANT
    if len(vues) < besoin:
        return None
    fen = vues[-besoin:]
    objets = [Candle(timestamp=x["t"], open=x["o"], high=x["h"],
                     low=x["l"], close=x["c"], volume=x.get("tv") or 0.0)
              for x in fen]
    return mp.zone_accumulation(objets, source=mp.VOLUME)


def main() -> int:
    brut = json.loads(FIXTURE.read_text(encoding="utf-8"))
    t0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
    bougies = [{"t": t0 + timedelta(minutes=5 * k), "o": o, "h": h,
                "l": b, "c": c, "tv": 0.0}
               for k, (o, h, b, c) in enumerate(brut)]
    objets = [Candle(timestamp=x["t"], open=x["o"], high=x["h"],
                     low=x["l"], close=x["c"], volume=0) for x in bougies]

    stats = {m: {"balayages": 0, "accu": 0, "zone_absente_avant": 0,
                 "bord": 0, "pas_bord": 0, "perce_sans_reintegrer": 0}
             for m, _, _ in CAS}

    depart = max(labo.FENETRE, mp.ACCU_RECENTES + mp.ACCU_AVANT) + 2
    fenetres = 0
    for i in range(depart, len(bougies)):
        fenetres += 1
        vus = {p.pattern.value for p in
               detect_patterns(objets[i - labo.FENETRE:i], "XAU/USD")}
        for motif, bord, _ in CAS:
            if motif not in vus:
                continue
            s = stats[motif]
            s["balayages"] += 1
            # Le comparant est la chaine DEJA declaree : `prise_en_accumulation`.
            if not labo._dans_accumulation(bougies, i):
                continue
            s["accu"] += 1
            zone = _zone_avant(bougies, i)
            if zone is None:
                # La zone n'existait PAS sans la bougie du signal : c'est ce
                # balayage qui la fabrique. Cas a compter, pas a ignorer.
                s["zone_absente_avant"] += 1
                continue
            signal = bougies[i - 1]
            niveau = zone[bord]
            if bord == "bas":
                perce = signal["l"] < niveau
                reintegre = signal["c"] > niveau
            else:
                perce = signal["h"] > niveau
                reintegre = signal["c"] < niveau
            if perce and reintegre:
                s["bord"] += 1
            elif perce:
                s["perce_sans_reintegrer"] += 1
            else:
                s["pas_bord"] += 1

    print(f"Fenetres examinees : {fenetres}  (bougies {depart} a {len(bougies)})")
    print(f"Zone : {mp.ACCU_RECENTES} bougies apres {mp.ACCU_AVANT}  |  "
          f"compression <= {mp.ACCU_COMPRESSION}  |  retour <= {mp.ACCU_RETOUR}")
    print(f"MIN_TRADES = {labo.MIN_TRADES} — sous ce seuil, verdict INSUFFISANT\n")

    verdicts = []
    for motif, bord, libelle in CAS:
        s = stats[motif]
        print(f"— {libelle}  (bord « {bord} »)")
        print(f"    balayages simples                    : {s['balayages']}")
        if s["balayages"] == 0:
            print("    (aucun : rien a dire)\n")
            verdicts.append((libelle, None, 0))
            continue
        a = s["accu"]
        print(f"    dont en accumulation (comparant)     : {a}"
              f"  ({100*a/s['balayages']:.1f} %)")
        if a == 0:
            print("    ⚠️ le COMPARANT lui-meme est muet sur la fixture\n")
            verdicts.append((libelle, None, 0))
            continue
        print(f"      zone inexistante sans le signal    : {s['zone_absente_avant']}"
              f"  ({100*s['zone_absente_avant']/a:.1f} %)")
        print(f"      perce le bord ET reintegre         : {s['bord']}"
              f"  ({100*s['bord']/a:.1f} %)   <- LA CHAINE")
        print(f"      perce sans reintegrer              : {s['perce_sans_reintegrer']}")
        print(f"      ne touche pas le bord              : {s['pas_bord']}")
        print()
        verdicts.append((libelle, 100 * s["bord"] / a, s["bord"]))

    print("VERDICT")
    for libelle, part, n in verdicts:
        if part is None:
            print(f"  {libelle} : indecidable — comparant muet sur la fixture")
        elif part >= 95:
            print(f"  {libelle} : ⛔ {part:.1f} % — la regle NE FILTRE RIEN. Elle "
                  "duplique `prise_en_accumulation` et coute du plafond a tout "
                  "le monde. NE PAS CODER.")
        elif n < labo.MIN_TRADES:
            print(f"  {libelle} : ⛔ n = {n} < MIN_TRADES = {labo.MIN_TRADES} — "
                  "INSUFFISANT garanti. La cellule couterait du plafond sans "
                  "jamais pouvoir conclure. NE PAS CODER en l'etat.")
        else:
            print(f"  {libelle} : ✅ filtre {100-part:.1f} % des balayages en "
                  f"accumulation et garde n = {n} >= {labo.MIN_TRADES} — "
                  "mesurable. La comparaison appariee peut etre montee.")
    print("\n⚠️ Une fixture d'un instrument ne dit pas le n sur 13 nuits et "
          "4 echelles. Elle dit si la regle est VIVANTE ou MORTE-NEE.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
