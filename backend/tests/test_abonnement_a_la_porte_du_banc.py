"""Tout test qui promeut en `AUTO_EXEC` doit DIRE ce qu'il fait de la porte.

## Le défaut que ce fichier empêche de revenir

La porte du banc d'essai est armée par défaut depuis le 2026-10-31 (audit
R-2). Un test qui pose un `AUTO_EXEC` pour arranger un scénario se fait donc
refuser par un `PermissionError` — sauf s'il s'abonne à la fixture
`porte_banc_desarmee`.

🔑 **Et c'est pire qu'un simple oubli : l'échec est INTERMITTENT.** Quatre
fichiers avaient été manqués. Deux échouaient tout de suite ; les deux autres
**passaient en ordre par défaut** et ne tombaient que sous certains ordres
d'exécution, parce qu'un test antérieur laissait derrière lui un état que la
porte acceptait. La suite complète en ordre normal n'en voyait **aucun des
deux**.

⛔ Deux leçons, payées dans la même séance :

1. **Ma sélection par mot-clé mentait.** J'avais rejoué la tranche
   `-k "admission or porte or bench..."` et conclu « 0 échec ». Les quatre
   fichiers disent « promotion », pas « admission » : ils n'étaient pas dans la
   tranche. Un « c'est vert » sur un sous-ensemble ne dit rien de l'ensemble.
2. **C'est l'ordre aléatoire de la CI qui les a révélés**, dès sa première
   exécution — exactement ce pour quoi il a été mis en place (constat R-27).

Ce test remplace donc la vigilance par une vérification : un fichier qui
promeut sans s'abonner échoue **ici**, tout de suite, et pas dans un run
aléatoire sur trois.

## Pourquoi par AST

Un `grep` trouverait la prose qui **décrit** `set_state(..., AUTO_EXEC)` —
ce fichier en est lui-même la preuve vivante — autant que les appels réels.
"""
from __future__ import annotations

import ast
import io
import pathlib

_RACINE = pathlib.Path(__file__).resolve().parent

#: Ces fichiers SURVEILLENT la porte : ils doivent la laisser armée, et
#: s'abonner à `porte_banc_desarmee` y serait une faute.
_SURVEILLANTS = {
    "test_research_bench_porte.py",
    "test_porte_banc_armee_par_defaut.py",
    "test_abonnement_a_la_porte_du_banc.py",   # ce fichier
}


def _promeut_en_auto_exec(arbre: ast.AST) -> bool:
    """Le fichier pose-t-il un `AUTO_EXEC`, ou déclenche-t-il une promotion ?"""
    for n in ast.walk(arbre):
        if not isinstance(n, ast.Call):
            continue
        nom = getattr(n.func, "attr", None) or getattr(n.func, "id", None)
        if nom == "evaluate_pair":
            return True
        if nom != "set_state":
            continue
        # l'etat vise : 2e argument positionnel, ou le mot-cle `new_state`
        cibles = list(n.args[1:2]) + [k.value for k in n.keywords
                                      if k.arg == "new_state"]
        for a in cibles:
            brut = (getattr(a, "attr", None) or getattr(a, "id", None)
                    or getattr(a, "value", None))
            if brut and "AUTO_EXEC" in str(brut):
                return True
    return False


def _inventaire() -> tuple[list[str], list[str]]:
    """`(abonnes, manquants)` parmi les fichiers qui promeuvent."""
    abonnes, manquants = [], []
    for chemin in sorted(_RACINE.glob("test_*.py")):
        if chemin.name in _SURVEILLANTS:
            continue
        src = io.open(chemin, encoding="utf-8", errors="ignore").read()
        try:
            arbre = ast.parse(src)
        except SyntaxError:
            continue
        if not _promeut_en_auto_exec(arbre):
            continue
        (abonnes if "porte_banc_desarmee" in src else manquants
         ).append(chemin.name)
    return abonnes, manquants


