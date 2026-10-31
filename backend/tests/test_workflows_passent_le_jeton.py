"""Un workflow qui exécute un lecteur du jeton doit lui PASSER le jeton.

## Le défaut que ce fichier empêche de revenir

Depuis l'audit S-1, 40 fichiers d'exploitation n'ont plus de jeton par
défaut : ils **sortent en erreur** quand `INFRA_NOTIFY_TOKEN` manque. C'est
voulu — une valeur par défaut était le défaut à corriger.

⛔ **Mais deux workflows planifiés les exécutaient sans passer la variable.**
`ea-health-check.yml` lance `monitoring/ea-health-check.sh` et
`ea-health-monitor.yml` lance `scripts/ea_health_monitor.py`, tous deux quatre
fois par jour. Après le durcissement, ils auraient échoué **4 fois par jour**,
en silence pour qui ne lit pas les runs — et le contrôle de santé du pont
serait mort sans que personne ne l'apprenne.

🔑 **C'est la même famille que « câbler l'acteur ET tous ses observateurs dans
le même commit ».** J'avais durci les lecteurs et listé les hôtes où poser la
variable ; j'avais oublié que **GitHub Actions est un hôte de plus**. Un
inventaire qui ne liste que les machines oublie les automatisations.

## Ce que ce test vérifie

Pour chaque workflow : s'il exécute un fichier du dépôt qui lit
`INFRA_NOTIFY_TOKEN`, alors ce workflow doit poser la variable — au niveau du
`job` ou de l'`step`. Sinon le run échouera.
"""
from __future__ import annotations

import pathlib
import re

import pytest

_RACINE = pathlib.Path(__file__).resolve().parents[2]
_WORKFLOWS = _RACINE / ".github" / "workflows"

#: les chemins de fichiers cites dans un `run:` -- shell ou python
_APPEL = re.compile(
    r"(?:(?:bash|sh|python3?)\s+|\./)([A-Za-z0-9_./-]+\.(?:sh|py))")


def _lecteurs_du_jeton() -> set[str]:
    """Les fichiers du depot qui lisent `INFRA_NOTIFY_TOKEN`."""
    trouves = set()
    for motif in ("scripts/*.py", "scripts/*.sh", "monitoring/*.sh",
                  "monitoring/*.py"):
        for chemin in _RACINE.glob(motif):
            texte = chemin.read_text(encoding="utf-8", errors="ignore")
            if "INFRA_NOTIFY_TOKEN" in texte:
                trouves.add(chemin.relative_to(_RACINE).as_posix())
    return trouves


def _workflows() -> list[pathlib.Path]:
    if not _WORKFLOWS.is_dir():
        return []
    return sorted(list(_WORKFLOWS.glob("*.yml")) + list(_WORKFLOWS.glob("*.yaml")))


def _manquants() -> dict[str, list[str]]:
    """{workflow: [lecteurs appeles]} pour ceux qui ne passent pas la variable."""
    lecteurs = _lecteurs_du_jeton()
    fautifs: dict[str, list[str]] = {}
    for wf in _workflows():
        texte = wf.read_text(encoding="utf-8", errors="ignore")
        appeles = [c for c in _APPEL.findall(texte) if c in lecteurs]
        if not appeles:
            continue
        # la variable doit etre posee quelque part dans le workflow
        if "INFRA_NOTIFY_TOKEN" not in texte:
            fautifs[wf.name] = sorted(set(appeles))
    return fautifs


# --- LE test ------------------------------------------------------------

def test_chaque_workflow_qui_lance_un_lecteur_lui_PASSE_le_jeton():
    """⛔ Si ce test échoue, un workflow planifié va mourir à sa prochaine
    exécution — et personne ne le verra tant qu'il ne lira pas les runs.

    Le réparer : ajouter dans l'étape concernée

        env:
          INFRA_NOTIFY_TOKEN: ${{ secrets.INFRA_NOTIFY_TOKEN }}

    et créer le secret dans GitHub (Settings > Secrets and variables >
    Actions), avec la même valeur que dans le `.env` de l'EC2.

    ⚠️ Et **jamais** en remettant une valeur par défaut dans le script : c'est
    exactement le défaut S-1 que le durcissement a corrigé.
    """
    fautifs = _manquants()
    assert fautifs == {}, (
        "%d workflow(s) lancent un lecteur de INFRA_NOTIFY_TOKEN sans le "
        "passer :\n%s" % (len(fautifs), "\n".join(
            "  %s -> %s" % (wf, ", ".join(f)) for wf, f in sorted(fautifs.items()))))


# --- temoins de l'instrument -------------------------------------------

def test_l_instrument_voit_REELLEMENT_des_workflows_et_des_lecteurs():
    """Deux énumérations vides rendraient le test principal vert sans rien
    avoir regardé — la panne silencieuse par excellence."""
    wf = _workflows()
    assert len(wf) >= 3, "seulement %d workflow(s) vu(s)" % len(wf)
    lecteurs = _lecteurs_du_jeton()
    assert len(lecteurs) >= 30, (
        "seulement %d lecteur(s) du jeton detecte(s) : l'enumeration a-t-elle "
        "cesse de fonctionner ?" % len(lecteurs))


@pytest.mark.parametrize("ligne,attendu", [
    ("        run: bash monitoring/ea-health-check.sh", "monitoring/ea-health-check.sh"),
    ("        run: python3 scripts/ea_health_monitor.py", "scripts/ea_health_monitor.py"),
    ("          run: python scripts/x.py", "scripts/x.py"),
    ("        run: ./scripts/y.sh", "scripts/y.sh"),
])
def test_l_instrument_reconnait_les_formes_d_appel(ligne, attendu):
    """Les quatre formes réellement écrites dans ce dépôt doivent mordre."""
    trouves = _APPEL.findall(ligne)
    assert attendu in trouves, "forme non reconnue : %r -> %r" % (ligne, trouves)


def test_l_instrument_IGNORE_ce_qui_n_appelle_aucun_lecteur():
    """Un faux positif ferait exiger la variable d'un workflow qui n'en a pas
    besoin, et la demande deviendrait du bruit qu'on apprend a ignorer."""
    faux = {
        "run: echo bonjour",
        "run: npm test",
        "uses: actions/checkout@v4",
        "# on lance monitoring/ea-health-check.sh ailleurs",
    }
    lecteurs = _lecteurs_du_jeton()
    for ligne in faux:
        appeles = [c for c in _APPEL.findall(ligne) if c in lecteurs]
        if "#" in ligne:
            # un commentaire PEUT matcher : c'est pourquoi le test principal
            # exige la variable seulement, et n'interdit rien.
            continue
        assert appeles == [], "faux positif sur %r -> %r" % (ligne, appeles)


def test_les_deux_workflows_de_sante_passent_bien_le_jeton():
    """Le cas concret qui a motivé ce fichier, verrouillé nommément."""
    for nom in ("ea-health-check.yml", "ea-health-monitor.yml"):
        chemin = _WORKFLOWS / nom
        assert chemin.exists(), "%s a disparu" % nom
        texte = chemin.read_text(encoding="utf-8", errors="ignore")
        assert "secrets.INFRA_NOTIFY_TOKEN" in texte, (
            "%s ne passe plus le jeton : il echouera 4 fois par jour" % nom)
