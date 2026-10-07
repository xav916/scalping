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
import socket
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, "/app")

DELAI = 10

# ⛔ LA PATIENCE DU CLIENT DOIT ETRE PLUS GRANDE QUE CELLE DU SERVEUR.
#
# Le 2026-10-07, cette sonde a renvoye 8 fois le MEME ordre metal (ticket
# 1360596228), toutes les 15 min :
#
#     ENVOI ECHOUE (TimeoutError: The read operation timed out)
#     curseur NON avance — l'evenement sera rejoue
#
# ... alors que le message PARTAIT a chaque fois.
#
# ⚠️ Le relais n'est PAS lent en permanence : mesure le soir du 07/10, il
# repond en **0,17 s** (et en 0,03 s quand il refuse l'authentification, donc
# le reseau n'y est pour rien). Ce fut un EPISODE de lenteur Telegram cet
# apres-midi la — le meme qui a fait expirer `veilleur_arret_or` a 15 s.
#
# 🔑 Le defaut n'est donc pas la lenteur, c'est que la patience du client
# etait EGALE a celle du serveur : 10 s ici, et `app.py` attend Telegram
# `httpx.AsyncClient(timeout=10.0)`, plus le DNS, le TLS et nginx — car
# l'appel sort du conteneur et revient par l'URL publique. Des que Telegram
# traine, le client lache AVANT le serveur et prend un succes lent pour un
# echec. Une marge franche suffit a le rendre impossible.
DELAI_NOTIF = int(os.environ.get("PREMIER_METAL_DELAI_NOTIF", "30"))

# Le relais sait taire un doublon — mais SEULEMENT si on lui donne une duree :
# `app.py` teste `if dedup_key and cooldown_seconds > 0`. La sonde envoyait la
# cle SANS la duree, donc la garde du serveur etait INERTE et chaque rejeu
# repartait vraiment.
COOLDOWN_NOTIF = int(os.environ.get("PREMIER_METAL_COOLDOWN", "21600"))

# ⛔ Et si la reponse n'arrive toujours pas : un delai de lecture n'est NI un
# succes NI un echec, c'est « je ne sais pas ». Rejouer indefiniment sur un
# « je ne sais pas » est ce qui a produit les 8 copies. Au-dela de ce nombre
# d'essais sans reponse, on avance le curseur en le DISANT : a ce stade le
# message est presque surement passe plusieurs fois, et continuer est pire.
MAX_ESSAIS_SANS_REPONSE = int(os.environ.get("PREMIER_METAL_MAX_ESSAIS", "3"))

# Nommés un par un, comme dans `bridge.py::_poche_du_symbole` : filtrer sur
# « métal » embarquerait le platine et le palladium, qui ne sont pas le sujet.
SYMBOLES_METAUX = ("XAU", "GOLD", "XAG", "SILVER")

# ⛔ Kraken en etait absent faute d'`/audit` : son bridge n'a pas cet
# endpoint. Il a `/fills`, et sur un exchange un FILL EST un ordre parti — la
# distinction intention/execution que cette sonde protege y est gratuite.
DESTINATIONS_SURVEILLEES = ("admin_legacy", "admin_live", "admin_kraken")

# Types de fill qui ne sont PAS un ordre que nous avons envoye.
#
# ⚠️ On NOMME ce qui est exclu plutot que de lister ce qui est admis : un type
# inconnu passe donc, et se voit. L'inverse rendrait la sonde MUETTE le jour ou
# Kraken renomme un libelle — et un detecteur ne se teste pas sur son silence.
FILL_TYPES_EXCLUS = frozenset({"liquidation", "assignment", "assignor",
                               "assignee"})

ETAT = Path(os.environ.get("PREMIER_METAL_ETAT_PATH",
                           "/app/data/premier_metal.json"))

TOKEN = os.environ.get("INFRA_NOTIFY_TOKEN",
                       "shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg")
# channel=sales : un ordre qui part est un événement de TRADING, pas
# d'infrastructure. ⛔ Omettre `channel` route vers le fil infra EN SILENCE.
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
        # ⚠️ Chez Kraken le stop est un ORDRE SEPARE : le fill ne le porte pas.
        # Afficher « stop None » se lirait comme une position nue.
        (f"stop     {o.get('sl')}" if o.get("sl") is not None
         else "stop     inconnu a cet instant"),
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


def _ms_depuis_iso(iso: str | None) -> int | None:
    """Horodatage ISO -> millisecondes epoque. `None` si illisible.

    ⛔ Jamais 0 : un curseur a zero ferait relire toute l'histoire et
    re-annoncer des ordres de mai comme s'ils partaient a l'instant.
    """
    if not iso:
        return None
    t = str(iso).strip().replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(t)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return int(d.timestamp() * 1000)


