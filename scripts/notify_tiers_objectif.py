#!/usr/bin/env python3
"""Une position OR ou ARGENT a fait UN TIERS du chemin vers son objectif.

Demandé le 2026-08-28 : être prévenu dès que le P&L flottant dépasse le tiers
du gain visé. Deux restrictions demandées, et elles réduisent le bruit d'un
ordre de grandeur :

- le compte **réel IC Markets seul** — le démo porte six positions en
  permanence et noierait le fil ;
- **l'or et l'argent seuls** — les deux instruments de la poche des 14 %
  ouverte le jour même, et les seuls dont le mouvement justifie qu'on regarde.

## Le seuil se décide sur les PRIX, pas sur les euros

    profit        = acquis          × k
    gain visé     = distance_objectif × k

`k` étant strictement positif, `profit >= gain_visé / 3` équivaut exactement à
`acquis >= distance_objectif / 3`. On tranche donc sur les prix, que le
courtier publie tous, plutôt que sur `k` — qui n'est PAS dérivable pour une
position pile à son prix d'entrée (division par zéro). Le montant en euros
sert au message, jamais à la décision.

> **Décider sur ce qui est toujours mesurable, rapporter sur ce qui est
> parlant.** Confondre les deux fait dépendre une alerte d'un cas limite.

## ⛔ Une position SANS objectif ne peut pas être mesurée

`tp = 0` : il n'existe aucun chemin dont on ferait un tiers. Elle ne
déclenchera donc jamais — et un non-événement invisible est exactement la
forme de silence que ce dépôt paie depuis des mois. Leur nombre est donc dit
**dans le message**, là où quelqu'un lit déjà, plutôt que dans une seconde
notification que personne n'a demandée.

## Une seule fois par ticket

Franchir le tiers est un événement, pas un état. Le ticket est mémorisé après
un envoi **confirmé** ; la mémoire est ensuite élaguée des tickets fermés.

⚠️ Au premier passage, les positions DÉJÀ au-delà du tiers sont annoncées :
c'est l'état courant, et le demandeur veut le connaître. Contrairement à la
sonde du premier ordre métal, il n'y a pas d'histoire ancienne à rejouer —
seulement des positions vivantes.

Usage :
    python notify_tiers_objectif.py
    DRY_RUN=1 python notify_tiers_objectif.py     # affiche, n'envoie ni n'écrit
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

DELAI = 10

# Réel IC Markets seul. Le démo porte six positions en permanence.
DESTINATION = os.environ.get("TIERS_OBJECTIF_DESTINATION", "admin_live")

# ⛔ La liste des métaux est IMPORTÉE, pas recopiée. Elle vit déjà dans
# `bridge.py` (la poche des 14 %), dans la sonde de saturation et dans la
# sonde du premier ordre métal : les deux premières tournent sur des machines
# différentes et doivent dupliquer, mais ces deux-ci partagent le même
# conteneur. Une quatrième copie serait une divergence en attente.
#
# Pas de repli si l'import échoue : une liste de métaux devinée alerterait sur
# les mauvaises positions, ce qui est pire que de ne pas démarrer.
from scripts.notify_premier_metal import est_metal  # noqa: E402

# La fraction du chemin. Réglable, mais c'est un tiers qui a été demandé.
FRACTION = float(os.environ.get("TIERS_OBJECTIF_FRACTION", "0.3333333"))

ETAT = Path(os.environ.get("TIERS_OBJECTIF_ETAT_PATH",
                           "/app/data/tiers_objectif.json"))

TOKEN = os.environ.get("INFRA_NOTIFY_TOKEN",
                       "shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg")
# channel=sales : une position qui avance est un événement de TRADING.
# ⛔ Omettre `channel` route vers le fil infra EN SILENCE.
NOTIFY_URL = ("https://app.scalping-radar.online/api/admin/"
              f"notify-infra-telegram?token={TOKEN}&channel=sales")


# --------------------------------------------------------------------------
# Mesure — fonctions PURES, testables sans réseau
# --------------------------------------------------------------------------

def _sens_vente(position: dict) -> bool:
    return str(position.get("type") or "").lower().startswith("s")


def mesurer(position: dict) -> dict:
    """Où en est cette position sur le chemin de son objectif ?

    Rend ``{mesurable, part, acquis, distance, profit, gain_vise, motif}``.

    ⛔ `mesurable=False` porte toujours un `motif`. « Pas d'objectif » et
    « prix illisible » n'appellent pas la même décision, et les confondre
    ferait passer une donnée cassée pour un choix de trading.
    """
    vide = {"mesurable": False, "part": None, "acquis": None,
            "distance": None, "profit": None, "gain_vise": None}
    try:
        entree = float(position["price_open"])
        courant = float(position["price_current"])
        tp = float(position.get("tp") or 0.0)
    except (TypeError, ValueError, KeyError):
        return {**vide, "motif": "prix illisibles"}

    if entree <= 0 or courant <= 0:
        return {**vide, "motif": "prix illisibles"}
    if tp <= 0:
        return {**vide, "motif": "aucun objectif posé"}

    vente = _sens_vente(position)
    acquis = (entree - courant) if vente else (courant - entree)
    distance = (entree - tp) if vente else (tp - entree)
    if distance <= 0:
        # Objectif du mauvais côté de l'entrée : la position ne peut pas
        # l'atteindre en gagnant. Mesuré sur 14 % des TP stockés en août —
        # ici c'est le TP VIVANT du courtier, donc c'est un vrai defaut.
        return {**vide, "motif": "objectif du mauvais côté de l'entrée"}

    # Le montant en euros n'entre PAS dans la décision : il peut manquer.
    profit = position.get("profit")
    try:
        profit = float(profit)
    except (TypeError, ValueError):
        profit = None
    gain_vise = None
    if profit is not None and abs(acquis) > 1e-12:
        k = profit / acquis
        if k > 0:
            gain_vise = distance * k

    return {"mesurable": True, "part": acquis / distance, "acquis": acquis,
            "distance": distance, "profit": profit, "gain_vise": gain_vise,
            "motif": "ok"}


# Tolérance sur la comparaison du seuil. ⛔ Sans elle, une position PILE au
# tiers ne déclenche pas : `4598 + 52 × 1/3` puis la soustraction rendent
# 0,33333315 au lieu de 0,3333333 — l'erreur de représentation à une magnitude
# de 4 598. Le seuil est inclusif, il doit le rester à la limite exacte.
# Même epsilon que la porte de la soupape d'équilibre.
_EPSILON = 1e-9


def franchit(mesure: dict, fraction: float) -> bool:
    """A-t-elle dépassé la fraction du chemin ? Non mesurable ⇒ non."""
    return (bool(mesure.get("mesurable"))
            and mesure["part"] >= fraction - _EPSILON)


def a_annoncer(positions, deja: set, fraction: float) -> tuple[list, list]:
    """``(à annoncer, non mesurables)``. Fonction pure.

    ⛔ Les non mesurables sont rendues À PART, jamais jetées : une position
    sans objectif ne déclenchera jamais, et ce silence-là doit se voir. Le
    décompte ne porte QUE sur les métaux : annoncer « 4 positions non
    mesurables » en comptant du forex qu'on ne surveille pas serait une
    inquiétude fabriquée.
    """
    a_dire, muettes = [], []
    for p in positions or []:
        if not isinstance(p, dict):
            continue
        if not est_metal(p.get("symbol")):
            continue
        m = mesurer(p)
        if not m["mesurable"]:
            muettes.append((p, m))
            continue
        if str(p.get("ticket")) in deja:
            continue
        if franchit(m, fraction):
            a_dire.append((p, m))
    return a_dire, muettes


def _eur(x) -> str:
    if x is None:
        return "non dérivable"
    return f"{x:,.2f}".replace(",", " ").replace(".", ",") + " €"


def message(position: dict, mesure: dict, muettes: int) -> tuple[str, str]:
    """⚠️ TEXTE SIMPLE : l'endpoint passe le corps dans `html.escape`."""
    sym = position.get("symbol")
    sens = str(position.get("type") or "").lower()
    reste = (None if mesure["gain_vise"] is None or mesure["profit"] is None
             else mesure["gain_vise"] - mesure["profit"])
    lignes = [
        f"{sym} {sens} — {mesure['part'] * 100:.0f} % du chemin vers "
        "l'objectif est fait.",
        "",
        f"P&L en cours   {_eur(mesure['profit'])}",
        f"gain vise      {_eur(mesure['gain_vise'])}",
        f"reste a faire  {_eur(reste)}",
        "",
        f"ticket    {position.get('ticket')}",
        f"entree    {position.get('price_open')}",
        f"prix      {position.get('price_current')}",
        f"objectif  {position.get('tp')}",
        f"stop      {position.get('sl')}",
    ]
    if muettes:
        lignes += [
            "",
            f"⚠️ {muettes} autre(s) position(s) metal sans objectif mesurable : "
            "elles ne declencheront JAMAIS cette alerte, quoi qu'elles fassent.",
        ]
    lignes += [
        "",
        "Ce message ne demande rien. La gestion de sortie a mesure "
        "-0,329 R par trade sur l'or : intervenir a la main sur cette "
        "information est precisement ce qui a coute.",
    ]
    return (f"🎯 Un tiers de l'objectif — {sym} {sens}", "\n".join(lignes))


