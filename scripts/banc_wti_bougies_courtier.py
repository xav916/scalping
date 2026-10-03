#!/usr/bin/env python3
"""Le WTI remesure sur les bougies DU COURTIER. Declare dans `13400af`.

⛔ POURQUOI CE BANC EXISTE. Le 2026-10-03 on a decouvert que Twelve Data ne
cotait pas le meme contrat que le courtier pour le WTI : 3,394 % d'ecart
constant, quand la deuxieme pire paire de l'univers est a 0,146 %. Les 9 261
lignes fantomes WTI depuis le 18 mai, et le backtest deja invalide en aout, ont
donc tous ete mesures sur le MAUVAIS instrument. On ne sait rien du WTI : ce
n'est pas une reevaluation, c'est une premiere mesure.

🔑 Trois differences avec le releve de l'or, toutes dans le sens de la rigueur :
  1. les bougies viennent du pont du reel — l'instrument qui sera execute ;
  2. le spread est MESURE dans les bougies (MT5 en stocke un par bougie) au
     lieu d'etre suppose ; c'est la faiblesse connue du banc de l'or ;
  3. les fenetres sont declarees AVANT la mesure, et strictement disjointes.

Usage :
    python scripts/banc_wti_bougies_courtier.py                # dans l'echantillon
    python scripts/banc_wti_bougies_courtier.py --hors-echantillon

⛔ `--hors-echantillon` ne doit pas etre lance avant que le verdict dans
l'echantillon soit ecrit ET commite.
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Fenetres declarees dans `docs/concepts-trading.md`, commit `13400af`, AVANT
# la premiere mesure. ⛔ Ne pas les bouger : un banc dont la fenetre derive ne
# mesure plus rien. L'historique M5 du courtier commence le 2025-05-07.
FENETRES = {
    "dans": ("2025-05-15", "2026-06-30"),
    "hors": ("2026-07-01", "2026-10-02"),
}

PAIRE = "WTI/USD"
SYMBOLE = "XTIUSD"
DESTINATION = "admin_live"

# ⚠️ 14 jours par page : 2 760 bougies M5 mesurees, sous le plafond de 5 000 du
# pont. Au-dela il tronque en gardant les plus ANCIENNES, et une requete de
# 400 jours le fait tomber en 502.
JOURS_PAR_PAGE = 14


def _destination():
    from backend.services.bridge_destinations import admin_destinations
    for d in admin_destinations():
        if str(getattr(d, "destination_id", "")) == DESTINATION:
            return d
    raise SystemExit(f"destination {DESTINATION} introuvable")


def _page(dest, debut: datetime, fin: datetime) -> dict:
    from backend.services import bridge_tick_validator as btv
    q = urllib.parse.urlencode({
        "pair": SYMBOLE, "timeframe": "M5",
        "from": debut.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "to": fin.strftime("%Y-%m-%dT%H:%M:%SZ")})
    url = f"{dest.bridge_url.rstrip('/')}/rates?{q}"
    with urllib.request.urlopen(
            urllib.request.Request(url, headers=btv._auth_header(dest)),
            timeout=60) as r:
        return json.load(r)


def charger(dest, debut: str, fin: str) -> tuple[list[dict], dict]:
    """Les bougies M5 du courtier sur la fenetre, paginees.

    ⛔ DEUX PIEGES, tous deux verifies le 2026-10-03 :
      - une fenetre anterieure a l'historique rend UNE bougie hors plage
        (datee du 2025-05-07T15:49). La recoller produirait un trou de
        plusieurs mois deguise en continuite ;
      - `tronque=true` signifie que le pont a garde les plus ANCIENNES. On
        refuse la page au lieu d'en prendre la fin.
    """
    d0 = datetime.fromisoformat(debut).replace(tzinfo=timezone.utc)
    d1 = datetime.fromisoformat(fin).replace(tzinfo=timezone.utc)
    bougies: list[dict] = []
    points: list[float] = []
    spreads: list[float] = []
    pages = refus = hors_plage = 0
    curseur = d0
    while curseur < d1:
        borne = min(curseur + timedelta(days=JOURS_PAR_PAGE), d1)
        j = _page(dest, curseur, borne)
        pages += 1
        if j.get("tronque"):
            refus += 1
            print(f"   ⛔ page {curseur.date()} TRONQUEE (n={j.get('n')}) — refusee",
                  file=sys.stderr)
            curseur = borne
            continue
        pt = float(j.get("point") or 0)
        if pt > 0:
            points.append(pt)
        for x in (j.get("bougies") or []):
            t = datetime.fromisoformat(str(x["t"]).replace("Z", "+00:00"))
            if not (curseur <= t < borne):
                hors_plage += 1
                continue
            bougies.append({"t": t, "o": float(x["o"]), "h": float(x["h"]),
                            "l": float(x["l"]), "c": float(x["c"]),
                            "tv": float(x.get("tv") or 0)})
            if x.get("s") is not None:
                spreads.append(float(x["s"]))
        curseur = borne

    bougies.sort(key=lambda b: b["t"])
    # Deduplication : deux pages adjacentes peuvent se toucher sur une bougie.
    vues = set()
    uniques = []
    for b in bougies:
        if b["t"] in vues:
            continue
        vues.add(b["t"])
        uniques.append(b)

    # ⛔ LES ETIQUETTES DU PONT NE SONT PAS SUR LA GRILLE, et elles derivent
    # d'une seconde par appel (`decalage_serveur_sec` -26905 puis -26906 sur
    # deux appels identiques). Sans cette correction le banc n'est pas
    # reproductible : il a rendu une cellule RETENUE a R=+0,4798 au premier
    # passage et la MEME a R=-0,1530 au second.
    # 🔑 La regle est celle de `bougies_du_pont`, pas une copie — la recopier
    # la ferait deriver, et le banc mesurerait un instrument que la production
    # ne trade pas.
    # ⛔ PAR BOUGIE, pas par une mediane globale : la fenetre de 412 jours
    # contient DEUX regimes de residu (0 s sur 41 026 bougies, 240 s sur
    # 38 448), parce que chaque page de 14 jours est lue avec le decalage de
    # son instant. Une mediane globale laissait 2 760 horodatages — la taille
    # d'une page — changer d'un chargement a l'autre.
    from backend.services.bougies_du_pont import (
        residu_de_grille, sur_la_grille_instant)
    residu = residu_de_grille([b["t"] for b in uniques], 5)
    for b in uniques:
        b["t"] = sur_la_grille_instant(b["t"], 5)
    # ⚠️ Deduplication APRES la correction : deux etiquettes voisines peuvent
    # tomber sur le meme point de grille.
    vues2, propres = set(), []
    for b in uniques:
        if b["t"] in vues2:
            continue
        vues2.add(b["t"])
        propres.append(b)
    ecrases = len(uniques) - len(propres)
    uniques = propres

    point = st.median(points) if points else 0.0
    info = {
        "pages": pages, "pages_refusees": refus, "bougies_hors_plage": hors_plage,
        "doublons": len(bougies) - len(uniques),
        "point": point,
        "residu_grille_sec": residu,
        "ecrases_par_la_grille": ecrases,
        "spread_points_median": st.median(spreads) if spreads else None,
        "spread_points_p90": (sorted(spreads)[int(len(spreads) * 0.9)]
                              if spreads else None),
        "spread_points_max": max(spreads) if spreads else None,
    }
    return uniques, info


# ⛔ POURQUOI LES BOUGIES SONT FIGEES SUR DISQUE. Mesure du 2026-10-03 : trois
# passages du banc sur la MEME fenetre ont rendu 0, puis 1, puis 0 cellule
# retenue, avec 57 / 54 / 50 cellules a R positif. Les bougies etaient
# pourtant au nombre identique (79 474) et les cellules aussi (250).
#
# L'experience qui tranche : en figeant les bougies dans un fichier et en
# relancant la mesure dans TROIS processus separes, le resultat est identique
# au bit — meme empreinte de cellules, meme t_vs_max. `laboratoire_or.mesurer`
# est donc parfaitement pure ; toute l'instabilite venait du CHARGEMENT.
#
# 🔑 La cause : le decalage serveur du pont derive (il est mesure sur le
# dernier tick), donc le residu de grille change entre deux chargements. Quand
# il franchit la demi-periode, toute la serie glisse d'un cran de 5 minutes —
# et l'agregation, qui range par `minute // pas * pas`, forme alors des bougies
# de 15 minutes avec d'AUTRES triplets. Les motifs detectes changent.
#
# ⚠️ Un banc dont les donnees sont refetchees a chaque passage n'est donc pas
# un banc. Elles sont figees ici une fois, archivees, et relues ensuite.
def _fige(cle: str) -> Path:
    return Path("/tmp") / f"banc_wti_{cle}.json"


def charger_ou_figer(dest, cle: str) -> tuple[list[dict], dict]:
    """Les bougies de la fenetre, lues du disque si elles y sont deja."""
    chemin = _fige(cle)
    if chemin.exists():
        d = json.loads(chemin.read_text())
        bougies = [{**x, "t": datetime.fromisoformat(x["t"])}
                   for x in d["bougies"]]
        print(f"bougies RELUES du gel : {chemin} ({len(bougies)})",
              file=sys.stderr)
        return bougies, d["info"]

    bougies, info = charger(dest, *FENETRES[cle])
    chemin.write_text(json.dumps({
        "fenetre": FENETRES[cle], "info": info,
        "bougies": [{**x, "t": x["t"].isoformat()} for x in bougies]}))
    print(f"bougies FIGEES : {chemin} ({len(bougies)})", file=sys.stderr)
    return bougies, info


def _resume(res: dict, info: dict, etiquette: str) -> dict:
    """Le releve, lu comme celui de l'or — et les quatre predictions."""
    cellules = res["cellules"]
    retenues = [c for c in cellules if c.get("verdict") == "RETENU"]
    candidates = [c for c in cellules if c.get("verdict") == "CANDIDAT"]
    t_sup2 = [c for c in cellules if (c.get("t") or 0) > 2.0]
    couts = {}
    for c in cellules:
        couts.setdefault(c["echelle"], []).append(c["spread_r"])

    print(f"\n{'=' * 72}")
    print(f"  LE WTI SUR LES BOUGIES DU COURTIER — {etiquette}")
    print(f"{'=' * 72}")
    print(f"  bougies M5      : {res['bougies_m5']}  "
          f"({info['pages']} pages, {info['pages_refusees']} refusees, "
          f"{info['bougies_hors_plage']} hors plage ecartees, "
          f"{info['doublons']} doublons)")
    print(f"  spread MESURE   : {info['spread_points_median']} points "
          f"= {res['spread']:.4f} $   "
          f"(p90 {info['spread_points_p90']}, max {info['spread_points_max']})")
    print(f"  cellules        : {res['k']}")
    print(f"  plafond hasard  : {res['plafond']:.3f}")
    print(f"  RETENUES        : {len(retenues)}")
    print(f"  candidates      : {len(candidates)}")

    print(f"\n  --- coût médian par trade, en R, par horizon ---")
    for ech in sorted(couts):
        print(f"    {_h(ech):>6s} : {st.median(couts[ech]):.4f} R "
              f"({len(couts[ech])} cellules)")

    print(f"\n  --- les 8 cellules les mieux classées (t contre le hasard) ---")
    tri = sorted(cellules, key=lambda c: -(c.get("t_vs_hasard") or -99))
    print(f"    {'horizon':>7s} {'motif':<24s} {'sens':<5s} "
          f"{'n':>5s} {'R':>8s} {'t_vs':>7s} {'verdict':>10s}")
    for c in tri[:8]:
        print(f"    {c['horizon']:>7s} {c['motif'][:24]:<24s} {c['sens']:<5s} "
              f"{c['n']:>5d} {c['r_moyen']:>+8.4f} "
              f"{(c.get('t_vs_hasard') or 0):>+7.3f} {c.get('verdict',''):>10s}")

    pct_t2 = 100.0 * len(t_sup2) / max(len(cellules), 1)
    print(f"\n  --- les prédictions, déclarées dans 13400af ---")
    print(f"    P1 zéro retenue        : {len(retenues)} retenue(s) -> "
          f"{'TENUE' if not retenues else '⛔ RÉFUTÉE'}")
    c5 = st.median(couts.get(1, [0])) if 1 in couts else None
    if c5 is not None:
        decroit = all(st.median(couts[a]) >= st.median(couts[b])
                      for a, b in zip(sorted(couts), sorted(couts)[1:]))
        print(f"    P2 coût > 0,02 R à 5min: {c5:.4f} R -> "
              f"{'TENUE' if c5 > 0.02 else '⛔ RÉFUTÉE'}"
              f"  | décroît avec l'horizon : "
              f"{'oui' if decroit else '⛔ non'}")
    print(f"    P4 ~5 % de cellules t>2: {pct_t2:.1f} % "
          f"({len(t_sup2)}/{len(cellules)})")
    print(f"       -> {'cohérent avec le hasard' if pct_t2 < 10 else '⚠️ au-delà du hasard'}")
    print(f"    P3 (réplication)       : exige la fenêtre hors échantillon")
    return {"retenues": retenues, "candidates": candidates,
            "pct_t_sup_2": pct_t2, "couts": {k: st.median(v) for k, v in couts.items()}}


