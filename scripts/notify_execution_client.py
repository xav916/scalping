#!/usr/bin/env python3
"""Alerte quand un client PAYANT cesse d'exécuter (2026-08-21).

Découvert le 21/08 : Cédric (`user:2`) recevait ~100 signaux/jour — plus que
les comptes de Xavier — dans une file que personne ne vidait. **2 912 ordres
en attente, 0 exécuté, EA hors ligne depuis le 15/08.** Il payait un service
qui ne fonctionnait plus depuis des semaines, et rien ne l'a signalé.

Pourquoi c'est resté invisible : chaque push répondait `ok=1`, qui signifie
« mis en file d'attente » et **jamais « exécuté »**.

> **Un compteur de livraison n'est pas un compteur d'exécution.**

Deux signaux surveillés, qui ne disent pas la même chose :
  - **EA muet** — plus aucun appel depuis N heures : le robot du client est
    éteint ou ne joint plus le serveur ;
  - **signaux jamais reçus sans exécution** — l'EA appelle, mais rien
    n'aboutit : ses ordres échouent chez son courtier.

⚠️ « Jamais reçus » compte `PENDING` **et `EXPIRED`**. Depuis que
`purge-file-ea.sh` tourne toutes les heures, un ordre non servi passe en
`EXPIRED` en moins d'une heure : ne compter que `PENDING` viderait ce
compteur en permanence et **rendrait ce signal aveugle**.

⚠️ Seuls les clients **actuellement éligibles** à l'auto-exec sont surveillés.
Un client en veille l'est délibérément : l'alerter en continu ferait du bruit
permanent, et le bruit finit par ne plus être lu.

Usage :
    python notify_execution_client.py
    DRY_RUN=1 python notify_execution_client.py
"""
from __future__ import annotations

import html
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/app")

DELAI = 10
SILENCE_EA_H = int(os.environ.get("SILENCE_EA_H", "24"))
FENETRE_J = int(os.environ.get("FENETRE_EXEC_J", "7"))
SEUIL_FILE = int(os.environ.get("SEUIL_FILE", "20"))

TOKEN = os.environ.get("INFRA_NOTIFY_TOKEN", "shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg")
# channel=sales : un client qui n'execute plus est un evenement COMMERCIAL.
NOTIFY_URL = ("https://app.scalping-radar.online/api/admin/"
              f"notify-infra-telegram?token={TOKEN}&channel=sales")


def diagnostiquer(etat: dict, maintenant: datetime,
                  silence_h: int = SILENCE_EA_H,
                  seuil_file: int = SEUIL_FILE) -> list[str]:
    """Rend la liste des problèmes d'un client. Fonction pure.

    `etat` : {dernier_appel: datetime|None, executes: int, echecs: int,
              en_attente: int, erreur_dominante: str|None}

    ⚠️ Extraite pour être testable **face à ce qu'elle doit trouver**. Noyée
    dans les entrées/sorties, elle n'aurait pu être vérifiée que sur son
    silence — l'erreur commise le 19/08 sur le détecteur de positions nues.
    """
    soucis: list[str] = []
    dernier = etat.get("dernier_appel")

    if dernier is None:
        soucis.append("son EA n'a JAMAIS appelé le serveur")
    else:
        heures = (maintenant - dernier).total_seconds() / 3600
        if heures >= silence_h:
            soucis.append(
                f"son EA est muet depuis {heures:.0f} h "
                f"(dernier appel {dernier:%d/%m %H:%M})")

    if etat.get("executes", 0) == 0:
        if etat.get("echecs", 0) > 0:
            motif = etat.get("erreur_dominante") or "sans motif remonté"
            soucis.append(
                f"0 exécution pour {etat['echecs']} échec(s) — {motif}")
        elif etat.get("jamais_recus", 0) >= seuil_file:
            soucis.append(
                f"{etat['jamais_recus']} signaux jamais reçus, 0 exécuté : "
                "on lui envoie des ordres que son EA ne prend pas")

    return soucis


