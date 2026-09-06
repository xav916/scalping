#!/usr/bin/env python3
"""Garde le remplissage de `personal_trades.horizon`.

Posée le 2026-08-26, le jour où l'essai `or-4h-2026-08-26` a été déclaré au banc.

## Ce qu'elle garde

L'essai ne compte que les clôtures portant `horizon = '4h'`. Cette colonne vient
d'une chaîne posée le même jour :

    dispatch -> mt5_pushes.horizon -> (ticket) -> personal_trades.horizon

Avant cette chaîne, l'horizon n'existait **nulle part** dans le persisté : ni sur
le trade, ni dans les 390 676 lignes de `signals`. Il mourait avec l'objet en
mémoire, après avoir pourtant servi à refuser des routes.

> ⛔ **Si le maillon casse, l'essai n'accumulera rien — et un essai qui
> n'accumule rien ressemble exactement à un marché calme.** On attendrait des
> mois avant de découvrir qu'on a attendu pour rien. C'est le motif de
> [[feedback_detection_par_absence]] dans sa forme la plus coûteuse : le silence
> est ici indiscernable du fonctionnement normal.

## Deux régimes, plus un

1. **La première fenêtre remplie** déclenche le message de VÉRIFICATION : la
   chaîne fonctionne, voici combien de trades portent leur horizon.
2. **Ensuite la sonde se tait**, sauf régression — des trades récents dont
   l'horizon est resté vide.
3. **Et elle crie aussi quand l'or clôture sans nourrir l'essai** : c'est le cas
   qui ne ressemble à rien d'anormal, donc celui que personne ne verrait.

## ⛔ Ce qu'elle ne fait pas

Elle **n'avance aucun curseur** et ne juge que sur une fenêtre temporelle, donc
un passage à blanc ne peut rien consommer. Le seul état persisté est « la
confirmation a-t-elle déjà été envoyée » et l'instant de la dernière alerte —
ni l'un ni l'autre n'est écrit en `DRY_RUN`.

## ⛔ Texte SIMPLE, pas de balises

Le corps est `html.escape`é côté serveur : une balise n'y est pas interprétée,
elle s'affiche telle quelle. Mesuré le 26/08 — un corps `AB<b>CD</b>` de 11
caractères en pèse 23 une fois échappé. Un test le verrouille.

Usage :
    python notify_horizon_rempli.py
    DRY_RUN=1 python notify_horizon_rempli.py
    FENETRE_H=48 python notify_horizon_rempli.py
"""
from __future__ import annotations

import json
import os
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

DELAI = 10
DB = os.environ.get("TRADES_DB", "/app/data/trades.db")
ETAT = os.environ.get("ETAT_SONDE", "/app/data/sonde_horizon_rempli.json")
FENETRE_H = int(os.environ.get("FENETRE_H", "24"))
ESSAI = os.environ.get("ESSAI_SLUG", "or-4h-2026-08-26")

#: En dessous, l'absence d'accumulation n'est que la lenteur normale du 4 h.
#: Crier là-dessus rendrait la sonde inaudible, et une sonde inaudible ne garde
#: rien du tout.
SEUIL_OR_SANS_ACCUMULATION = 8

#: ⛔ La chaîne est PROSPECTIVE : les trades antérieurs au déploiement n'ont
#: aucun horizon et n'en auront jamais. Les juger ferait crier la sonde sur un
#: passé qu'aucun correctif ne peut atteindre.
DEPLOI = os.environ.get("DEPUIS_DEPLOI", "2026-08-26T07:20:00+00:00")

DESTINATIONS = ("admin_live", "admin_legacy")

TOKEN = os.environ.get("INFRA_NOTIFY_TOKEN", "shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg")
# channel=infra : c'est une panne d'INSTRUMENTATION, pas un évènement de trading.
# ⛔ Omettre `channel` routerait vers infra par défaut — ce qui tomberait juste
# ici, mais par accident. Le défaut qui a égaré 4 notificateurs du 04/08 au
# 19/08 venait précisément de s'être fié à un défaut.
NOTIFY_URL = ("https://app.scalping-radar.online/api/admin/"
              f"notify-infra-telegram?token={TOKEN}&channel=infra")
COOLDOWN_SEC = 86400


# ─── La décision, isolée pour être testable ─────────────────────────────


