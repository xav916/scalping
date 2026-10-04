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
# ⚠️ PLUSIEURS paires depuis le 2026-10-04, a la demande de Xavier apres
# l'ouverture de BTC et ETH au reel. Le defaut garde le WTI : si le reglage
# disparait, la veille deja armee ne cesse pas de surveiller.
PAIRES: tuple[str, ...] = tuple(
    x.strip() for x in os.getenv(
        "VEILLE_PAIRES", "WTI/USD,BTC/USD,ETH/USD").split(",") if x.strip())
DEST = "admin_live"
# ⛔ FENETRE GLISSANTE, pas une date en dur. La premiere version portait
# `datetime(2026, 10, 4, 23, 0)` — l'ouverture du marche WTI — et cette date
# est devenue le FUTUR : la veille comptait donc zero ordre et zero refus pour
# toutes les paires, en ayant l'air de surveiller. Xavier l'a vu avant moi
# (<< il n'y a toujours pas de trade >>) alors que la production refusait
# 300 signaux par heure.
#
# 🔑 Une veille ne doit jamais dependre d'une date ecrite a la main : elle
# regarde les dernieres N heures, quelle que soit la date du jour.
HEURES_FENETRE = int(os.getenv("VEILLE_HEURES", "6"))


def _depuis() -> str:
    return (datetime.now(timezone.utc)
            - timedelta(hours=HEURES_FENETRE)).isoformat()


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


def _admission(PAIRE: str) -> dict:
    from backend.services.pair_admission_controller import get_current_state
    return {s: get_current_state(PAIRE, direction=s, destination=DEST)
            for s in ("buy", "sell")}


def _regulateur(PAIRE: str) -> dict:
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


def _ordres(PAIRE: str) -> list[dict]:
    """Les ordres WTI pousses depuis l'ouverture."""
    with sqlite3.connect(_db()) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute(
            "SELECT id, pushed_at, direction, horizon, pattern, ok, "
            "mt5_ticket, entry_price_5dp, destination_id, "
            "substr(COALESCE(bridge_response,''),1,120) AS reponse "
            "FROM mt5_pushes WHERE pair = ? AND pushed_at >= ? "
            "ORDER BY id", (PAIRE, _depuis()))]


def _refus(PAIRE: str) -> list[tuple[str, int]]:
    """Les motifs de refus sur NOTRE destination, les plus frequents d'abord.

    ⛔ FILTRE PAR DESTINATION, et il n'y etait pas. La premiere version comptait
    toutes les destinations : la veille annoncait << ETH : pair_not_whitelisted
    x672 >> alors que ces refus venaient de la DEMO, dont la liste blanche est
    une autre et n'a jamais ete ouverte. Un moniteur qui melange les comptes
    fait chercher un defaut la ou il n'y en a pas.
    """
    with sqlite3.connect(_db()) as c:
        return [(r[0], r[1]) for r in c.execute(
            "SELECT reason_code, COUNT(*) FROM signal_rejections "
            "WHERE pair = ? AND created_at >= ? AND destination_id = ? "
            "GROUP BY reason_code ORDER BY COUNT(*) DESC LIMIT 6",
            (PAIRE, _depuis(), DEST))]


def _tick(PAIRE: str) -> dict | None:
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


def _marche_ouvert(PAIRE: str) -> bool:
    try:
        from backend.services.market_hours import is_market_open_for_destination
        return bool(is_market_open_for_destination(PAIRE, DEST))
    except Exception:  # noqa: BLE001
        return False


def releve_paire(pair: str) -> dict:
    """Le releve d'UNE paire. ⚠️ Un echec sur une paire ne doit pas emporter
    les autres : c'est la lecon du backfill d'admission du 02/10."""
    ordres = _ordres(pair)
    return {
        "marche_ouvert": _marche_ouvert(pair),
        "admission": _admission(pair),
        "regulateur": _regulateur(pair),
        "ordres": ordres,
        "dernier_ordre_id": max((o["id"] for o in ordres), default=0),
        "refus": _refus(pair),
        "tick": _tick(pair),
    }


def releve() -> dict:
    """L'etat complet : l'execution une fois, puis une entree PAR PAIRE."""
    paires = {}
    for pair in PAIRES:
        try:
            paires[pair] = releve_paire(pair)
        except Exception as e:  # noqa: BLE001
            paires[pair] = {"erreur": f"{type(e).__name__}: {e}"[:120]}
    return {
        "a": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "execution": _execution(),
        "paires": paires,
    }


