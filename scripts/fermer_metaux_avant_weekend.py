#!/usr/bin/env python3
"""Ferme les positions avant la cloture du vendredi soir.

⚠️ **PORTEE ELARGIE le 2026-09-04** : ce script ne ferme plus seulement l'or
et l'argent, mais **tout ce dont le marche ferme** — forex, metaux, petrole,
indices. Un gap de week-end frappe le forex et le petrole exactement comme le
metal ; l'incident du gap WTI en est la preuve. Seules restent ouvertes les
positions dont le marche tourne le week-end (crypto), et **le message les
nomme** : une exclusion silencieuse est une position qu'on croit fermee.

⚠️ Le NOM du fichier reste `fermer_metaux_*` par prudence de deploiement — le
cron, le wrapper `.sh` et le chemin dans l'image y renvoient. Renommer un
jour, hors vendredi.

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

RAISON = "pre_weekend"

# ⛔ Ce que l'on NE ferme PAS : les marches qui tournent le week-end. Les
# fermer ne protegerait d'aucun gap — il n'y en a pas — et priverait la
# position de deux jours de marche.
#
# ⚠️ Reglable, mais jamais vide par accident : une liste vide fermerait AUSSI
# la crypto, et personne ne s'en apercevrait avant le lundi.
TICKERS_WEEKEND = tuple(
    t.strip().upper() for t in os.environ.get(
        "FERMETURE_WEEKEND_EXCLUS",
        "BTC,ETH,BCH,LTC,XRP,ADA,SOL,DOT,LINK,DOGE,BNB,XLM,AVAX,MATIC,UNI,"
        "AAVE,ALGO,ATOM,TRX,SEI,ENS,HBAR,ARB,CRV,LDO,PAXG,MANA,ETHFI,SHIB"
    ).split(",") if t.strip())


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


def traverse_le_weekend(symbole: str | None) -> bool:
    """Ce marche reste-t-il OUVERT pendant le week-end ?

    ⛔ On nomme ce qui est EXCLU, jamais ce qui est inclus. Le 23/08, filtrer
    par classe d'actif avait recoupe 14 des 23 cryptos sans que rien ne le
    dise ; une liste positive aurait le meme defaut ici, mais en pire — elle
    ferait passer une position le week-end au lieu d'en fermer une de trop.

    ⚠️ `startswith` et non `in` : « AUDUSD » contient AUD, pas ADA, mais un
    jour un symbole contiendra par accident un ticker crypto. Les symboles
    crypto commencent par leur ticker (`ETHUSD`, `BCHUSD`).
    """
    s = (symbole or "").upper().replace("/", "").replace("_", "")
    return any(s.startswith(t) for t in TICKERS_WEEKEND)


def a_fermer(positions) -> tuple[list[dict], list[dict]]:
    """``(a fermer, laissees ouvertes)``.

    Depuis le 2026-09-04 on ferme **tout ce dont le marche ferme**, plus
    seulement l'or et l'argent : le week-end, un gap frappe le forex et le
    petrole exactement comme le metal — l'incident du gap WTI en temoigne.

    ⛔ Les positions laissees ouvertes sont RENDUES, pas jetees : le message
    les nomme. Une exclusion silencieuse est une position qu'on croit fermee.
    """
    fermer, laissees = [], []
    for p in (positions or []):
        if not isinstance(p, dict):
            continue
        (laissees if traverse_le_weekend(p.get("symbol")) else fermer).append(p)
    return fermer, laissees


def _eur(x) -> str:
    try:
        return f"{float(x):,.2f}".replace(",", " ").replace(".", ",") + " €"
    except (TypeError, ValueError):
        return "?"


def message(fermees: list, echouees: list, forcee: bool,
            laissees: list | None = None) -> tuple[str, str]:
    """⚠️ TEXTE SIMPLE : l'endpoint passe le corps dans `html.escape`."""
    total = len(fermees) + len(echouees)
    lignes = []
    if forcee:
        lignes += ["⚠️ Execution FORCEE, hors de la fenetre du vendredi soir.",
                   ""]
    if not total:
        lignes.append("Aucune position a fermer avant la cloture du week-end.")
    else:
        lignes.append(f"{len(fermees)}/{total} position(s) fermee(s) avant la "
                      "cloture du week-end.")
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
    # ⛔ Nommer ce qu'on a DELIBEREMENT laisse ouvert. Sans cette liste, une
    # position crypto restee ouverte se lit comme un oubli — ou pire, on croit
    # tout ferme et personne ne regarde.
    if laissees:
        lignes += ["",
                   f"{len(laissees)} position(s) laissee(s) OUVERTE(S) : leur "
                   "marche tourne le week-end, il n'y a pas de gap a eviter."]
        for d, p in laissees:
            lignes.append(f"   • {p.get('symbol')} {p.get('type')} · {d} · "
                          f"ticket {p.get('ticket')}")

    if fermees:
        lignes += ["",
                   "Rappel : fermer systematiquement le vendredi est de la "
                   "gestion de sortie, la famille qui a mesure -0,329 R par "
                   "trade sur l'or. Chaque fermeture porte "
                   f"close-reason={RAISON} pour qu'on puisse la juger."]
    titre = ("🔒 Positions fermees avant le week-end" if fermees
             else ("⛔ Fermeture week-end EN ECHEC" if echouees
                   else "🔒 Aucune position a fermer"))
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

    fermees, echouees, laissees = [], [], []
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
        a_traiter, ouvertes = a_fermer(charge.get("positions"))
        laissees += [(did, p) for p in ouvertes]
        print(f"{did} : {len(a_traiter)} a fermer, {len(ouvertes)} laissee(s) "
              "ouverte(s) (marche week-end)")
        for p in a_traiter:
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
        # ⚠️ Silence seulement s'il n'y avait VRAIMENT rien. S'il reste des
        # positions volontairement ouvertes, on le dit : croire tout ferme est
        # le resultat le plus dangereux.
        if not laissees:
            print("aucune position a fermer — pas de message")
            return 0
    titre, corps = message(fermees, echouees, forcee, laissees)
    _notifier(titre, corps)
    return 0 if not echouees else 1


if __name__ == "__main__":
    raise SystemExit(main())
