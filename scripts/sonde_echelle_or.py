#!/usr/bin/env python3
"""Témoin EXTÉRIEUR de l'échelle de stop : rendre vérifiable « c'est passé
au-dessus d'1 € ».

    python scripts/sonde_echelle_or.py              # une boucle de ~55 s, pas de 5 s
    python scripts/sonde_echelle_or.py --une-passe  # un seul echantillon
    python scripts/sonde_echelle_or.py --bilan      # affiche le suivi, n'observe pas

## ⛔ POURQUOI ELLE EXISTE

Xavier, le 2026-10-09 : « Pourquoi les SL n'ont pas évolué car les trades sont
passés au-delà d'1 € ». **Je n'ai pas pu repondre** : quand l'echelle decide de
ne rien faire, elle ne journalise RIEN — zero ligne en 30 minutes. Sa question
restait un DESACCORD au lieu d'etre une MESURE.

Et la limite est reelle : l'echelle sonde toutes les **15 s** alors que ses
paliers sont espaces d'environ 0,28 $ sur l'or. Un pic qui franchit +1 € et
redescend entre deux sondages est **invisible**.

## 🔑 UN TEMOIN EXTERIEUR, ET NON UN JOURNAL DE L'ECHELLE

Une echelle qui rend compte d'elle-meme ne peut pas prouver qu'elle n'a rien
rate : elle ne voit que ce qu'elle a regarde. Cette sonde echantillonne **plus
vite** (5 s contre 15 s) et conserve le **maximum vu**. Si un palier a ete
franchi sans que le stop bouge, c'est elle qui le dira.

🔑 Et elle **n'est pas installee par rebuild** : `docker cp` + cron, comme les
autres veilleurs. Un rebuild desarmerait REM-002 — ce qui a coute six heures de
marche le 07/10.

## ⚠️ Ce qu'elle REUTILISE au lieu de le recopier

Le jugement vient de `echelle_stop_or` : `MARQUE_RADAR` et `palier_atteint()`.
Une copie de la regle dériverait en silence le jour ou les paliers changent —
piege deja paye deux fois dans ce depot.

## Ce qu'elle enregistre, et pourquoi chaque colonne

| colonne | a quoi elle repond |
|---|---|
| `profit_max_eur` / `profit_max_a` | « est-ce VRAIMENT passe au-dessus d'1 € ? » |
| `palier_max_eur` | « quel palier a ete franchi ? » |
| `sl_au_max` / `sl_dernier` | « le stop a-t-il bouge APRES ? » |
| `suivie` / `motif` | « cette position est-elle meme prise en charge ? » |
| `vu_n` | « combien de fois a-t-on regarde ? » (une sonde muette se voit) |
"""
from __future__ import annotations

import logging
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, "/app")

logger = logging.getLogger("sonde_echelle_or")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

DUREE_SEC = int(os.environ.get("SONDE_ECHELLE_DUREE_SEC", "55"))
PAS_SEC = float(os.environ.get("SONDE_ECHELLE_PAS_SEC", "5"))


def _db_path() -> str:
    from backend.services.mt5_sync import _db_path as p
    return p()


def _assurer_table(c: sqlite3.Connection) -> None:
    c.execute("""
        CREATE TABLE IF NOT EXISTS echelle_or_suivi (
            ticket              INTEGER PRIMARY KEY,
            symbol              TEXT,
            sens                TEXT,
            entree              REAL,
            suivie              INTEGER NOT NULL DEFAULT 0,
            motif               TEXT DEFAULT '',
            profit_max_eur      REAL,
            profit_max_a        TEXT,
            palier_max_eur      REAL,
            sl_au_max           REAL,
            profit_dernier_eur  REAL,
            sl_dernier          REAL,
            vu_n                INTEGER NOT NULL DEFAULT 0,
            vu_dernier_a        TEXT
        )
    """)


