#!/usr/bin/env python3
"""Ferme les positions OR et ARGENT avant la cloture du vendredi soir.

Demande le 2026-08-28, un vendredi a 21 h 08 UTC — treize minutes APRES la
cloture de l'or, avec une position `XAUUSD sell` a +17,67 EUR qui passait le
week-end faute de moyen de la fermer. Le bridge n'avait alors que `/kill`, qui
ferme TOUT : fermer l'or obligeait a fermer aussi le forex.

> **Un interrupteur general n'est pas un outil de precision.** Les deux gestes
> portent le meme nom et n'ont rien de commun.

## ⛔ Le garde-fou du JOUR vit ICI, pas seulement dans le cron

Un fichier de cron se copie, s'edite, se duplique en `.bak` — et `cron.d`
charge les `.bak` (mesure : 7 sauvegardes = 240 passages/h au lieu de 30). Un
script qui ferme des positions reelles ne peut pas dependre de l'endroit d'ou
on l'appelle pour savoir s'il a le droit de le faire.

Il refuse donc de tourner hors de sa fenetre : **vendredi, entre
`FENETRE_DEBUT` et `FENETRE_FIN` en UTC**. `FORCER=1` leve la garde, et le
dit dans le message — une exception qui ne se voit pas est une regle qui n'en
est plus une.

## ⚠️ Ce que ce mecanisme EST

De la gestion de sortie systematique — la famille qui a mesure **-0,329 R par
trade sur l'or**, et **+21 %** une fois desarmee. C'est une decision de
Xavier, prise deux fois et maintenue apres que la mesure lui a ete rappelee.
Chaque fermeture est journalisee avec sa raison pour qu'on puisse un jour la
JUGER au lieu d'y croire : `close-reason = pre_weekend_metal`.

Usage :
    python fermer_metaux_avant_weekend.py
    DRY_RUN=1 python fermer_metaux_avant_weekend.py   # affiche, ne ferme rien
    FORCER=1 python fermer_metaux_avant_weekend.py    # hors fenetre, assume
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, "/app")

DELAI = 15

# ⛔ Liste IMPORTEE, pas recopiee : elle vit deja dans `bridge.py` (la poche
# des 14 %) et dans les deux sondes metal. Une quatrieme copie serait une
# divergence en attente, et ici elle designerait ce qu'on FERME.
from scripts.notify_premier_metal import est_metal  # noqa: E402

DESTINATIONS_SURVEILLEES = tuple(
    d.strip() for d in os.environ.get(
        "FERMETURE_METAUX_DESTINATIONS", "admin_legacy,admin_live").split(",")
    if d.strip())

# Fenetre autorisee, en minutes depuis minuit UTC. L'or ferme a 21 h 00 UTC le
# vendredi : on vise 20 h 30, assez tot pour que le spread ne soit pas encore
# celui de la derniere minute, assez tard pour laisser la journee se jouer.
FENETRE_DEBUT = int(os.environ.get("FERMETURE_METAUX_DEBUT_MIN", "1200"))  # 20:00
FENETRE_FIN = int(os.environ.get("FERMETURE_METAUX_FIN_MIN", "1259"))      # 20:59

TOKEN = os.environ.get("INFRA_NOTIFY_TOKEN",
                       "shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg")
# channel=sales : fermer une position est un evenement de TRADING.
# ⛔ Omettre `channel` route vers le fil infra EN SILENCE.
NOTIFY_URL = ("https://app.scalping-radar.online/api/admin/"
              f"notify-infra-telegram?token={TOKEN}&channel=sales")

RAISON = "pre_weekend_metal"


# --------------------------------------------------------------------------
# Mesure — fonctions PURES
# --------------------------------------------------------------------------

def dans_la_fenetre(maintenant: datetime, debut: int, fin: int) -> bool:
    """Vendredi, entre `debut` et `fin` (minutes UTC depuis minuit).

    ⛔ Le jour ET l'heure. Un script qui ferme des positions reelles ne doit
    pas pouvoir s'executer un mardi matin parce qu'on l'a lance a la main pour
    voir ce qu'il dit.
    """
    if maintenant.weekday() != 4:      # 0 = lundi, 4 = vendredi
        return False
    minutes = maintenant.hour * 60 + maintenant.minute
    return debut <= minutes <= fin


def metaux_ouverts(positions) -> list[dict]:
    """Les positions OR/ARGENT de la liste. Le reste n'est pas touche."""
    return [p for p in (positions or [])
            if isinstance(p, dict) and est_metal(p.get("symbol"))]


def _eur(x) -> str:
    try:
        return f"{float(x):,.2f}".replace(",", " ").replace(".", ",") + " €"
    except (TypeError, ValueError):
        return "?"


