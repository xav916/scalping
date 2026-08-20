#!/usr/bin/env python3
"""Surveille le compte IBKR U27532710 depuis Telegram (2026-08-20).

Xavier voulait suivre cette route depuis son téléphone. L'application IBKR ne
peut pas : elle refuse de se connecter tant que le Gateway occupe la session,
et le second utilisateur qui règlerait ça n'est pas proposé sur son compte.
Le bridge, lui, expose déjà tout — on lit par là.

Deux comportements :
  - **à chaque passage** : signale une position qui s'ouvre ou se ferme, en
    comparant au relevé précédent conservé sur disque ;
  - **`DIGEST=1`** : envoie l'état complet même sans changement, pour le
    point quotidien.

⚠️ Une lecture qui échoue n'est **jamais** traitée comme « aucune position » :
un bridge injoignable annoncerait la clôture de tout le portefeuille. C'est le
même garde-fou que `notify_position_fermee`, et il vient d'une vraie frayeur.

⚠️ La CHUTE du Gateway n'est pas annoncée ici : `bridge_ibkr` du
`bridge_monitor` s'en charge déjà, en moins de deux minutes. Doubler l'alerte
la rendrait bruyante et on finirait par ne plus la lire.

Usage :
    python notify_ibkr_etat.py              # signale les changements
    DIGEST=1 python notify_ibkr_etat.py     # état complet
    DRY_RUN=1 python notify_ibkr_etat.py    # affiche sans envoyer
"""
from __future__ import annotations

import html
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, "/app")

DELAI = 10
INSTANTANE = Path(os.environ.get(
    "IBKR_SNAPSHOT_PATH", "/app/data/ibkr_positions.json"))

TOKEN = os.environ.get("INFRA_NOTIFY_TOKEN", "shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg")
# channel=sales : le fil `trades` est reserve au compte MT5 reel 13137475.
# IBKR est une autre route, comme Kraken.
NOTIFY_URL = ("https://app.scalping-radar.online/api/admin/"
              f"notify-infra-telegram?token={TOKEN}&channel=sales")


def _lire(chemin: str):
    """GET sur le bridge IBKR. Rend (charge, lecture_reussie).

    ⚠️ En-tete `X-Bridge-Key`, PAS `X-API-Key` : ce dernier est celui des
    bridges MT5, et l'employer ici rend un 401 qui fait croire a une cle
    desynchronisee.
    """
    base = os.environ.get("IBKR_BRIDGE_URL", "").rstrip("/")
    if not base:
        return None, False
    cle = os.environ.get("IBKR_BRIDGE_API_KEY", "")
    try:
        rq = urllib.request.Request(
            base + chemin, headers={"X-Bridge-Key": cle} if cle else {})
        with urllib.request.urlopen(rq, timeout=DELAI) as r:
            if r.status != 200:
                return None, False
            return json.load(r), True
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
        print(f"  lecture impossible ({type(e).__name__}: {e})")
        return None, False


def _cle_position(p: dict) -> str:
    return f"{p.get('symbol')}|{p.get('position') or p.get('size')}"


def releve() -> tuple[dict, dict, dict, bool]:
    """Rend (sante, compte, positions_indexees, lecture_complete)."""
    sante, ok_s = _lire("/health")
    compte, ok_c = _lire("/account")
    pos, ok_p = _lire("/positions")
    if not (ok_s and ok_c and ok_p):
        return sante or {}, compte or {}, {}, False
    liste = pos.get("positions")
    if not isinstance(liste, list):
        # Une reponse 200 mal formee n'est pas une lecture reussie.
        return sante, compte, {}, False
    return sante, compte, {_cle_position(p): p for p in liste}, True


def _euros(v) -> str:
    try:
        return f"{float(v):,.2f}".replace(",", " ").replace(".", ",")
    except (TypeError, ValueError):
        return "inconnu"


def _bloc_compte(sante: dict, compte: dict) -> str:
    devise = html.escape(str(compte.get("currency") or ""))
    return (
        f"Compte <b>{html.escape(str(compte.get('account') or 'IBKR'))}</b> · "
        f"{'connecté' if sante.get('connected') else 'DÉCONNECTÉ'}\n"
        f"Valeur {_euros(compte.get('NetLiquidation'))} {devise} · "
        f"disponible {_euros(compte.get('AvailableFunds'))} {devise}"
    )


def _ligne_position(p: dict) -> str:
    taille = p.get("position") or p.get("size")
    return (f"• <b>{html.escape(str(p.get('symbol')))}</b> {taille} "
            f"@ {p.get('avg_cost') or p.get('price') or '?'}")


def _notifier(titre: str, corps: str, dedup: str) -> bool:
    if os.environ.get("DRY_RUN") == "1":
        print(f"  [DRY_RUN] {titre}\n{corps}")
        return True
    charge = json.dumps({
        "title": titre, "body": corps,
        "dedup_key": dedup, "cooldown_seconds": 1800,
    }).encode("utf-8")
    rq = urllib.request.Request(
        NOTIFY_URL, data=charge,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(rq, timeout=DELAI) as r:
            print(f"  notifié ({r.status})")
            return r.status < 300
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"  ENVOI ÉCHOUÉ ({type(e).__name__}: {e})")
        return False


def main() -> int:
    digest = os.environ.get("DIGEST") == "1"
    sante, compte, courant, complet = releve()

    if not complet:
        print("  lecture incomplète — aucune conclusion tirée")
        if digest:
            _notifier(
                "⚠️ IBKR : lecture impossible",
                "Le bridge IBKR n'a pas pu être lu entièrement.\n\n"
                "Ce n'est PAS « aucune position » — c'est « on ne sait pas ».",
                dedup="ibkr-illisible")
        return 1

    try:
        avant = set(json.loads(INSTANTANE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        avant = set()

    ouvertes = [p for c, p in courant.items() if c not in avant]
    fermees = [c for c in avant if c not in courant]
    print(f"  {len(courant)} position(s) · {len(ouvertes)} ouverte(s) · "
          f"{len(fermees)} fermée(s)")

    envoye = True
    if ouvertes or fermees:
        lignes = [_bloc_compte(sante, compte), ""]
        for p in ouvertes:
            lignes.append("🟢 OUVERTE " + _ligne_position(p))
        for c in fermees:
            lignes.append(f"🔵 FERMÉE • <b>{html.escape(c.split('|')[0])}</b>")
        envoye = _notifier(
            "IBKR — mouvement de position",
            "\n".join(lignes),
            dedup="ibkr-mvt-" + "_".join(sorted(list(courant) + fermees)))
    elif digest:
        lignes = [_bloc_compte(sante, compte), ""]
        lignes += ([_ligne_position(p) for p in courant.values()]
                   or ["Aucune position ouverte."])
        lignes.append("")
        lignes.append("Route en lecture seule : le radar n'y envoie pas "
                      "encore d'ordre, faute de capital suffisant.")
        envoye = _notifier("IBKR — état du compte", "\n".join(lignes),
                           dedup="ibkr-digest")
    else:
        print("  aucun mouvement")

    # ⚠️ L'instantané n'avance QUE si l'envoi a abouti : un mouvement non
    # annoncé doit rejouer au passage suivant plutôt qu'être perdu.
    if envoye and os.environ.get("DRY_RUN") != "1":
        try:
            INSTANTANE.parent.mkdir(parents=True, exist_ok=True)
            INSTANTANE.write_text(json.dumps(sorted(courant)), encoding="utf-8")
        except OSError as e:
            print(f"  instantané non écrit ({e})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
