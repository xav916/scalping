#!/usr/bin/env python3
"""Alerte quand le radar vise un instrument que la destination ne sait pas tracer.

Découvert le 23/08 : **14 des 23 cryptos** de `WATCHED_PAIRS` étaient scorées,
passées au travers des cinq portes d'admission, poussées vers Kraken — et
jetées au dernier mètre par un `HTTP 400 unsupported pair`. Chaque nuit,
depuis l'extension de l'univers de 2 à 23 instruments.

Cause : l'admission raisonne en **classe d'actif**, jamais en instrument.

    allowed_asset_classes = frozenset({"crypto"})   # une CLASSE, pas une liste

La seule place où vit « ce bridge sait-il tracer cette paire » est une table
écrite en dur dans le source du bridge, consultée **au dernier moment**, et
qui s'exprime par un code HTTP. Rien ne reliait les deux côtés, donc rien
n'a protesté pendant que 61 % du flux crypto partait à la poubelle.

> **Une porte posée d'un seul côté n'est pas une porte.**

⚠️ On sonde par `/tick/<paire>`, qui appelle le **même `_resolve_symbol`** que
le chemin d'ordre. C'est volontaire : une liste déclarative que le bridge
publierait pourrait diverger de ce qu'il fait vraiment. On mesure l'effet.

Usage :
    python notify_divergence_univers.py
    DRY_RUN=1 python notify_divergence_univers.py
"""
from __future__ import annotations

import html
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, "/app")

DELAI = 8
TOKEN = os.environ.get("INFRA_NOTIFY_TOKEN", "shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg")
NOTIFY_URL = ("https://app.scalping-radar.online/api/admin/"
              f"notify-infra-telegram?token={TOKEN}&channel=infra")

# Destinations dont le bridge resout un SYMBOLE par paire, et expose `/tick`.
# Les autres (MT5) passent par MT5_SYMBOL_MAP et un autre mecanisme : les
# ajouter demande de verifier leur vrai chemin de resolution, pas de supposer.
SONDABLES = {"admin_kraken", "admin_kraken_spot", "admin_kraken_stocks"}


def _tracable(url: str, cle: str, paire: str) -> bool | None:
    """`True` tracable, `False` refusee, `None` si le bridge n'a pas repondu.

    ⚠️ `None` n'est PAS `False`. Un bridge injoignable rendrait « tout est
    divergent » et noierait l'alerte — on le signale a part.
    """
    cible = f"{url}/tick/{urllib.parse.quote(paire, safe='')}"
    rq = urllib.request.Request(cible, headers={"X-Bridge-Key": cle})
    try:
        with urllib.request.urlopen(rq, timeout=DELAI) as r:
            return bool(json.loads(r.read()).get("ok"))
    except urllib.error.HTTPError as e:
        try:
            corps = json.loads(e.read())
        except (json.JSONDecodeError, ValueError, OSError):
            return None
        # 400 « unsupported pair » = reponse VALIDE du bridge : il ne sait pas.
        if "unsupported pair" in str(corps.get("error", "")):
            return False
        return None
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None


def analyser(destination_id: str, attendues: list[str],
             verdicts: dict[str, bool | None]) -> dict:
    """Trie les paires en tracables / refusees / injoignables. Fonction pure."""
    return {
        "destination": destination_id,
        "attendues": len(attendues),
        "tracables": sorted(p for p in attendues if verdicts.get(p) is True),
        "refusees": sorted(p for p in attendues if verdicts.get(p) is False),
        "muettes": sorted(p for p in attendues if verdicts.get(p) is None),
    }


def _notifier(titre: str, corps: str, dedup: str) -> bool:
    if os.environ.get("DRY_RUN") == "1":
        print(f"  [DRY_RUN] {titre}\n{corps}\n")
        return True
    charge = json.dumps({
        "title": titre, "body": corps,
        # 24 h : une divergence de configuration est un etat, pas un evenement.
        "dedup_key": dedup, "cooldown_seconds": 86400,
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
    from config.settings import WATCHED_PAIRS, asset_class_for
    from backend.services.bridge_destinations import admin_destinations

    pairs = [p.strip() for p in WATCHED_PAIRS if p and p.strip()]
    sortie = 0

    for dest in admin_destinations():
        if dest.destination_id not in SONDABLES:
            continue
        if not dest.auto_exec_enabled:
            continue

        attendues = [p for p in pairs
                     if asset_class_for(p) in (dest.allowed_asset_classes or set())]
        if not attendues:
            continue

        verdicts = {p: _tracable(dest.bridge_url, dest.bridge_api_key, p)
                    for p in attendues}
        r = analyser(dest.destination_id, attendues, verdicts)

        print(f"  {r['destination']}: {len(r['tracables'])}/{r['attendues']} "
              f"traçables, {len(r['refusees'])} refusées, "
              f"{len(r['muettes'])} sans réponse")

        if r["muettes"]:
            # ⚠️ Muet n'est pas « refuse ». On le dit, on ne l'additionne pas.
            _notifier(
                f"⚠️ Univers {r['destination']} : bridge partiellement muet",
                f"{len(r['muettes'])} paire(s) sans réponse du bridge :\n"
                + ", ".join(html.escape(p) for p in r["muettes"])
                + "\n\nCe n'est PAS « ces paires sont refusées » : le bridge "
                  "n'a pas répondu. La divergence reste indéterminée.",
                dedup=f"divergence-muet:{r['destination']}")
            sortie = 1

        if r["refusees"]:
            part = 100.0 * len(r["refusees"]) / r["attendues"]
            _notifier(
                f"⛔ {len(r['refusees'])} instruments jetés — {r['destination']}",
                f"Le radar score et pousse ces paires ; le bridge ne sait pas "
                f"les tracer :\n\n<b>"
                + ", ".join(html.escape(p) for p in r["refusees"])
                + f"</b>\n\n{len(r['refusees'])}/{r['attendues']} de l'univers "
                  f"({part:.0f} %) part à la poubelle après avoir consommé "
                  f"tout le scoring.\n\nSoit on complète la table de symboles "
                  f"du bridge, soit on retire ces paires de WATCHED_PAIRS — "
                  f"mais pas les deux à moitié.",
                dedup=f"divergence-univers:{r['destination']}")
            sortie = 1

    return sortie


if __name__ == "__main__":
    raise SystemExit(main())
