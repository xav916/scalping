"""Refuse de publier un verdict dont le rejeu n'est pas valide.

Le 25/10, deux mesures et deux issues opposees :
  - le 12/10 : le rejeu reproduisait la journee sur TROIS cibles -> publiable ;
  - le hors echantillon : ecart -0,5731 EUR/trade contre une barre de 0,50
    posee d'avance -> NON CONCLUANT, et c'est ce calcul qui m'a arrete.

🔑 Une barre calculee arrete ; une bonne intention ecrite, non.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from or_commun import sections  # noqa: E402

REQUIS = ("n", "t", "ecart_par_trade", "valide")
PUBLIABLE, REFUS = "PUBLIABLE", "NE PAS PUBLIER"


def _seuil(expression: str) -> float | None:
    """Le nombre d'une expression de seuil, ou None si indechiffrable.

    Fail-closed : ancre sur l'operateur de comparaison. Un nombre nu ou sans
    operateur (ex. 'p95 par permutation') rend None, pas un nombre incident.
    """
    import re
    _SEUIL = re.compile(r"[<>]=?\s*([-+]?\d+(?:[.,]\d+)?)")
    m = _SEUIL.search(expression or "")
    return float(m.group(1).replace(",", ".")) if m else None


_NUMERIQUES = ("n", "t", "ecart_par_trade")


def _problemes_requis(resultat: dict) -> list[str]:
    """Les champs de REQUIS absents, a `None`, ou du mauvais type.

    Chaque probleme NOMME le champ et la nature du probleme -- jamais un
    simple "manquant" qui confondrait absence, nullite et mauvais type.
    `n`, `t`, `ecart_par_trade` doivent etre convertibles en nombre ;
    `valide` doit etre un booleen VERITABLE (`"false"` est une chaine, et une
    chaine non vide est toujours vraie en Python -- piege mesure le 25/10).
    """
    problemes: list[str] = []
    for c in REQUIS:
        if c not in resultat:
            problemes.append("[%s] absent" % c)
            continue
        v = resultat[c]
        if v is None:
            problemes.append("[%s] est null" % c)
            continue
        if c == "valide":
            if not isinstance(v, bool):
                problemes.append(
                    "[%s] n'est pas un booleen veritable (type %s, valeur %r)"
                    % (c, type(v).__name__, v))
            continue
        if c in _NUMERIQUES:
            if isinstance(v, bool):
                problemes.append("[%s] est un booleen, pas un nombre" % c)
                continue
            try:
                float(v)
            except (TypeError, ValueError):
                problemes.append(
                    "[%s] n'est pas convertible en nombre (type %s, "
                    "valeur %r)" % (c, type(v).__name__, v))
    return problemes


def juger(resultat: dict, bloc: dict | None,
          critere_intact: bool | None,
          raison_indeterminable: str | None = None) -> tuple[str, list[str]]:
    """`(decision, raisons)`. `decision` vaut PUBLIABLE ou NE PAS PUBLIER.

    `raison_indeterminable` : texte a afficher quand `critere_intact is
    None`, au lieu du message generique -- distingue par exemple "chemin non
    resolu au depot" de "empreinte non comparable" (git muet, fichier non
    suivi) : la premiere n'accuse pas d'une falsification qui n'a pas eu
    lieu.
    """
    raisons: list[str] = []

    if bloc is None:
        raisons.append("bloc machine absent : pre-inscription anterieure a la "
                       "convention du 25/10, ou critere non machine-lisible")
        return REFUS, raisons

    if critere_intact is None:
        raisons.append(raison_indeterminable or
                       "impossible de COMPARER l'empreinte du critere a sa "
                       "version commitee")
        return REFUS, raisons
    if critere_intact is False:
        raisons.append("critere REECRIT apres coup : son empreinte ne "
                       "correspond plus a la version commitee")
        return REFUS, raisons

    problemes = _problemes_requis(resultat)
    if problemes:
        raisons.append("champ(s) REQUIS invalide(s), la condition de validite "
                       "n'est pas calculable : %s" % "; ".join(problemes))
        return REFUS, raisons

    barre = _seuil(bloc.get("validite", ""))
    if barre is None:
        raisons.append("bloc [validite] indechiffrable : aucun nombre lisible")
        return REFUS, raisons

    ecart = abs(float(resultat["ecart_par_trade"]))
    if not resultat["valide"] or ecart >= barre:
        raisons.append("condition de validite NON tenue : ecart %.4f contre "
                       "une barre de %.2f" % (ecart, barre))
        return REFUS, raisons

    t = float(resultat["t"])
    haut = _seuil(bloc.get("admission", ""))
    if haut is None:
        raisons.append("bloc [admission] indechiffrable : aucun nombre lisible")
        return REFUS, raisons
    bas = _seuil(bloc.get("rejet", ""))
    if bas is None:
        raisons.append("bloc [rejet] indechiffrable : aucun nombre lisible")
        return REFUS, raisons

    if t > haut:
        raisons.append("admission franchie : t = %+.2f > %+.2f" % (t, haut))
    elif t < bas:
        raisons.append("rejet franchi : t = %+.2f < %+.2f" % (t, bas))
    else:
        raisons.append("indecidable : t = %+.2f reste entre %+.2f et %+.2f"
                       % (t, bas, haut))
    return PUBLIABLE, raisons


def _racine_et_chemin_relatif(chemin: str) -> tuple[pathlib.Path, pathlib.Path] | None:
    """`(racine_depot, chemin_relatif_a_la_racine)`, ou `None`.

    La racine est deduite du REPERTOIRE DU FICHIER (`git rev-parse
    --show-toplevel` execute avec `cwd` dans ce repertoire), pas du cwd du
    processus appelant -- ce qui fait marcher la fonction depuis n'importe
    quel repertoire, avec un chemin relatif ou absolu.
    """
    path = pathlib.Path(chemin).resolve()
    out_root = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, timeout=20, cwd=str(path.parent))
    if out_root.returncode != 0:
        return None
    root = pathlib.Path(out_root.stdout.strip()).resolve()
    try:
        rel = path.relative_to(root)
    except ValueError:
        return None
    return root, rel


def empreinte_critere(chemin: str) -> bool | None:
    """Le bloc CRITERE-MACHINE sur le DISQUE est-il celui qui a ete commite ?

    REVISE LE 2026-10-26 : hache desormais le bloc `CRITERE-MACHINE`, pas la
    section en prose "critere". Sur le corpus reel de docs/predictions, 16
    formes de titre contiennent "critere", 5 fichiers sur 38 en ont
    plusieurs, et dans l'un d'eux le premier est du recit -- l'empreinte
    hachait donc la mauvaise section, fail-open sur la garde meme qu'elle
    constitue. Le bloc machine est delimite par un marqueur unique et
    contient precisement ce qui ne doit pas bouger (les seuils) ; la prose
    autour peut etre reecrite, completee, corrigee sans toucher l'empreinte.

    `None` si la comparaison est impossible (bloc absent sur le disque ou
    dans la version commitee, git muet, fichier non suivi, ou chemin non
    resolu a un depot git). Marche depuis n'importe quel repertoire et avec
    un chemin relatif OU absolu -- la racine du depot est deduite du fichier
    lui-meme, jamais du cwd du processus appelant.
    """
    def _hash(texte: str) -> str | None:
        bloc = sections.bloc_machine_texte(texte)
        if bloc is None:
            return None
        return hashlib.sha256(bloc.encode("utf-8")).hexdigest()

    try:
        resolu = _racine_et_chemin_relatif(chemin)
        if resolu is None:
            return None
        root, rel = resolu
        rel_git = rel.as_posix()  # git attend des '/' , meme sous Windows

        disque = _hash(pathlib.Path(chemin).resolve().read_text(encoding="utf-8"))
        if disque is None:
            return None

        out = subprocess.run(["git", "log", "--diff-filter=A", "--format=%H",
                              "--", rel_git],
                             capture_output=True, text=True, timeout=20,
                             cwd=str(root))
        commits = [l for l in out.stdout.splitlines() if l.strip()]
        if not commits:
            return None
        montre = subprocess.run(
            ["git", "show", "%s:%s" % (commits[-1], rel_git)],
            capture_output=True, text=True, timeout=20, cwd=str(root))
        if montre.returncode != 0:
            return None
        commite = _hash(montre.stdout)
        if commite is None:
            return None  # bloc absent de la version commitee : indeterminable
        return disque == commite
    except Exception:  # noqa: BLE001
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("preinscription")
    ap.add_argument("resultat", help="le JSON emis par le banc")
    a = ap.parse_args(argv)

    try:
        texte = pathlib.Path(a.preinscription).read_text(encoding="utf-8")
        resultat = json.loads(pathlib.Path(a.resultat).read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print("ECHEC : entree illisible (%s)" % e)
        return 1

    critere_intact = empreinte_critere(a.preinscription)
    raison_indeterminable = None
    if critere_intact is None and _racine_et_chemin_relatif(a.preinscription) is None:
        raison_indeterminable = (
            "chemin non resolu a un depot git : impossible de deduire la "
            "racine du depot ou le chemin relatif depuis '%s' -- ce n'est "
            "PAS une accusation de critere reecrit" % a.preinscription)
    try:
        decision, raisons = juger(resultat, sections.bloc_machine(texte),
                                  critere_intact, raison_indeterminable)
    except Exception as e:  # noqa: BLE001 -- fail-closed ET bavard, jamais un traceback nu
        print("ECHEC : resultat illisible pour le jugement (%s)" % e)
        return 1
    print("=== %s" % decision)
    for r in raisons:
        print("  - " + r)
    return 0 if decision == PUBLIABLE else 1


if __name__ == "__main__":
    sys.exit(main())