# --- LE test ------------------------------------------------------------

def test_chaque_fichier_qui_promeut_est_ABONNE_a_la_porte():
    """⛔ Si ce test échoue, un fichier va devenir un échec INTERMITTENT.

    Le réparer : ajouter dans ce fichier

        @pytest.fixture(autouse=True)
        def _la_porte_du_banc_est_hors_sujet(porte_banc_desarmee):
            \"\"\"...pourquoi la porte est hors sujet ICI...\"\"\"

    ⚠️ Et **pas** en désarmant la porte dans `conftest.py` : elle le serait
    alors pour toute la suite, y compris pour les fichiers qui la surveillent,
    et plus rien ne la garderait.
    """
    _, manquants = _inventaire()
    assert manquants == [], (
        "%d fichier(s) promeuvent en AUTO_EXEC sans s'abonner a "
        "`porte_banc_desarmee` :\n%s\n"
        "Ils passeront ou echoueront SELON L'ORDRE d'execution."
        % (len(manquants), "\n".join("  " + f for f in manquants)))


# --- temoins de l'instrument -------------------------------------------

def test_l_instrument_voit_REELLEMENT_des_fichiers_qui_promeuvent():
    """Si l'inventaire rendait deux listes vides, le test principal serait vert
    sans rien avoir regardé — la panne silencieuse par excellence."""
    abonnes, manquants = _inventaire()
    assert len(abonnes) + len(manquants) >= 8, (
        "seulement %d fichier(s) detecte(s) comme promouvant : la detection "
        "AST a-t-elle cesse de reconnaitre set_state/evaluate_pair ?"
        % (len(abonnes) + len(manquants)))


def test_l_instrument_DETECTE_une_promotion_ecrite_de_trois_facons():
    """Les trois formes réellement présentes dans la suite doivent mordre."""
    positionnel = ast.parse("pac.set_state('XAU/USD', pac.STATE_AUTO_EXEC, 'x')")
    mot_cle = ast.parse("set_state('XAU/USD', new_state='AUTO_EXEC', reason='x')")
    indirect = ast.parse("d = pac.evaluate_pair('XAU/USD', direction='buy')")
    for forme, arbre in (("positionnel", positionnel), ("mot-cle", mot_cle),
                         ("evaluate_pair", indirect)):
        assert _promeut_en_auto_exec(arbre), "forme non detectee : %s" % forme


def test_l_instrument_IGNORE_ce_qui_ne_promeut_pas():
    """Un faux positif ferait exiger la fixture d'un fichier qui n'en a pas
    besoin, et la demande deviendrait du bruit qu'on apprend a ignorer."""
    for source in (
        "pac.set_state('XAU/USD', pac.STATE_PAUSED, 'x')",
        "pac.set_state('XAU/USD', 'TELEGRAM', 'x')",
        "pac.get_current_state('XAU/USD', direction='buy')",
        "# on pose un set_state vers AUTO_EXEC plus loin dans le fichier",
    ):
        assert not _promeut_en_auto_exec(ast.parse(source)), (
            "faux positif sur : %s" % source)


def test_les_SURVEILLANTS_de_la_porte_ne_la_desarment_PAS():
    """⛔ Le témoin qui protège du pire : si un surveillant s'abonnait à la
    fixture, la porte ne serait plus surveillée par personne — et les deux
    tests qui la gardent passeraient, vides."""
    for nom in sorted(_SURVEILLANTS - {"test_abonnement_a_la_porte_du_banc.py"}):
        chemin = _RACINE / nom
        assert chemin.exists(), (
            "%s est declare surveillant mais n'existe pas : la porte n'est "
            "peut-etre plus gardee du tout" % nom)
        src = io.open(chemin, encoding="utf-8", errors="ignore").read()
        assert "porte_banc_desarmee" not in src, (
            "%s SURVEILLE la porte et ne doit jamais la desarmer" % nom)
