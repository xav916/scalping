#!/usr/bin/env python3
"""Veille du WTI sur l'argent reel, armee le 2026-10-03 a la demande de Xavier.

⛔ POURQUOI. Le WTI a ete rouvert en AUTO_EXEC sur `admin_live` CONTRE la
mesure du jour : le banc pre-inscrit (`2f1bb55`, verdicts `cf15d13` et
`e134d7c`) n'a retenu aucune cellule sur 493, et l'historique reel de la paire
est de -20,61 % puis -28,05 % sur 30 trades. Aucune regle d'arret n'a ete
posee. Cette veille ne decide rien : elle DIT ce qui se passe.

🔑 Deux choses peuvent refermer le WTI sans que personne n'y touche, et ce sont
elles qu'on surveille en premier :
  1. le regulateur de P&L par paire met en pause a -10 %. Le WTI entre dans la
     semaine avec 5 trades reportes et -4,96 % deja consommes ; le regulateur
     commence a juger au 10e trade ;
  2. tout redeploiement ferme l'execution (REM-002 lie l'armement a l'empreinte
     du commit). Sans rearmement, rien ne trade — WTI compris.

Mode EVENEMENT (defaut) : n'envoie un message QUE si quelque chose a change.
Mode --resume : envoie l'etat complet, meme si rien n'a bouge.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ETAT = Path(os.getenv("VEILLE_WTI_ETAT", "/app/data/veille_wti_etat.json"))
PAIRE = "WTI/USD"
DEST = "admin_live"
# L'ouverture du marche WTI pour admin_live, mesuree : dimanche 23:00 UTC.
OUVERTURE = datetime(2026, 10, 4, 23, 0, tzinfo=timezone.utc)


def _etat_lu() -> dict:
    try:
        return json.loads(ETAT.read_text())
    except Exception:  # noqa: BLE001 — premier passage, ou fichier abime
        return {}


def _etat_ecrit(d: dict) -> None:
    try:
        ETAT.parent.mkdir(parents=True, exist_ok=True)
        ETAT.write_text(json.dumps(d, indent=2, default=str))
    except Exception as e:  # noqa: BLE001
        print(f"veille_wti: etat non ecrit ({e})", file=sys.stderr)


def _execution() -> dict:
    from backend.services.global_execution_switch import execution_allowed
    v = execution_allowed()
    return {"autorisee": bool(v.allowed), "motif": v.reason_code,
            "arme": v.fingerprint_armed, "tourne": v.fingerprint_running}


def _admission() -> dict:
    from backend.services.pair_admission_controller import get_current_state
    return {s: get_current_state(PAIRE, direction=s, destination=DEST)
            for s in ("buy", "sell")}


def _regulateur() -> dict:
    from backend.services.pair_pnl_regulator import evaluate_pair
    r = evaluate_pair(PAIRE, DEST)
    m = r.get("metrics") or {}
    return {"action": r.get("action"), "motif": r.get("reason"),
            "n": m.get("n"), "euros": m.get("sum_pnl"),
            "pct_r": m.get("pnl_pct"), "pct_euros": m.get("pnl_pct_euros"),
            "wr": m.get("wr")}


def _db() -> str:
    from backend.services.pair_admission_controller import _db_path
    return _db_path()


def _ordres() -> list[dict]:
    """Les ordres WTI pousses depuis l'ouverture."""
    with sqlite3.connect(_db()) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute(
            "SELECT id, pushed_at, direction, horizon, pattern, ok, "
            "mt5_ticket, entry_price_5dp, destination_id, "
            "substr(COALESCE(bridge_response,''),1,120) AS reponse "
            "FROM mt5_pushes WHERE pair = ? AND pushed_at >= ? "
            "ORDER BY id", (PAIRE, OUVERTURE.isoformat()))]


def _refus() -> list[tuple[str, int]]:
    """Les motifs de refus WTI depuis l'ouverture, les plus frequents d'abord."""
    with sqlite3.connect(_db()) as c:
        return [(r[0], r[1]) for r in c.execute(
            "SELECT reason_code, COUNT(*) FROM signal_rejections "
            "WHERE pair = ? AND created_at >= ? "
            "GROUP BY reason_code ORDER BY COUNT(*) DESC LIMIT 6",
            (PAIRE, OUVERTURE.isoformat()))]


