#!/usr/bin/env python3
"""Prévient dès qu'une position se ferme, sur MT5 comme sur Kraken (2026-08-09).

Les positions auto ne sont suivies **nulle part** en base : un ordre poussé au
bridge n'est plus regardé ensuite, et `personal_trades` ne porte que le journal
manuel. Le seul témoin d'une clôture est le courtier. On compare donc le relevé
courant à celui du passage précédent, conservé dans un instantané sur disque.

Le raisonnement de sécurité est dans `backend.services.positions_fermees` :
un bridge injoignable rend « aucune position », et sans garde-fou une coupure
réseau annoncerait la clôture de tout le portefeuille. Ici on se contente de
lui dire honnêtement si la lecture a réussi.

⚠️ Une clôture n'est annoncée **qu'une fois** : après l'envoi, l'instantané est
réécrit. Un échec d'enrichissement (prix de sortie, P&L) ne doit donc jamais
faire abandonner l'envoi — mieux vaut annoncer « fermée, P&L inconnu » que se
taire définitivement. C'est pourquoi chaque enrichissement est enveloppé.

Usage :
    python notify_position_fermee.py            # vérifie + notifie
    DRY_RUN=1 python notify_position_fermee.py  # affiche sans notifier
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/app")

from backend.services.destinations_registry import DESTINATIONS  # noqa: E402
from backend.services.positions_fermees import (  # noqa: E402
    clotures,
    doit_memoriser,
    indexer,
)

INSTANTANE = Path(os.environ.get(
    "POSITIONS_SNAPSHOT_PATH", "/app/data/positions_ouvertes.json"))
DELAI = 10

TOKEN = os.environ.get("INFRA_NOTIFY_TOKEN", "shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg")
# Routage PAR DESTINATION (2026-08-19). Le fil `trades` suit le compte reel
# 13137475 de bout en bout : son ouverture y est deja annoncee par
# notify-miroir-demo-reel.sh, sa cloture l'y rejoint. Les autres destinations
# restent sur `sales`.
#
# ⚠️ Le routage se fait par MESSAGE, pas globalement : une cloture reelle et
# une cloture Kraken dans le meme passage produisent DEUX envois, chacun sur
# son fil. Grouper les deux enverrait du Kraken sur un fil cense ne porter que
# le compte reel.
CANAL_PAR_DESTINATION = {"admin_live": "trades"}
CANAL_DEFAUT = "sales"


def _url(canal: str) -> str:
    return ("https://app.scalping-radar.online/api/admin/"
            f"notify-infra-telegram?token={TOKEN}&channel={canal}")

# Tickets ayant une action manuelle en attente à leur clôture. Vide par défaut :
# la notification rappelle elle-même de vider la variable, donc la liste ne
# rouille pas en silence comme les cartes de symboles codées en dur.
TICKETS_SUIVIS = frozenset(
    t.strip() for t in (os.environ.get("TICKETS_ACTION_EN_ATTENTE") or "").split(",")
    if t.strip()
)

DESTINATIONS_SURVEILLEES = ("admin_live", "admin_legacy", "admin_kraken")


def _appel(dest, chemin: str):
    """GET sur un bridge. Rend (charge_utile, lecture_reussie)."""
    url = os.environ.get(dest.url_env or "", "")
    if not url:
        return None, False
    cle = os.environ.get(dest.key_env or "", "")
    entetes = {dest.key_header: cle} if cle and dest.key_header else {}
    try:
        rq = urllib.request.Request(url.rstrip("/") + chemin, headers=entetes)
        with urllib.request.urlopen(rq, timeout=DELAI) as r:
            if r.status != 200:
                return None, False
            return json.load(r), True
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
        print(f"    lecture impossible ({type(e).__name__}: {e})")
        return None, False


def releve(dest):
    """Positions ouvertes chez un courtier, et si on a vraiment pu les lire."""
    charge, ok = _appel(dest, "/positions")
    if not ok or not isinstance(charge, dict):
        return {}, False
    positions = charge.get("positions")
    if not isinstance(positions, list):
        # Une réponse 200 mal formée n'est pas une lecture réussie : la traiter
        # comme « zéro position » ferait exactement le dégât qu'on évite.
        return {}, False
    return indexer(dest.bridge_type, positions), True


def _sortie_mt5(dest, ticket) -> dict:
    charge, ok = _appel(dest, f"/deals?ticket={int(ticket)}")
    if not ok or not isinstance(charge, dict) or not charge.get("closed"):
        return {}
    return {"exit": charge.get("exit_price"), "pnl": charge.get("pnl"),
            "quand": charge.get("closed_at")}


def _sortie_kraken(dest, pos) -> dict:
    """Kraken ne donne pas de ticket : on retient la dernière exécution du
    symbole ayant réalisé un P&L — `realized_pnl` non nul signifie exactement
    « cette exécution a réduit ou fermé une position »."""
    charge, ok = _appel(dest, "/fills")
    if not ok or not isinstance(charge, dict):
        return {}
    symbole = str(pos.get("symbol") or "").upper()
    candidats = [
        f for f in charge.get("fills") or []
        if str(f.get("symbol") or "").upper() == symbole and f.get("realized_pnl")
    ]
    if not candidats:
        return {}
    dernier = max(candidats, key=lambda f: str(f.get("fill_time") or ""))
    return {"exit": dernier.get("price"),
            "pnl": (dernier.get("realized_pnl") or 0) + (dernier.get("realized_funding") or 0),
            "quand": dernier.get("fill_time")}


def enrichir(dest, pos) -> dict:
    """Prix de sortie et P&L. Ne lève jamais : une clôture s'annonce même nue."""
    try:
        if (dest.bridge_type or "").startswith("kraken"):
            return _sortie_kraken(dest, pos)
        return _sortie_mt5(dest, pos.get("ticket"))
    except Exception as e:  # noqa: BLE001 — se taire coûterait l'annonce
        print(f"    enrichissement impossible : {type(e).__name__}: {e}")
        return {}


