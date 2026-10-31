"""Aucun jeton d'infrastructure ne doit revenir dans un fichier suivi.

## Le défaut qu'il garde

Audit S-1 (ÉLEVÉ) : le jeton `shdw_…` était publié en clair dans la
documentation, servait de **valeur par défaut** dans 36 scripts
d'exploitation, 2 sondes et 1 script PowerShell, figurait dans 6 tests, et
son hash était écrit **en dur à neuf endroits** de `backend/app.py`.

> « Le dépôt étant cloné dans des environnements d'agents, le jeton est de
> fait diffusé. »

🔑 **Ce test fait foi du périmètre.** Un nettoyage se constate, il ne se
promet pas : sans garde, la valeur par défaut revient au premier script écrit
dans l'urgence, et personne ne le voit.

## Ce qu'il interdit, et ce qu'il autorise

⛔ Interdit : une chaîne **de la forme d'un jeton** — `shdw_` suivi d'au
moins 16 caractères. Le vrai jeton en comptait 32.

✅ Autorisé : le **préfixe seul**. Il n'est pas un secret, et l'interdire
rendrait impossible de documenter la commande de génération
(`print('shdw_'+secrets.token_urlsafe(24))`) ou d'expliquer, dans un test,
pourquoi le jeton de test l'évite.

✅ Autorisé aussi : `docs/audit-externe-2026-09-16.md`. Un audit qui cite le
secret qu'il dénonce est une **pièce à conviction**, pas une fuite à
corriger — et le réécrire effacerait la preuve du constat.
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess

# `shdw_` suivi d'au moins 16 caracteres de jeton. Le vrai en avait 32.
_FORME_JETON = re.compile(r"shdw_[A-Za-z0-9_\-]{16,}")

_RACINE = pathlib.Path(__file__).resolve().parents[2]

#: Seul fichier autorise a porter le jeton : il le DENONCE.
_AUDIT = "docs/audit-externe-2026-09-16.md"

_IGNORES = {".git", "node_modules", "__pycache__", ".pytest_cache",
            ".worktrees", "venv", ".venv", "dist", "build", ".omc"}


def _fichiers_suivis() -> list[str]:
    """Les fichiers SUIVIS par git, ou, à défaut, l'arborescence.

    ⛔ Pas de `pytest.skip` si git manque : un garde-fou qui s'absente quand
    son outil manque ne garde rien, et un `skipped` se lit comme un `passed`
    dans un compteur. On retombe donc sur un parcours de fichiers.
    """
    try:
        out = subprocess.run(["git", "ls-files"], cwd=_RACINE,
                             capture_output=True, text=True, timeout=120)
        if out.returncode == 0 and out.stdout.strip():
            return [l for l in out.stdout.splitlines() if l.strip()]
    except (OSError, subprocess.SubprocessError):
        pass
    trouves = []
    for dossier, sous, fichiers in os.walk(_RACINE):
        sous[:] = [d for d in sous if d not in _IGNORES]
        for f in fichiers:
            p = pathlib.Path(dossier, f)
            trouves.append(str(p.relative_to(_RACINE)).replace(os.sep, "/"))
    return trouves


def _porteurs() -> dict[str, list[int]]:
    """{chemin: [lignes]} des fichiers portant une chaîne de forme jeton."""
    porteurs: dict[str, list[int]] = {}
    for rel in _fichiers_suivis():
        if rel == _AUDIT:
            continue
        chemin = _RACINE / rel
        try:
            texte = chemin.read_text(encoding="utf-8", errors="ignore")
        except (OSError, IsADirectoryError):
            continue
        lignes = [i for i, l in enumerate(texte.splitlines(), 1)
                  if _FORME_JETON.search(l)]
        if lignes:
            porteurs[rel] = lignes
    return porteurs


# --- LE test ------------------------------------------------------------

def test_aucun_jeton_de_forme_complete_dans_un_fichier_suivi():
    """⛔ Si ce test échoue, un secret est revenu dans le dépôt.

    Le réparer, ce n'est pas assouplir ce test : c'est lire
    `INFRA_NOTIFY_TOKEN` depuis l'environnement, **sans valeur par défaut**,
    et s'arrêter avec un message clair si elle manque.
    """
    porteurs = _porteurs()
    assert porteurs == {}, (
        "jeton d'infrastructure retrouve dans %d fichier(s) suivi(s) :\n%s\n"
        "Lire INFRA_NOTIFY_TOKEN depuis l'environnement, sans defaut."
        % (len(porteurs),
           "\n".join("  %s : ligne(s) %s" % (f, l)
                     for f, l in sorted(porteurs.items()))))


# --- temoins de l'instrument -------------------------------------------

def test_l_instrument_DETECTE_bien_une_chaine_de_forme_jeton():
    """⛔ Un garde-fou qui ne détecte rien passe toujours. Témoin obligatoire :
    sans lui, le test précédent serait vert même avec une expression cassée."""
    # ⛔ Les temoins sont ASSEMBLES a l'execution, et leur corps est
    # manifestement faux. Ecrire un vrai jeton ici le REINTRODUIRAIT dans le
    # depot -- ce que ce fichier a fait jusqu'au 2026-10-31 : il portait le
    # jeton de l'audit en clair a cette ligne meme.
    #
    # 🔑 Et il restait VERT, parce que `git ls-files` ne le listait pas encore
    # quand sa preuve a tourne : il n'etait pas SUIVI. Un garde-fou qui
    # s'evalue sur un instantane d'ou il est absent ne se garde pas lui-meme.
    # Il ne s'est denonce qu'au commit SUIVANT, une fois entre dans l'index.
    forme = "shdw_" + "FAUX" * 4 + "_temoin"
    assert _FORME_JETON.search("token=" + forme)
    assert _FORME_JETON.search('TOKEN="shdw_' + "a" * 20 + '"')


def test_l_instrument_AUTORISE_le_prefixe_seul():
    """Le préfixe n'est pas un secret : la commande de génération et
    l'explication d'un test doivent rester écrivables."""
    assert not _FORME_JETON.search(
        """python -c "import secrets; print('shdw_'+secrets.token_urlsafe(24))" """)
    assert not _FORME_JETON.search("il ne commence pas par `shdw_` : le garde-fou")


def test_l_instrument_voit_REELLEMENT_des_fichiers():
    """Si l'énumération rendait une liste vide, le test principal serait vert
    sans rien avoir regardé — la panne silencieuse par excellence."""
    fichiers = _fichiers_suivis()
    assert len(fichiers) > 500, "seulement %d fichiers vus" % len(fichiers)
    assert any(f.endswith("backend/app.py") for f in fichiers)


def test_l_audit_est_bien_EXCLU_et_porte_encore_le_jeton():
    """La seule exception doit être réelle : si l'audit ne portait plus le
    jeton, l'exception serait du bruit à retirer."""
    audit = (_RACINE / _AUDIT)
    assert audit.exists(), "l'audit a disparu : l'exclusion est-elle encore utile ?"
    assert _FORME_JETON.search(audit.read_text(encoding="utf-8", errors="ignore")), (
        "l'audit ne porte plus le jeton : retirer l'exclusion de ce test")


