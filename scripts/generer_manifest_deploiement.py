#!/usr/bin/env python3
"""Ecrit `deployment_manifest.json` — REM-003. A lancer AU BUILD, jamais apres.

Usage (depuis la racine du depot, sur la machine qui construit l'image) :

    python scripts/generer_manifest_deploiement.py --out deployment_manifest.json

⛔ Ce script lit l'etat git du repertoire de travail. Il doit donc tourner
AVANT `docker build`, dans le clone qui sera copie dans l'image. Le lancer
depuis l'interieur du conteneur ne dirait rien : il n'y a pas de `.git`.

⚠️ Si l'arbre de travail est SALE, le manifest le dit (`git_dirty: true`) et
le commit ne suffit plus a identifier le code. Le verrou d'execution global
refuse d'armer dans ce cas — c'est voulu : « a peu pres ce commit » n'est pas
une identification.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ("git", *args), cwd=RACINE, capture_output=True, text=True,
            timeout=30, check=False,
        )
        return out.stdout.strip() or None if out.returncode == 0 else None
    except Exception:  # noqa: BLE001
        return None


def _schema_version() -> str | None:
    """Version du schema de base, si le depot la declare quelque part."""
    for cand in ("backend/migrations/VERSION", "backend/db/SCHEMA_VERSION"):
        p = RACINE / cand
        if p.exists():
            return p.read_text(encoding="utf-8").strip()
    # A defaut : empreinte du fichier qui cree le schema.
    for cand in ("backend/services/trade_log_service.py",):
        p = RACINE / cand
        if p.exists():
            import hashlib
            return hashlib.sha256(p.read_bytes()).hexdigest()[:12]
    return None


def _rules_version(chemin: str) -> str | None:
    """Empreinte d'un jeu de regles, pour qu'un changement se VOIE."""
    p = RACINE / chemin
    if not p.exists():
        return None
    import hashlib
    return hashlib.sha256(p.read_bytes()).hexdigest()[:12]


def construire() -> dict:
    sys.path.insert(0, str(RACINE))
    from backend.services.deployment_manifest import configuration_hash

    statut = _git("status", "--porcelain")
    return {
        "git_commit_sha": _git("rev-parse", "HEAD"),
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "git_dirty": bool(statut),
        "git_dirty_files": (statut or "").splitlines()[:20],
        "build_timestamp": datetime.now(timezone.utc).isoformat(),
        "docker_image_digest": os.getenv("DOCKER_IMAGE_DIGEST"),
        "configuration_hash": configuration_hash(),
        "database_schema_version": _schema_version(),
        "research_rules_version": _rules_version(
            "backend/services/laboratoire_or.py"),
        "risk_rules_version": _rules_version("backend/services/sizing.py"),
        "build_environment": os.getenv("BUILD_ENVIRONMENT", "unknown"),
        "deployment_timestamp": os.getenv("DEPLOYMENT_TIMESTAMP"),
        "manifest_schema": 1,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="deployment_manifest.json")
    ap.add_argument(
        "--exiger-propre", action="store_true",
        help="echoue si l'arbre de travail est sale",
    )
    args = ap.parse_args()

    m = construire()
    if not m["git_commit_sha"]:
        print("ERREUR : aucun commit git lisible — manifest inutilisable",
              file=sys.stderr)
        return 2
    if args.exiger_propre and m["git_dirty"]:
        print("ERREUR : arbre de travail SALE, refus de generer un manifest",
              file=sys.stderr)
        for f in m["git_dirty_files"]:
            print("   ", f, file=sys.stderr)
        return 3

    Path(args.out).write_text(
        json.dumps(m, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    etat = "SALE" if m["git_dirty"] else "propre"
    print(f"manifest ecrit : {args.out}")
    print(f"  commit  {m['git_commit_sha'][:12]} ({m['git_branch']}, {etat})")
    print(f"  config  {m['configuration_hash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