def _h(facteur: int) -> str:
    return {1: "5min", 3: "15min", 6: "30min", 12: "60min"}.get(
        facteur, f"x{facteur}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--hors-echantillon", action="store_true",
                   help="⛔ seulement apres que le verdict dans l'echantillon "
                        "soit ecrit et commite")
    a = p.parse_args()
    cle = "hors" if a.hors_echantillon else "dans"
    debut, fin = FENETRES[cle]
    etiquette = (f"{'HORS' if a.hors_echantillon else 'DANS'} L'ÉCHANTILLON  "
                 f"{debut} → {fin}")

    print(f"chargement des bougies du courtier, {debut} → {fin} …",
          file=sys.stderr)
    dest = _destination()
    bougies, info = charger_ou_figer(dest, cle)
    if len(bougies) < 1000:
        print(f"⛔ seulement {len(bougies)} bougies — mesure abandonnee",
              file=sys.stderr)
        return 1

    # ⛔ Le spread en unites de PRIX : `rejouer_cellule` calcule
    # `cout = spread / risque` ou `risque` est une distance de prix.
    spread = (info["spread_points_median"] or 0) * (info["point"] or 0)
    if spread <= 0:
        print("⛔ spread illisible dans les bougies — mesure abandonnee",
              file=sys.stderr)
        return 1

    from backend.services import laboratoire_or as labo
    res = labo.mesurer(bougies, spread, pair=PAIRE)
    _resume(res, info, etiquette)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
