#!/usr/bin/env python3
"""Sonde horaire du calendrier : ForexFactory nous donne-t-il le chiffre PUBLIE ?

## La question, et pourquoi elle est la seule qui compte

Mesure du 2026-10-04 sur la base de production :

    220 evenements · 116 avec PREVISION · 150 avec PRECEDENTE · 0 avec ACTUEL

Zero chiffre publie, jamais. Or la PREVISION seule ne predit rien : c'est le
consensus des economistes, public des jours a l'avance, donc **deja dans le
prix**. Ce qui peut faire bouger un cours, c'est la SURPRISE — l'ecart entre
le chiffre publie et ce consensus. Sans `actual`, elle est incalculable.

⛔ Et le flux ne semble pas la fournir : `ff_calendar_thisweek.json` couvre une
fenetre qui GLISSE vers l'avant (04/10 -> 09/10 au moment de la mesure), avec
UN seul evenement deja passe, sans chiffre. `lastweek.json` et
`nextweek.json` repondent **404**.

⚠️ Mais un seul evenement passe un DIMANCHE ne prouve rien. Cette sonde
synchronise toutes les heures et **parle le jour ou un `actual` apparait**.
Lundi est charge en publications : on saura mardi.

## Ce qu'elle ne fait pas

⛔ Elle n'ecrit pas dans le calendrier autrement qu'en appelant
`refresh_calendar()` — un test lit sa source et refuse tout INSERT/UPDATE/
DELETE. Une sonde qui ecrit dans ce qu'elle observe ne mesure plus rien.

🔑 **Aucun redeploiement.** Elle tourne par `docker exec` depuis un cron de
l'hote, comme la veille WTI : pas de rebuild, donc REM-002 reste arme.

## Mode EVENEMENT

Elle se tait tant que rien ne change. Une sonde qui parle 24 fois par jour
pour dire « toujours rien » n'est plus lue au bout de deux jours.
"""
from __future__ import annotations

import asyncio
import html
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DB = os.getenv("SONDE_CAL_DB", "/app/data/scalping.db")
ETAT = Path(os.getenv("SONDE_CAL_ETAT", "/app/data/sonde_calendrier.json"))


# ─── Mesure ─────────────────────────────────────────────────────────────────

def mesurer(db) -> dict | None:
    """Compte les evenements et, separement, ceux qui portent chaque chiffre.

    ⛔ Rend `None` si la base est injoignable. Trois etats, jamais deux :
    confondre « aucun chiffre » et « je n'ai pas pu regarder » est exactement
    le defaut que `event_blackout` a paye.
    """
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as c:
            t, f, p, a = c.execute(
                "SELECT COUNT(*), SUM(forecast IS NOT NULL), "
                " SUM(previous IS NOT NULL), SUM(actual IS NOT NULL) "
                "FROM economic_events").fetchone()
    except Exception:  # noqa: BLE001
        return None
    return {"total": int(t or 0), "forecast": int(f or 0),
            "previous": int(p or 0), "actual": int(a or 0)}


def nouveaux_actuels(db, etat: dict) -> list[dict]:
    """Les evenements qui portent un chiffre publie et qu'on n'avait pas vus."""
    vus = set(etat.get("vus") or [])
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as c:
            c.row_factory = sqlite3.Row
            lignes = c.execute(
                "SELECT id, ts_utc, currency, event_name, actual, forecast "
                "FROM economic_events WHERE actual IS NOT NULL "
                "ORDER BY ts_utc").fetchall()
    except Exception:  # noqa: BLE001
        return []
    return [dict(l) for l in lignes if l["id"] not in vus]


def etat_suivant(etat: dict, neufs: list[dict]) -> dict:
    """⚠️ Le curseur ne recule JAMAIS : un oubli reannoncerait un vieux chiffre
    comme une decouverte."""
    vus = set(etat.get("vus") or []) | {n["id"] for n in neufs}
    return {"vus": sorted(vus)}


# ─── Message ────────────────────────────────────────────────────────────────