def message(fermees: list, echouees: list, forcee: bool) -> tuple[str, str]:
    """⚠️ TEXTE SIMPLE : l'endpoint passe le corps dans `html.escape`."""
    total = len(fermees) + len(echouees)
    lignes = []
    if forcee:
        lignes += ["⚠️ Execution FORCEE, hors de la fenetre du vendredi soir.",
                   ""]
    if not total:
        lignes.append("Aucune position or ou argent ouverte avant la cloture.")
    else:
        lignes.append(f"{len(fermees)}/{total} position(s) metal fermee(s) "
                      "avant la cloture du week-end.")
    for d, p, r in fermees:
        lignes += ["",
                   f"✅ {p.get('symbol')} {p.get('type')} · {d}",
                   f"   ticket {p.get('ticket')} · {p.get('volume')} lot",
                   f"   P&L au moment de la fermeture {_eur(p.get('profit'))}"]
    for d, p, r in echouees:
        motif = (r or {}).get("error") or (r or {}).get("message") or "?"
        retcode = (r or {}).get("retcode")
        lignes += ["",
                   f"⛔ {p.get('symbol')} {p.get('type')} · {d} — NON FERMEE",
                   f"   ticket {p.get('ticket')} · {motif}"
                   + (f" (retcode {retcode})" if retcode else ""),
                   "   Elle passe le week-end : verifier a la main."]
    if fermees:
        lignes += ["",
                   "Rappel : fermer systematiquement le vendredi est de la "
                   "gestion de sortie, la famille qui a mesure -0,329 R par "
                   "trade sur l'or. Chaque fermeture porte "
                   f"close-reason={RAISON} pour qu'on puisse la juger."]
    titre = ("🔒 Metaux fermes avant le week-end" if fermees
             else ("⛔ Fermeture metaux EN ECHEC" if echouees
                   else "🔒 Aucun metal a fermer"))
    return titre, "\n".join(lignes)


# --------------------------------------------------------------------------
# Reseau
# --------------------------------------------------------------------------

def _appel(dest, chemin: str, charge: dict | None = None):
    """GET ou POST sur un bridge. Rend `(reponse, ok)`."""
    url = os.environ.get(dest.url_env or "", "")
    if not url:
        return None, False
    cle = os.environ.get(dest.key_env or "", "")
    entetes = {dest.key_header: cle} if cle and dest.key_header else {}
    donnees = None
    if charge is not None:
        donnees = json.dumps(charge).encode("utf-8")
        entetes["Content-Type"] = "application/json"
    try:
        rq = urllib.request.Request(url.rstrip("/") + chemin, data=donnees,
                                    headers=entetes)
        with urllib.request.urlopen(rq, timeout=DELAI) as r:
            return json.load(r), r.status == 200
    except urllib.error.HTTPError as e:
        # ⛔ Le corps d'une erreur porte le MOTIF : le jeter ne laisserait
        # qu'un code, et « 409 » ne dit pas pourquoi le courtier a refuse.
        try:
            return json.load(e), False
        except ValueError:
            return {"error": f"HTTP {e.code}"}, False
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
        return {"error": f"{type(e).__name__}: {e}"}, False


def _notifier(titre: str, corps: str) -> bool:
    if os.environ.get("DRY_RUN") == "1":
        print(f"  [DRY_RUN] {titre}\n{corps}\n")
        return False
    charge = json.dumps({"title": titre, "body": corps,
                         "dedup_key": "fermeture_metaux"}).encode("utf-8")
    rq = urllib.request.Request(
        NOTIFY_URL, data=charge,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(rq, timeout=DELAI) as r:
            reponse = json.load(r)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        print(f"  ENVOI ECHOUE ({type(e).__name__}: {e})")
        return False
    print(f"  reponse : {reponse}")
    return bool(reponse.get("sent"))


def main() -> int:
    maintenant = datetime.now(timezone.utc)
    forcee = os.environ.get("FORCER") == "1"
    if not dans_la_fenetre(maintenant, FENETRE_DEBUT, FENETRE_FIN):
        if not forcee:
            print(f"hors fenetre ({maintenant:%A %H:%M} UTC) — rien fait. "
                  "FORCER=1 pour passer outre.")
            return 0
        print(f"⚠️ HORS FENETRE ({maintenant:%A %H:%M} UTC) mais FORCER=1")

    try:
        from backend.services.destinations_registry import DESTINATIONS
    except ImportError as exc:
        print(f"registre des destinations illisible : {exc}")
        return 1

    fermees, echouees = [], []
    for did in DESTINATIONS_SURVEILLEES:
        dest = DESTINATIONS.get(did)
        if dest is None:
            print(f"{did} : destination inconnue — ignoree")
            continue
        charge, ok = _appel(dest, "/positions")
        if not ok or not isinstance(charge, dict):
            # ⛔ Un bridge muet ne vaut PAS « aucun metal ouvert ». On le dit.
            print(f"{did} : positions illisibles — RIEN FERME, a verifier")
            echouees.append((did, {"symbol": "?", "type": "?", "ticket": "?"},
                             {"error": "positions illisibles"}))
            continue
        metaux = metaux_ouverts(charge.get("positions"))
        print(f"{did} : {len(metaux)} position(s) metal a fermer")
        for p in metaux:
            if os.environ.get("DRY_RUN") == "1":
                print(f"  [DRY_RUN] fermerait #{p.get('ticket')} "
                      f"{p.get('symbol')} ({_eur(p.get('profit'))})")
                fermees.append((did, p, {"ok": True, "dry_run": True}))
                continue
            r, ok = _appel(dest, "/position/close",
                           {"ticket": p.get("ticket"), "raison": RAISON})
            if ok and (r or {}).get("ok"):
                print(f"  ferme #{p.get('ticket')} {p.get('symbol')}")
                fermees.append((did, p, r))
            else:
                print(f"  ECHEC #{p.get('ticket')} {p.get('symbol')} : {r}")
                echouees.append((did, p, r))

    if not fermees and not echouees:
        print("aucun metal ouvert — pas de message")
        return 0
    titre, corps = message(fermees, echouees, forcee)
    _notifier(titre, corps)
    return 0 if not echouees else 1


if __name__ == "__main__":
    raise SystemExit(main())
