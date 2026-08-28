#!/usr/bin/env python3
"""Alerte dès qu'une position tourne SANS stop, sur MT5 comme sur Kraken.

Posé le 2026-08-19. Jusqu'ici, **rien** ne pouvait dire qu'une position avait
perdu sa protection :

- sur Kraken, une entrée envoie **trois ordres indépendants** (marché, stop,
  objectif). Le stop peut échouer à la pose sans que l'entrée échoue — et
  `/positions` ne dit rien des ordres. D'où l'endpoint `/openorders`, ajouté
  le même jour ;
- sur MT5 les stops vivent dans la position elle-même, donc `sl` s'y lit
  directement. C'est déjà arrivé qu'il soit absent (incident de position nue
  du 2026-08-05, et le correctif SL/TP du bridge live).

⚠️ Une lecture qui échoue n'est **jamais** traitée comme « aucune position
non protégée » : un bridge injoignable annoncerait alors que tout va bien,
exactement le silence qu'on cherche à supprimer. On le dit explicitement.

⚠️ **Confirmation en deux passages.** Entre l'ordre au marché et la pose du
stop il s'écoule un instant : une position vue à cet instant paraîtrait nue à
tort. On n'alerte donc que si elle l'était **déjà au passage précédent**. Ce
choix évite aussi de dépendre de l'horodatage d'ouverture — que Kraken rend à
`1970-01-01`, donc inutilisable comme délai de grâce.

Usage :
    python notify_positions_non_protegees.py
    DRY_RUN=1 python notify_positions_non_protegees.py   # affiche sans notifier
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, "/app")

from backend.services.destinations_registry import DESTINATIONS  # noqa: E402

DELAI = 10
INSTANTANE = Path(os.environ.get(
    "NUES_SNAPSHOT_PATH", "/app/data/positions_non_protegees.json"))

TOKEN = os.environ.get("INFRA_NOTIFY_TOKEN", "shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg")
# channel=sales : une position sans stop est un evenement de TRADING.
NOTIFY_URL = ("https://app.scalping-radar.online/api/admin/"
              f"notify-infra-telegram?token={TOKEN}&channel=sales")

DESTINATIONS_SURVEILLEES = ("admin_live", "admin_legacy", "admin_kraken")

# Re-alerte toutes les heures tant que la position reste nue : c'est de
# l'argent reel expose, se taire apres un seul envoi serait pire que du bruit.
COOLDOWN_SEC = 3600


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


def _sans_stop_mt5(dest) -> tuple[list, bool]:
    """MT5 porte le stop DANS la position : `sl` a 0 ou absent = pas de stop."""
    charge, ok = _appel(dest, "/positions")
    if not ok or not isinstance(charge, dict):
        return [], False
    positions = charge.get("positions")
    if not isinstance(positions, list):
        return [], False
    nues = []
    for p in positions:
        try:
            sl = float(p.get("sl") or 0.0)
        except (TypeError, ValueError):
            sl = 0.0
        if sl == 0.0:
            nues.append({
                "cle": f"{dest.id}:{p.get('ticket')}",
                "symbole": p.get("symbol"),
                "sens": p.get("type"),
                "taille": p.get("volume"),
                "ticket": p.get("ticket"),
                "objectif_pose": bool(p.get("tp")),
            })
    return nues, True


def _sans_stop_kraken(dest) -> tuple[list, bool]:
    """Kraken : le croisement positions/ordres est fait par le bridge."""
    charge, ok = _appel(dest, "/openorders")
    if not ok or not isinstance(charge, dict) or not charge.get("ok"):
        return [], False
    brutes = charge.get("positions_non_protegees")
    if not isinstance(brutes, list):
        return [], False
    return [{
        "cle": f"{dest.id}:{p.get('symbol')}",
        "symbole": p.get("symbol"),
        "sens": p.get("side"),
        "taille": p.get("size"),
        "ticket": None,
        "objectif_pose": bool(p.get("objectif_pose")),
    } for p in brutes], True


def _charger_instantane() -> set:
    try:
        return set(json.loads(INSTANTANE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return set()


def _ecrire_instantane(cles: set) -> None:
    try:
        INSTANTANE.parent.mkdir(parents=True, exist_ok=True)
        INSTANTANE.write_text(json.dumps(sorted(cles)), encoding="utf-8")
    except OSError as e:
        print(f"  instantané non écrit ({e})")


def _notifier(titre: str, corps: str, dedup: str) -> None:
    if os.environ.get("DRY_RUN") == "1":
        print(f"  [DRY_RUN] {titre}\n{corps}")
        return
    charge = json.dumps({
        "title": titre, "body": corps,
        "dedup_key": dedup, "cooldown_seconds": COOLDOWN_SEC,
    }).encode("utf-8")
    rq = urllib.request.Request(
        NOTIFY_URL, data=charge,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(rq, timeout=DELAI) as r:
            print(f"  notifié ({r.status})")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"  ENVOI ÉCHOUÉ ({type(e).__name__}: {e})")


def main() -> int:
    vues_avant = _charger_instantane()
    nues_maintenant: dict = {}
    illisibles = []

    for did in DESTINATIONS_SURVEILLEES:
        dest = DESTINATIONS.get(did)
        if dest is None:
            continue
        print(f"{did} :")
        if dest.bridge_type == "kraken":
            nues, ok = _sans_stop_kraken(dest)
        else:
            nues, ok = _sans_stop_mt5(dest)
        if not ok:
            # Muet ≠ vide. Le dire, sinon l'absence d'alerte se lit « sain ».
            illisibles.append(did)
            print("    ILLISIBLE — aucune conclusion tirée")
            continue
        for n in nues:
            nues_maintenant[n["cle"]] = n
        print(f"    {len(nues)} position(s) sans stop")

    # Confirmation en deux passages : on n'alerte que sur ce qui l'était déjà.
    confirmees = [n for c, n in nues_maintenant.items() if c in vues_avant]
    _ecrire_instantane(set(nues_maintenant))

    for n in confirmees:
        sym = str(n["symbole"])
        objectif = "objectif encore posé" if n["objectif_pose"] else "aucun objectif non plus"
        titre = f"🚨 Position SANS STOP — {sym}"
        corps = (
            f"{sym} {str(n['sens'])} "
            f"taille {str(n['taille'])}\n"
            f"Destination : {n['cle'].split(':')[0]}\n"
            f"{objectif}\n\n"
            "Cette position court sans protection : une perte n'y est bornée "
            "par rien. Vérifier chez le courtier et reposer un stop, ou fermer."
        )
        print(f"  ALERTE {n['cle']}")
        _notifier(titre, corps, dedup=f"nue:{n['cle']}")

    if illisibles:
        titre = "⚠️ Protection des positions : lecture impossible"
        corps = (
            "Impossible de vérifier les stops sur : "
            f"{', '.join(illisibles)}.\n\n"
            "Ce n'est pas « aucune position nue » — c'est « on ne sait pas »."
        )
        _notifier(titre, corps, dedup=f"nue-illisible:{','.join(illisibles)}")

    if not confirmees and not illisibles:
        print("Aucune position sans stop.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