def _releve(c: sqlite3.Connection, user_id: int) -> dict:
    depuis = (datetime.now(timezone.utc) - timedelta(days=FENETRE_J)).isoformat()
    r = c.execute(
        "SELECT MAX(fetched_at) FROM mt5_pending_orders WHERE user_id=?",
        (user_id,)).fetchone()
    dernier = None
    if r and r[0]:
        try:
            dernier = datetime.fromisoformat(r[0])
            if dernier.tzinfo is None:
                dernier = dernier.replace(tzinfo=timezone.utc)
        except ValueError:
            dernier = None

    compte = dict(c.execute(
        "SELECT status, COUNT(*) FROM mt5_pending_orders "
        " WHERE user_id=? AND created_at >= ? GROUP BY status",
        (user_id, depuis)).fetchall())

    err = c.execute(
        "SELECT substr(mt5_error,1,60), COUNT(*) n FROM mt5_pending_orders "
        " WHERE user_id=? AND created_at >= ? AND mt5_error IS NOT NULL "
        " GROUP BY 1 ORDER BY n DESC LIMIT 1",
        (user_id, depuis)).fetchone()

    return {
        "dernier_appel": dernier,
        "executes": compte.get("EXECUTED", 0),
        "echecs": compte.get("FAILED", 0),
        # PENDING + EXPIRED : la purge horaire fait passer l'un dans l'autre en
        # moins d'une heure. Ne compter que PENDING rendrait ce signal aveugle.
        "jamais_recus": compte.get("PENDING", 0) + compte.get("EXPIRED", 0),
        "erreur_dominante": err[0] if err else None,
    }


def _notifier(titre: str, corps: str, dedup: str) -> bool:
    if os.environ.get("DRY_RUN") == "1":
        print(f"  [DRY_RUN] {titre}\n{corps}")
        return True
    charge = json.dumps({
        "title": titre, "body": corps,
        # Re-alerte une fois par jour : un client sans service est un probleme
        # persistant, pas un evenement ponctuel.
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
    from backend.services import users_service

    try:
        clients = users_service.list_premium_auto_exec_users()
    except Exception as e:  # noqa: BLE001
        # ⚠️ Muet n'est pas vide : ne pas conclure « aucun client a surveiller ».
        print(f"  liste des clients illisible ({type(e).__name__}: {e})")
        _notifier("⚠️ Surveillance client : lecture impossible",
                  "La liste des clients en auto-exec n'a pas pu être lue.\n\n"
                  "Ce n'est PAS « aucun client en difficulté ».",
                  dedup="exec-client-illisible")
        return 1

    if not clients:
        print("  aucun client en auto-exec (veille ou aucun abonné)")
        return 0

    maintenant = datetime.now(timezone.utc)
    with sqlite3.connect(str(users_service._DB_PATH)) as c:
        for cl in clients:
            uid = cl["id"]
            etat = _releve(c, uid)
            soucis = diagnostiquer(etat, maintenant)
            print(f"  user:{uid} {cl.get('email','?')} — "
                  f"{etat['executes']} exécutés / {etat['echecs']} échecs / "
                  f"{etat['jamais_recus']} jamais reçus")
            if not soucis:
                continue
            corps = (
                f"<b>{html.escape(str(cl.get('email') or f'user:{uid}'))}</b>\n\n"
                + "\n".join(f"• {html.escape(s)}" for s in soucis)
                + f"\n\nSur {FENETRE_J} jours : {etat['executes']} exécuté(s), "
                  f"{etat['echecs']} échec(s), "
                  f"{etat['jamais_recus']} jamais reçu(s).\n\n"
                  "Ce client PAIE. Le radar lui envoie des signaux qui "
                  "n'aboutissent pas."
            )
            print(f"    ALERTE : {'; '.join(soucis)}")
            _notifier(f"🚨 Client sans exécution — user:{uid}", corps,
                      dedup=f"exec-client:{uid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