def fills_en_lignes_audit(fills) -> list[dict]:
    """Traduit les fills Kraken dans la forme que la sonde sait lire.

    🔑 Sur un exchange, un FILL EST un ordre parti : le `status="filled"` que
    l'audit MT5 porte y est acquis par construction. C'est ce qui rend la
    traduction honnete plutot que complaisante.

    ⚠️ L'`id` est l'horodatage en MILLISECONDES : Kraken n'a pas de compteur
    entier, et `fill_id` est un UUID. L'ordre chronologique est preserve, donc
    le curseur fonctionne — au prix connu suivant : deux fills dans la MEME
    milliseconde et le second serait saute. A quelques ordres par jour, le cas
    ne s'est jamais produit ; il est ecrit ici plutot que tu, pour qu'on sache
    ou regarder s'il arrive.

    ⛔ Le stop n'y figure pas : chez Kraken c'est un ordre independant. On rend
    `None`, et le message le dit — pas un zero, qui se lirait « pas de stop ».
    """
    lignes = []
    for f in fills or []:
        if not isinstance(f, dict):
            continue
        if str(f.get("fill_type") or "").lower() in FILL_TYPES_EXCLUS:
            continue
        ms = _ms_depuis_iso(f.get("fill_time"))
        if ms is None:
            # Sans horodatage lisible, la ligne n'a pas de place dans l'ordre
            # chronologique : la garder casserait le curseur.
            continue
        lignes.append({
            "id": ms,
            "status": "filled",
            "symbol": f.get("symbol"),
            "direction": f.get("side"),
            "ticket": f.get("order_id") or f.get("fill_id"),
            "lots": f.get("size"),
            "entry": f.get("price"),
            "sl": None,
            "created_at": f.get("fill_time"),
        })
    lignes.sort(key=lambda l: l["id"])
    return lignes


def _lignes_fills(dest, depuis_id):
    """Equivalent Kraken de `_lignes_audit`. `(lignes, ok)`.

    ⛔ Le filtrage se fait ICI, apres lecture : `/fills` ne prend pas de
    curseur. Une lecture ratee rend `(None, False)` — « je n'ai pas pu lire »
    n'est pas « aucun ordre ».
    """
    charge, ok = _appel(dest, "/fills")
    if not ok or not isinstance(charge, dict) or not charge.get("ok"):
        return None, False
    lignes = fills_en_lignes_audit(charge.get("fills"))
    return [l for l in lignes if l["id"] > int(depuis_id)], True


def _lignes_du_journal(dest, depuis_id):
    """Le journal du courtier, quel qu'il soit.

    ⚠️ Le bridge Kraken n'a PAS d'`/audit`. Le brancher dessus rendrait
    « illisible » a chaque passage — un silence qu'on lirait comme
    « aucun ordre metal », c'est-a-dire l'inverse de ce que la sonde cherche.
    """
    if getattr(dest, "bridge_type", "") in ("kraken", "kraken_spot"):
        return _lignes_fills(dest, depuis_id)
    return _lignes_audit(dest, depuis_id)


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