def _tick() -> dict | None:
    """Le spread et la divergence VIVANTS, si le marche est ouvert."""
    try:
        import urllib.parse
        import urllib.request
        from backend.services import bridge_tick_validator as btv
        from backend.services.bridge_destinations import admin_destinations
        d = [x for x in admin_destinations() if x.destination_id == DEST][0]
        url = (f"{d.bridge_url.rstrip('/')}/tick/"
               f"{urllib.parse.quote(PAIRE, safe='')}")
        with urllib.request.urlopen(urllib.request.Request(
                url, headers=btv._auth_header(d)), timeout=10) as r:
            t = json.load(r)
        bid, ask = float(t.get("bid") or 0), float(t.get("ask") or 0)
        if bid <= 0 or ask <= 0:
            return None
        mid = (bid + ask) / 2
        return {"mid": round(mid, 4),
                "spread_pct": round((ask - bid) / mid * 100, 4),
                "spread_max_pct": btv._max_spread_pct_for(PAIRE)}
    except Exception as e:  # noqa: BLE001 — marche ferme, pont muet : on ne sait pas
        return {"erreur": f"{type(e).__name__}"}


def _marche_ouvert() -> bool:
    try:
        from backend.services.market_hours import is_market_open_for_destination
        return bool(is_market_open_for_destination(PAIRE, DEST))
    except Exception:  # noqa: BLE001
        return False


def releve() -> dict:
    ordres = _ordres()
    return {
        "a": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "marche_ouvert": _marche_ouvert(),
        "execution": _execution(),
        "admission": _admission(),
        "regulateur": _regulateur(),
        "ordres": ordres,
        "dernier_ordre_id": max((o["id"] for o in ordres), default=0),
        "refus": _refus(),
        "tick": _tick(),
    }


def evenements(avant: dict, apres: dict) -> list[str]:
    """Ce qui a CHANGE et qui vaut un message. Vide = on se taît."""
    ev: list[str] = []
    if not avant:
        return ["veille armée"]

    a, b = avant.get("dernier_ordre_id", 0), apres["dernier_ordre_id"]
    if b > a:
        neufs = [o for o in apres["ordres"] if o["id"] > a]
        ev.append(f"{len(neufs)} ordre(s) WTI poussé(s)")

    ra = (avant.get("regulateur") or {}).get("action")
    rb = apres["regulateur"]["action"]
    if ra != rb:
        ev.append(f"régulateur : {_e(ra)} → <b>{_e(rb)}</b>")

    for sens in ("buy", "sell"):
        xa = (avant.get("admission") or {}).get(sens)
        xb = apres["admission"][sens]
        if xa != xb:
            ev.append(f"admission {sens} : {_e(xa)} → <b>{_e(xb)}</b>")

    ea = (avant.get("execution") or {}).get("autorisee")
    eb = apres["execution"]["autorisee"]
    if ea != eb:
        ev.append("exécution " + ("RÉOUVERTE" if eb
                                  else f"<b>FERMÉE</b> ({_e(apres['execution']['motif'])})"))

    if not avant.get("marche_ouvert") and apres["marche_ouvert"]:
        ev.append("marché WTI OUVERT")
    return ev


def _e(x) -> str:
    """Tout texte venu de la BASE passe par ici avant d'entrer dans le message.

    ⛔ DEFAUT REEL, attrape au 1er envoi du 2026-10-03 :
        send_infra_text: HTTP 400 "can't parse entities: Unsupported start tag"
    Le motif du regulateur vaut litteralement << sample too small (n=5 < 10) >>.
    Telegram lit le `<` comme un debut de balise et REFUSE tout le message.

    🔑 La veille serait restee MUETTE toute la semaine, l'echec ne vivant que
    dans un log que personne ne lit. Un moniteur qui echoue en silence est pire
    que pas de moniteur : il rassure.
    """
    import html
    return html.escape(str(x), quote=False)