def evenements_paire(pair: str, avant: dict, apres: dict) -> list[str]:
    """Ce qui a change POUR UNE PAIRE et vaut un message."""
    ev: list[str] = []
    if "erreur" in apres:
        return [f"{pair} : ⛔ releve illisible ({_e(apres['erreur'])})"]

    a = (avant or {}).get("dernier_ordre_id", 0)
    b = apres.get("dernier_ordre_id", 0)
    if b > a:
        neufs = [o for o in apres["ordres"] if o["id"] > a]
        ok = sum(1 for o in neufs if o.get("ok"))
        ev.append(f"<b>{pair} : {len(neufs)} ordre(s)</b> ({ok} OK)")

    ra = ((avant or {}).get("regulateur") or {}).get("action")
    rb = (apres.get("regulateur") or {}).get("action")
    if avant and ra != rb:
        ev.append(f"{pair} régulateur : {_e(ra)} → <b>{_e(rb)}</b>")

    for sens in ("buy", "sell"):
        xa = ((avant or {}).get("admission") or {}).get(sens)
        xb = (apres.get("admission") or {}).get(sens)
        if avant and xa != xb:
            ev.append(f"{pair} admission {sens} : {_e(xa)} → <b>{_e(xb)}</b>")

    if avant and not (avant or {}).get("marche_ouvert")             and apres.get("marche_ouvert"):
        ev.append(f"{pair} : marché OUVERT")
    return ev


def evenements(avant: dict, apres: dict) -> list[str]:
    """Ce qui a CHANGE, toutes paires. Vide = on se taît."""
    if not avant:
        return ["veille armée sur " + ", ".join(sorted(apres.get("paires", {})))]

    ev: list[str] = []
    ea = (avant.get("execution") or {}).get("autorisee")
    eb = (apres.get("execution") or {}).get("autorisee")
    if ea != eb:
        ev.append("exécution " + ("RÉOUVERTE" if eb else
                  f"<b>FERMÉE</b> ({_e((apres.get('execution') or {}).get('motif'))})"))

    av, ap = avant.get("paires") or {}, apres.get("paires") or {}
    # ⚠️ Une paire AJOUTEE au reglage doit se signaler, sinon on croirait
    # qu'elle est surveillee depuis toujours.
    for pair in sorted(set(ap) - set(av)):
        ev.append(f"{pair} : <b>ajoutée à la veille</b>")
    for pair in sorted(ap):
        ev += evenements_paire(pair, av.get(pair) or {}, ap[pair])
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
    L = ["<b>VEILLE — argent réel IC Markets</b>"]
    if ev:
        L.append("⚡ " + " · ".join(ev))
    L.append("")

    e = r.get("execution") or {}
    L.append(f"exécution : {'ALLOW' if e.get('autorisee') else '⛔ ' + _e(e.get('motif'))}"
             f"  (armé {_e(e.get('arme'))}, tourne {_e(e.get('tourne'))})")

    for pair in sorted(r.get("paires") or {}):
        p = r["paires"][pair]
        L.append("")
        if "erreur" in p:
            L.append(f"<b>{_e(pair)}</b> — ⛔ relevé illisible : {_e(p['erreur'])}")
            continue
        adm = p.get("admission") or {}
        L.append(f"<b>{_e(pair)}</b> — marché "
                 f"{'ouvert' if p.get('marche_ouvert') else 'fermé'} · "
                 f"achat {_e(adm.get('buy'))} · vente {_e(adm.get('sell'))}")

        g = p.get("regulateur") or {}
        L.append(f"  régulateur (pause à -10 %) : {_e(g.get('action'))} · "
                 f"{_e(g.get('motif'))}")
        L.append(f"  n={_e(g.get('n'))} · {_e(g.get('euros'))} € · "
                 f"{_e(g.get('pct_r'))} % en R · wr {_e(g.get('wr'))} %")

        t = p.get("tick") or {}
        if "spread_pct" in t:
            L.append(f"  prix {_e(t['mid'])} · spread {_e(t['spread_pct'])} % "
                     f"(plafond {_e(t['spread_max_pct'])} %)")

        ordres = p.get("ordres") or []
        if ordres:
            L.append(f"  <b>{len(ordres)} ordre(s)</b> depuis l'ouverture :")
            for o in ordres[-4:]:
                L.append(f"    {_e(str(o['pushed_at'])[:16])} "
                         f"{_e(o['direction'])} {_e(o['horizon'])} "
                         f"{_e(o['pattern'])} · "
                         f"{'OK' if o['ok'] else 'ÉCHEC'} "
                         f"ticket {_e(o['mt5_ticket'])}")
        else:
            L.append("  aucun ordre depuis l'ouverture")

        refus = p.get("refus") or []
        if refus:
            L.append("  refus : " + " · ".join(
                f"{_e(m)} {_e(n)}" for m, n in refus[:4]))

    L.append("")
    L.append("⛔ Rappel : aucune règle d'arrêt. Le banc n'a retenu aucune "
             "cellule sur 4 580 (or) ni 493 (WTI), et la porte des frais est "
             "EXEMPTÉE sur BTC et ETH. Le régulateur à -10 % est le seul garde "
             "automatique, et il ne juge qu'à partir de 10 trades par paire.")
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
