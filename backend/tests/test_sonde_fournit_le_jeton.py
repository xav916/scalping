"""L'enveloppe `sonde.sh` doit fournir le jeton aux sondes de cron.

## Le défaut que ce fichier empêche de revenir

Depuis l'audit S-1, 39 fichiers d'exploitation n'ont plus de jeton par défaut :
ils **sortent en erreur** quand `INFRA_NOTIFY_TOKEN` manque. C'est voulu.

⛔ **Mais cron ne donne aucun environnement.** Les crons de l'EC2 ne posent que
`PATH`, `SHELL`, `CRON_TZ` et `MAILTO` — mesuré le 2026-10-31. Poser la
variable dans `/opt/scalping/.env` ne la fait donc **pas** arriver jusqu'à la
sonde : cron ne lit pas ce fichier.

**15 scripts sont à la fois durcis et lancés par un cron**, dont
`check-live-positions-sltp.sh` et `check-kraken-positions-sltp.sh`, qui
tournent **chaque minute** et vérifient la protection SL/TP de positions
réelles. Sans ce correctif, ils mouraient à chaque passage dès le déploiement
— et la contrainte posée était « aucune fenêtre de coupure acceptée ».

🔑 **La leçon : un inventaire qui ne liste que les machines oublie les
automatisations.** J'avais durci les lecteurs et listé les hôtes où poser la
variable ; cron et GitHub Actions sont deux hôtes de plus. C'est la même
famille que « câbler l'acteur ET tous ses observateurs dans le même commit ».

## Ce que ce test garantit

`sonde.sh` lit la variable dans le `.env` quand elle manque, l'exporte vers la
sonde qu'elle enrobe, laisse gagner une variable déjà posée, et **ne refuse
rien elle-même** — le refus reste dans la sonde qui en a besoin.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess

import pytest

_RACINE = pathlib.Path(__file__).resolve().parents[2]
_SONDE = _RACINE / "scripts" / "sonde.sh"

_SANS_BASH = pytest.mark.skipif(
    shutil.which("bash") is None or os.name == "nt",
    reason="MOTIF DOCUMENTE : ces tests lancent `sonde.sh` dans un vrai shell "
           "avec des chemins de fichiers. Sous Windows, Python passe des "
           "chemins `C:\...` que Git Bash ne resout pas, et la sonde rend "
           "une sortie vide — l'echec serait un artefact de plateforme, pas "
           "un defaut. Ils MORDENT en CI (ubuntu-latest), soit exactement la "
           "ou les 14 crons tournent. Le comportement a par ailleurs ete "
           "verifie a la main depuis Git Bash : exit 1 sans le .env, "
           "`RECU:20` et exit 0 avec. Les deux tests de contrat en bas de "
           "fichier, eux, tournent PARTOUT.")

_ENFANT = """#!/bin/bash
# BUT: temoin -- dit si le jeton est arrive
TOKEN="${INFRA_NOTIFY_TOKEN:?INFRA_NOTIFY_TOKEN absente}"
echo "RECU:${#TOKEN}"
"""


def _lancer(tmp_path, env_contenu: str | None, variable: str | None = None):
    """Lance `sonde.sh` sur une sonde temoin et rend `(code, sortie)`."""
    enfant = tmp_path / "enfant.sh"
    enfant.write_text(_ENFANT, encoding="utf-8", newline="\n")
    enfant.chmod(0o755)

    env = {k: v for k, v in os.environ.items() if k != "INFRA_NOTIFY_TOKEN"}
    if env_contenu is None:
        env["SCALPING_ENV_FILE"] = str(tmp_path / "inexistant")
    else:
        fichier = tmp_path / ".env"
        fichier.write_text(env_contenu, encoding="utf-8", newline="\n")
        env["SCALPING_ENV_FILE"] = str(fichier)
    if variable is not None:
        env["INFRA_NOTIFY_TOKEN"] = variable

    r = subprocess.run(["bash", str(_SONDE), str(enfant)],
                       capture_output=True, text=True, env=env, timeout=120,
                       cwd=str(_RACINE))
    return r.returncode, (r.stdout or "") + (r.stderr or "")


# --- LE test ------------------------------------------------------------

@_SANS_BASH
def test_la_sonde_recoit_le_jeton_pose_dans_le_ENV():
    """⛔ LE test qui compte : c'est le chemin exact des 14 crons."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        code, sortie = _lancer(pathlib.Path(d),
                               "AUTRE=x\nINFRA_NOTIFY_TOKEN=jeton-de-preuve-2026\n")
    assert "RECU:20" in sortie, (
        "la sonde n'a pas recu le jeton : %r" % sortie[:300])
    assert code == 0