def _somme(v) -> str:
    return "inconnu" if v is None else f"{float(v):+.2f}"


def decrire(dest, pos, sortie) -> str:
    kraken = (dest.bridge_type or "").startswith("kraken")
    if kraken:
        quoi = f"{pos.get('symbol')} {pos.get('side')} {pos.get('size')}"
        ref = ""
    else:
        quoi = f"{pos.get('symbol')} {pos.get('type')} {pos.get('volume')} lot"
        ref = f" #{pos.get('ticket')}"
    entree = pos.get("price") if kraken else pos.get("price_open")
    ligne = (f"{dest.badge} {quoi}{ref}\n"
             f"   entree {entree}  ->  sortie {sortie.get('exit', 'inconnue')}\n"
             f"   P&L {_somme(sortie.get('pnl'))} {'USD' if kraken else 'EUR'}")
    if str(pos.get("ticket")) in TICKETS_SUIVIS:
        ligne += ("\n   ⚠️ ACTION EN ATTENTE sur ce ticket : le retirer de "
                  "DAILY_LOSS_EXCLUDED_TICKETS et d'ACK_TICKETS sur le bridge, "
                  "restaurer MAX_DAILY_LOSS_PCT et MAX_OPEN_POSITIONS, puis "
                  "vider TICKETS_ACTION_EN_ATTENTE.")
    return ligne


def notifier(corps: str, cles: list[str], canal: str = CANAL_DEFAUT) -> bool:
    titre = ("Position fermee — compte reel 13137475" if canal == "trades"
             else "Position fermee")
    charge = json.dumps({
        "title": titre,
        "body": corps,
        "dedup_key": "cloture_" + "_".join(sorted(cles)),
        "cooldown_seconds": 3600,
    }).encode()
    rq = urllib.request.Request(
        _url(canal), data=charge, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(rq, timeout=DELAI) as r:
            print(f"  notify [{canal}] HTTP {r.status}")
            return r.status < 300
    except Exception as e:  # noqa: BLE001
        print(f"  notify [{canal}] ECHEC : {type(e).__name__}: {e}")
        return False


def main() -> int:
    a_blanc = os.environ.get("DRY_RUN") == "1"
    print(datetime.now(timezone.utc).isoformat(timespec="seconds"),
          "notify-position-fermee", "(a blanc)" if a_blanc else "")

    try:
        memoire = json.loads(INSTANTANE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        memoire = {}

    # {canal: (lignes, cles)} — le routage se decide par destination.
    groupes: dict[str, tuple[list, list]] = {}
    nouvelle_memoire = dict(memoire)

    for did in DESTINATIONS_SURVEILLEES:
        dest = DESTINATIONS.get(did)
        if dest is None:
            continue
        courant, ok = releve(dest)
        fermees = clotures(dest.bridge_type, memoire.get(did), courant, ok)
        etat = "lue" if ok else "INJOIGNABLE (rien ne sera conclu)"
        print(f"  {did:14s} {etat}, {len(courant)} ouverte(s), "
              f"{len(fermees)} fermee(s)")

        canal = CANAL_PAR_DESTINATION.get(did, CANAL_DEFAUT)
        lignes_c, cles_c = groupes.setdefault(canal, ([], []))
        for pos in fermees:
            lignes_c.append(decrire(dest, pos, enrichir(dest, pos)))
            cles_c.append(f"{did}:{pos.get('ticket') or pos.get('symbol')}")

        if doit_memoriser(ok):
            nouvelle_memoire[did] = courant

    groupes = {c: v for c, v in groupes.items() if v[0]}

    if not groupes:
        # ⚠️ L'instantané se met à jour même sans clôture : c'est lui qui suit
        # les OUVERTURES. Sans cela, la prochaine comparaison partirait d'un
        # relevé périmé et annoncerait des clôtures fantômes.
        if not a_blanc:
            INSTANTANE.parent.mkdir(parents=True, exist_ok=True)
            INSTANTANE.write_text(json.dumps(nouvelle_memoire), encoding="utf-8")
        print("  aucune cloture")
        return 0

    for canal, (lignes_c, _) in sorted(groupes.items()):
        print(f"--- message [{canal}] ---\n" + "\n\n".join(lignes_c))
    if a_blanc:
        return 0

    # ⚠️ Liste, PAS de générateur : `all()` court-circuiterait, et l'échec du
    # premier fil empêcherait le second d'être tenté. Chaque canal part
    # indépendamment.
    resultats = [notifier("\n\n".join(l), c, canal)
                 for canal, (l, c) in sorted(groupes.items())]

    # ⚠️ TOUS les envois doivent aboutir pour que l'instantané avance. Sinon
    # une clôture non annoncée serait perdue pour toujours. Le renvoi d'un
    # groupe déjà parti est neutralisé par sa `dedup_key` côté endpoint.
    if not all(resultats):
        print("  instantane conserve, nouvel essai dans 2 minutes")
        return 1

    INSTANTANE.parent.mkdir(parents=True, exist_ok=True)
    INSTANTANE.write_text(json.dumps(nouvelle_memoire), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
