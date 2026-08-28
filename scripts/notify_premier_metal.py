#!/usr/bin/env python3
"""Le premier ordre OR ou ARGENT qui PART vraiment — et sinon, qui l'arrête.

Posé le 2026-08-28, le jour où la poche des métaux a été ouverte à 14 % de
l'equity. Le budget existe, mais **rien ne prouve qu'un ordre en sorte** :

- côté bridge, la poche a cessé de refuser (`bridge_plafond_risque` : 2 refus
  ce jour-là, tous deux AVANT le déploiement, zéro depuis) ;
- côté radar, l'or continue d'être arrêté plus haut — 10 `fees_exceed_edge`,
  6 `correlated_exposure`, 1 `pattern_not_allowed` sur la première heure et
  demie, et **126 des 128 refus du jour portent sur du 5 minutes**.

> **Une porte qu'on ouvre ne prouve pas qu'un ordre passe.** Le silence qui
> suit ressemble trait pour trait au silence d'avant.

Cette sonde répond donc à deux questions distinctes, et les distingue :

1. **un ordre métal est-il PARTI ?** — une ligne `filled` sur XAU/XAG dans
   l'audit du courtier, lue par `/audit?since_id=`. C'est le seul fait qui
   prouve la chaîne complète ;
2. **sinon, qui l'a arrêté ?** — le décompte des refus par motif, au plus une
   fois par 24 h, pour que « rien ne part » ne se lise jamais comme « rien ne
   se passe ».

⛔ **Le curseur n'avance QUE sur un envoi confirmé.** Ni en `DRY_RUN`, ni
quand Telegram a refusé : une observation ne doit rien déplacer, et un
événement dont l'annonce a échoué doit être réannoncé au passage suivant.
C'est la leçon de la sonde de capture, dont le `DRY_RUN` avançait l'état.

⛔ **Au premier passage, on n'annonce RIEN** : on note l'id courant. Sans ça,
la sonde déclarerait « premier ordre métal ! » sur une ligne de mai.

⚠️ Le corps est passé dans `html.escape` par l'endpoint : **texte simple**,
aucune balise. Seul le `title` est mis en gras, par l'endpoint lui-même.

Usage :
    python notify_premier_metal.py
    DRY_RUN=1 python notify_premier_metal.py     # affiche, n'envoie ni n'avance
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, "/app")

DELAI = 10

# Nommés un par un, comme dans `bridge.py::_poche_du_symbole` : filtrer sur
# « métal » embarquerait le platine et le palladium, qui ne sont pas le sujet.
SYMBOLES_METAUX = ("XAU", "GOLD", "XAG", "SILVER")

DESTINATIONS_SURVEILLEES = ("admin_legacy", "admin_live")

ETAT = Path(os.environ.get("PREMIER_METAL_ETAT_PATH",
                           "/app/data/premier_metal.json"))

TOKEN = os.environ.get("INFRA_NOTIFY_TOKEN",
                       "shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg")
# channel=sales : un ordre qui part est un événement de TRADING, pas
# d'infrastructure. ⛔ Omettre `channel` route vers le fil infra EN SILENCE.
NOTIFY_URL = ("https://app.scalping-radar.online/api/admin/"
              f"notify-infra-telegram?token={TOKEN}&channel=sales")

# Le rapport de silence est un digest, pas une alarme : au plus un par jour.
SILENCE_SEC = int(os.environ.get("PREMIER_METAL_SILENCE_SEC", "86400"))


# --------------------------------------------------------------------------
# Mesure — fonctions PURES, testables sans réseau
# --------------------------------------------------------------------------

def est_metal(symbole: str | None) -> bool:
    s = (symbole or "").upper()
    return any(m in s for m in SYMBOLES_METAUX)


def metaux_partis(lignes) -> list[dict]:
    """Les ordres métal qui ont VRAIMENT atteint le courtier.

    ⛔ `filled` et rien d'autre. Un `paper`, un `blocked` ou un `rejected`
    décrivent une intention, pas un ordre parti — et c'est justement la
    confusion que cette sonde existe pour empêcher.
    """
    partis = []
    for l in lignes or []:
        if not isinstance(l, dict):
            continue
        if str(l.get("status") or "").lower() != "filled":
            continue
        if not est_metal(l.get("symbol")):
            continue
        partis.append(l)
    return partis


def id_max(lignes) -> int | None:
    """Plus grand `id` de la page. `None` si la page est vide ou illisible —
    jamais 0, qui ferait repartir le curseur au début de l'histoire."""
    ids = []
    for l in lignes or []:
        try:
            ids.append(int((l or {}).get("id")))
        except (TypeError, ValueError):
            continue
    return max(ids) if ids else None


