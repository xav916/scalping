#!/usr/bin/env python3
"""Alerte quand le plafond de risque est sur le point de FERMER l'admission.

Posé le 2026-08-23. Ce jour-là, le démo tournait à **89,3 %** du plafond des
6 % et le réel à **85,7 %** — 3,37 € et 4,79 € de marge restante, pour des
trades qui en risquent 7 à 9. **Le prochain signal était refusé des deux
côtés**, et rien ne le disait :

- `/health` publie le RÉGLAGE (`max_risque_engage_pct`), jamais la CONSOMMATION ;
- un ordre refusé pour dépassement ne produit aucune notification ;
- il fallait sommer les risques à la main pour découvrir que c'était fermé.

> **Un refus silencieux se lit comme une absence de signal.** Les deux
> ressemblent à « rien ne se passe ».

La soupape d'équilibre ([[project_stop_equilibre_arme_2026_08_23]]) ne suffit
pas à rendre l'état lisible : le 23/08 elle n'avait **aucun candidat** (aucune
position n'atteignait 1 R), donc elle se serait déclenchée pour rien. On
compte donc aussi ce qu'elle pourrait libérer — « saturé et rien à libérer »
et « saturé mais 8 € récupérables » n'appellent pas la même décision.

⚠️ Le risque en devise se **dérive du profit rapporté** : `profit = (courant −
entrée) × k`, donc `k = profit / (courant − entrée)` et
`risque = (entrée − stop) × k`. Aucun besoin du tick value ni du contract
size, et c'est exact — vérifié au centime près contre les positions réelles
du 23/08. Le prix à payer est qu'une position **pile à son prix d'entrée** n'a
pas de facteur dérivable : elle est alors NON MESURABLE, jamais zéro.

Usage :
    python notify_saturation_risque.py
    DRY_RUN=1 python notify_saturation_risque.py    # affiche sans notifier
"""
from __future__ import annotations

import json
import math
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, "/app")

DELAI = 10

# Le plafond n'est jamais atteint pile : on veut le savoir AVANT que le
# prochain ordre tombe.
#
# ⚠️ Baissé de 85 à 72 le 2026-08-25 (85 → 80 → 72 le même jour), après avoir
# mesuré le démo à **83 %** — donc SILENCIEUX — avec 5,24 € de marge pour des
# trades qui en risquent 7 à 9. L'admission y était déjà fermée en pratique,
# sous le seuil.
#
# 🔑 72 % n'est pas un chiffre rond, c'est le seul qui suit de la mesure : le
# seuil doit laisser, AU MOMENT DE L'ALERTE, plus qu'un trade typique. Sur un
# plafond de ~32 € et un trade qui risque jusqu'à 9 € :
#
#     seuil_max = 100 × (1 − 9 / 32) ≈ 72 %
#
# À 85 % il restait 4,80 € et à 80 % encore 6,40 € : dans les deux cas
# l'alerte annonçait un blocage DÉJÀ EN COURS au lieu de le prévenir. Un
# seuil qui prévient trop tard ne se distingue pas d'un silence.
#
# ⚠️ Le seuil dépend donc du PLAFOND, qui suit l'equity. Si le capital monte
# nettement, 72 % redevient trop tardif — c'est le rapport « trade typique /
# plafond » qu'il faut refaire, pas le pourcentage qu'il faut retenir.
#
# ⛔ CE DÉFAUT EST APPARIÉ à celui de `notify-saturation-risque.sh`, qui
# l'écrase via `docker exec -e`. Changer l'un sans l'autre ferait diverger le
# cron et la commande `risque` à la demande — un test épingle leur égalité.
SEUIL_PCT = float(os.environ.get("SEUIL_SATURATION_PCT", "72"))

INSTANTANE = Path(os.environ.get(
    "SATURATION_SNAPSHOT_PATH", "/app/data/saturation_risque.json"))

TOKEN = os.environ.get("INFRA_NOTIFY_TOKEN", "shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg")
# channel=sales : l'admission qui se ferme est un evenement de TRADING, pas
# d'infrastructure. Meme choix que la sonde des positions non protegees.
# ⛔ Omettre `channel` router ait vers le fil infra EN SILENCE.
NOTIFY_URL = ("https://app.scalping-radar.online/api/admin/"
              f"notify-infra-telegram?token={TOKEN}&channel=sales")

