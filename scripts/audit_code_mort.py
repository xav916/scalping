#!/usr/bin/env python3
"""Audit du code MORT — modules jamais importes, fonctions jamais appelees.

    python scripts/audit_code_mort.py              # le rapport
    python scripts/audit_code_mort.py --detail     # avec les lignes de definition

Demande de Xavier le 2026-10-11 : « il y a forcement du code mort dans tout
l'outil de scalping, faisons un audit pour le trouver et le supprimer ».

## ⛔ POURQUOI PAS `vulture`, ET CE N'EST PAS PAR GOUT

`vulture` compte les references SYNTAXIQUES. Ce depot est plein de references
qui n'en sont pas :

    getattr(settings, var_token)        le nom du reglage vient d'une TABLE
    os.getenv("XAU_SANS_OBJECTIF")      le drapeau vit dans un .env
    docker exec ... scripts/x.py        l'appelant est une ligne de CRON
    id="echelle_stop_or"                un travail retrouve par son nom
    importlib / __import__              import construit

=> un outil syntaxique declarerait morts des modules appeles chaque minute.
Ce fichier indexe donc TOUT LE TEXTE du depot (py, sh, md, yml, env, cron) et
ne declare mort que ce dont le nom n'apparait **nulle part ailleurs** que dans
son propre fichier de definition.

## ⚠️ ET MEME AINSI, UN RESULTAT N'EST PAS UNE AUTORISATION DE SUPPRIMER

J'ai produit DEUX faux << mort >> le jour meme sur les scripts de l'hote :
`miroir_supabase.py` (appele par une crontab que je n'avais pas lue) et
`disk_reclaim` (un timer systemd). La regle qui en sort : un candidat se
verifie en le RETIRANT et en voyant quelque chose tomber, jamais sur la foi
d'un comptage.
"""
from __future__ import annotations

import ast
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]

# ⛔ Les worktrees d'agents contiennent des COPIES du depot : les indexer
# ferait apparaitre chaque module comme << reference ailleurs >>, et l'audit
# ne trouverait jamais rien.
EXCLUS = {".git", ".claude", "node_modules", "__pycache__", ".venv", "venv",
          "frontend-react", "dist", "build", ".pytest_cache"}

# Les fichiers ou un nom peut etre reference autrement qu'en Python.
SUFFIXES_TEXTE = {".py", ".sh", ".md", ".yml", ".yaml", ".json", ".txt",
                  ".env", ".cfg", ".ini", ".toml", ".sql", ".service",
                  ".timer", ".mq5", ".html"}

# Un nom plus court que ca produit trop de collisions pour conclure.
MIN_NOM = 5


def fichiers(suffixes=None):
    for d, sous, noms in os.walk(RACINE):
        sous[:] = [s for s in sous if s not in EXCLUS and not s.startswith(".")]
        for n in noms:
            p = Path(d) / n
            if suffixes is None or p.suffix in suffixes:
                yield p


def lire(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        return ""


def main() -> int:
    detail = "--detail" in sys.argv

    # ── ① L'index de TOUT le texte, fichier par fichier ──────────────────
    textes: dict[Path, str] = {p: lire(p) for p in fichiers(SUFFIXES_TEXTE)}
    print("indexe : %d fichiers texte" % len(textes))

    # ── ② Les modules Python du projet, et qui les mentionne ─────────────
    # ⛔ SEULS LES MODULES IMPORTABLES. Mon premier passage incluait les
    # fichiers de TESTS et les scripts autonomes, et le resultat etait noye :
    # 357 << morts >> dont l'immense majorite etaient des tests. Un test n'est
    # nomme par personne — pytest le decouvre par son MOTIF de nom — et un
    # script autonome est lance par un cron, pas importe. Les declarer morts
    # etait un artefact de ma portee, pas une trouvaille.
    IMPORTABLES = ("backend/services", "backend/models", "backend/core",
                   "backend/api", "config")
    modules: dict[str, Path] = {}
    for p in fichiers({".py"}):
        rel = p.relative_to(RACINE).as_posix()
        if not any(rel.startswith(d) for d in IMPORTABLES):
            continue
        if p.stem in ("__init__", "conftest"):
            continue
        modules[p.stem] = p

    morts_modules = []
    for nom, p in sorted(modules.items()):
        if len(nom) < MIN_NOM:
            continue
        ailleurs = [q for q, t in textes.items()
                    if q != p and re.search(r"\b%s\b" % re.escape(nom), t)]
        if not ailleurs:
            lignes = len(lire(p).splitlines())
            morts_modules.append((nom, p.relative_to(RACINE), lignes))

    # ── ③ Les fonctions et classes de niveau zero, jamais nommees ailleurs
    morts_defs = []
    for p in fichiers({".py"}):
        rel = p.relative_to(RACINE)
        if not any(rel.as_posix().startswith(d) for d in
                   ("backend/services", "backend/models", "backend/core",
                    "backend/api", "config")):
            continue
        try:
            arbre = ast.parse(lire(p))
        except SyntaxError:
            continue
        for n in arbre.body:
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef)):
                continue
            nom = n.name
            if nom.startswith("__") or len(nom) < MIN_NOM:
                continue
            motif = re.compile(r"\b%s\b" % re.escape(nom))
            vu = False
            for q, t in textes.items():
                if q == p:
                    continue
                if motif.search(t):
                    vu = True
                    break
            if not vu:
                # est-il appele dans son PROPRE fichier ?
                propre = lire(p)
                occ = len(motif.findall(propre))
                if occ <= 1:              # 1 = sa seule definition
                    morts_defs.append((rel, nom, n.lineno,
                                       "jamais nomme, nulle part"))

    # ── ④ Les drapeaux d'environnement lus par le code ───────────────────
    lus: dict[str, list] = defaultdict(list)
    for p in fichiers({".py"}):
        rel = p.relative_to(RACINE)
        if rel.parts[0] not in ("backend", "scripts", "config"):
            continue
        if "tests" in rel.parts:
            continue
        for m in re.finditer(r'(?:os\.)?getenv\(\s*["\']([A-Z][A-Z_0-9]{4,})["\']',
                             lire(p)):
            lus[m.group(1)].append(rel)

    # ── LE RAPPORT ───────────────────────────────────────────────────────
    print()
    print("=" * 66)
    print("① MODULES dont le nom n'apparait NULLE PART ailleurs : %d"
          % len(morts_modules))
    print("=" * 66)
    total = 0
    for nom, rel, lignes in sorted(morts_modules, key=lambda x: -x[2]):
        print("   %6d lignes   %s" % (lignes, rel))
        total += lignes
    print("   ---> %d lignes au total" % total)

    print()
    print("=" * 66)
    print("② FONCTIONS / CLASSES jamais nommees ailleurs : %d" % len(morts_defs))
    print("=" * 66)
    par_fichier: dict = defaultdict(list)
    for rel, nom, ligne, _ in morts_defs:
        par_fichier[rel].append((nom, ligne))
    for rel in sorted(par_fichier, key=lambda r: -len(par_fichier[r]))[:25]:
        noms = par_fichier[rel]
        print("   %-52s %d" % (str(rel), len(noms)))
        if detail:
            for nom, ligne in sorted(noms, key=lambda x: x[1]):
                print("        l.%-5d %s" % (ligne, nom))

    print()
    print("=" * 66)
    print("③ DRAPEAUX d'environnement lus par le code : %d" % len(lus))
    print("=" * 66)
    print("   (a croiser avec le .env de production — fait a part)")
    for nom in sorted(lus):
        print("   %s" % nom)
    return 0


if __name__ == "__main__":
    sys.exit(main())
