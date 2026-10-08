#!/usr/bin/env python3
"""Le spread de l'or varie-t-il au cours de la journee ? Profil horaire, a frais.

Question de Xavier le 2026-10-08 : « le spread est-il toujours le meme sur tous
les trades a 0,01 lot en or, ou augmente-t-il au cours de la journee ? »

## 🔑 POURQUOI UN RAPPORT ET PAS UNE VALEUR ABSOLUE

⛔ Le spread stocke dans les bougies SOUS-ESTIME l'or de **10 fois** : 0,05
dans la bougie contre 0,50 au tick (mesure du 2026-10-03). On ne peut donc PAS
servir ces chiffres en valeur absolue.

🔑 Mais un **RAPPORT entre heures** annule un biais multiplicatif constant. Si
le courtier ecrit systematiquement un dixieme du vrai spread, « 20h coute deux
fois 10h » reste vrai. La FORME est lisible, le NIVEAU non.

⇒ Ce script rend donc des **rapports au plateau**, et prend son niveau absolu
du **tick**, seul arbitre.

## La mesure du 2026-08-11, qu'on rafraichit

« 15 150 bougies M1 / 14 jours : plateau a x1,00 de 06h a 19h UTC, puis
**x2,13 a 20h et 22h** ». Elle a fonde la fenetre `XAU/USD: 06-19` en
production. Quatorze jours, c'est peu — on refait sur plusieurs mois.
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import urllib.parse
import urllib.request
from collections import defaultdict

PAIRE = "XAU/USD"
BASE = os.environ.get("MT5_BRIDGE_LIVE_URL", "http://100.74.160.72:8788")
CLE = (os.environ.get("MT5_BRIDGE_LIVE_API_KEY")
       or os.environ.get("MT5_BRIDGE_API_KEY") or "")
DEPUIS = "2026-04-01T00:00:00"
JUSQUA = "2026-10-08T00:00:00"
PLATEAU = range(6, 20)          # 06h-19h UTC, la fenetre en production


def _get(chemin: str):
    rq = urllib.request.Request(BASE.rstrip("/") + chemin,
                                headers={"X-API-Key": CLE})
    with urllib.request.urlopen(rq, timeout=180) as r:
        return json.load(r)


def tick_vivant() -> float | None:
    """`ask - bid` a l'instant. Le seul arbitre du NIVEAU."""
    try:
        t = _get(f"/tick/{PAIRE}")
        return float(t["ask"]) - float(t["bid"])
    except Exception as e:  # noqa: BLE001
        print(f"  (tick indisponible : {type(e).__name__}: {e})")
        return None


def bougies():
    """Toutes les bougies de la fenetre, en suivant `suite_from`.

    🔑 Possible depuis `9056d41` seulement : avant, une plage large rendait 502.
    """
    depuis, vues, pages = DEPUIS, {}, 0
    while depuis and pages < 200:
        q = urllib.parse.urlencode({"pair": PAIRE, "timeframe": "M5",
                                    "from": depuis, "to": JUSQUA})
        d = _get("/rates?" + q)
        for b in d.get("bougies") or []:
            vues[b["t"]] = b
        pages += 1
        depuis = d.get("suite_from")
    print(f"  {len(vues)} bougies distinctes en {pages} pages")
    return list(vues.values())


def main() -> int:
    print("=== PROFIL HORAIRE DU SPREAD DE L'OR ===")
    niveau = tick_vivant()
    if niveau is not None:
        print(f"  niveau au tick, a l'instant : {niveau:.3f} $")
    print("")
    bgs = bougies()
    if len(bgs) < 5000:
        print("  pas assez de bougies")
        return 1

    par_heure = defaultdict(list)
    point = 0.01       # or : 1 point = 0,01 $
    for b in bgs:
        s = b.get("s")
        if s is None:
            continue
        h = int(str(b["t"])[11:13])
        par_heure[h].append(float(s) * point)

    base = [v for h in PLATEAU for v in par_heure.get(h, [])]
    if not base:
        print("  plateau vide")
        return 1
    ref = statistics.median(base)
    echelle = (niveau / ref) if (niveau and ref > 0) else None
    print("")
    print(f"  plateau 06h-19h UTC : mediane stockee {ref:.3f} $"
          + (f", soit x{echelle:.1f} pour atteindre le tick" if echelle else ""))
    print("")
    # ⛔ LA MEDIANE NE SUFFIT PAS. Premier passage : elle vaut EXACTEMENT
    # 0,050 $ aux 24 heures, rapport 1,00 partout. C'est la signature d'un
    # PLANCHER QUANTIFIE — le courtier ecrit 5 points la plupart du temps, et
    # toute variation horaire se cache dans la QUEUE de la distribution.
    #
    # 🔑 On regarde donc la moyenne, les hauts percentiles, et la PART des
    # bougies au-dessus du plancher. C'est la que « le spread augmente-t-il ? »
    # se lit.
    plancher = min(min(v) for v in par_heure.values() if v)
    print(f"  plancher observe : {plancher:.3f} $  "
          f"(le courtier y colle la plupart du temps)")
    print("")
    print(f"  {'h UTC':>6s} {'n':>6s} {'moyenne':>8s} {'p75':>7s} {'p90':>7s} "
          f"{'p99':>7s} {'% > plancher':>13s} {'rapport moy':>12s}")
    moy_base = statistics.fmean(base)
    for h in range(24):
        v = par_heure.get(h)
        if not v:
            continue
        v2 = sorted(v)
        moy = statistics.fmean(v2)
        def pct(q):
            return v2[min(len(v2) - 1, int(q * len(v2)))]
        au_dessus = sum(1 for x in v2 if x > plancher + 1e-9) * 100 / len(v2)
        rap = moy / moy_base if moy_base > 0 else float("nan")
        marque = "" if h in PLATEAU else "  <- HORS fenetre"
        if rap >= 1.5:
            marque += "  ⚠️"
        print(f"  {h:4d} h {len(v2):6d} {moy:8.3f} {pct(0.75):7.3f} "
              f"{pct(0.90):7.3f} {pct(0.99):7.3f} {au_dessus:12.1f} % "
              f"{rap:11.2f}{marque}")

    print("")
    print("  🔑 Le RAPPORT est fiable (un biais multiplicatif constant")
    print("     s'annule). La colonne « estime au tick » applique l'echelle du")
    print("     tick au profil : c'est une ESTIMATION, pas une mesure.")
    print("  ⛔ Le spread ne depend PAS du lot : a 0,01 comme a 1,00 le")
    print("     courtier cote le meme ecart. C'est le COUT EN EUROS qui suit")
    print("     le lot, pas le spread.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