# Persistant tant que c'est saturé : quatre rappels par jour au plus. Se taire
# apres un seul envoi rendrait invisible un blocage qui dure des jours.
COOLDOWN_SEC = 21600

DESTINATIONS_SURVEILLEES = ("admin_legacy", "admin_live")

# Volatilite journaliere relative en dessous de laquelle on refuse de conclure.
# Un flux GELE rend un sigma minuscule mais positif : sans ce plancher, toute
# position deviendrait eligible. Le forex reel vaut 0,15 a 0,75 % par jour.
SIGMA_REL_MIN = float(os.environ.get("SIGMA_REL_MIN", "0.0001"))
# Fenetre de mesure, alignee sur `EQUILIBRE_VOL_HEURES` cote bridge.
VOL_HEURES = int(os.environ.get("VOL_HEURES", "720"))


# --------------------------------------------------------------------------
# Mesure — fonctions PURES, testables sans réseau
# --------------------------------------------------------------------------

def mesurer_position(p: dict) -> dict:
    """Rend `{nue, risque, marge_r}` pour une position MT5.

    ⛔ `risque=None` n'est pas `risque=0.0`. Les deux cas où il vaut `None` :
    la position est **nue** (risque non borné) ou son facteur n'est **pas
    dérivable** (elle est pile à son prix d'entrée). Rendre zéro rabaisserait
    le total engagé et cacherait précisément la saturation qu'on cherche.
    """
    try:
        sl = float(p.get("sl") or 0.0)
    except (TypeError, ValueError):
        sl = 0.0
    if sl <= 0:
        return {"nue": True, "risque": None, "marge_r": None}

    try:
        entree = float(p["price_open"])
        courant = float(p["price_current"])
        profit = float(p["profit"])
    except (TypeError, ValueError, KeyError):
        return {"nue": False, "risque": None, "marge_r": None}

    est_vente = str(p.get("type", "")).lower().startswith("s")
    delta = (entree - courant) if est_vente else (courant - entree)
    if abs(delta) < 1e-12:
        # Pile a l'entree : `k` est indefini. On ne devine pas.
        return {"nue": False, "risque": None, "marge_r": None}

    k = profit / delta
    distance = (sl - entree) if est_vente else (entree - sl)
    if distance <= 0:
        # Stop a l'equilibre ou au-dela : la position ne peut plus perdre.
        # C'est un VRAI zero, mesure — pas une faute de mesure.
        return {"nue": False, "risque": 0.0, "marge_r": None}

    risque = distance * k
    if risque <= 0:
        return {"nue": False, "risque": None, "marge_r": None}
    return {"nue": False, "risque": risque, "marge_r": profit / risque}


def _acquis_en_prix(p: dict) -> float | None:
    """Profit acquis, en unités de PRIX, signé par le sens de la position."""
    try:
        entree = float(p["price_open"])
        courant = float(p["price_current"])
    except (TypeError, ValueError, KeyError):
        return None
    if courant <= 0:
        return None
    est_vente = str(p.get("type", "")).lower().startswith("s")
    return (entree - courant) if est_vente else (courant - entree)


def sigma_journalier(clotures) -> float | None:
    """Écart-type journalier, en unités de PRIX. ``None`` si incalculable.

    ⚠️ **Formule DUPLIQUÉE depuis `bridge.py::_sigma_journalier`.** Les deux
    tournent sur des machines différentes et ne peuvent pas partager de code à
    l'exécution. Toute modification ici doit être répercutée là-bas, et
    inversement : des tests épinglent la formule des deux côtés sur les mêmes
    entrées.

    Rendements log H1 → écart-type → `× √24` → `× dernière clôture`.

    ⛔ Rend ``None``, jamais 0.0 : un σ nul rendrait tout éligible, et un
    échantillon trop mince servirait quand même à décider.
    """
    if not clotures or len(clotures) < 100:
        return None
    try:
        c = [float(x) for x in clotures if float(x) > 0]
    except (TypeError, ValueError):
        return None
    if len(c) < 100:
        return None
    rend = [math.log(c[i] / c[i - 1]) for i in range(1, len(c))]
    moy = sum(rend) / len(rend)
    var = sum((r - moy) ** 2 for r in rend) / (len(rend) - 1)
    sigma_rel = math.sqrt(var) * math.sqrt(24.0)
    # ⛔ Un flux GELE donne un sigma minuscule mais POSITIF, donc toute
    # position deviendrait eligible — fail-open, exactement l'inverse du but.
    # Une volatilite journaliere reelle vaut 0,15 a 0,75 % sur ces paires ;
    # sous 0,01 % ce n'est pas un marche calme, c'est un flux casse.
    if sigma_rel < SIGMA_REL_MIN:
        return None
    sigma = sigma_rel * c[-1]
    return sigma if sigma > 0 else None