def _notifier(titre: str, corps: str, dedup: str,
              destination_id: str | None = None) -> bool | None:
    """Trois états, jamais deux : `True` envoyé, `False` refusé, `None` **sans
    réponse** — et « sans réponse » n'est pas « pas envoyé ».

    ⛔ On lit `sent` dans la réponse. Un POST qui aboutit ne prouve pas qu'un
    message est arrivé — c'est exactement ainsi que le moniteur est resté muet
    trois mois avec un jeton mort.
    """
    if os.environ.get("DRY_RUN") == "1":
        print(f"  [DRY_RUN] {titre}\n{corps}\n")
        return False
    charge = json.dumps({"title": titre, "body": corps,
                         "dedup_key": dedup,
                         # ⛔ Sans cette duree, la garde du relais est inerte.
                         "cooldown_seconds": COOLDOWN_NOTIF}).encode("utf-8")
    rq = urllib.request.Request(
        f"{BASE_URL}&channel={canal_pour(destination_id)}", data=charge,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(rq, timeout=DELAI_NOTIF) as r:
            reponse = json.load(r)
    except (TimeoutError, socket.timeout) as e:
        # ⛔ PAS « echoue » : sans reponse, on ne SAIT pas. Le message est
        # peut-etre parti. C'est l'appelant qui tranche, avec son compteur.
        print(f"  REPONSE NON RECUE apres {DELAI_NOTIF} s ({type(e).__name__}:"
              f" {e}) — l'envoi a peut-etre abouti")
        return None
    except (urllib.error.URLError, OSError, ValueError) as e:
        cause = getattr(e, "reason", None)
        if isinstance(cause, (TimeoutError, socket.timeout)):
            print(f"  REPONSE NON RECUE apres {DELAI_NOTIF} s ({cause!r}) — "
                  f"l'envoi a peut-etre abouti")
            return None
        print(f"  ENVOI ECHOUE ({type(e).__name__}: {e})")
        return False
    envoye = bool(reponse.get("sent")) or reponse.get("skipped") == "cooldown"
    print(f"  reponse : {reponse}")
    return envoye


def _trancher(issue: bool | None, etat: dict, nouveau: dict,
              dedup: str, quoi: str) -> bool:
    """Faut-il considérer l'annonce comme faite ? Arbitre les TROIS états.

    ⛔ Le cas qui a produit les 8 doublons du 2026-10-07 est `issue is None` :
    la réponse n'arrive pas. Rejouer indéfiniment sur un « je ne sais pas »
    envoie un doublon de plus à chaque passage, toutes les 15 min.

    🔑 On compte les essais sans réponse, et au bout de
    `MAX_ESSAIS_SANS_REPONSE` on considère l'annonce faite **en le disant**.
    Se tromper là coûte une alerte manquée ; ne pas trancher coûte une alerte
    répétée sans fin — et une alerte répétée sans fin n'est plus lue.
    """
    cle = f"essais_sans_reponse:{dedup}"
    if issue is True:
        nouveau.pop(cle, None)
        return True
    if issue is False:
        # Un vrai refus : le relais a répondu non. On rejoue.
        nouveau.pop(cle, None)
        return False
    essais = int(etat.get(cle) or 0) + 1
    if essais >= MAX_ESSAIS_SANS_REPONSE:
        nouveau.pop(cle, None)
        print(f"    {essais} essais SANS REPONSE sur {quoi} — annonce "
              f"consideree FAITE : un {essais + 1}e rejeu enverrait surtout un "
              f"doublon de plus")
        return True
    nouveau[cle] = essais
    print(f"    essai {essais}/{MAX_ESSAIS_SANS_REPONSE} sans reponse sur "
          f"{quoi} — on rejouera")
    return False


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
            lignes, ok = _lignes_du_journal(dest, 0)
            if not ok:
                print("    audit illisible — curseur NON pose")
                continue
            # `/audit?since_id=0` rend les 500 PREMIERES lignes : on remonte
            # page par page jusqu'a la fin pour poser le curseur au present.
            dernier = id_max(lignes)
            while lignes and len(lignes) >= 500:
                lignes, ok = _lignes_du_journal(dest, dernier)
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

        lignes, ok = _lignes_du_journal(dest, curseur)
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
        dedup = f"metal_parti:{did}:{borne}"
        print(f"  ALERTE : {len(partis)} ordre(s) metal parti(s)")
        issue = _notifier(titre, corps, dedup=dedup, destination_id=did)
        if _trancher(issue, etat, nouveau, dedup, "l'ordre metal"):
            # ⛔ Le curseur n'avance qu'ici. Une annonce VRAIMENT ratee doit
            # etre rejouee au passage suivant, pas perdue.
            nouveau[f"curseur:{did}"] = borne
        else:
            print("    curseur NON avance — l'evenement sera rejoue")

    # ── Digest de silence ────────────────────────────────────────────────
    maintenant = datetime.now(timezone.utc)
    heures = max(1, SILENCE_SEC // 3600)
    if quelque_chose_est_parti:
        print("silence : sans objet, quelque chose est parti")
        # 🔑 On RETIENT la date du dernier depart. Sans elle, le digest ne
        # savait que ce que CE passage avait vu.
        nouveau["dernier_depart_metal"] = maintenant.isoformat()
    elif not doit_parler_du_silence(etat.get("dernier_depart_metal"),
                                    maintenant, SILENCE_SEC):
        # ⛔ LE 4e DEFAUT DU 2026-10-07, revele le soir meme.
        #
        # A 19h30 UTC la sonde a envoye « Aucun ordre or ni argent n'est parti
        # depuis 24 h » — alors que QUATRE etaient partis l'apres-midi meme
        # (ids 4922, 4926, 4928, 4929). Elle affirmait un fait sur 24 HEURES
        # en ne testant qu'une condition de CE PASSAGE : `quelque_chose_est_
        # parti` ne vaut que pour les lignes neuves lues a l'instant.
        #
        # Les 8 rejeux le masquaient : ils gardaient le drapeau a vrai a chaque
        # passage. Avancer le curseur a la main a leve le masque.
        #
        # > Un message ne doit jamais affirmer plus large que ce qu'il mesure.
        reste = etat.get("dernier_depart_metal")
        print(f"silence : TU — un metal est parti a {reste}, il est faux de "
              f"dire que rien n'est parti depuis {heures} h")
    elif doit_parler_du_silence(etat.get("dernier_silence"), maintenant,
                                SILENCE_SEC):
        refus, horizons = _refus_metaux(heures)
        titre, corps = message_silence(refus, heures, horizons)
        print(f"silence : {len(refus)} motif(s) de refus sur {heures} h")
        issue = _notifier(titre, corps, dedup="metal_silence")
        if _trancher(issue, etat, nouveau, "metal_silence", "le digest"):
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
