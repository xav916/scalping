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
          critere_ambigu: bool = False) -> tuple[str, list[str]]:
    """`(decision, raisons)`. `decision` vaut PUBLIABLE ou NE PAS PUBLIER.

    `critere_ambigu` : plusieurs titres de la pre-inscription contiennent
    "critere" -- la section retenue l'a ete par heuristique (position la plus
    precoce du mot-cle), pas par une correspondance unique. Ce n'est pas en
    soi un refus, mais l'humain qui lit le verdict doit le savoir : on ne le
    rend jamais silencieux.
    """
    raisons: list[str] = []

    if critere_ambigu:
        raisons.append("ATTENTION : plusieurs titres de la pre-inscription "
                       "contiennent \"critere\" -- la section retenue l'a ete "
                       "par heuristique (position la plus precoce du mot-cle "
                       "dans le titre), verifier qu'il s'agit bien du critere "
                       "et non d'un recit qui le mentionne")

    if bloc is None:
        raisons.append("bloc machine absent : pre-inscription anterieure a la "
                       "convention du 25/10, ou critere non machine-lisible")
        return REFUS, raisons

    if critere_intact is None:
        raisons.append("impossible de COMPARER l'empreinte du critere a sa "
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


def empreinte_critere(chemin: str) -> bool | None:
    """Le critere sur le DISQUE est-il celui qui a ete commite ?

    `None` si la comparaison est impossible (git muet, fichier non suivi).
    """
    def _hash(texte: str) -> str | None:
        corps = sections.section(texte, "critere")
        if corps is None:
            return None
        return hashlib.sha256(corps.encode("utf-8")).hexdigest()

    try:
        disque = _hash(pathlib.Path(chemin).read_text(encoding="utf-8"))
        out = subprocess.run(["git", "log", "--diff-filter=A", "--format=%H",
                              "--", chemin],
                             capture_output=True, text=True, timeout=20)
        commits = [l for l in out.stdout.splitlines() if l.strip()]
        if not commits or disque is None:
            return None
        montre = subprocess.run(["git", "show", "%s:%s" % (commits[-1], chemin)],
                                capture_output=True, text=True, timeout=20)
        if montre.returncode != 0:
            return None
        return disque == _hash(montre.stdout)
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

    critere_ambigu = sections.nombre_titres_correspondants(texte, "critere") > 1
    try:
        decision, raisons = juger(resultat, sections.bloc_machine(texte),
                                  empreinte_critere(a.preinscription),
                                  critere_ambigu)
    except Exception as e:  # noqa: BLE001 -- fail-closed ET bavard, jamais un traceback nu
        print("ECHEC : resultat illisible pour le jugement (%s)" % e)
        return 1
    print("=== %s" % decision)
    for r in raisons:
        print("  - " + r)
    return 0 if decision == PUBLIABLE else 1


if __name__ == "__main__":
    sys.exit(main())
