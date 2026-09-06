#!/usr/bin/env python3
"""Surveille que le bridge retient bien les SL/TP VIVANTS à chaque clôture.

Posé le 2026-08-25, en remplacement d'une veille de session.

## Ce qu'elle garde

MT5 ne journalise pas les `TRADE_ACTION_SLTP` : à la seconde où une position
ferme, le niveau qu'elle portait réellement est perdu. Le monitor du bridge le
capture **un tour avant** — c'est la seule fenêtre, et il n'existe **aucune
route rétroactive** (vérifié le 25/08 : `niveau_declencheur` reste vide même
sur les clôtures par stop, MT5 fermant sur un ordre au marché).

> **Si cette capture cesse, plus rien ne le dira.** Les colonnes resteraient
> vides, les clôtures continueraient d'arriver, et l'analyse repartirait sur
> les niveaux d'ORIGINE — ceux dont on a mesuré qu'ils sont faux dans 44 % des
> cas. Un silence qui ressemble au fonctionnement normal : exactement le motif
> de [[feedback_detection_par_absence]].

## Deux régimes

1. **La première clôture jugée** déclenche le message de VÉRIFICATION : la
   capture a-t-elle eu lieu, et le niveau retenu diffère-t-il de l'origine ?
2. **Ensuite**, la sonde se tait, sauf régression — une clôture MT5 sans
   niveaux capturés. C'est une sonde de panne, pas un flux de trades.

## ⛔ Le délai de grâce, sans lequel elle mentirait

Entre la clôture chez le courtier et l'écriture en base, il y a le passage de
`mt5_sync`. Juger tout de suite ferait déclarer « capture manquante » sur une
ligne simplement **pas encore synchronisée**. Les clôtures de moins de
`GRACE_MIN` minutes ne sont donc **pas jugées**, et le curseur ne les dépasse
pas — elles seront jugées au passage suivant.

Usage :
    python notify_capture_niveaux.py
    DRY_RUN=1 python notify_capture_niveaux.py
    DEPUIS=2026-08-25T00:00:00+00:00 python notify_capture_niveaux.py   # rejuge
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

DELAI = 10
DB = os.environ.get("TRADES_DB", "/app/data/trades.db")
ETAT = os.environ.get("ETAT_SONDE", "/app/data/sonde_capture_niveaux.json")
GRACE_MIN = int(os.environ.get("GRACE_MIN", "20"))

TOKEN = os.environ.get("INFRA_NOTIFY_TOKEN", "shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg")
# channel=sales : evenement de TRADING. ⛔ Omettre `channel` routerait vers le
# fil infra EN SILENCE — le defaut qui a egare 4 notificateurs du 04/08 au 19/08.
# ── Le fil suit le COMPTE dont parle le message (2026-09-06) ─────────
#
# ⛔ Tout partait sur `channel=sales`, c'est-à-dire le bot nommé « IC MARKETS
# trades » : les positions Kraken et démo s'affichaient dans le fil du compte
# forex réel. La sonde connaît pourtant sa destination à chaque message.
#
# 🔑 La règle : un message qui parle d'une POSITION part dans le fil de son
# compte ; un message qui parle de LA SONDE (base illisible, silence, récap
# global) part sur `infra` — `canal_pour(None)` y mène.
sys.path.insert(0, "/app")
from backend.services.canaux_telegram import canal_pour  # noqa: E402

BASE_URL = ("https://app.scalping-radar.online/api/admin/"
            f"notify-infra-telegram?token={TOKEN}")
COOLDOWN_SEC = 21600

# Seules les destinations MT5 portent des SL/TP capturables par le monitor.
# Kraken a sa propre route, sans equivalent — l'inclure ferait crier la sonde
# sur des trades qu'elle ne surveille pas.
DESTINATIONS = ("admin_live", "admin_legacy")


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


def _lire_etat() -> dict:
    try:
        with open(ETAT, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _ecrire_etat(etat: dict) -> None:
    # ⛔ Un passage « à blanc » qui AVANCE le curseur n'est pas à blanc : la
    # clôture qu'il vient de juger ne serait jamais rejugée par le vrai
    # passage, donc jamais notifiée. Défaut trouvé le 25/08 en testant le
    # chemin qui alerte — le DRY_RUN avait mangé l'événement qu'il servait à
    # démontrer. Une observation ne doit rien déplacer.
    if os.environ.get("DRY_RUN") == "1":
        print(f"  [DRY_RUN] curseur NON avancé (resterait à {etat.get('curseur')})")
        return
    try:
        with open(ETAT, "w", encoding="utf-8") as f:
            json.dump(etat, f, indent=1)
    except OSError as e:
        # ⚠️ Un curseur non ecrit fait REJUGER les memes lignes au passage
        # suivant. C'est bruyant mais sans danger ; l'inverse (avancer sans
        # avoir juge) perdrait une regression en silence.
        print(f"  etat non ecrit ({e}) — les lignes seront rejugees")


def _instant(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def clotures_depuis(curseur: str) -> list[dict]:
    """Clôtures MT5 postérieures au curseur, les plus anciennes d'abord."""
    marques = ",".join("?" * len(DESTINATIONS))
    with sqlite3.connect(DB) as c:
        c.row_factory = sqlite3.Row
        lignes = c.execute(
            f"""SELECT mt5_ticket, pair, direction, close_reason, closed_at,
                       stop_loss, take_profit,
                       sl_at_close, tp_at_close, niveaux_source, pnl
                  FROM personal_trades
                 WHERE status = 'CLOSED'
                   AND mt5_ticket IS NOT NULL
                   AND destination_id IN ({marques})
                   AND closed_at > ?
                 ORDER BY closed_at ASC""",
            (*DESTINATIONS, curseur)).fetchall()
    return [dict(r) for r in lignes]