def message(r: dict, ev: list[str]) -> str:
    L = ["<b>VEILLE WTI — argent réel IC Markets</b>"]
    if ev:
        L.append("⚡ " + " · ".join(ev))
    L.append("")

    e = r["execution"]
    L.append(f"exécution : {'ALLOW' if e['autorisee'] else '⛔ ' + _e(e['motif'])}"
             f"  (armé {_e(e['arme'])}, tourne {_e(e['tourne'])})")
    L.append(f"admission : achat {_e(r['admission']['buy'])} · "
             f"vente {_e(r['admission']['sell'])}")
    L.append(f"marché : {'ouvert' if r['marche_ouvert'] else 'fermé'}")

    g = r["regulateur"]
    L.append("")
    L.append("<b>régulateur de P&amp;L</b> — pause à -10 %")
    L.append(f"  {_e(g['action'])} · {_e(g['motif'])}")
    L.append(f"  n={_e(g['n'])} · {_e(g['euros'])} € · {_e(g['pct_r'])} % en R "
             f"· wr {_e(g['wr'])} %")

    t = r.get("tick") or {}
    if "spread_pct" in t:
        L.append("")
        L.append(f"<b>tick vivant</b> — prix {_e(t['mid'])} · spread "
                 f"{_e(t['spread_pct'])} % (plafond {_e(t['spread_max_pct'])} %)")

    L.append("")
    if r["ordres"]:
        L.append(f"<b>{len(r['ordres'])} ordre(s) WTI depuis l'ouverture</b>")
        for o in r["ordres"][-5:]:
            L.append(f"  {_e(str(o['pushed_at'])[:16])} {_e(o['direction'])} "
                     f"{_e(o['horizon'])} {_e(o['pattern'])} · "
                     f"{'OK' if o['ok'] else 'ÉCHEC'} ticket {_e(o['mt5_ticket'])}")
    else:
        L.append("<b>aucun ordre WTI</b> depuis l'ouverture")

    if r["refus"]:
        L.append("")
        L.append("<b>motifs de refus WTI</b> (depuis l'ouverture)")
        for motif, n in r["refus"]:
            L.append(f"  {_e(motif)} : {_e(n)}")

    L.append("")
    L.append("⛔ Rappel : le banc n'a retenu aucune cellule sur 493, et aucune "
             "règle d'arrêt n'est posée. Le régulateur à -10 % est le seul "
             "garde automatique.")
    return "\n".join(L)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--resume", action="store_true",
                   help="envoie l'etat complet meme si rien n'a change")
    p.add_argument("--sec", action="store_true",
                   help="n'envoie rien, affiche seulement")
    a = p.parse_args()

    avant = _etat_lu()
    r = releve()
    ev = evenements(avant, r)
    _etat_ecrit(r)

    if not ev and not a.resume:
        print(f"veille_wti: rien de neuf ({r['a']})")
        return 0

    txt = message(r, ev)
    if a.sec:
        print(txt)
        return 0
    from backend.services.telegram_service import send_infra_text
    ok = asyncio.run(send_infra_text(txt))
    if not ok:
        # ⛔ REPLI EN TEXTE BRUT. Le 2026-10-03, le tout premier envoi a ete
        # refuse par un HTTP 400 — un `<` dans un motif venu de la base. La
        # cause est corrigee (`_e`), mais le principe reste : un moniteur qui
        # echoue en silence est PIRE que pas de moniteur, parce qu'il rassure.
        # Une balise mal formee ne doit plus jamais couter le message entier.
        import re
        brut = re.sub(r"</?b>", "", txt).replace("&amp;", "&")
        brut = "[repli texte brut — l'envoi HTML a echoue]\n" + brut
        ok = asyncio.run(send_infra_text(brut, parse_mode="plain"))
        print(f"veille_wti: HTML refuse, repli brut {'OK' if ok else 'ECHEC'}",
              file=sys.stderr)
    print(f"veille_wti: envoi {'OK' if ok else 'ECHEC'} — {' · '.join(ev) or 'resume'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
