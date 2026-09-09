"""Le Fair Value Gap et le breakaway gap sont-ils vraiment deux choses ?

Question de Xavier le 2026-09-09. Sa thèse : la distinction se joue sur la
**troisième bougie** — si elle clôture DANS la deuxième, le prix retracera dans
la zone avant de repartir ; si elle clôture AU-DELÀ, la tendance est trop forte
et il repart sans retracer.

⛔ Les deux termes viennent de deux traditions (ICT pour le FVG, Edwards &
Magee pour le breakaway gap), et sa règle n'est ni l'une ni l'autre. Répondre
par la définition serait répondre à côté. Les **deux** ont donc été codées, et
cette sonde lit le verdict du laboratoire.

## Ce qu'elle compare, et pourquoi ainsi

Elle ne juge pas les motifs un par un — le laboratoire le fait déjà. Elle
répond à **la** question : `gap_retrace_*` et `gap_breakaway_*` ont-ils des R
moyens **différents** ?

- écart NET et cohérent entre les deux sens ⇒ la distinction existe
- écart nul ⇒ un même événement sous deux noms

⚠️ **Et l'écart lui-même doit battre le hasard.** Deux motifs peuvent différer
par pur bruit d'échantillonnage : le laboratoire publie un `plafond` de |t| que
le hasard atteint, et cette sonde le rappelle à chaque envoi. Sans lui, un
écart de 0,3 R sur n=40 se lirait comme une découverte.

⚠️ Le prior : **sept motifs mesurés, aucun ne bat le hasard** (Δ = +0,004 R sur
29 000 trades). Ceux-ci sont les huitième et neuvième.

## Invariants

- lecture seule, aucun curseur, aucun état déplacé ;
- un seul message par passage (`dedup_key`) ;
- **aucune balise** : l'endpoint échappe le HTML, une balise s'afficherait
  telle quelle — défaut déjà propagé sur huit sondes ;
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


def lire(c: sqlite3.Connection) -> tuple[str | None, list[dict]]:
    """`(jour, cellules)` de la DERNIERE nuit mesurée. Rien si jamais mesuré."""
    ligne = c.execute(
        "SELECT MAX(substr(mesure_le,1,10)) FROM labo_or_cellules WHERE pair = ?",
        (PAIRE,)).fetchone()
    jour = ligne[0] if ligne else None
    if not jour:
        return None, []
    rows = c.execute(
        "SELECT horizon, motif, sens, n, r_moyen, t, plafond FROM labo_or_cellules "
        " WHERE pair = ? AND substr(mesure_le,1,10) = ? "
        "   AND motif IN (?,?,?,?,?,?)",
        (PAIRE, jour, *RETRACE, *BREAKAWAY, *FVG)).fetchall()
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


def verdict(r_ret, n_ret, r_bre, n_bre, plafond) -> tuple[str, str]:
    """`(titre court, phrase)`. Séparé pour être testable sans base ni réseau —
    c'est la seule partie qui peut se tromper en silence."""
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
    sens = "le RETRACEMENT" if ecart > 0 else "la CONTINUATION"
    return (f"ecart en faveur de {sens.lower()}",
            f"{sens} rend {abs(ecart):.3f} R de plus ({r_ret:+.3f} contre "
            f"{r_bre:+.3f}). ⚠️ A confirmer sur plusieurs nuits : le laboratoire "
            f"place le plafond du hasard a |t| = {plafond:.2f}, et un ecart "
            "entre deux motifs peut naitre du seul bruit.")


def construire(jour: str | None, cellules: list[dict]) -> tuple[str, str]:
    if not jour or not cellules:
        return ("🔬 Face-a-face des gaps : rien a lire",
                "Le laboratoire n'a encore mesure aucune cellule sur les motifs "
                "de gap. Ce n'est PAS « aucun ecart » — c'est une mesure qui "
                "n'a pas eu lieu.")

    plafond = max((c["plafond"] or 0) for c in cellules) or 0.0
    r_ret, n_ret = _moyenne_ponderee(cellules, RETRACE)
    r_bre, n_bre = _moyenne_ponderee(cellules, BREAKAWAY)
    r_fvg, n_fvg = _moyenne_ponderee(cellules, FVG)
    court, phrase = verdict(r_ret or 0, n_ret, r_bre or 0, n_bre, plafond)

    corps = [
        "BUT — le Fair Value Gap et le breakaway gap sont-ils deux choses "
        "differentes, ou le meme evenement sous deux noms ?",
        "",
        f"Nuit du {jour}, sur {PAIRE} :",
        "",
        f"  ta regle, retracement attendu : {(r_ret if r_ret is not None else 0):+.3f} R   sur {n_ret} fenetres",
        f"  ta regle, continuation        : {(r_bre if r_bre is not None else 0):+.3f} R   sur {n_bre} fenetres",
        f"  FVG standard (ICT)            : {(r_fvg if r_fvg is not None else 0):+.3f} R   sur {n_fvg} fenetres",
        "",
        f"VERDICT — {court}. {phrase}",
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
        "(+0,004 R sur 29 000 trades). Aucun de ces six n'est arme sur un "
        "compte — ils ne servent qu'a etre mesures.",
    ]
    return (f"🔬 Face-a-face des gaps — {court}", "\n".join(corps))


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