def _e(x) -> str:
    """Tout texte venu de la BASE passe par ici.

    ⛔ Defaut reel du 2026-10-03 : le 1er envoi de la veille WTI a ete refuse
    en HTTP 400 parce qu'un motif valait litteralement
    `sample too small (n=5 < 10)` — Telegram lit le `<` comme une balise et
    REFUSE tout le message. Un nom d'evenement peut contenir `<` ou `&`
    (« CPI M/M & Y/Y »).
    """
    return html.escape(str(x), quote=False)


def _ecart(actual: str | None, forecast: str | None) -> str:
    """La surprise, quand elle est calculable.

    ⚠️ Les valeurs ForexFactory sont du TEXTE : « 9.0K », « 6.4% », « <0.1 ».
    On affiche sans calculer plutot que de lever.
    """
    try:
        return f" · surprise <b>{float(actual) - float(forecast):+.4g}</b>"
    except (TypeError, ValueError):
        return ""


def message(neufs: list[dict], m: dict | None) -> str:
    lignes = ["<b>📅 Le calendrier livre enfin un chiffre PUBLIÉ</b>", ""]
    for n in neufs[:12]:
        lignes.append(
            f"• {_e(n['ts_utc'][:16])} {_e(n['currency'])} "
            f"<b>{_e(n['event_name'])}</b>")
        lignes.append(
            f"   réel <b>{_e(n['actual'])}</b> · prévision "
            f"{_e(n['forecast'] or '—')}{_ecart(n['actual'], n['forecast'])}")
    if len(neufs) > 12:
        lignes.append(f"… et {len(neufs) - 12} autres")
    if m:
        lignes += ["", f"base : {m['total']} évènements · {m['forecast']} avec "
                       f"prévision · <b>{m['actual']} avec le réel</b>"]
    lignes += ["", "🔑 La surprise (réel − prévision) devient calculable. "
                   "⛔ Cela ne valide aucune hypothèse : elle devra être "
                   "pré-enregistrée puis passée au banc."]
    return "\n".join(lignes)


# ─── Effets de bord, isoles pour que les tests les remplacent ───────────────

def _synchroniser() -> int:
    from backend.services.economic_calendar_service import refresh_calendar
    return refresh_calendar()


def _envoyer(txt: str) -> bool:
    from backend.services.telegram_service import send_infra_text
    ok = asyncio.run(send_infra_text(txt))
    if not ok:
        # ⛔ Repli en texte brut. Une balise mal formee ne doit jamais couter
        # le message entier : un moniteur qui echoue en silence est PIRE que
        # pas de moniteur, parce qu'il rassure.
        import re
        brut = re.sub(r"</?b>", "", txt).replace("&amp;", "&")
        ok = asyncio.run(send_infra_text(
            "[repli texte brut — l'envoi HTML a echoue]\n" + brut,
            parse_mode="plain"))
    return bool(ok)


def _etat_lu() -> dict:
    try:
        return json.loads(ETAT.read_text())
    except Exception:  # noqa: BLE001 — 1er passage, ou fichier abime
        return {}


def _etat_ecrit(d: dict) -> None:
    try:
        ETAT.parent.mkdir(parents=True, exist_ok=True)
        ETAT.write_text(json.dumps(d, indent=2))
    except Exception as e:  # noqa: BLE001
        print(f"sonde_calendrier: etat non ecrit ({e})", file=sys.stderr)


def main() -> int:
    try:
        n = _synchroniser()
    except Exception as e:  # noqa: BLE001
        # ⚠️ Une panne de synchro ne doit pas emporter la MESURE : un chiffre
        # a pu arriver au passage precedent.
        n = -1
        print(f"sonde_calendrier: synchro en echec ({e})", file=sys.stderr)

    m = mesurer(DB)
    etat = _etat_lu()
    neufs = nouveaux_actuels(DB, etat)

    if not neufs:
        print(f"sonde_calendrier: aucun chiffre publié "
              f"(synchro {n}, base {m['actual'] if m else '?'} actuels)")
        return 0

    ok = _envoyer(message(neufs, m))
    _etat_ecrit(etat_suivant(etat, neufs))
    print(f"sonde_calendrier: {len(neufs)} chiffre(s) publié(s) — "
          f"envoi {'OK' if ok else 'ECHEC'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