# Nommés UN PAR UN, jamais par classe d'actif : « métal » embarquerait le
# platine et le palladium, que personne n'a demandé à financer sur ce budget.
_SYMBOLES_OR_ARGENT = ("XAU", "GOLD", "XAG", "SILVER")


def poche_du_symbole(symbole: str) -> str:
    """Poche de risque : or et argent d'un côté, tout le reste de l'autre.

    ⚠️ **Règle DUPLIQUÉE depuis `bridge.py::_poche_du_symbole`** — même raison
    que `sigma_journalier` : les deux tournent sur des machines différentes et
    ne peuvent pas partager de code à l'exécution. Toute modification ici doit
    être répercutée là-bas ; un test épingle les deux sur les mêmes entrées.
    """
    s = (symbole or "").upper()
    return ("or_argent" if any(m in s for m in _SYMBOLES_OR_ARGENT)
            else "autres")


def evaluer(positions: list, equity: float, plafond_pct: float,
            marge_min_r: float, sigmas=None,
            marge_min_sigma: float = 0.0,
            plafond_metaux_pct: float = 0.0) -> dict:
    """Somme les risques et compte ce que la soupape pourrait libérer.

    ⛔ `indecidable` dès qu'une position est nue, non mesurable, ou que
    l'equity manque : un pourcentage calculé sur un total amputé serait une
    mesure inventée, et c'est pire qu'une absence de mesure.

    ## Deux poches depuis le 2026-08-28

    Le bridge borne séparément les métaux — or **et argent** — à 14 % et le
    reste à 6 %, et **ne prête rien de l'une à l'autre**. Un pourcentage
    unique sur 20 % afficherait 35 % là où la poche des métaux est PLEINE : le
    blocage redeviendrait exactement ce que cette sonde existe pour empêcher —
    un refus silencieux.

    ⇒ On mesure chaque poche et on remonte **la plus saturée**. Les clés
    historiques (`pct`, `plafond`, `risque_total`, `restant`, `candidats`,
    `liberable`) décrivent donc cette poche-là, nommée par `poche`.

    `plafond_metaux_pct <= 0` ⇒ une seule poche : l'état d'avant, au bit près.
    """
    or_separe = plafond_metaux_pct > 0
    poches = ("autres", "or_argent") if or_separe else ("autres",)
    total = {q: 0.0 for q in poches}
    candidats = {q: 0 for q in poches}
    liberable = {q: 0.0 for q in poches}
    nues, non_mesurables = 0, 0

    for p in positions or []:
        q = poche_du_symbole(p.get("symbol")) if or_separe else "autres"
        m = mesurer_position(p)
        if m["nue"]:
            nues += 1
            continue
        if m["risque"] is None:
            non_mesurables += 1
            continue
        total[q] += m["risque"]
        if not (m["risque"] > 0 and m["marge_r"] is not None
                and m["marge_r"] >= marge_min_r - 1e-9):
            continue
        # ⛔ La porte de BRUIT, la même que le bridge applique depuis le
        # 24/08. Sans elle, la sonde annonçait 3 candidats qui n'en étaient
        # aucun : elle promettait du budget libérable qui n'existait pas.
        # Volatilité inconnue ⇒ pas candidat (fail-closed, comme le bridge).
        if marge_min_sigma > 0:
            try:
                sigma = sigmas(p.get("symbol")) if sigmas else None
            except Exception:
                sigma = None
            if not sigma or sigma <= 0:
                continue
            acquis = _acquis_en_prix(p)
            if acquis is None or acquis < marge_min_sigma * sigma - 1e-12:
                continue
        candidats[q] += 1
        liberable[q] += m["risque"]

    equity_ok = equity is not None and equity > 0
    indecidable = bool(nues or non_mesurables or not equity_ok)
    pcts = {q: (plafond_pct if q == "autres" else plafond_metaux_pct)
            for q in poches}
    plafonds = {q: (equity * pcts[q] / 100.0) if (equity_ok and pcts[q] > 0)
                else None for q in poches}

    # La poche qui MORD est celle dont le pourcentage est le plus haut : c'est
    # elle qui refusera le prochain ordre, donc elle qu'il faut annoncer. Une
    # moyenne, ou un total rapporté à la somme des plafonds, diluerait une
    # poche pleine dans une poche vide — et se tairait.
    def _pct(q):
        return (None if (indecidable or not plafonds[q])
                else 100.0 * total[q] / plafonds[q])

    mesurables = [q for q in poches if _pct(q) is not None]
    q_max = max(mesurables, key=_pct) if mesurables else poches[0]
    plafond, pct = plafonds[q_max], _pct(q_max)

    return {
        "lisible": True, "indecidable": indecidable,
        "poche": q_max, "multi_poches": or_separe,
        "detail_poches": {
            q: {"risque": total[q], "plafond": plafonds[q], "pct": _pct(q),
                "candidats": candidats[q], "liberable": liberable[q]}
            for q in poches
        },
        "risque_total": total[q_max], "plafond": plafond, "pct": pct,
        "restant": (plafond - total[q_max]) if plafond is not None else None,
        "nues": nues, "non_mesurables": non_mesurables,
        "positions": len(positions or []),
        "candidats": candidats[q_max], "liberable": liberable[q_max],
    }


