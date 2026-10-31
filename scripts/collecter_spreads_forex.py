#!/usr/bin/env python3
"""Collecte le bid/ask du courtier, agrégé par MINUTE, pour les paires sans mesure.

## Pourquoi ce collecteur existe

`cout_execution` ne sait mesurer que l'or : c'est la seule paire dont le
bid/ask soit persisté (`ticks_courtier.db`, 12 M de ticks). Partout ailleurs
il rend une **hypothèse déclarée**, que `exiger_mesure()` refuse pour tout
niveau absolu. Conséquence mesurée le 2026-10-31 : aucun chiffre de coût
n'est publiable sur `EUR/USD`, `BTC/USD` ou `WTI/USD`.

⛔ Et la route `/rates` ne peut pas y suppléer : MT5 y stocke le spread en
nombre ENTIER de points, donc **96 % des bougies `EUR/USD` affichent zéro**.
Mesure du 31/10 sur la route `/ticks` : `EUR/USD` cote à **0,8 pip** — un
spread réel, systématiquement tronqué à 0 par l'autre route.

## Pourquoi un AGRÉGAT par minute, et pas les ticks

Le magasin d'or pèse **1,7 Go pour 40 jours et UNE paire**. Onze paires en
ticks bruts demanderaient ~150 Go/an pour 29 Go libres : impossible.

🔑 Mesurer un COÛT ne demande pas chaque tick, mais la **distribution** du
spread. On garde donc `min`, `médiane` et `max` par minute : l'enveloppe de
variation intra-minute reste visible — et elle existe (l'or passe de 15 à
22 points en deux minutes).

⚠️ La résolution est donc la MINUTE. Une recherche « au tick de l'instant »
comme celle faite sur l'or n'est pas possible ici ; `min`/`max` bornent ce
qu'on aurait pu payer dans la minute.

## Les deux pièges que ce script évite

⛔ **Le marché FERMÉ.** Le 31/10 à 09h25 UTC — un samedi — l'or cotait un
spread de **0,40 $** contre **0,086 $** de médiane en séance : **4,6× plus
large**. Collecter sans le noter aurait pollué le magasin dans le sens
pessimiste. Chaque minute porte donc `marche_ouvert`, relevé À LA COLLECTE.

⛔ **La minute EN COURS.** L'agréger donnerait une valeur partielle, que le
`INSERT OR IGNORE` figerait ensuite définitivement. On s'arrête donc à la
dernière minute RÉVOLUE.

## Le témoin

`XAU/USD` est collecté **exprès**, alors que son coût est déjà mesuré : c'est
lui qui dira si cet instrument-ci est juste. Un agrégat-minute de l'or qui ne
retrouverait pas ~0,086 $ de médiane en séance condamnerait la méthode avant
qu'on s'en serve ailleurs.

## Ce que ce script NE dit PAS

⛔ **Le markup est INCONNU hors de l'or.** Les 10 points mesurés le 12/10
valent pour `XAU/USD` sur la route `/ticks` ; rien ne dit qu'ils valent pour
`EUR/USD`. La table `provenance` le déclare, et toute mesure devra l'établir
avant de publier un niveau.

Usage :
    python3 scripts/collecter_spreads_forex.py [--minutes 120] [--paires EUR/USD,...]
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import sqlite3
import statistics
import sys

import httpx

logger = logging.getLogger("collecte_spreads")

MAGASIN = os.getenv("MAGASIN_SPREADS", "/app/data/spreads_minute.db")

# Les paires sans mesure, PLUS l'or comme temoin.
# ⛔ La crypto n'est pas ici : elle n'est pas dans les classes autorisees de
# `admin_live` (energy, forex, metal) ni dans celles que le registre declare
# acceptees par IC Markets. Elle passe par Kraken, dont le pont a ses propres
# routes.
PAIRES_DEFAUT = [
    "XAU/USD",                                            # TEMOIN
    "EUR/USD", "GBP/USD", "USD/JPY", "EUR/GBP", "USD/CHF",
    "AUD/USD", "USD/CAD", "EUR/JPY", "GBP/JPY",           # forex
    "XAG/USD",                                            # metal sans mesure
    "WTI/USD",                                            # energie
]

# Au-dela, le pont tronque et pagine ; on reste raisonnable par appel.
FENETRE_MAX_MIN = 240


def _schema(c: sqlite3.Connection) -> None:
    c.execute("""
        CREATE TABLE IF NOT EXISTS spread_minute (
            pair TEXT NOT NULL,
            minute TEXT NOT NULL,          -- 'AAAA-MM-JJTHH:MM' UTC
            n INTEGER NOT NULL,            -- ticks agreges dans la minute
            spread_min REAL NOT NULL,
            spread_med REAL NOT NULL,
            spread_max REAL NOT NULL,
            mid_med REAL NOT NULL,
            point REAL,
            marche_ouvert INTEGER,         -- releve A LA COLLECTE
            spread_constant INTEGER,       -- SUSPICION de cotation gelee
            PRIMARY KEY (pair, minute)
        )""")
    c.execute("CREATE TABLE IF NOT EXISTS provenance (cle TEXT PRIMARY KEY, valeur TEXT)")
    for cle, val in (
        ("source", "pont MT5 IC Markets (admin_live, port 8788), route /ticks"),
        ("resolution", "AGREGAT PAR MINUTE, pas le tick -- contrainte de disque "
                       "(l'or pese 1,7 Go pour 40 j et 1 paire). min/med/max "
                       "bornent la variation intra-minute."),
        ("markup", "INCONNU hors de l'or. Les 10 points mesures le 2026-10-12 "
                   "valent pour XAU/USD sur cette route ; rien ne dit qu'ils "
                   "valent pour EUR/USD. A ETABLIR avant tout niveau absolu."),
        ("marche_ouvert", "releve a la collecte par market_hours.is_market_open_for. "
                          "Un samedi, l'or cote 0,40 $ contre 0,086 en seance : "
                          "filtrer AVANT de mesurer."),
        ("temoin", "XAU/USD est collecte expres : son cout est deja mesure "
                   "(mediane 0,0859 $ de spread magasin). Si l'agregat-minute "
                   "ne le retrouve pas en seance, c'est l'instrument qui est faux."),
        ("minute_en_cours", "JAMAIS agregee : une valeur partielle serait figee "
                            "par le INSERT OR IGNORE des passages suivants."),
        ("spread_constant", "SUSPICION de cotation GELEE : min == max sur >= 10 "
                            "ticks. Mesure du 2026-10-30 : le flux de l'or s'est "
                            "fige a 09h15 sur un spread de 0,4000 EXACTEMENT "
                            "(min = max) pendant 18 minutes, puis le magasin de "
                            "ticks s'est arrete a 11h06. Un spread de marche "
                            "FLUCTUE ; un spread constant a une valeur ronde est "
                            "une cotation qui ne se met plus a jour. Ce n'est PAS "
                            "un verdict : sur une minute calme, min == max est "
                            "legitime. D'ou 'suspicion', et le filtrage au moment "
                            "de MESURER, pas de collecter."),
    ):
        c.execute("INSERT OR IGNORE INTO provenance (cle, valeur) VALUES (?,?)",
                  (cle, val))


def derniere_minute(c: sqlite3.Connection, pair: str) -> str | None:
    r = c.execute("SELECT MAX(minute) FROM spread_minute WHERE pair=?",
                  (pair,)).fetchone()
    return r[0] if r and r[0] else None


def agreger(ticks: list[dict]) -> dict[str, dict]:
    """Les ticks, groupés par minute. Écarte les cotations impossibles.

    ⛔ `ask <= bid` ou un prix nul n'est pas un spread serré : c'est un
    instrument faux. On l'exclut et le compte reste visible via `n`.
    """
    par_minute: dict[str, list[tuple[float, float]]] = {}
    for t in ticks:
        try:
            bid, ask = float(t["bid"]), float(t["ask"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (ask > bid > 0):
            continue
        quand = str(t.get("t") or "")[:16]      # 'AAAA-MM-JJTHH:MM'
        if len(quand) != 16:
            continue
        par_minute.setdefault(quand, []).append((ask - bid, (ask + bid) / 2.0))
    out = {}
    for minute, vals in par_minute.items():
        sp = [v[0] for v in vals]
        out[minute] = {
            "n": len(vals),
            "spread_min": min(sp),
            "spread_med": statistics.median(sp),
            "spread_max": max(sp),
            "mid_med": statistics.median([v[1] for v in vals]),
            # ⛔ On MARQUE, on ne jette pas. Un spread de marche FLUCTUE ; un
            # spread constant est une cotation qui ne se met plus a jour.
            # Mais sur une minute calme min == max reste legitime : c'est une
            # SUSPICION, levee au moment de mesurer.
            "spread_constant": 1 if (len(vals) >= 10
                                     and min(sp) == max(sp)) else 0,
        }
    return out


def _marche_ouvert(pair: str) -> int | None:
    try:
        from backend.services.market_hours import is_market_open_for
        return 1 if is_market_open_for(pair) else 0
    except Exception as e:  # noqa: BLE001
        logger.warning("etat du marche indeterminable pour %s : %s", pair, e)
        return None            # ⛔ inconnu = NULL, jamais 0


def collecter_paire(c: sqlite3.Connection, url: str, cle: str,
                    pair: str, minutes: int) -> tuple[int, int]:
    """Rend `(minutes_ecrites, ticks_lus)`."""
    fin = dt.datetime.now(dt.timezone.utc).replace(second=0, microsecond=0)
    # ⛔ La minute EN COURS est exclue : elle serait partielle, et figee.
    derniere = derniere_minute(c, pair)
    if derniere:
        debut = dt.datetime.fromisoformat(derniere + ":00").replace(
            tzinfo=dt.timezone.utc) + dt.timedelta(minutes=1)
    else:
        debut = fin - dt.timedelta(minutes=minutes)
    if (fin - debut) > dt.timedelta(minutes=FENETRE_MAX_MIN):
        debut = fin - dt.timedelta(minutes=FENETRE_MAX_MIN)
    if debut >= fin:
        return 0, 0

    r = httpx.get(url.rstrip("/") + "/ticks", headers={"X-API-Key": cle},
                  timeout=60,
                  params={"pair": pair, "from": debut.isoformat(),
                          "to": fin.isoformat()})
    r.raise_for_status()
    charge = r.json()
    ticks = charge.get("ticks") or []
    point = charge.get("point")
    ouvert = _marche_ouvert(pair)

    # ⛔ L'invariant « jamais la minute en cours » s'applique ICI, pas chez la
    # source. Demander `to=debut_de_la_minute` ne suffit pas : rien ne garantit
    # que le pont borne exactement comme nous, et un test l'a montre. Une
    # minute partielle ecrite une fois serait FIGEE par le `INSERT OR IGNORE`
    # des passages suivants -- donc fausse pour toujours.
    minute_en_cours = fin.isoformat()[:16]
    ecrites = 0
    for minute, a in agreger(ticks).items():
        if minute >= minute_en_cours:
            continue
        cur = c.execute(
            "INSERT OR IGNORE INTO spread_minute "
            " (pair, minute, n, spread_min, spread_med, spread_max, mid_med,"
            "  point, marche_ouvert, spread_constant)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (pair, minute, a["n"], a["spread_min"], a["spread_med"],
             a["spread_max"], a["mid_med"], point, ouvert,
             a["spread_constant"]))
        ecrites += cur.rowcount or 0
    return ecrites, len(ticks)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--minutes", type=int, default=120,
                    help="fenetre au PREMIER passage, quand le magasin est vide")
    ap.add_argument("--paires", default=None,
                    help="liste separee par des virgules")
    ap.add_argument("--magasin", default=MAGASIN)
    a = ap.parse_args(argv)

    sys.path.insert(0, "/app")
    try:
        from config.settings import (MT5_BRIDGE_LIVE_URL,
                                     MT5_BRIDGE_LIVE_API_KEY)
    except Exception as e:  # noqa: BLE001
        print("ECHEC : configuration illisible (%s)" % e)
        return 2
    if not MT5_BRIDGE_LIVE_URL or not MT5_BRIDGE_LIVE_API_KEY:
        print("ECHEC : pont admin_live non configure -- rien n'est collecte")
        return 2

    paires = ([p.strip() for p in a.paires.split(",") if p.strip()]
              if a.paires else PAIRES_DEFAUT)
    with sqlite3.connect(a.magasin) as c:
        _schema(c)
        total_min = total_ticks = 0
        for pair in paires:
            try:
                m, t = collecter_paire(c, MT5_BRIDGE_LIVE_URL,
                                       MT5_BRIDGE_LIVE_API_KEY, pair,
                                       a.minutes)
            except Exception as e:  # noqa: BLE001
                # ⛔ Une paire fautive ne doit pas couter les autres.
                print("   %-9s ECHEC %s: %s" % (pair, type(e).__name__, e))
                continue
            total_min += m
            total_ticks += t
            etat = {1: "ouvert", 0: "FERME", None: "inconnu"}[_marche_ouvert(pair)]
            print("   %-9s %4d minute(s) ecrite(s)  %6d tick(s) lus  "
                  "marche %s" % (pair, m, t, etat))
        print()
        print("TOTAL : %d minute(s), %d tick(s) lus, magasin %s"
              % (total_min, total_ticks, a.magasin))
    return 0


if __name__ == "__main__":
    sys.exit(main())