def _ecart(ligne: dict) -> bool:
    """Le niveau capturé diffère-t-il de celui enregistré à l'origine ?

    C'est la question qui donne sa valeur à la colonne : si les deux étaient
    toujours identiques, elle ne mesurerait rien de neuf.
    """
    for vif, origine in (("sl_at_close", "stop_loss"),
                         ("tp_at_close", "take_profit")):
        a, b = ligne.get(vif), ligne.get(origine)
        if a is not None and b is not None and abs(a - b) > 1e-9:
            return True
    return False


def _decrire(ligne: dict) -> str:
    t = ligne["mt5_ticket"]
    pnl = ligne.get("pnl")
    montant = f"{pnl:+.2f} €" if pnl is not None else "montant inconnu"
    tete = (f"{str(ligne['pair'])} "
            f"{str(ligne.get('direction') or '')} "
            f"— ticket {t}, fermé en {str(ligne.get('close_reason'))}"
            f", {montant}")
    if not ligne.get("niveaux_source"):
        return (tete + "\n  ⛔ aucun niveau retenu — le stop réellement "
                "porté à la clôture est perdu")
    corps = (f"\n  stop retenu : {ligne['sl_at_close']}   "
             f"(enregistré à l'ouverture : {ligne['stop_loss']})"
             f"\n  objectif retenu : {ligne['tp_at_close']}   "
             f"(à l'ouverture : {ligne['take_profit']})"
             f"\n  source : {str(ligne['niveaux_source'])}")
    if _ecart(ligne):
        corps += ("\n  🔑 le niveau avait BOUGÉ — c'est précisément ce "
                  "que la base ne savait pas voir")
    else:
        corps += ("\n  niveau inchangé depuis l'ouverture sur ce trade : la "
                  "capture marche, mais ne le démontre pas encore")
    return tete + corps


def _notifier(titre: str, corps: str, dedup: str,
              destination_id: str | None = None) -> None:
    if os.environ.get("DRY_RUN") == "1":
        print(f"  [DRY_RUN] {titre}\n{corps}\n")
        return
    charge = json.dumps({"title": titre, "body": corps, "dedup_key": dedup,
                         "cooldown_seconds": COOLDOWN_SEC}).encode("utf-8")
    rq = urllib.request.Request(
        f"{BASE_URL}&channel={canal_pour(destination_id)}", data=charge,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(rq, timeout=DELAI) as r:
            print(f"  notifié ({r.status}) — ⚠️ c'est NOTRE 200, pas la "
                  "preuve d'arrivée chez Telegram")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"  ENVOI ÉCHOUÉ ({type(e).__name__}: {e})")


