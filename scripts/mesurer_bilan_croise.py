"""Le bilan de la nuit sur les 20 instruments — et ce qu'il faut en croire.

Posée le 2026-09-09, le soir du branchement de la validation croisée. Xavier
veut lire, chaque matin, ce que la nuit a produit sur l'ensemble des
instruments — pas seulement sur l'or.

## Ce qu'elle dit, et dans cet ordre

1. **combien d'instruments** ont été mesurés, et **lesquels ont échoué** — une
   nuit à 12 instruments sur 20 n'est pas une nuit à 20, et le taire ferait lire
   une couverture qu'on n'a pas ;
2. le **plafond du hasard** effectivement appliqué ;
3. la **concordance** : quel motif bat ce plafond, et sur combien d'instruments.

## ⛔ Pourquoi la concordance est le seul chiffre qui compte

L'audit du 25/08 a mesuré `PBO = 0,579` sur l'argent réel : **sélectionner sur
la performance mesurée ne généralise pas**, pire que pile ou face. Un motif qui
gagne sur un seul instrument est exactement l'objet que ce chiffre condamne.

⇒ Le message ne titre donc **jamais** sur un R élevé. Il titre sur le nombre
d'instruments concordants, et rappelle le PBO dès qu'un motif ressort isolé.

⚠️ Le signe compte : un motif qui gagne ici et perd là n'est pas « validé sur
deux instruments », c'est du bruit qui change de signe. `concordance()` ne
retient que le sens majoritaire.

## Invariants

- lecture seule, aucun curseur, aucun état déplacé ;
- un seul message par passage (`dedup_key`) ;
- **aucune balise** — l'endpoint échappe le HTML, défaut déjà propagé sur huit
  sondes ;
- `substr(mesure_le,1,10)`, jamais `date()` : le piège de la fenêtre SQLite a
  mordu deux fois.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import urllib.request

DB = os.environ.get("TRADES_DB", "/app/data/trades.db")


def lire(c: sqlite3.Connection) -> tuple[str | None, dict[str, list[dict]]]:
    """`(jour, {paire: cellules})` de la DERNIÈRE nuit mesurée."""
    ligne = c.execute(
        "SELECT MAX(substr(mesure_le,1,10)) FROM labo_or_cellules").fetchone()
    jour = ligne[0] if ligne else None
    if not jour:
        return None, {}
    par_paire: dict[str, list[dict]] = {}
    for pair, horizon, motif, sens, n, r, t, plafond in c.execute(
            "SELECT pair, horizon, motif, sens, n, r_moyen, t, plafond "
            "  FROM labo_or_cellules WHERE substr(mesure_le,1,10) = ?", (jour,)):
        par_paire.setdefault(pair, []).append(
            {"pair": pair, "horizon": horizon, "motif": motif, "sens": sens,
             "n": n, "r_moyen": r, "t": t, "plafond": plafond})
    return jour, par_paire


def verdict(concordance: dict, instruments: int) -> tuple[str, str]:
    """`(titre court, phrase)` — le SENS du bilan.

    ⛔ Séparé pour être testable sans base ni réseau : c'est la seule partie qui
    peut se tromper en silence.
    """
    if instruments == 0:
        return ("aucune mesure",
                "Le laboratoire n'a rien mesure cette nuit. Ce n'est PAS "
                "« rien a signaler » — c'est une mesure qui n'a pas eu lieu.")
    if not concordance:
        return ("rien ne bat le hasard",
                f"Aucun motif ne depasse le plafond sur {instruments} "
                "instrument(s). C'est le resultat ATTENDU — sept motifs mesures "
                "avant septembre, aucun n'y est parvenu.")

    meilleur = max(concordance.values(), key=lambda x: x["instruments"])
    n = meilleur["instruments"]
    if n <= 1:
        return ("un motif ISOLE, donc suspect",
                "Un seul instrument le porte. ⚠️ L'audit du 25/08 a mesure "
                "PBO = 0,579 sur l'argent reel : selectionner sur la "
                "performance mesuree ne generalise pas, pire que pile ou face. "
                "Un motif isole est exactement cet objet — a suivre, pas a "
                "armer.")
    return (f"{n} instruments concordants",
            f"Le meilleur motif tient sur {n} instruments sur {instruments}. "
            "C'est le seul genre de resultat qui vaille quelque chose ici. "
            "⚠️ A confirmer sur plusieurs nuits avant toute decision : une "
            "nuit ne fait pas un verdict.")


def construire(jour, par_paire, plafond, concordance) -> tuple[str, str]:
    if not jour or not par_paire:
        court, phrase = verdict({}, 0)
        return (f"🔬 Bilan croise — {court}", phrase)

    instruments = len(par_paire)
    cellules = sum(len(v) for v in par_paire.values())
    court, phrase = verdict(concordance, instruments)

    corps = [
        "BUT — ce que la nuit a produit sur TOUS les instruments, et ce qu'il "
        "faut en croire.",
        "",
        f"Nuit du {jour} : {instruments} instrument(s), {cellules} cellules, "
        f"plafond du hasard {plafond:.3f}",
        "",
    ]
    if concordance:
        corps.append("Motifs qui depassent le plafond :")
        for motif, d in sorted(concordance.items(),
                               key=lambda x: -x[1]["instruments"]):
            corps.append(f"  {motif:<20} {d['instruments']}/{d['sur']} "
                         f"({d['sens']}) — {', '.join(d['paires'][:6])}")
    else:
        corps.append("Aucun motif ne depasse le plafond.")

    corps += ["", f"VERDICT — {court}. {phrase}", "",
              "Instruments mesures : " + ", ".join(sorted(par_paire))]
    return (f"🔬 Bilan croise — {court}", "\n".join(corps))


def _poster(titre: str, corps: str) -> int:
    jeton = os.environ.get("NOTIFY_TOKEN",
                           "shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg")
    # `infra` : c'est une mesure de RECHERCHE, elle n'engage l'argent d'aucun
    # compte. La convention du 06/09 reserve les fils de compte a leur argent.
    url = ("https://app.scalping-radar.online/api/admin/notify-infra-telegram"
           f"?token={jeton}&channel=infra")
    charge = json.dumps({"title": titre, "body": corps,
                         "dedup_key": "bilan_croise",
                         "cooldown_seconds": 3600}).encode()
    if os.environ.get("DRY_RUN") == "1":
        print(f"[DRY_RUN] {titre}\n{corps}\n")
        return 0
    try:
        req = urllib.request.Request(
            url, data=charge, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            print(f"bilan poste, HTTP {r.status}")
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ ENVOI DU BILAN ECHOUE : {e}")
        print(f"{titre}\n{corps}")
        return 1


def main() -> int:
    from backend.services.laboratoire_or import concordance as _conc
    try:
        with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as c:
            jour, par_paire = lire(c)
    except Exception as e:  # noqa: BLE001
        return _poster("⚠️ Bilan croise : mesure impossible",
                       f"La base est illisible ({e}). Le bilan reste SANS "
                       "REPONSE, et non « rien a signaler ».")
    plafond = max((x["plafond"] or 0)
                  for v in par_paire.values() for x in v) if par_paire else 0.0
    return _poster(*construire(jour, par_paire, plafond,
                               _conc(par_paire, plafond) if par_paire else {}))


if __name__ == "__main__":
    sys.exit(main())
