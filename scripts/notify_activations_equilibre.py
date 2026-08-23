#!/usr/bin/env python3
"""Rend la soupape d'équilibre JUGEABLE : compte ses activations et leur suite.

Posé le 2026-08-24. La soupape appartient à la famille de gestes mesurée à
**−0,329 R par trade sur l'or** ; elle a été armée contre ma recommandation,
puis son seuil abaissé à 0,40 R. Une décision prise contre la mesure doit au
minimum rester **révisable sur des mesures**.

> **Un mécanisme qu'on ne peut pas compter est un mécanisme auquel on ne peut
> que croire.**

Ce que la sonde répond, et que rien ne disait :

1. **combien de fois** la soupape s'est déclenchée ;
2. **ce que sont devenues** les positions dont elle a remonté le stop —
   sorties à l'équilibre (le coût redouté) ou parties à l'objectif ;
3. **combien de risque** elle a réellement libéré.

Source : les lignes d'audit `status='equilibre'` que le bridge écrit à chaque
déplacement réussi, lues par `/audit` — le même chemin que `mt5_sync`. Le
devenir vient de `personal_trades`, joint par `mt5_ticket`.

⚠️ **Cette sonde ne conclut pas.** Sur une poignée d'activations — le
déclenchement est mesuré à ~1 par mois — aucun verdict n'est décidable ;
c'est exactement le piège du groupe à 27. Elle **compte et expose**, en
disant combien il en manque avant que la question se pose.

Usage :
    python notify_activations_equilibre.py
    DRY_RUN=1 python notify_activations_equilibre.py
    FENETRE_J=30 python notify_activations_equilibre.py
"""
from __future__ import annotations

import html
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request

sys.path.insert(0, "/app")

DELAI = 10
FENETRE_J = int(os.environ.get("FENETRE_J", "7"))
# En dessous, on ne prétend même pas amorcer une conclusion. 30 est le
# plancher déjà retenu par `verdict_directionnel` pour le groupe qui décide.
N_MIN_JUGEMENT = int(os.environ.get("N_MIN_JUGEMENT", "30"))

TOKEN = os.environ.get("INFRA_NOTIFY_TOKEN", "shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg")
# channel=sales : c'est un evenement de TRADING. ⛔ Omettre `channel`
# routerait vers le fil infra EN SILENCE.
NOTIFY_URL = ("https://app.scalping-radar.online/api/admin/"
              f"notify-infra-telegram?token={TOKEN}&channel=sales")
COOLDOWN_SEC = 86400

DESTINATIONS_SURVEILLEES = ("admin_legacy", "admin_live")


def _appel(dest, chemin: str):
    """GET sur un bridge. Rend `(charge, lecture_reussie)`."""
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


def activations(dest) -> tuple[list, bool]:
    """Lignes d'audit `status='equilibre'`. `(liste, lecture_reussie)`.

    ⛔ `([], False)` et `([], True)` sont deux verdicts distincts : « on n'a
    pas pu lire » n'est pas « il ne s'est rien passé ». Confondre les deux
    ferait passer un bridge muet pour un mécanisme au repos.
    """
    charge, ok = _appel(dest, "/audit?since_id=0&limit=5000")
    if not ok or not isinstance(charge, dict):
        return [], False
    lignes = charge.get("orders")
    if not isinstance(lignes, list):
        return [], False
    return [o for o in lignes if o.get("status") == "equilibre"], True


def _devenir(tickets: list) -> dict:
    """`{ticket: (close_reason, pnl, status)}` depuis `personal_trades`."""
    if not tickets:
        return {}
    try:
        from backend.services.trade_log_service import _DB_PATH
        with sqlite3.connect(f"file:{_DB_PATH}?mode=ro", uri=True,
                             timeout=10) as c:
            marques = ",".join("?" * len(tickets))
            q = (f"select mt5_ticket, close_reason, pnl, status "
                 f"from personal_trades where mt5_ticket in ({marques})")
            return {r[0]: (r[1], r[2], r[3]) for r in c.execute(q, tickets)}
    except Exception as e:
        print(f"  devenir illisible ({type(e).__name__}: {e})")
        return {}


