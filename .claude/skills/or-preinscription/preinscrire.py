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
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from or_commun import sections  # noqa: E402

MINIMUM_PREDICTIONS = 3
_COMPARAISON_NUM = re.compile(r"[<>]=?\s*[-+]?\d")
_NEGATION = re.compile(r"(^|\s)(pas|non|ne)(\s|$)", re.IGNORECASE)


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
        else:
            # Verifier le CONTENU de admission
            admission_val = bloc["admission"]
            if not _COMPARAISON_NUM.search(admission_val):
                manques.append("contenu de admission invalide : doit contenir "
                               "une comparaison numerique (ex. t > +2)")
            if _NEGATION.search(admission_val):
                manques.append("contenu de admission invalide : ne doit pas "
                               "contenir de negation (pas, non, ne)")

        if "validite" not in bloc:
            manques.append("aucune condition de validite du rejeu, distincte "
                           "du critere")

        if "cellules" not in bloc:
            manques.append("cellules absent : impossible de determiner si un "
                           "plafond par permutation est necessaire")
        else:
            try:
                cellules = int(bloc["cellules"])
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
        manques.append("impossible de PROUVER que la pre-inscription precede "
                       "le banc (git muet, ou banc non suivi)")
    elif anteriorite is False:
        manques.append("le banc est anterieur a sa pre-inscription")

    return manques


def _premier_commit(chemin: str) -> str | None:
    """SHA du commit qui a ajoute le fichier (ou None)."""
    try:
        path = pathlib.Path(chemin)
        # Trouver le repo git root a partir du repertoire du fichier
        out_root = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=20, cwd=str(path.parent))
        if out_root.returncode != 0:
            return None
        root = pathlib.Path(out_root.stdout.strip())

        # Obtenir le chemin relatif par rapport a la racine du repo
        rel_path = path.relative_to(root)

        # Git log pour obtenir le SHA du premier commit qui a ajoute le fichier
        out = subprocess.run(
            ["git", "log", "--diff-filter=A", "--format=%H", "--", str(rel_path)],
            capture_output=True, text=True, timeout=20, cwd=str(root))
        if out.returncode != 0:
            return None
        lignes = [l for l in out.stdout.splitlines() if l.strip()]
        return lignes[-1] if lignes else None
    except Exception:
        return None


def anteriorite_git(preinscription: str, banc: str | None) -> bool | None:
    """`True` si la pre-inscription precede le banc, `None` si indeterminable.

    ⛔ Un banc non suivi par git rend `None`, pas `True` : on ne peut pas
    prouver qu'il est posterieur.

    Utilise `git merge-base --is-ancestor` pour determiner l'ordre des commits,
    ce qui evite les problemes de timestamp identique.
    """
    if banc is None:
        return None
    a_sha, b_sha = _premier_commit(preinscription), _premier_commit(banc)
    if a_sha is None or b_sha is None:
        return None
    try:
        # Trouver le repo git a partir de la preinscription
        path = pathlib.Path(preinscription)
        out_root = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=20, cwd=str(path.parent))
        if out_root.returncode != 0:
            return None
        root = out_root.stdout.strip()

        # `git merge-base --is-ancestor A B` retourne 0 si A est ancetre de B
        # (c-a-d si A precede B dans l'histoire des commits)
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", a_sha, b_sha],
            capture_output=True, timeout=20, cwd=root)
        return result.returncode == 0
    except Exception:
        return None


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