def doit_parler_du_silence(dernier_iso: str | None, maintenant: datetime,
                           silence_sec: int) -> bool:
    """A-t-on déjà dit récemment que rien ne partait ?

    Jamais dit ⇒ oui. Le digest ne remplace pas l'alerte : il ne se déclenche
    que lorsqu'aucun ordre métal n'est parti.
    """
    if not dernier_iso:
        return True
    try:
        dernier = datetime.fromisoformat(str(dernier_iso))
    except ValueError:
        return True
    if dernier.tzinfo is None:
        dernier = dernier.replace(tzinfo=timezone.utc)
    return (maintenant - dernier).total_seconds() >= silence_sec


def message_depart(destination: str, ordres: list[dict]) -> tuple[str, str]:
    """⚠️ Texte SIMPLE : l'endpoint échappe le corps, une balise s'y afficherait
    telle quelle."""
    o = ordres[0]
    lignes = [
        f"Un ordre {o.get('symbol')} {o.get('direction')} est parti chez le "
        f"courtier sur {destination}.",
        "",
        f"ticket   {o.get('ticket')}",
        f"lots     {o.get('lots')}",
        f"entree   {o.get('entry')}",
        f"stop     {o.get('sl')}",
        f"quand    {str(o.get('created_at'))[:19]}",
    ]
    if len(ordres) > 1:
        lignes += ["", f"({len(ordres) - 1} autre(s) sur le meme passage.)"]
    lignes += [
        "",
        "C'est le premier fait qui prouve la chaine complete depuis "
        "l'ouverture de la poche metaux a 14 % : le budget existait, rien ne "
        "disait qu'un ordre en sortait.",
    ]
    return (f"🥇 Ordre metal PARTI — {destination}", "\n".join(lignes))


def message_silence(refus: list[tuple], heures: int,
                    horizons: dict) -> tuple[str, str]:
    """Le digest : aucun ordre metal parti, voici qui les arrete."""
    lignes = [f"Aucun ordre or ni argent n'est parti depuis {heures} h.",
              ""]
    if not refus:
        lignes += ["Et aucun signal metal n'a ete refuse non plus : il n'en "
                   "arrive tout simplement pas. La poche des 14 % est prete, "
                   "rien ne s'y presente."]
    else:
        lignes.append("Ce qui les arrete, par motif :")
        for motif, n in refus:
            lignes.append(f"  {n:4d}  {motif}")
        if horizons:
            detail = ", ".join(f"{h or 'inconnu'} {n}"
                               for h, n in sorted(horizons.items(),
                                                  key=lambda kv: -kv[1]))
            lignes += ["", f"Horizons de ces signaux : {detail}"]
        # ⛔ Ne JAMAIS affirmer « la poche ne refuse rien » sans regarder :
        # le premier essai a blanc listait 20 `bridge_plafond_risque` juste
        # au-dessus de cette phrase. Une conclusion que la liste dementait
        # trois lignes plus haut vaut moins que pas de conclusion.
        plafond = next((n for m, n in refus if m == "bridge_plafond_risque"), 0)
        if plafond:
            lignes += ["",
                       f"⚠️ Dont {plafond} refus par le plafond de risque "
                       "lui-meme. A verifier : ils peuvent dater d'avant "
                       "l'ouverture de la poche."]
        else:
            lignes += ["",
                       "⛔ Aucun de ces refus n'est le plafond de risque : la "
                       "poche metaux ne refuse rien."]
        lignes += ["",
                   "Desserrer une de ces portes pour voir passer un ordre "
                   "fabriquerait le resultat au lieu de le mesurer."]
    return ("⏳ Toujours aucun ordre metal parti", "\n".join(lignes))


# --------------------------------------------------------------------------
# Lectures
# --------------------------------------------------------------------------

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


def _lignes_audit(dest, depuis_id):
    """Page d'audit après `depuis_id`. `(lignes, ok)`."""
    chemin = f"/audit?limit=500&since_id={int(depuis_id)}"
    charge, ok = _appel(dest, chemin)
    if not ok or not isinstance(charge, dict):
        return None, False
    lignes = charge.get("orders")
    if lignes is None:
        lignes = charge.get("rows")
    if not isinstance(lignes, list):
        return None, False
    return lignes, True


