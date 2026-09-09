"""Deux motifs qui prétendent la même chose : lequel a raison ?

Née le 2026-09-09 de la question de Xavier — le *Fair Value Gap* et le
*breakaway gap* sont-ils deux choses, ou une seule ? Généralisée le même soir à
toute confrontation qui a du sens.

## Ce qu'elle compare, et surtout ce qu'elle NE compare pas

Elle ne juge pas les motifs un par un — le laboratoire le fait déjà, cellule par
cellule, contre un tirage au hasard. Elle ne sert que là où **deux familles
prétendent à la même chose sur le même événement** :

    gap_retrace / gap_breakaway   le meme gap, deux issues annoncees
    bos / breakout                la meme cassure, avec et sans contexte

⛔ **J'avais déclaré deux autres prédictions « à signes opposés »** — BOS contre
CHoCH, et le FVG contre son inversion. **Mal formées.** Le laboratoire calcule
`signe = 1 si buy sinon -1` : le R est le résultat du **trade**, pas le
mouvement du prix. Deux signaux qui marchent ont **tous deux** un R positif,
quel que soit leur sens. Rien ne les oppose.

⇒ Ces deux confrontations ont été **retirées** plutôt que codées : un test de
plus qui n'apprend rien relève le plafond du hasard pour tout le monde.

## Ce qui protège le verdict

⚠️ **L'écart doit battre le hasard.** Deux motifs peuvent différer par pur bruit
d'échantillonnage : le laboratoire publie un `plafond` de |t| que le hasard
atteint, et la sonde le rappelle à chaque envoi. Sans lui, +0,3 R sur n=40 se
lirait comme une découverte.

⚠️ Le prior : **sept motifs mesurés avant septembre, aucun ne bat le hasard**
(Δ = +0,004 R sur 29 000 trades).

## Invariants

- lecture seule, aucun curseur, aucun état déplacé ;
- un seul message par passage (`dedup_key`) ;
- **aucune balise** : l'endpoint échappe le HTML — défaut déjà propagé sur huit
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
PAIRE = os.environ.get("GAPS_PAIRE", "XAU/USD")

RETRACE = ("gap_retrace_up", "gap_retrace_down")
BREAKAWAY = ("gap_breakaway_up", "gap_breakaway_down")
FVG = ("fvg_up", "fvg_down")

# ⛔ LES SEULES COMPARAISONS PAR PAIRE QUI AIENT UN SENS (2026-09-09, corrige).
#
# J'avais declare deux autres predictions « a signes opposes » : BOS contre
# CHoCH, et le FVG contre son inversion. **MAL FORMEES.** Le laboratoire calcule
# `signe = 1 si buy sinon -1` : le R est le resultat du TRADE, pas le mouvement
# du prix. Deux signaux qui marchent ont TOUS DEUX un R positif, quel que soit
# leur sens. Rien ne les oppose.
#
# 🔑 Une comparaison par paire n'a de sens que si les deux familles pretendent
# a la MEME chose sur le MEME evenement :
#
#   gap_retrace / gap_breakaway  le meme gap, deux issues annoncees
#   bos / breakout               la meme cassure, avec et sans contexte
#
# Tout le reste — « ce motif marche-t-il ? » — est deja tranche par le
# laboratoire, cellule par cellule, contre un tirage au hasard. Y ajouter une
# comparaison serait un test de plus qui releve le plafond sans rien apprendre.
CONFRONTATIONS = (
    {
        "titre": "les deux definitions du gap",
        "a": RETRACE, "b": BREAKAWAY,
        "nom_a": "retracement attendu", "nom_b": "continuation",
        "question": "le Fair Value Gap et le breakaway gap sont-ils deux choses "
                    "differentes, ou le meme evenement sous deux noms ?",
    },
    {
        "titre": "le contexte de tendance sert-il a quelque chose",
        "a": ("bos_up", "bos_down"), "b": ("breakout_up", "breakout_down"),
        "nom_a": "cassure AVEC contexte (BOS)", "nom_b": "cassure NUE (breakout)",
        "question": "la meme cassure, lue avec et sans tendance : le contexte "
                    "ajoute-t-il de l'information ?",
    },
)


def lire(c: sqlite3.Connection) -> tuple[str | None, list[dict]]:
    """`(jour, cellules)` de la DERNIERE nuit mesurée. Rien si jamais mesuré."""
    ligne = c.execute(
        "SELECT MAX(substr(mesure_le,1,10)) FROM labo_or_cellules WHERE pair = ?",
        (PAIRE,)).fetchone()
    jour = ligne[0] if ligne else None
    if not jour:
        return None, []
    motifs = sorted({m for conf in CONFRONTATIONS
                     for m in conf["a"] + conf["b"]} | set(FVG))
    trous = ",".join("?" * len(motifs))
    rows = c.execute(
        "SELECT horizon, motif, sens, n, r_moyen, t, plafond FROM labo_or_cellules "
        f" WHERE pair = ? AND substr(mesure_le,1,10) = ? AND motif IN ({trous})",
        (PAIRE, jour, *motifs)).fetchall()
    return jour, [
        {"horizon": h, "motif": m, "sens": s, "n": n, "r": r, "t": t, "plafond": p}
        for h, m, s, n, r, t, p in rows]


def _moyenne_ponderee(cellules: list[dict], motifs: tuple) -> tuple[float | None, int]:
    """R moyen pondéré par n, et le n total. ⛔ Pondéré : une cellule à n=3
    pèserait autant qu'une à n=300 dans une moyenne simple."""
    retenues = [c for c in cellules if c["motif"] in motifs and (c["n"] or 0) > 0]
    n = sum(c["n"] for c in retenues)
    if not n:
        return None, 0
    return sum(c["r"] * c["n"] for c in retenues) / n, n