def observer(positions: list[dict], taux_eur_usd: float) -> int:
    """Un echantillon. Rend le nombre de positions enregistrees.

    ⛔ Ne leve jamais : appelee en boucle sur des donnees du courtier.
    """
    if not taux_eur_usd or taux_eur_usd <= 0:
        # ⛔ Sans le taux, les euros sont inconvertibles. On ne devine pas un
        # profit sur de l'argent reel.
        logger.warning("sonde echelle : taux EUR/USD illisible (%r) — "
                       "aucune observation", taux_eur_usd)
        return 0

    from backend.services import echelle_stop_or as E

    maintenant = datetime.now(timezone.utc).isoformat()
    enregistrees = 0

    for p in positions or []:
        ticket = p.get("ticket")
        try:
            sym = str(p.get("symbol") or "").upper()
            if "XAU" not in sym and "GOLD" not in sym:
                continue
            sens = str(p.get("type") or "").lower()
            entree = float(p.get("price_open"))
            courant = float(p.get("price_current"))
            if sens not in ("buy", "sell") or entree <= 0 or courant <= 0:
                raise ValueError("sens ou prix hors domaine")
            sl = p.get("sl")
            sl = float(sl) if sl else None
        except Exception as e:  # noqa: BLE001
            # ⛔ Ecartee ET DITE. Une position illisible passee en silence
            # ferait croire a une sonde complete.
            logger.warning("sonde echelle : position %s illisible (%s: %s) — "
                           "ecartee", ticket, type(e).__name__, e)
            continue

        # 🔑 Le profit se compte depuis le PRIX, comme le fait l'echelle.
        signe = 1 if sens == "buy" else -1
        profit_eur = signe * (courant - entree) / taux_eur_usd

        # 🔑 Le jugement vient de l'echelle, jamais d'une copie de sa regle.
        suivie = E.MARQUE_RADAR in str(p.get("comment") or "")
        motif = "" if suivie else (
            "position ouverte A LA MAIN : elle ne porte pas la marque "
            f"{E.MARQUE_RADAR!r}, l'echelle ne la suit pas")
        palier = E.palier_atteint(profit_eur)

        try:
            with sqlite3.connect(_db_path()) as c:
                _assurer_table(c)
                c.execute("""
                    INSERT INTO echelle_or_suivi
                      (ticket, symbol, sens, entree, suivie, motif,
                       profit_max_eur, profit_max_a, palier_max_eur, sl_au_max,
                       profit_dernier_eur, sl_dernier, vu_n, vu_dernier_a)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,?)
                    ON CONFLICT (ticket) DO UPDATE SET
                      suivie = excluded.suivie,
                      motif  = excluded.motif,
                      -- ⛔ LE CŒUR DE LA SONDE : le maximum ne REDESCEND
                      -- jamais. Sans ce `CASE`, un repli effacerait la preuve
                      -- que le palier avait ete franchi — exactement ce qu'on
                      -- cherche a etablir.
                      profit_max_eur = CASE
                          WHEN excluded.profit_max_eur > echelle_or_suivi.profit_max_eur
                          THEN excluded.profit_max_eur
                          ELSE echelle_or_suivi.profit_max_eur END,
                      profit_max_a = CASE
                          WHEN excluded.profit_max_eur > echelle_or_suivi.profit_max_eur
                          THEN excluded.profit_max_a
                          ELSE echelle_or_suivi.profit_max_a END,
                      palier_max_eur = CASE
                          WHEN excluded.profit_max_eur > echelle_or_suivi.profit_max_eur
                          THEN excluded.palier_max_eur
                          ELSE echelle_or_suivi.palier_max_eur END,
                      sl_au_max = CASE
                          WHEN excluded.profit_max_eur > echelle_or_suivi.profit_max_eur
                          THEN excluded.sl_au_max
                          ELSE echelle_or_suivi.sl_au_max END,
                      profit_dernier_eur = excluded.profit_dernier_eur,
                      sl_dernier = excluded.sl_dernier,
                      vu_n = echelle_or_suivi.vu_n + 1,
                      vu_dernier_a = excluded.vu_dernier_a
                """, (int(ticket), sym, sens, entree, 1 if suivie else 0, motif,
                      profit_eur, maintenant, palier, sl,
                      profit_eur, sl, maintenant))
        except Exception as e:  # noqa: BLE001
            logger.warning("sonde echelle : ecriture du ticket %s echouee "
                           "(%s: %s)", ticket, type(e).__name__, e)
            continue

        enregistrees += 1

        # ⚠️ L'ALERTE QUI REPOND A LA QUESTION DE XAVIER. Un palier franchi sur
        # une position SUIVIE dont le stop est reste du cote de la perte.
        if suivie and palier is not None and sl is not None:
            du_cote_du_profit = (sl > entree) if sens == "buy" else (sl < entree)
            if not du_cote_du_profit:
                logger.warning(
                    "sonde echelle : ticket %s a atteint %+.2f EUR (palier "
                    "%+.2f) et son stop %s est ENCORE du cote de la perte "
                    "(entree %s). Si cela persiste au-dela de 15 s, l'echelle "
                    "n'a pas agi.", ticket, profit_eur, palier, sl, entree)

    return enregistrees