def _refus_metaux(heures: int) -> tuple[list[tuple], dict]:
    """Refus de signaux métal des `heures` dernières heures, par motif.

    Lecture seule de `signal_rejections`. Rend aussi la répartition par
    horizon : le 28/08, 126 refus sur 128 portaient sur du 5 minutes, et sans
    ce chiffre on chercherait la cause du mauvais côté.
    """
    import sqlite3
    from collections import Counter
    try:
        from backend.services.trade_log_service import _DB_PATH
    except ImportError:
        return [], {}
    depuis = (datetime.now(timezone.utc)
              - timedelta(hours=heures)).isoformat()
    motifs, horizons = Counter(), Counter()
    try:
        with sqlite3.connect(f"file:{_DB_PATH}?mode=ro", uri=True) as c:
            for code, details in c.execute(
                    "SELECT reason_code, details FROM signal_rejections "
                    "WHERE created_at >= ? AND (pair LIKE '%XAU%' "
                    "OR pair LIKE '%XAG%')", (depuis,)):
                motifs[code] += 1
                try:
                    horizons[json.loads(details or "{}").get("horizon")] += 1
                except (ValueError, AttributeError):
                    horizons[None] += 1
    except sqlite3.Error as e:
        print(f"  refus illisibles ({e})")
        return [], {}
    return motifs.most_common(), dict(horizons)


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
    """Rend **True seulement si l'envoi est confirmé**.

    ⛔ On lit `sent` dans la réponse. Un POST qui aboutit ne prouve pas qu'un
    message est arrivé — c'est exactement ainsi que le moniteur est resté muet
    trois mois avec un jeton mort.
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
    envoye = bool(reponse.get("sent")) or reponse.get("skipped") == "cooldown"
    print(f"  reponse : {reponse}")
    return envoye


def main() -> int:
    try:
        from backend.services.destinations_registry import DESTINATIONS
    except ImportError as exc:
        print(f"registre des destinations illisible : {exc}")
        return 1

    etat = _charger_etat()
    nouveau = dict(etat)
    quelque_chose_est_parti = False

    for did in DESTINATIONS_SURVEILLEES:
        dest = DESTINATIONS.get(did)
        if dest is None:
            continue
        print(f"{did} :")
        curseur = etat.get(f"curseur:{did}")

        if curseur is None:
            # Premier passage : on note où on en est, sans rien annoncer.
            lignes, ok = _lignes_audit(dest, 0)
            if not ok:
                print("    audit illisible — curseur NON pose")
                continue
            # `/audit?since_id=0` rend les 500 PREMIERES lignes : on remonte
            # page par page jusqu'a la fin pour poser le curseur au present.
            dernier = id_max(lignes)
            while lignes and len(lignes) >= 500:
                lignes, ok = _lignes_audit(dest, dernier)
                if not ok:
                    break
                dernier = id_max(lignes) or dernier
            if dernier is None:
                print("    audit vide — curseur NON pose")
                continue
            nouveau[f"curseur:{did}"] = dernier
            print(f"    premier passage : curseur pose a {dernier}, "
                  "rien annonce (une ligne de mai n'est pas un premier ordre)")
            continue

        lignes, ok = _lignes_audit(dest, curseur)
        if not ok:
            print("    audit illisible — curseur inchange")
            continue
        partis = metaux_partis(lignes)
        borne = id_max(lignes)
        print(f"    {len(lignes)} ligne(s) depuis l'id {curseur}, "
              f"{len(partis)} metal(aux) parti(s)")

        if not partis:
            if borne is not None:
                nouveau[f"curseur:{did}"] = borne
            continue

        quelque_chose_est_parti = True
        titre, corps = message_depart(did, partis)
        print(f"  ALERTE : {len(partis)} ordre(s) metal parti(s)")
        if _notifier(titre, corps, dedup=f"metal_parti:{did}:{borne}"):
            # ⛔ Le curseur n'avance qu'ici. Une annonce ratee doit etre
            # rejouee au passage suivant, pas perdue.
            nouveau[f"curseur:{did}"] = borne
        else:
            print("    curseur NON avance — l'evenement sera rejoue")

    # ── Digest de silence ────────────────────────────────────────────────
    maintenant = datetime.now(timezone.utc)
    heures = max(1, SILENCE_SEC // 3600)
    if quelque_chose_est_parti:
        print("silence : sans objet, quelque chose est parti")
    elif doit_parler_du_silence(etat.get("dernier_silence"), maintenant,
                                SILENCE_SEC):
        refus, horizons = _refus_metaux(heures)
        titre, corps = message_silence(refus, heures, horizons)
        print(f"silence : {len(refus)} motif(s) de refus sur {heures} h")
        if _notifier(titre, corps, dedup="metal_silence"):
            nouveau["dernier_silence"] = maintenant.isoformat()
    else:
        print("silence : deja dit recemment")

    if os.environ.get("DRY_RUN") == "1":
        # ⛔ Une observation ne deplace RIEN. Le DRY_RUN de la sonde de
        # capture avancait son curseur : on ne refait pas ca.
        print("[DRY_RUN] etat NON ecrit")
        return 0
    _ecrire_etat(nouveau)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