@_SANS_BASH
def test_sans_ENV_ni_variable_la_sonde_REFUSE_toujours():
    """⛔ Le témoin qui protège du pire : si `sonde.sh` fournissait une valeur
    par défaut, elle réintroduirait exactement le défaut S-1."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        code, sortie = _lancer(pathlib.Path(d), None)
    assert code == 1, "la sonde devait refuser, code obtenu : %d" % code
    assert "INFRA_NOTIFY_TOKEN absente" in sortie


@_SANS_BASH
def test_une_variable_DEJA_posee_gagne_sur_le_fichier():
    """La lecture est un filet pour cron, pas une surcharge."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        code, sortie = _lancer(pathlib.Path(d),
                               "INFRA_NOTIFY_TOKEN=celui-du-fichier-19c\n",
                               variable="celui-de-l-environnement")
    assert "RECU:24" in sortie, (
        "l'environnement devait gagner (24 caracteres) : %r" % sortie[:200])
    assert code == 0


@_SANS_BASH
def test_les_GUILLEMETS_du_env_sont_retires():
    """⚠️ Un `TOKEN="shdw_..."` donnerait un jeton avec ses guillemets, donc un
    hash qui ne correspond pas, donc un **403 silencieux**.

    Ce dépôt a déjà payé cette faute : deux paires fantômes à guillemets
    collés vivent dans la table d'admission depuis le 2026-08-23.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        code, sortie = _lancer(pathlib.Path(d),
                               'INFRA_NOTIFY_TOKEN="jeton-de-preuve-2026"\n')
    assert "RECU:20" in sortie, (
        "les guillemets n'ont pas ete retires (22 au lieu de 20) : %r"
        % sortie[:200])
    assert code == 0


# --- le contrat, verifiable meme sans bash ------------------------------

def test_sonde_sh_ne_porte_AUCUNE_valeur_par_defaut_du_jeton():
    """⛔ `${VAR:-valeur}` ici réintroduirait le défaut S-1 pour 14 sondes
    d'un coup, et de la façon la plus discrète possible."""
    src = _SONDE.read_text(encoding="utf-8", errors="ignore")
    assert "INFRA_NOTIFY_TOKEN" in src, (
        "sonde.sh ne fournit plus le jeton : les 14 sondes de cron vont mourir")
    assert "INFRA_NOTIFY_TOKEN:-}" in src or "INFRA_NOTIFY_TOKEN:-\"\"" in src, (
        "la garde `[ -z \"${INFRA_NOTIFY_TOKEN:-}\" ]` a disparu")
    # aucune valeur de repli autre que la chaine vide
    for interdit in ("INFRA_NOTIFY_TOKEN:-shdw", "INFRA_NOTIFY_TOKEN:-jeton"):
        assert interdit not in src, (
            "sonde.sh porte une valeur par defaut du jeton : %s" % interdit)


def test_sonde_sh_ne_refuse_PAS_elle_meme():
    """Elle enrobe aussi des sondes qui n'ont pas besoin du jeton. Le refus
    appartient à la sonde qui en a besoin, avec son message qui dit quoi
    poser — le déplacer ici casserait les autres."""
    src = _SONDE.read_text(encoding="utf-8", errors="ignore")
    assert "INFRA_NOTIFY_TOKEN:?" not in src, (
        "sonde.sh refuse l'absence du jeton : elle ferait echouer les sondes "
        "qui n'en ont pas besoin")
