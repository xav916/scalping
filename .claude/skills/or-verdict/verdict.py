"""Refuse de publier un verdict dont le rejeu n'est pas valide.

Le 25/10, deux mesures et deux issues opposees :
  - le 12/10 : le rejeu reproduisait la journee sur TROIS cibles -> publiable ;
  - le hors echantillon : ecart -0,5731 EUR/trade contre une barre de 0,50
    posee d'avance -> NON CONCLUANT, et c'est ce calcul qui m'a arrete.

🔑 Une barre calculee arrete ; une bonne intention ecrite, non.

DEUX FORMES DE BANC sont jugees, declarees par le champ `forme` du resultat :

  - `rejeu` (defaut) : une periode rejouee, confrontee a la realite VECUE.
    `ecart_par_trade` mesure cette fidelite, et la barre pre-inscrite la
    borne.
  - `placebo` (pose le 2026-10-27) : le reel confronte a une distribution de
    REFERENCE. Pas de rejeu, donc pas d `ecart_par_trade` ; a la place,
    TOUTES les clauses du critere sont RECALCULEES contre les champs du
    resultat.
  - `seuil` (pose le 2026-10-27) : le reel confronte a une CONSTANTE
    arithmetique, sans aucun second bras. Meme evaluateur que `placebo`, mais
    sa decision favorable est `PUBLIABLE_SANS_CONTROLE` et JAMAIS `PUBLIABLE`
    -- un banc sans controle ne dit pas s il existe une information.

⛔ LA FORME EST DECLAREE, JAMAIS DEVINEE, et une forme inconnue est REFUSEE --
pas rabattue sur `rejeu`.

⛔ ET NE JAMAIS FABRIQUER `ecart_par_trade` sur un banc qui n en a pas :
emettre `0.0` ferait croire a une fidelite PARFAITE alors qu il n y a pas de
rejeu du tout. Ce serait commettre, sur le champ de controle de cette skill,
exactement la faute qu elle existe pour empecher. Declarer la bonne forme est
la seule voie.

🔑 CE QUE CES FORMES APPORTENT MEME SANS CONTROLE : le lien NOM PAR NOM entre
les champs que le critere engage et ceux que le banc emet. Mesure du
2026-10-27 sur le banc de la geometrie 1d : CINQ NOMS SUR CINQ divergeaient
(`z_binomial` contre `P3_z_binomial`, etc.) et rien ne l avait vu, parce que
le banc evaluait ses branches en interne avec des constantes recopiees. Un
critere engage sous un nom et mesure sous un autre n est pas un critere.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from or_commun import sections  # noqa: E402

REQUIS = ("n", "t", "ecart_par_trade", "valide")
PUBLIABLE, REFUS = "PUBLIABLE", "NE PAS PUBLIER"

#: Decision propre aux bancs SANS CONTROLE (forme `seuil`). ⛔ Distincte de
#: `PUBLIABLE` a dessein : un banc sans second bras ne peut pas dire s il
#: existe une information, seulement si une geometrie atteint son propre seuil
#: arithmetique. Rendre `PUBLIABLE` effacerait cette difference dans la seule
#: sortie que quelqu un lit vraiment. Le code de sortie reste 0 : c est
#: publiable, a condition de le dire.
PUBLIABLE_SANS_CONTROLE = "PUBLIABLE SANS CONTROLE"


def _seuil(expression: str) -> float | None:
    """Le nombre d'une expression de seuil, ou None si indechiffrable.

    Fail-closed : ancre sur l'operateur de comparaison. Un nombre nu ou sans
    operateur (ex. 'p95 par permutation') rend None, pas un nombre incident.
    """
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



# ─── Formes de banc ────────────────────────────────────────────────────────
#
# ⛔ LA FORME EST DECLAREE, JAMAIS DEVINEE. Inferer « placebo » de
# `ecart_par_trade is None` confondrait « il n'y a pas de rejeu » avec « le
# rejeu est casse » -- deux situations qui n'appellent pas le meme verdict.
FORME_REJEU = "rejeu"
FORME_PLACEBO = "placebo"
# Un banc compare a un SEUIL ARITHMETIQUE, sans second bras d aucune sorte.
# Juge sur ses clauses, mais sa decision favorable est
# `PUBLIABLE_SANS_CONTROLE` et jamais `PUBLIABLE`.
FORME_SEUIL = "seuil"
FORMES = (FORME_REJEU, FORME_PLACEBO, FORME_SEUIL)

#: Champs exiges de la forme PLACEBO. `ecart_par_trade` n'en fait pas partie :
#: il n'y a pas de rejeu dont mesurer la fidelite. Le reste demeure.
REQUIS_PLACEBO = ("n", "t", "valide")

_CLAUSE_SIMPLE = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(<=|>=|<|>)\s*([-+]?\d+(?:[.,]\d+)?)\s*$")
# Comparaison de DEUX CHAMPS. Forme indispensable, et trouvee manquante par
# les tests : « esperance_R_reel > cout_R_median » compare un resultat a un
# cout mesure, pas a une constante. Sans elle l evaluateur declarait
# l admission illisible et refusait TOUT -- fail-closed correct, mais inutile.
_CLAUSE_ABS_SIMPLE = re.compile(
    r"^\s*abs\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)"
    r"\s*(<=|>=|<|>)\s*([-+]?\d+(?:[.,]\d+)?)\s*$")

_CLAUSE_CHAMPS = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(<=|>=|<|>)"
    r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*$")

_CLAUSE_ECART = re.compile(
    r"^\s*abs\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*-\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)"
    r"\s*(<=|>=|<|>)\s*([-+]?\d+(?:[.,]\d+)?)\s*$")

_OPERATEURS = {
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
}


def _nombre(resultat: dict, champ: str) -> tuple[float | None, str | None]:
    """La valeur numerique de `champ`, ou `(None, probleme nomme)`."""
    if champ not in resultat:
        return None, "[%s] cite par le critere mais ABSENT du resultat" % champ
    v = resultat[champ]
    if v is None:
        return None, "[%s] cite par le critere mais null" % champ
    if isinstance(v, bool):
        return None, "[%s] est un booleen, pas un nombre" % champ
    try:
        return float(v), None
    except (TypeError, ValueError):
        return None, ("[%s] n'est pas convertible en nombre (type %s, "
                      "valeur %r)" % (champ, type(v).__name__, v))


def evaluer_clauses(expression: str, resultat: dict
                    ) -> tuple[bool | None, list[str]]:
    """Evalue une expression multi-clauses contre les champs du resultat.

    Rend `(verdict, raisons)`. `verdict is None` = **expression non
    evaluable**, ce qui n'est NI vrai NI faux.

    ⛔ FAIL-CLOSED SUR CE QUI N'EST PAS COMPRIS. Une clause illisible, un champ
    absent ou non numerique rend `None` en NOMMANT le probleme -- jamais `True`
    par defaut, et jamais une clause silencieusement ignoree. Ignorer une
    clause qu'on ne comprend pas revient a publier sur un critere PARTIEL,
    c'est-a-dire la faute exacte que cette skill existe pour empecher.

    Deux formes de clause sont acceptees, separees par ` ET ` :
      - `champ <op> nombre`
      - `abs(champ_a - champ_b) <op> nombre`

    Volontairement etroit : un evaluateur d'expressions arbitraires ne serait
    pas auditable, et ce qui juge une mise en production doit l'etre.
    """
    if not (expression or "").strip():
        return None, ["expression de critere vide"]

    raisons: list[str] = []
    tenue = True
    for brute in re.split(r"\s+ET\s+", expression):
        clause = brute.strip()
        if not clause:
            continue

        m = _CLAUSE_ECART.match(clause)
        if m:
            a, b, op, seuil = m.group(1), m.group(2), m.group(3), m.group(4)
            va, pa = _nombre(resultat, a)
            vb, pb = _nombre(resultat, b)
            if pa or pb:
                return None, [x for x in (pa, pb) if x]
            s = float(seuil.replace(",", "."))
            ecart = abs(va - vb)
            if not _OPERATEURS[op](ecart, s):
                tenue = False
                raisons.append(
                    "clause NON tenue : abs(%s - %s) = %.4f, attendu %s %s"
                    " (%s = %.4f, %s = %.4f)"
                    % (a, b, ecart, op, seuil, a, va, b, vb))
            continue

        # ⛔ LACUNE COMBLEE LE 2026-10-27 : `abs(champ) <op> n`, a UN SEUL
        # champ. Deux verdicts avaient ete refuses sur cette FORME et non sur
        # leur substance. 🔑 J ai refuse de corriger quand le resultat concerne
        # etait douteux -- et corriger seulement quand un resultat arrange
        # serait pire. La correction est appliquee aux DEUX, et elle ne change
        # aucun chiffre.
        m = _CLAUSE_ABS_SIMPLE.match(clause)
        if m:
            champ, op, seuil = m.group(1), m.group(2), m.group(3)
            v, probleme = _nombre(resultat, champ)
            if probleme:
                return None, [probleme]
            s_ = float(seuil.replace(",", "."))
            if not _OPERATEURS[op](abs(v), s_):
                tenue = False
                raisons.append(
                    "clause NON tenue : abs(%s) = %s, attendu %s %s"
                    % (champ, _joli(abs(v)), op, seuil))
            continue

        m = _CLAUSE_SIMPLE.match(clause)
        if m:
            champ, op, seuil = m.group(1), m.group(2), m.group(3)
            v, probleme = _nombre(resultat, champ)
            if probleme:
                return None, [probleme]
            s = float(seuil.replace(",", "."))
            if not _OPERATEURS[op](v, s):
                tenue = False
                raisons.append(
                    "clause NON tenue : %s = %s, attendu %s %s"
                    % (champ, _joli(v), op, seuil))
            continue

        m = _CLAUSE_CHAMPS.match(clause)
        if m:
            a_, op, b_ = m.group(1), m.group(2), m.group(3)
            va, pa = _nombre(resultat, a_)
            vb, pb = _nombre(resultat, b_)
            if pa or pb:
                return None, [x for x in (pa, pb) if x]
            if not _OPERATEURS[op](va, vb):
                tenue = False
                raisons.append(
                    "clause NON tenue : %s = %s, attendu %s %s = %s"
                    % (a_, _joli(va), op, b_, _joli(vb)))
            continue

        return None, ["clause ILLISIBLE, donc non evaluable : %r -- le"
                      " critere ne peut pas etre applique en partie" % clause]

    return tenue, raisons


def _joli(v: float) -> str:
    """Un nombre lisible : entier sans decimale, sinon quatre chiffres."""
    return "%d" % v if float(v).is_integer() else "%.4f" % v


def _juger_par_clauses(resultat: dict, bloc: dict, etiquette: str,
                       note: str = "") -> tuple[str, list[str]]:
    """La forme PLACEBO : toutes les clauses, recalculees.

    ⛔ ADMISSION ET REJET SONT EVALUES EN ENTIER, pas sur leur premier nombre.
    Un critere d'admission a trois clauses dont on ne verifierait que le `t`
    donnerait un feu vert sur un critere PARTIEL -- et c'est precisement sur un
    critere partiel que le banc du 27/10 aurait ete publie a tort.
    """
    raisons: list[str] = []

    manques = [c for c in REQUIS_PLACEBO
               if c not in resultat or resultat[c] is None]
    if manques:
        return REFUS, ["champ(s) REQUIS invalide(s) sur la forme placebo : %s"
                       % "; ".join("[%s] absent ou null" % c for c in manques)]
    if not isinstance(resultat["valide"], bool):
        return REFUS, ["[valide] n'est pas un booleen veritable (type %s,"
                       " valeur %r)" % (type(resultat["valide"]).__name__,
                                        resultat["valide"])]

    tenue, details = evaluer_clauses(bloc.get("validite", ""), resultat)
    if tenue is None:
        return REFUS, ["condition de validite NON evaluable : %s"
                       % "; ".join(details)]
    if not tenue:
        return REFUS, ["condition de validite NON tenue : %s"
                       % "; ".join(details)]
    if not resultat["valide"]:
        return REFUS, ["le banc se declare lui-meme NON valide (`valide:"
                       " false`), meme si ses nombres tiennent les clauses"]

    adm, d_adm = evaluer_clauses(bloc.get("admission", ""), resultat)
    if adm is None:
        return REFUS, ["bloc [admission] NON evaluable : %s" % "; ".join(d_adm)]
    rej, d_rej = evaluer_clauses(bloc.get("rejet", ""), resultat)
    if rej is None:
        return REFUS, ["bloc [rejet] NON evaluable : %s" % "; ".join(d_rej)]

    if adm and rej:
        return REFUS, ["admission ET rejet tenus SIMULTANEMENT : le critere"
                       " pre-inscrit est contradictoire, aucun verdict n'en"
                       " sort"]
    if adm:
        raisons.append("ADMISSION : toutes les clauses tenues" + note)
        return etiquette, raisons
    if rej:
        raisons.append("REJET : toutes les clauses tenues" + note)
        return etiquette, raisons

    return REFUS, ["ni admission ni rejet : %s"
                   % "; ".join(d_adm + d_rej) if (d_adm or d_rej)
                   else "ni admission ni rejet, et aucune clause ne le dit"]


#: La note accolee a toute decision de la forme `seuil`. Elle vit dans la
#: SORTIE, parce que la documentation ne suffit pas : personne ne la relit au
#: moment de publier un chiffre.
NOTE_SANS_CONTROLE = (" -- ⛔ AUCUN CONTROLE : ce banc n a ni rejeu ni placebo,"
                      " donc il ne dit PAS s il existe une information, seulement"
                      " si une geometrie atteint son propre seuil arithmetique."
                      " Une comparaison a des entrees tirees au HASARD reste a"
                      " faire.")


def _juger_placebo(resultat: dict, bloc: dict) -> tuple[str, list[str]]:
    """Forme `placebo` : le reel contre une distribution de reference."""
    return _juger_par_clauses(resultat, bloc, PUBLIABLE)


def _juger_seuil(resultat: dict, bloc: dict) -> tuple[str, list[str]]:
    """Forme `seuil` : le reel contre une constante arithmetique.

    Mecaniquement identique au placebo -- memes clauses, meme recalcul. La
    difference est SEMANTIQUE et doit rester VISIBLE : pas de second bras,
    donc pas de `PUBLIABLE`.
    """
    return _juger_par_clauses(resultat, bloc, PUBLIABLE_SANS_CONTROLE,
                              NOTE_SANS_CONTROLE)


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

    # ─── Aiguillage par FORME de banc ───────────────────────────────────
    #
    # Absente, la forme vaut REJEU : toute pre-inscription anterieure au
    # 2026-10-27 continue d etre jugee exactement comme avant.
    forme = resultat.get("forme") or FORME_REJEU
    if forme not in FORMES:
        raisons.append(
            "forme de banc INCONNUE : %r -- les formes jugees sont %s."
            " Une forme non comprise n est PAS traitee comme un rejeu :"
            " se tromper doit rendre bavard, jamais permissif."
            % (forme, ", ".join(FORMES)))
        return REFUS, raisons
    if forme == FORME_PLACEBO:
        decision, details = _juger_placebo(resultat, bloc)
        return decision, raisons + details
    if forme == FORME_SEUIL:
        decision, details = _juger_seuil(resultat, bloc)
        return decision, raisons + details

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
    # ⛔ `PUBLIABLE_SANS_CONTROLE` rend 0 : c est publiable. Ce qui change est
    # ce que la sortie DIT, pas le droit de publier -- un code 1 ferait croire
    # a un refus, et un code 0 muet ferait croire a un controle.
    return 0 if decision in (PUBLIABLE, PUBLIABLE_SANS_CONTROLE) else 1


if __name__ == "__main__":
    sys.exit(main())