def verdict(r_ret, n_ret, r_bre, n_bre, plafond,
            nom_a: str = "la premiere", nom_b: str = "la seconde") -> tuple[str, str]:
    """`(titre court, phrase)`. Séparé pour être testable sans base ni réseau —
    c'est la seule partie qui peut se tromper en silence.

    ⚠️ `nom_a` / `nom_b` nomment les familles comparées. Sans eux, le message
    parlait de « RETRACEMENT » même pour la confrontation BOS/breakout — un
    verdict juste sous une étiquette fausse est pire qu'un verdict absent.
    """
    if n_ret == 0 or n_bre == 0:
        return ("pas encore mesurable",
                "Une des deux familles n'a aucune fenêtre exploitable. "
                "Il faut plus de nuits avant de comparer quoi que ce soit.")
    ecart = r_ret - r_bre
    if min(n_ret, n_bre) < 30:
        return ("trop tot pour conclure",
                f"Ecart de {ecart:+.3f} R, mais seulement {min(n_ret, n_bre)} "
                "fenetres du cote le plus pauvre. A ce compte, l'ecart est du "
                "bruit d'echantillonnage — attendre.")
    if abs(ecart) < 0.10:
        return ("AUCUNE difference",
                f"R moyen quasi identique ({r_ret:+.3f} contre {r_bre:+.3f}, "
                f"ecart {ecart:+.3f} R). La distinction que tu decris ne se voit "
                "pas dans les chiffres : ce serait un meme evenement sous deux "
                "noms.")
    sens = nom_a if ecart > 0 else nom_b
    return (f"ecart en faveur de : {sens}",
            f"{sens} rend {abs(ecart):.3f} R de plus ({r_ret:+.3f} contre "
            f"{r_bre:+.3f}). ⚠️ A confirmer sur plusieurs nuits : le laboratoire "
            f"place le plafond du hasard a |t| = {plafond:.2f}, et un ecart "
            "entre deux motifs peut naitre du seul bruit.")


def construire(jour: str | None, cellules: list[dict]) -> tuple[str, str]:
    if not jour or not cellules:
        return ("🔬 Face-a-face des motifs : rien a lire",
                "Le laboratoire n'a encore mesure aucune cellule sur ces motifs. "
                "Ce n'est PAS « aucun ecart » — c'est une mesure qui n'a pas eu "
                "lieu.")

    plafond = max((c["plafond"] or 0) for c in cellules) or 0.0
    corps: list[str] = []
    titres: list[str] = []

    for conf in CONFRONTATIONS:
        r_a, n_a = _moyenne_ponderee(cellules, conf["a"])
        r_b, n_b = _moyenne_ponderee(cellules, conf["b"])
        court, phrase = verdict(r_a or 0, n_a, r_b or 0, n_b, plafond,
                                conf["nom_a"], conf["nom_b"])
        titres.append(f"{conf['titre']} : {court}")
        corps += [
            f"BUT — {conf['question']}",
            "",
            f"  {conf['nom_a']:<30} {(r_a if r_a is not None else 0):+.3f} R "
            f"sur {n_a} fenetres",
            f"  {conf['nom_b']:<30} {(r_b if r_b is not None else 0):+.3f} R "
            f"sur {n_b} fenetres",
            "",
            f"VERDICT — {court}. {phrase}",
            "",
            "— — —",
            "",
        ]

    r_fvg, n_fvg = _moyenne_ponderee(cellules, FVG)
    corps += [
        f"Pour reference, FVG standard (ICT) : "
        f"{(r_fvg if r_fvg is not None else 0):+.3f} R sur {n_fvg} fenetres.",
        "",
        "Le detail par horizon :",
    ]
    for c in sorted(cellules, key=lambda x: (x["motif"], x["horizon"])):
        if (c["n"] or 0) == 0:
            continue
        corps.append(f"  {c['motif']:<19} {c['horizon']:<6} n={c['n']:<4} "
                     f"R={c['r']:+.3f}  t={c['t']:+.2f}")
    corps += [
        "",
        "⚠️ Rappel : sept motifs mesures avant ceux-ci, AUCUN ne bat le hasard "
        "(+0,004 R sur 29 000 trades). Aucun de ces motifs n'est arme sur un "
        "compte — ils ne servent qu'a etre mesures.",
    ]
    return (f"🔬 Face-a-face — nuit du {jour}", "\n".join(corps))


def _poster(titre: str, corps: str) -> int:
    jeton = os.environ.get("NOTIFY_TOKEN",
                           "shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg")
    # `infra` et non `ic_markets` : c'est une mesure de RECHERCHE, elle
    # n'engage l'argent d'aucun compte. La convention du 06/09 reserve les fils
    # de compte a ce qui touche a leur argent.
    url = ("https://app.scalping-radar.online/api/admin/notify-infra-telegram"
           f"?token={jeton}&channel=infra")
    charge = json.dumps({"title": titre, "body": corps,
                         "dedup_key": "face_a_face_gaps",
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
    try:
        with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as c:
            jour, cellules = lire(c)
    except Exception as e:  # noqa: BLE001
        return _poster("⚠️ Face-a-face des gaps : mesure impossible",
                       f"La base est illisible ({e}). Le verdict reste SANS "
                       "REPONSE, et non « aucun ecart ».")
    return _poster(*construire(jour, cellules))


if __name__ == "__main__":
    sys.exit(main())