def juger(recents: list[dict], essai_n_obs: int, essai_min: int,
          clotures_or_depuis_declaration: int,
          confirmation_deja_envoyee: bool) -> dict:
    """Que faut-il dire, au vu de la fenêtre ? Fonction pure.

    Ordre des verdicts, et il compte : **la régression prime sur la
    confirmation**. Si la toute première fenêtre contient déjà des trous, ce
    serait mentir que d'envoyer un message rassurant avant de se taire.
    """
    manquants = [t for t in recents if not t.get("horizon")]
    remplis = [t for t in recents if t.get("horizon")]

    if manquants:
        return {
            "action": "alerte",
            "manquants": len(manquants), "remplis": len(remplis),
            "message": (
                f"⚠️ L'horizon ne se remplit plus\n\n"
                f"Sur les {len(recents)} derniers trades automatiques, "
                f"{len(manquants)} n'ont pas d'horizon enregistré.\n\n"
                f"Sans lui, l'essai {ESSAI} ne les comptera jamais : "
                f"il attend des clôtures marquées 4 h, et une clôture non marquée "
                f"n'en est pas une.\n\n"
                f"Où regarder : la table mt5_pushes — si la colonne "
                f"horizon y est vide aussi, c'est le dispatch qui ne "
                f"la transmet plus. Si elle y est pleine, c'est la jointure par le "
                f"ticket qui a lâché."),
        }

    if (clotures_or_depuis_declaration >= SEUIL_OR_SANS_ACCUMULATION
            and essai_n_obs == 0):
        return {
            "action": "alerte",
            "manquants": 0, "remplis": len(remplis),
            "message": (
                f"⚠️ L'essai n'accumule rien\n\n"
                f"L'or a clôturé {clotures_or_depuis_declaration} fois depuis "
                f"la déclaration, et l'essai {ESSAI} en compte "
                f"0 sur {essai_min}.\n\n"
                f"Ça ne ressemble pas à une panne — ça ressemble à un marché calme. "
                f"C'est justement pour ça que personne ne le verrait.\n\n"
                f"Cause probable : les clôtures de l'or ne portent pas "
                f"horizon = 4h. Vérifier mt5_pushes puis "
                f"personal_trades.horizon sur XAU/USD."),
        }

    if remplis and not confirmation_deja_envoyee:
        return {
            "action": "confirmation",
            "manquants": 0, "remplis": len(remplis),
            "message": (
                f"✅ La chaîne de l'horizon fonctionne\n\n"
                f"{len(remplis)} trades viennent d'être enregistrés avec leur "
                f"horizon. Avant le 26/08, cette information n'existait nulle part "
                f"une fois le trade passé.\n\n"
                f"L'essai {ESSAI} peut donc se remplir : "
                f"{essai_n_obs} sur {essai_min} clôtures à ce jour.\n\n"
                f"Cette sonde se tait à partir de maintenant, sauf si ça casse."),
        }

    return {"action": "rien", "manquants": 0, "remplis": len(remplis),
            "message": ""}


# ─── Lectures ───────────────────────────────────────────────────────────


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


def trades_recents() -> list[dict]:
    """Trades automatiques créés dans la fenêtre, et après le déploiement.

    ⛔ Aucun curseur : la fenêtre est temporelle, donc un passage ne peut rien
    consommer. Le prix est de rejuger les mêmes lignes ; le cooldown s'en charge.
    """
    depuis = max(
        (_maintenant() - timedelta(hours=FENETRE_H)).isoformat(), DEPLOI)
    marques = ",".join("?" * len(DESTINATIONS))
    with sqlite3.connect(DB) as c:
        c.row_factory = sqlite3.Row
        lignes = c.execute(
            f"""SELECT pair, horizon, created_at, mt5_ticket
                  FROM personal_trades
                 WHERE is_auto = 1
                   AND destination_id IN ({marques})
                   AND created_at > ?
                 ORDER BY created_at ASC""",
            (*DESTINATIONS, depuis)).fetchall()
    return [dict(r) for r in lignes]