def resumer(lignes: list, devenirs: dict) -> dict:
    """Agrège les activations. Fonction pure, testable sans réseau."""
    total = len(lignes)
    libere = 0.0
    for o in lignes:
        msg = str(o.get("message") or "")
        for morceau in msg.split():
            if morceau.startswith("libere="):
                try:
                    libere += float(morceau.split("=", 1)[1])
                except ValueError:
                    pass
    sorties = {"a_l_equilibre": 0, "objectif": 0, "stop": 0,
               "autre": 0, "encore_ouvert": 0, "inconnu": 0}
    for o in lignes:
        t = o.get("ticket")
        if t not in devenirs:
            sorties["inconnu"] += 1
            continue
        cause, pnl, statut = devenirs[t]
        if statut != "CLOSED":
            sorties["encore_ouvert"] += 1
        elif cause in ("TP1", "TP2"):
            sorties["objectif"] += 1
        elif cause == "SL":
            # Stop touche APRES remontee a l'equilibre = sortie a ~0.
            # C'est le cout redoute du mecanisme, celui qu'il faut compter.
            sorties["a_l_equilibre"] += 1
        elif cause:
            sorties["autre"] += 1
        else:
            sorties["inconnu"] += 1
    return {"total": total, "libere": round(libere, 2), "sorties": sorties}


def _notifier(titre: str, corps: str, dedup: str) -> None:
    if os.environ.get("DRY_RUN") == "1":
        print(f"  [DRY_RUN] {titre}\n{corps}\n")
        return
    charge = json.dumps({"title": titre, "body": corps, "dedup_key": dedup,
                         "cooldown_seconds": COOLDOWN_SEC}).encode("utf-8")
    rq = urllib.request.Request(
        NOTIFY_URL, data=charge,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(rq, timeout=DELAI) as r:
            print(f"  notifié ({r.status})")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"  ENVOI ÉCHOUÉ ({type(e).__name__}: {e})")


def main() -> int:
    try:
        from backend.services.destinations_registry import DESTINATIONS
    except ImportError as exc:
        print(f"registre illisible : {exc}")
        return 1

    blocs, illisibles, total_global = [], [], 0
    for did in DESTINATIONS_SURVEILLEES:
        dest = DESTINATIONS.get(did)
        if dest is None:
            continue
        print(f"{did} :")
        lignes, ok = activations(dest)
        if not ok:
            illisibles.append(did)
            print("    ILLISIBLE — aucune conclusion tirée")
            continue
        r = resumer(lignes, _devenir([o.get("ticket") for o in lignes
                                      if o.get("ticket")]))
        total_global += r["total"]
        s = r["sorties"]
        print(f"    {r['total']} activation(s), {r['libere']} EUR libérés, "
              f"sorties {s}")
        if r["total"]:
            blocs.append(
                f"<b>{html.escape(did)}</b> — {r['total']} activation(s), "
                f"{r['libere']:.2f} € libérés\n"
                f"  objectif atteint : {s['objectif']}\n"
                f"  sorti À L'ÉQUILIBRE : {s['a_l_equilibre']}   "
                f"(le coût du mécanisme)\n"
                f"  encore ouvert : {s['encore_ouvert']}   "
                f"autre : {s['autre']}   inconnu : {s['inconnu']}")

    if illisibles:
        _notifier("⚠️ Activations de la soupape : lecture impossible",
                  "Impossible de lire les activations sur : "
                  f"<b>{html.escape(', '.join(illisibles))}</b>.\n\n"
                  "Ce n'est pas « aucune activation » — c'est « on ne sait "
                  "pas ».",
                  dedup=f"equilibre-illisible:{','.join(illisibles)}")

    if not blocs:
        print("Aucune activation à ce jour — la soupape n'a jamais agi.")
        return 0

    manque = max(0, N_MIN_JUGEMENT - total_global)
    pied = (f"\n⛔ <b>Ne rien conclure</b> : {total_global} activation(s), il "
            f"en faudrait au moins {N_MIN_JUGEMENT}. Il en manque {manque}."
            if manque else
            f"\n✅ {total_global} activations : le seuil de {N_MIN_JUGEMENT} "
            "est atteint, la question devient décidable. À juger par contrôle "
            "aléatoire, pas à l'œil.")

    _notifier(f"⚖️ Soupape d'équilibre — {total_global} activation(s)",
              "\n\n".join(blocs) + "\n" + pied,
              dedup=f"equilibre-activations:{total_global}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