# --------------------------------------------------------------------------
# Lectures et envoi
# --------------------------------------------------------------------------

def _positions(dest) -> list | None:
    """`GET /positions`. **`None` = lecture ratée**, pas « aucune position »."""
    url = os.environ.get(dest.url_env or "", "")
    if not url:
        return None
    cle = os.environ.get(dest.key_env or "", "")
    entetes = {dest.key_header: cle} if cle and dest.key_header else {}
    try:
        rq = urllib.request.Request(url.rstrip("/") + "/positions",
                                    headers=entetes)
        with urllib.request.urlopen(rq, timeout=DELAI) as r:
            if r.status != 200:
                return None
            charge = json.load(r)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
        print(f"  lecture impossible ({type(e).__name__}: {e})")
        return None
    positions = charge.get("positions") if isinstance(charge, dict) else None
    return positions if isinstance(positions, list) else None


def _charger_etat() -> dict:
    try:
        return json.loads(ETAT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _ecrire_etat(etat: dict) -> None:
    try:
        ETAT.parent.mkdir(parents=True, exist_ok=True)
        ETAT.write_text(json.dumps(etat, sort_keys=True), encoding="utf-8")
    except OSError as e:
        print(f"  etat non ecrit ({e})")


def _notifier(titre: str, corps: str, dedup: str) -> bool:
    """**True seulement si l'envoi est confirmé** (`sent` lu dans la réponse).

    ⛔ Un POST qui aboutit ne prouve pas qu'un message est arrivé — c'est ainsi
    que le moniteur est resté muet trois mois avec un jeton mort.
    """
    if os.environ.get("DRY_RUN") == "1":
        print(f"  [DRY_RUN] {titre}\n{corps}\n")
        return False
    charge = json.dumps({"title": titre, "body": corps,
                         "dedup_key": dedup}).encode("utf-8")
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
    return bool(reponse.get("sent")) or reponse.get("skipped") == "cooldown"


def main() -> int:
    try:
        from backend.services.destinations_registry import DESTINATIONS
    except ImportError as exc:
        print(f"registre des destinations illisible : {exc}")
        return 1

    dest = DESTINATIONS.get(DESTINATION)
    if dest is None:
        print(f"destination inconnue : {DESTINATION}")
        return 1

    positions = _positions(dest)
    if positions is None:
        # ⛔ Un bridge muet ne vaut pas « aucune position au tiers ». On ne
        # touche pas l'etat : le franchissement sera vu au passage suivant.
        print(f"{DESTINATION} : positions illisibles — etat inchange")
        return 0

    etat = _charger_etat()
    deja = set(etat.get("annonces") or [])
    a_dire, muettes = a_annoncer(positions, deja, FRACTION)
    metaux = [p for p in positions
              if isinstance(p, dict) and est_metal(p.get("symbol"))]
    print(f"{DESTINATION} : {len(positions)} position(s) dont "
          f"{len(metaux)} metal(aux), {len(a_dire)} au-dela de "
          f"{FRACTION:.0%}, {len(muettes)} non mesurable(s)")
    for p, m in muettes:
        print(f"    non mesurable : ticket {p.get('ticket')} "
              f"{p.get('symbol')} — {m['motif']}")

    annonces = set(deja)
    for p, m in a_dire:
        titre, corps = message(p, m, len(muettes))
        print(f"  ALERTE {p.get('symbol')} ticket {p.get('ticket')} "
              f"— {m['part']:.0%} du chemin")
        if _notifier(titre, corps, dedup=f"tiers_objectif:{p.get('ticket')}"):
            # ⛔ Le ticket n'est retenu qu'ici : une annonce ratee doit etre
            # rejouee au passage suivant, pas perdue.
            annonces.add(str(p.get("ticket")))
        else:
            print("    ticket NON retenu — l'evenement sera rejoue")

    # Elagage : on ne garde que les tickets encore ouverts, sinon le fichier
    # grossit sans fin et on ne saurait plus le relire.
    ouverts = {str(p.get("ticket")) for p in positions
               if isinstance(p, dict) and est_metal(p.get("symbol"))}
    annonces &= ouverts

    if os.environ.get("DRY_RUN") == "1":
        print("[DRY_RUN] etat NON ecrit")
        return 0
    _ecrire_etat({"annonces": sorted(annonces),
                  "maj": datetime.now(timezone.utc).isoformat()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