def evaluation_illisible() -> dict:
    """⛔ Muet n'est pas sain. Un bridge injoignable ne vaut pas « 0 % »."""
    return {
        "lisible": False, "indecidable": True,
        "poche": None, "multi_poches": False, "detail_poches": {},
        "risque_total": None, "plafond": None, "pct": None, "restant": None,
        "nues": 0, "non_mesurables": 0, "positions": 0,
        "candidats": 0, "liberable": 0.0,
    }


def verdict(evaluation: dict, seuil_pct: float) -> str:
    """`illisible` | `indecidable` | `sature` | `ok` — jamais un repli muet."""
    if not evaluation.get("lisible"):
        return "illisible"
    if evaluation.get("indecidable"):
        return "indecidable"
    pct = evaluation.get("pct")
    if pct is None:
        return "indecidable"
    return "sature" if pct >= seuil_pct else "ok"


def doit_parler(avant: str | None, maintenant: str) -> str | bool:
    """On se tait UNIQUEMENT quand tout va bien et allait déjà bien.

    Le retour sous le seuil est annoncé : sans ça, on ne saurait jamais que
    l'admission s'est rouverte. La répétition d'un état saturé est bornée par
    le cooldown côté serveur, pas ici.
    """
    if maintenant == "ok" and avant in (None, "ok"):
        return False
    return True


# --------------------------------------------------------------------------
# Réseau, état, envoi
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


def _source_volatilite(dest):
    """Rend `symbole -> ecart-type journalier en prix`, via `/rates` du bridge.

    ⚠️ **Meme fenetre et meme formule que le bridge** (`EQUILIBRE_VOL_HEURES`
    = 720 h). C'est ce qui garantit que la sonde annonce ce que le bridge
    fera — l'inverse etait le defaut qu'on repare.

    Cache par passage : plusieurs positions partagent souvent un symbole.
    ⛔ Rend `None` sur toute lecture ratee : l'appelant ecarte alors la
    position, comme le bridge (fail-closed).
    """
    cache: dict = {}

    def _lire(symbole):
        if not symbole:
            return None
        if symbole in cache:
            return cache[symbole]
        fin = datetime.now(timezone.utc)
        debut = fin - timedelta(hours=VOL_HEURES)
        q = urllib.parse.urlencode({
            "pair": symbole, "timeframe": "H1",
            "from": debut.strftime("%Y-%m-%dT%H:%M:%S"),
            "to": fin.strftime("%Y-%m-%dT%H:%M:%S")})
        charge, ok = _appel(dest, "/rates?" + q)
        clotures = None
        if ok and isinstance(charge, dict):
            clotures = [b.get("c") for b in (charge.get("bougies") or [])
                        if b.get("c")]
        cache[symbole] = sigma_journalier(clotures) if clotures else None
        return cache[symbole]

    return _lire


