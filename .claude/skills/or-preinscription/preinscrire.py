"""Refuse une mesure dont le critere n'est pas falsifiable.

Nee de deux fautes en trois jours : les 12/10 et 14/10, mon critere n'avait
qu'une condition « pas significativement pire », franchie trivialement par
tout ce qui est proche de zero. Une condition de non-degradation ne peut
JAMAIS servir de condition d'ADMISSION.

Et du 14/10 : sans plafond par permutation, SEPT cellules auraient « passe »
a t = 2 -- le hasard seul en fait passer autant.
"""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from or_commun import sections  # noqa: E402

MINIMUM_PREDICTIONS = 3


def valider(markdown: str, anteriorite: bool | None) -> list[str]:
    """La liste des manques. Vide = la pre-inscription tient."""
    manques: list[str] = []

    if sections.section(markdown, "critere") is None:
        manques.append("aucune section critere")

    bloc = sections.bloc_machine(markdown)
    if bloc is None:
        manques.append("bloc machine CRITERE-MACHINE absent : un seuil devine "
                       "dans de la prose serait silencieusement faux")
    else:
        if "admission" not in bloc:
            manques.append("aucune condition d'admission : « pas "
                           "significativement pire » n'en est jamais une "
                           "(fautes des 12/10 et 14/10)")
        if "validite" not in bloc:
            manques.append("aucune condition de validite du rejeu, distincte "
                           "du critere")
        try:
            cellules = int(bloc.get("cellules", "1"))
        except ValueError:
            cellules = 2  # illisible => on exige le plafond, fail-closed
            manques.append("nombre de cellules illisible")
        if cellules > 1 and "plafond" not in bloc:
            manques.append("plafond par permutation absent pour %d cellules : "
                           "le 14/10, sept cellules auraient passe a t=2"
                           % cellules)

    n = sections.compter_predictions(markdown)
    if n < MINIMUM_PREDICTIONS:
        manques.append("%d prediction(s) numerotee(s), il en faut %d"
                       % (n, MINIMUM_PREDICTIONS))

    if anteriorite is None:
        manques.append("impossible de prouver que la pre-inscription precede "
                       "le banc (git muet, ou banc non suivi)")
    elif anteriorite is False:
        manques.append("le banc est anterieur a sa pre-inscription")

    return manques


def _premier_commit(chemin: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "log", "--diff-filter=A", "--format=%ct", "--", chemin],
            capture_output=True, text=True, timeout=20)
    except Exception:
        return None
    lignes = [l for l in out.stdout.splitlines() if l.strip()]
    return lignes[-1] if lignes else None


def anteriorite_git(preinscription: str, banc: str | None) -> bool | None:
    """`True` si la pre-inscription precede le banc, `None` si indeterminable.

    ⛔ Un banc non suivi par git rend `None`, pas `True` : on ne peut pas
    prouver qu'il est posterieur.
    """
    if banc is None:
        return None
    a, b = _premier_commit(preinscription), _premier_commit(banc)
    if a is None or b is None:
        return None
    return int(a) <= int(b)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("preinscription")
    ap.add_argument("--banc", default=None)
    a = ap.parse_args(argv)

    try:
        texte = pathlib.Path(a.preinscription).read_text(encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        print("ECHEC : pre-inscription illisible (%s)" % e)
        return 1

    manques = valider(texte, anteriorite_git(a.preinscription, a.banc))
    if not manques:
        print("OK : la pre-inscription tient. Le banc peut etre ecrit.")
        return 0
    print("REFUS : %d manque(s)\n" % len(manques))
    for m in manques:
        print("  - " + m)
    return 1


if __name__ == "__main__":
    sys.exit(main())