def etat_essai() -> tuple[int, int, str | None]:
    """``(n_obs, min_sample, declared_at)`` de l'essai surveillé.

    ⛔ Passe par `_clotures_eligibles`, jamais par `evaluate` : consulter un
    essai ne doit pas dépenser son unique verdict.
    """
    try:
        from backend.services import research_bench as rb
        t = rb.get_trial(ESSAI)
        # ⛔ Un essai ABANDONNE ou JUGE n'est plus a alimenter. Sans ce test,
        # la sonde continuait de crier « l'essai n'accumule rien » sur un essai
        # que personne n'alimente plus — le bruit exact qu'on cherche a
        # supprimer, et qui finit par faire ignorer les vraies alertes.
        if not t or t.get("status") != "open":
            return (0, 0, None)
        n = len(rb._clotures_eligibles(t["selector"], t["declared_at"]))
        return (n, t["min_sample"], t["declared_at"])
    except Exception as e:  # noqa: BLE001 — une sonde ne casse pas la prod
        print(f"  état de l'essai illisible ({e})")
        return (0, 0, None)


def clotures_or_depuis(declared_at: str | None) -> int:
    if not declared_at:
        return 0
    marques = ",".join("?" * len(DESTINATIONS))
    with sqlite3.connect(DB) as c:
        return int(c.execute(
            f"""SELECT COUNT(*) FROM personal_trades
                 WHERE pair = 'XAU/USD' AND status = 'CLOSED' AND is_auto = 1
                   AND destination_id IN ({marques}) AND closed_at > ?""",
            (*DESTINATIONS, declared_at)).fetchone()[0])


# ─── État, envoi ────────────────────────────────────────────────────────


def _lire_etat() -> dict:
    try:
        with open(ETAT, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _ecrire_etat(etat: dict) -> None:
    # ⛔ Un passage « à blanc » qui marque la confirmation comme envoyée n'est
    # pas à blanc : le vrai passage se tairait ensuite pour toujours.
    if os.environ.get("DRY_RUN") == "1":
        print("  [DRY_RUN] état NON écrit")
        return
    try:
        with open(ETAT, "w", encoding="utf-8") as f:
            json.dump(etat, f, indent=1)
    except OSError as e:
        print(f"  état non écrit ({e}) — le message pourra se répéter")


def envoyer(titre: str, message: str) -> None:
    if os.environ.get("DRY_RUN") == "1":
        print(f"  [DRY_RUN] n'envoie pas :\n{message}\n")
        return
    # ⛔ La clé est `body`. Mesuré en production le 26/08 : `{"message": ...}`
    # rend `chars: 10`, soit le TITRE SEUL — le corps est ignoré EN SILENCE.
    # C'est le défaut que « prouver que l'alerte arrive » a fait tomber, et
    # qu'aucun 200 n'aurait révélé.
    charge = json.dumps({"title": titre, "body": message,
                         "dedup_key": "sonde-horizon",
                         "cooldown_seconds": COOLDOWN_SEC}).encode("utf-8")
    rq = urllib.request.Request(
        NOTIFY_URL, data=charge,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(rq, timeout=DELAI) as r:
            print(f"  notifié ({r.status}) — ⚠️ c'est NOTRE 200, pas la preuve "
                  "d'arrivée chez Telegram")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"  ENVOI ÉCHOUÉ ({type(e).__name__}: {e})")


def main() -> int:
    etat = _lire_etat()
    recents = trades_recents()
    n_obs, minimum, declared_at = etat_essai()
    or_clos = clotures_or_depuis(declared_at)

    print(f"fenêtre {FENETRE_H} h : {len(recents)} trades auto · "
          f"essai {n_obs}/{minimum} · or clôturé {or_clos} fois depuis déclaration")

    v = juger(recents, n_obs, minimum, or_clos,
              bool(etat.get("confirmation_envoyee")))
    print(f"  verdict : {v['action']}  (remplis {v['remplis']}, "
          f"manquants {v['manquants']})")

    if v["action"] == "rien":
        return 0

    if v["action"] == "alerte":
        derniere = etat.get("derniere_alerte")
        if derniere:
            try:
                ecart = (_maintenant() - datetime.fromisoformat(derniere)).total_seconds()
                if ecart < COOLDOWN_SEC:
                    print(f"  alerte retenue (cooldown, {int(ecart)}s < {COOLDOWN_SEC}s)")
                    return 0
            except ValueError:
                pass
        envoyer("Sonde horizon", v["message"])
        etat["derniere_alerte"] = _maintenant().isoformat()
    else:
        envoyer("Sonde horizon", v["message"])
        etat["confirmation_envoyee"] = True
        etat["confirmee_le"] = _maintenant().isoformat()

    _ecrire_etat(etat)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