def _lire_destination(dest) -> dict:
    """Santé + compte + positions. Toute lecture ratée ⇒ `illisible`."""
    sante, ok = _appel(dest, "/health")
    if not ok or not isinstance(sante, dict):
        return evaluation_illisible()
    gf = sante.get("garde_fous") or {}
    try:
        plafond_pct = float(gf.get("max_risque_engage_pct"))
        # Poche des metaux (2026-08-28). L'ancien nom est encore lu : entre le
        # deploiement de l'EC2 et celui du VPS, le bridge publie encore
        # `..._or_pct`, et ne lire que le nouveau nom ferait retomber la sonde
        # a UNE poche EN SILENCE — donc a un pourcentage rassurant et faux.
        # Absent des deux (vieux bridge) => 0, retro-compatible.
        plafond_metaux_pct = float(
            gf.get("max_risque_engage_or_argent_pct")
            or gf.get("max_risque_engage_or_pct")
            or 0.0)
        marge_min_r = float(gf.get("equilibre_marge_r", 1.0))
        # ⛔ Le bridge applique AUSSI cette porte depuis le 24/08. L'ignorer
        # faisait annoncer du budget liberable qui n'existait pas.
        # Absent (vieux bridge) => 0, donc porte desarmee : retro-compatible.
        marge_min_sigma = float(gf.get("equilibre_marge_sigma", 0.0) or 0.0)
    except (TypeError, ValueError):
        return evaluation_illisible()
    if plafond_pct <= 0 and plafond_metaux_pct <= 0:
        # Porte desarmee des DEUX cotes : il n'y a pas de plafond a saturer.
        # Une seule des deux a zero laisse l'autre mesurable — donc dite.
        e = evaluation_illisible()
        e.update({"lisible": True, "indecidable": False, "pct": 0.0,
                  "desarme": True})
        return e

    compte, ok = _appel(dest, "/account")
    if not ok or not isinstance(compte, dict):
        return evaluation_illisible()
    charge, ok = _appel(dest, "/positions")
    if not ok or not isinstance(charge, dict):
        return evaluation_illisible()
    positions = charge.get("positions")
    if not isinstance(positions, list):
        return evaluation_illisible()

    try:
        equity = float(compte.get("equity"))
    except (TypeError, ValueError):
        return evaluation_illisible()

    e = evaluer(positions, equity, plafond_pct, marge_min_r,
                sigmas=_source_volatilite(dest), marge_min_sigma=marge_min_sigma,
                plafond_metaux_pct=plafond_metaux_pct)
    e["login"] = sante.get("login")
    e["marge_min_r"] = marge_min_r
    e["marge_min_sigma"] = marge_min_sigma
    return e