def main() -> int:
    etat = _lire_etat()
    curseur = os.environ.get("DEPUIS") or etat.get("curseur")
    if not curseur:
        # Premier passage : on n'alerte PAS sur le passe. Les clotures
        # anterieures au deploiement n'ont legitimement aucun niveau ; crier
        # dessus noierait la vraie premiere verification.
        curseur = _maintenant().isoformat()
        etat["curseur"] = curseur
        _ecrire_etat(etat)
        print(f"curseur initialise a {curseur} — rien a juger sur le passe")
        return 0

    try:
        lignes = clotures_depuis(curseur)
    except sqlite3.Error as e:
        # ⛔ Une base illisible n'est PAS « aucune cloture ». Le dire, et ne
        # surtout pas avancer le curseur.
        _notifier("⚠️ Sonde capture des niveaux : base illisible",
                  f"Impossible de lire {DB} : "
                  f"{str(e)}.\n\nCe n'est pas « aucune clôture », "
                  "c'est « on ne sait pas ».",
                  dedup="capture-niveaux-illisible")
        return 1

    limite = _maintenant() - timedelta(minutes=GRACE_MIN)
    jugeables, trop_recentes = [], 0
    for l in lignes:
        d = _instant(l.get("closed_at"))
        if d is None or d > limite:
            trop_recentes += 1
            continue
        jugeables.append(l)

    print(f"curseur {curseur} · {len(lignes)} clôture(s) MT5 depuis · "
          f"{len(jugeables)} jugeable(s), {trop_recentes} trop récente(s)")

    if not jugeables:
        # ⚠️ Ne PAS avancer le curseur : les trop recentes doivent revenir.
        return 0

    manquantes = [l for l in jugeables if not l.get("niveaux_source")]
    capturees = [l for l in jugeables if l.get("niveaux_source")]
    for l in jugeables:
        print(f"  {l['mt5_ticket']} {l['pair']} "
              f"source={l.get('niveaux_source') or 'AUCUNE'}")

    if not etat.get("verification_faite"):
        premiere = jugeables[0]
        ok = bool(premiere.get("niveaux_source"))
        titre = ("✅ Capture des niveaux : ça marche" if ok else
                 "⛔ Capture des niveaux : ça NE marche PAS")
        intro = (
            "Première clôture depuis le déploiement du 25/08. Le bridge doit "
            "retenir le stop et l'objectif réellement portés par la "
            "position, pas ceux notés à l'ouverture — MT5 les efface à la "
            "seconde où elle ferme.\n\n")
        pied = ("\n\nÀ partir de maintenant la sonde se tait, sauf si une "
                "clôture arrive sans niveaux retenus."
                if ok else
                "\n\n⛔ À corriger : sans cette capture, toute analyse de "
                "sortie repart sur des niveaux faux dans 44 % des cas.")
        _notifier(titre, intro + _decrire(premiere) + pied,
                  dedup="capture-niveaux-verification")
        etat["verification_faite"] = True
    elif manquantes:
        _notifier(
            f"⛔ {len(manquantes)} clôture(s) sans niveaux retenus",
            "Le bridge n'a pas retenu le stop réellement porté. Le niveau est "
            "définitivement perdu pour ces positions — MT5 ne le "
            "rendra jamais.\n\n"
            + "\n\n".join(_decrire(l) for l in manquantes[:5])
            + "\n\nCauses probables : bridge redémarré juste avant la clôture, "
              "ou monitor arrêté.",
            dedup=f"capture-niveaux-manquantes:{manquantes[-1]['mt5_ticket']}")
    else:
        print(f"  {len(capturees)} clôture(s), toutes capturées — rien à dire")

    etat["curseur"] = jugeables[-1]["closed_at"]
    if not os.environ.get("DEPUIS"):
        _ecrire_etat(etat)
    return 0


if __name__ == "__main__":
    sys.exit(main())