# --- uniformite du garde dans les scripts d'exploitation ----------------

def test_chaque_lecteur_du_jeton_REFUSE_quand_il_manque():
    """🔑 Le garde est recopié dans 39 fichiers : la duplication n'est
    acceptable que si elle est VÉRIFIÉE.

    Tout fichier qui lit `INFRA_NOTIFY_TOKEN` doit aussi porter son refus :
    `${VAR:?...}` en shell, un `SystemExit` en Python, un `exit 1` en
    PowerShell. Un lecteur sans refus, c'est une valeur par défaut qui
    revient — vide cette fois, donc une requête non authentifiée.
    """
    sans_refus = []
    for rel in _fichiers_suivis():
        if not rel.startswith(("scripts/", "monitoring/", "mt5-bridge/")):
            continue
        if not rel.endswith((".py", ".sh", ".ps1")):
            continue
        texte = (_RACINE / rel).read_text(encoding="utf-8", errors="ignore")
        if "INFRA_NOTIFY_TOKEN" not in texte:
            continue
        refuse = ("INFRA_NOTIFY_TOKEN:?" in texte      # shell
                  or "raise SystemExit" in texte       # python
                  or "exit 1" in texte)                # powershell
        if not refuse:
            sans_refus.append(rel)
    assert sans_refus == [], (
        "%d fichier(s) lisent INFRA_NOTIFY_TOKEN sans refuser son absence :\n%s"
        % (len(sans_refus), "\n".join("  " + f for f in sans_refus)))