def _charger_etats() -> dict:
    try:
        return json.loads(INSTANTANE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _ecrire_etats(etats: dict) -> None:
    try:
        INSTANTANE.parent.mkdir(parents=True, exist_ok=True)
        INSTANTANE.write_text(json.dumps(etats, sort_keys=True), encoding="utf-8")
    except OSError as e:
        print(f"  instantané non écrit ({e})")


def _notifier(titre: str, corps: str, dedup: str) -> None:
    if os.environ.get("DRY_RUN") == "1":
        print(f"  [DRY_RUN] {titre}\n{corps}\n")
        return
    charge = json.dumps({
        "title": titre, "body": corps,
        "dedup_key": dedup, "cooldown_seconds": COOLDOWN_SEC,
    }).encode("utf-8")
    rq = urllib.request.Request(
        NOTIFY_URL, data=charge,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(rq, timeout=DELAI) as r:
            print(f"  notifié ({r.status})")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"  ENVOI ÉCHOUÉ ({type(e).__name__}: {e})")


def _message(did: str, e: dict, v: str) -> tuple[str, str]:
    """Titre et corps de l'alerte. **Texte simple, sans une seule balise.**

    ⛔ Corrige le 2026-08-28. Ce corps partait avec des `<b>`, et l'endpoint
    `notify-infra-telegram` passe le body dans `html.escape` : les balises
    s'affichaient **en clair** dans Telegram (`<b>28,75 €</b>`), sur toutes
    les alertes de saturation depuis leur pose. Seul le `title` est mis en
    gras, et c'est l'endpoint qui le fait.

    ⛔ Et `html.escape` etait applique ICI en plus : un nom contenant `&`
    ressortait donc en `&amp;` a l'ecran, double-echappe. Echapper deux fois
    n'est pas echapper mieux.

    > **Une mise en forme qui traverse un echappement n'est plus une mise en
    > forme, c'est du bruit.** On met donc l'accent avec des majuscules et de
    > l'espace, qui survivent a tout.
    """
    nom = did
    compte = str(e.get("login") or "?")

    if v == "illisible":
        return (f"⚠️ Risque engagé illisible — {nom}",
                f"Impossible de lire le risque engagé sur {nom}.\n\n"
                "Ce n'est pas « le compte a de la place » — c'est « on ne "
                "sait pas ». L'admission peut être fermée sans que rien "
                "ne le dise.")

    if v == "indecidable":
        if e["nues"]:
            return (f"🚨 Admission FERMÉE — {nom}",
                    f"{e['nues']} position(s) SANS STOP sur {nom} "
                    f"(compte {compte}).\n\nUn risque non borné rend toute "
                    "somme impossible : AUCUN nouvel ordre ne passera "
                    "tant qu'elles sont là. Reposer un stop ou fermer.")
        return (f"⚠️ Risque engagé indécidable — {nom}",
                f"{e['non_mesurables']} position(s) non mesurable(s) "
                f"sur {nom}.\n\nLe total serait amputé, donc rassurant à "
                "tort. On ne conclut pas.")

    pct, restant = e["pct"], e["restant"]
    # ⛔ Nommer la poche n'est pas cosmétique : « 88 % du plafond » sur un
    # compte qui en a deux ne dit pas CE QUI est fermé, et les métaux bouchés
    # n'appellent pas la même décision que le forex bouché.
    poche = (f" (poche {e.get('poche')})" if e.get("multi_poches") else "")
    etiquette = f" [{e.get('poche')}]" if e.get("multi_poches") else ""
    if v == "ok":
        return (f"✅ Admission rouverte — {nom}{etiquette}",
                f"Le risque engagé de {nom} (compte {compte}){poche} est "
                f"redescendu à {pct:.0f} % du plafond — {restant:.2f} € "
                "de marge. Les nouveaux ordres repassent.")

    soupape = (f"La soupape d'équilibre peut libérer {e['liberable']:.2f} € "
               f"({e['candidats']} position(s) au-delà de {e['marge_min_r']:.0f} R)."
               if e["candidats"] else
               "⛔ La soupape d'équilibre n'a AUCUN candidat : aucune "
               f"position n'atteint {e['marge_min_r']:.0f} R de profit. Elle se "
               "déclenchera, ne trouvera rien, et le refus tiendra.")

    # L'autre poche est dite aussi : « les métaux sont pleins » et « tout est
    # plein » n'appellent pas la même décision, et rien d'autre ne le publie.
    autres = "".join(
        f"\nAutre poche {q} : {d['risque']:.2f} € "
        + (f"sur {d['plafond']:.2f} € ({d['pct']:.0f} %)"
           if d["pct"] is not None else "— non mesurée")
        for q, d in sorted((e.get("detail_poches") or {}).items())
        if q != e.get("poche"))

    return (f"🚨 Risque engagé à {pct:.0f} % — {nom}{etiquette}",
            f"{nom} (compte {compte}) — {e['positions']} position(s)\n"
            f"Risque engagé{poche} {e['risque_total']:.2f} € sur un "
            f"plafond de {e['plafond']:.2f} €{autres}\n"
            f"Marge restante : {restant:.2f} €\n\n"
            f"{soupape}\n\n"
            "Un ordre refusé pour dépassement ne produit aucune notification : "
            "sans ce message, le blocage ressemblerait à une absence de signal.")


def main() -> int:
    try:
        from backend.services.destinations_registry import DESTINATIONS
    except ImportError as exc:
        print(f"registre des destinations illisible : {exc}")
        return 1

    etats = _charger_etats()
    nouveaux = dict(etats)

    for did in DESTINATIONS_SURVEILLEES:
        dest = DESTINATIONS.get(did)
        if dest is None:
            continue
        print(f"{did} :")
        e = _lire_destination(dest)
        v = verdict(e, SEUIL_PCT)
        if e.get("desarme"):
            print("    plafond désarmé — rien à saturer")
            nouveaux[did] = "ok"
            continue

        if e["pct"] is None:
            print(f"    {v.upper()}")
        else:
            print(f"    {e['pct']:.1f} % du plafond [{e.get('poche')}] "
                  f"({e['risque_total']:.2f} / {e['plafond']:.2f}) — "
                  f"{e['candidats']} candidat(s), {v}")

        avant = etats.get(did)
        nouveaux[did] = v
        if not doit_parler(avant, v):
            continue
        titre, corps = _message(did, e, v)
        print(f"  ALERTE ({avant} -> {v})")
        _notifier(titre, corps, dedup=f"saturation:{did}:{v}")

    _ecrire_etats(nouveaux)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
