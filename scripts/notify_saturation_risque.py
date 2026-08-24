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

import html
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
# prochain ordre tombe. 85 % laisse ~5 € sur un compte de 550 €, soit moins
# qu'un trade typique — donc « saturé » veut bien dire « le prochain passe mal ».
SEUIL_PCT = float(os.environ.get("SEUIL_SATURATION_PCT", "85"))

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


def evaluer(positions: list, equity: float, plafond_pct: float,
            marge_min_r: float, sigmas=None,
            marge_min_sigma: float = 0.0) -> dict:
    """Somme les risques et compte ce que la soupape pourrait libérer.

    ⛔ `indecidable` dès qu'une position est nue, non mesurable, ou que
    l'equity manque : un pourcentage calculé sur un total amputé serait une
    mesure inventée, et c'est pire qu'une absence de mesure.
    """
    total, nues, non_mesurables = 0.0, 0, 0
    candidats, liberable = 0, 0.0

    for p in positions or []:
        m = mesurer_position(p)
        if m["nue"]:
            nues += 1
            continue
        if m["risque"] is None:
            non_mesurables += 1
            continue
        total += m["risque"]
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
        candidats += 1
        liberable += m["risque"]

    equity_ok = equity is not None and equity > 0
    indecidable = bool(nues or non_mesurables or not equity_ok)
    plafond = (equity * plafond_pct / 100.0) if equity_ok else None
    pct = None if (indecidable or not plafond) else 100.0 * total / plafond

    return {
        "lisible": True, "indecidable": indecidable,
        "risque_total": total, "plafond": plafond, "pct": pct,
        "restant": (plafond - total) if plafond is not None else None,
        "nues": nues, "non_mesurables": non_mesurables,
        "positions": len(positions or []),
        "candidats": candidats, "liberable": liberable,
    }


def evaluation_illisible() -> dict:
    """⛔ Muet n'est pas sain. Un bridge injoignable ne vaut pas « 0 % »."""
    return {
        "lisible": False, "indecidable": True,
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
        marge_min_r = float(gf.get("equilibre_marge_r", 1.0))
        # ⛔ Le bridge applique AUSSI cette porte depuis le 24/08. L'ignorer
        # faisait annoncer du budget liberable qui n'existait pas.
        # Absent (vieux bridge) => 0, donc porte desarmee : retro-compatible.
        marge_min_sigma = float(gf.get("equilibre_marge_sigma", 0.0) or 0.0)
    except (TypeError, ValueError):
        return evaluation_illisible()
    if plafond_pct <= 0:
        # Porte desarmee : il n'y a pas de plafond a saturer.
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
                sigmas=_source_volatilite(dest), marge_min_sigma=marge_min_sigma)
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
    nom = html.escape(did)
    compte = html.escape(str(e.get("login") or "?"))

    if v == "illisible":
        return (f"⚠️ Risque engagé illisible — {nom}",
                f"Impossible de lire le risque engagé sur <b>{nom}</b>.\n\n"
                "Ce n'est pas « le compte a de la place » — c'est « on ne "
                "sait pas ». L'admission peut être fermée sans que rien "
                "ne le dise.")

    if v == "indecidable":
        if e["nues"]:
            return (f"🚨 Admission FERMÉE — {nom}",
                    f"<b>{e['nues']}</b> position(s) SANS STOP sur {nom} "
                    f"(compte {compte}).\n\nUn risque non borné rend toute "
                    "somme impossible : <b>aucun nouvel ordre ne passera</b> "
                    "tant qu'elles sont là. Reposer un stop ou fermer.")
        return (f"⚠️ Risque engagé indécidable — {nom}",
                f"<b>{e['non_mesurables']}</b> position(s) non mesurable(s) "
                f"sur {nom}.\n\nLe total serait amputé, donc rassurant à "
                "tort. On ne conclut pas.")

    pct, restant = e["pct"], e["restant"]
    if v == "ok":
        return (f"✅ Admission rouverte — {nom}",
                f"Le risque engagé de {nom} (compte {compte}) est redescendu "
                f"à <b>{pct:.0f} %</b> du plafond — {restant:.2f} € de marge. "
                "Les nouveaux ordres repassent.")

    soupape = (f"La soupape d'équilibre peut libérer <b>{e['liberable']:.2f} €</b> "
               f"({e['candidats']} position(s) au-delà de {e['marge_min_r']:.0f} R)."
               if e["candidats"] else
               "⛔ <b>La soupape d'équilibre n'a AUCUN candidat</b> : aucune "
               f"position n'atteint {e['marge_min_r']:.0f} R de profit. Elle se "
               "déclenchera, ne trouvera rien, et le refus tiendra.")

    return (f"🚨 Risque engagé à {pct:.0f} % — {nom}",
            f"<b>{nom}</b> (compte {compte}) — {e['positions']} position(s)\n"
            f"Risque engagé <b>{e['risque_total']:.2f} €</b> sur un plafond de "
            f"{e['plafond']:.2f} €\n"
            f"Marge restante : <b>{restant:.2f} €</b>\n\n"
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
            print(f"    {e['pct']:.1f} % du plafond "
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