def _taux() -> float | None:
    from backend.services import echelle_stop_boucle as B
    try:
        return B._taux()
    except Exception as e:  # noqa: BLE001
        logger.warning("sonde echelle : taux illisible (%s)", e)
        return None


def _positions() -> list[dict] | None:
    import httpx
    base = (os.getenv("MT5_BRIDGE_LIVE_URL", "") or "").rstrip("/")
    cle = os.getenv("MT5_BRIDGE_LIVE_API_KEY", "") or ""
    if not base:
        return None
    try:
        r = httpx.get(base + "/positions", headers={"X-API-Key": cle}, timeout=8)
        if r.status_code != 200:
            logger.warning("sonde echelle : /positions a rendu %s", r.status_code)
            return None
        return (r.json() or {}).get("positions") or []
    except Exception as e:  # noqa: BLE001
        logger.warning("sonde echelle : pont muet (%s)", e)
        return None


def _bilan() -> None:
    try:
        with sqlite3.connect(_db_path()) as c:
            c.row_factory = sqlite3.Row
            _assurer_table(c)
            lignes = list(c.execute(
                "SELECT * FROM echelle_or_suivi ORDER BY vu_dernier_a DESC LIMIT 12"))
    except Exception as e:  # noqa: BLE001
        print(f"bilan illisible : {e}")
        return
    if not lignes:
        print("aucune position suivie pour l'instant")
        return
    for r in lignes:
        suivie = "SUIVIE" if r["suivie"] else "non suivie"
        print(f"ticket {r['ticket']} {r['sens']} entree {r['entree']} [{suivie}]")
        print(f"   max vu     : {r['profit_max_eur']:+.2f} EUR a "
              f"{str(r['profit_max_a'])[11:19]}   palier "
              f"{r['palier_max_eur'] if r['palier_max_eur'] is not None else '-'}")
        print(f"   sl au max  : {r['sl_au_max']}        sl maintenant : {r['sl_dernier']}")
        print(f"   dernier    : {r['profit_dernier_eur']:+.2f} EUR   "
              f"({r['vu_n']} observations)")
        if r["motif"]:
            print(f"   ⛔ {r['motif']}")


def main() -> int:
    if "--bilan" in sys.argv:
        _bilan()
        return 0

    taux = _taux()
    une = "--une-passe" in sys.argv
    fin = time.monotonic() + (0 if une else DUREE_SEC)
    passes = total = 0
    while True:
        pos = _positions()
        if pos is not None:
            total += observer(pos, taux or 0)
            passes += 1
        if une or time.monotonic() >= fin:
            break
        time.sleep(PAS_SEC)
    print(f"sonde echelle : {passes} passage(s), {total} observation(s), "
          f"pas {PAS_SEC:.0f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
