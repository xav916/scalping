"""Manifest de deploiement — REM-003 / REM-004.

## Le defaut que ce module supprime

Le 2026-09-25, l'image en service datait du **20/09 20 h 42**. Les ~100 commits
posterieurs etaient dans l'historique et **ne tournaient pas** : un
`systemctl restart` recree le conteneur depuis l'image, il ne la reconstruit
pas. Rien, dans le systeme, ne pouvait dire quel code s'executait.

Corollaire mesure le 2026-09-08 : les taches planifiees de l'hote executaient
`/opt/scalping/scripts/`, un VRAI dossier distinct du clone git. Huit fichiers
y divergeaient.

⇒ « Commite » n'est pas « deploye », et « deploye » n'etait pas verifiable.

## La regle

Le build ECRIT le manifest dans l'image. Le runtime le LIT. Les deux ne peuvent
plus differer sans que ca se voie, parce que le fichier est immuable dans
l'image et que la verification compare ce que l'image declare a ce que
l'environnement attend.

⛔ **Fail-closed (PR-01)** : un manifest absent, illisible ou incoherent rend
`MANIFEST_MISSING` / `MANIFEST_UNREADABLE` / `COMMIT_MISMATCH`, et l'appelant
(le verrou d'execution global) doit refuser d'executer. Un manifest absent
n'est pas « pas de contrainte » — c'est « on ne sait pas ce qui tourne ».
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

#: Emplacement par defaut dans l'image. Ecrit au build, jamais a l'execution.
MANIFEST_PATH_DEFAUT = "/app/deployment_manifest.json"


def manifest_path() -> Path:
    """⛔ Resolu a l'APPEL, pas a l'import.

    Un chemin fige a l'import rend le module intestable : la variable
    d'environnement posee par un test arrive toujours trop tard. C'est le
    meme defaut que « le patch sur un import mort ».
    """
    return Path(os.getenv("DEPLOYMENT_MANIFEST_PATH", MANIFEST_PATH_DEFAUT))

#: Etats explicites de l'integrite du deploiement (PR-02).
OK = "OK"
MANIFEST_MISSING = "MANIFEST_MISSING"
MANIFEST_UNREADABLE = "MANIFEST_UNREADABLE"
MANIFEST_INCOMPLETE = "MANIFEST_INCOMPLETE"
COMMIT_MISMATCH = "COMMIT_MISMATCH"

#: Champs sans lesquels un manifest ne dit rien d'utile.
CHAMPS_REQUIS = (
    "git_commit_sha",
    "git_branch",
    "build_timestamp",
    "configuration_hash",
    "build_environment",
)


@dataclass(frozen=True)
class DeploymentIntegrity:
    """Verdict d'integrite du deploiement en cours."""

    status: str
    running_commit: str | None = None
    expected_commit: str | None = None
    manifest: dict | None = None
    detail: str | None = None

    @property
    def ok(self) -> bool:
        """⛔ Vrai UNIQUEMENT sur OK explicite."""
        return self.status == OK

    def as_details(self) -> dict:
        d = asdict(self)
        # Le manifest complet est volumineux ; on ne garde que l'essentiel
        # dans les details d'un refus.
        if self.manifest:
            d["manifest"] = {
                k: self.manifest.get(k) for k in CHAMPS_REQUIS
            }
        return d


def configuration_hash(env: dict[str, str] | None = None) -> str:
    """Empreinte des reglages qui decident d'un ORDRE REEL.

    ⛔ N'inclut aucune valeur secrete : on hache les cles ET les valeurs des
    seuls reglages de decision, et le resultat est tronque. Un hash qui
    changerait a chaque redemarrage (horodatage, PID) ne servirait a rien ;
    un hash qui inclurait un jeton serait une fuite.

    🔑 La liste est explicite, pas un prefixe : `MT5_*` aurait embarque les
    identifiants du courtier.
    """
    source = env if env is not None else os.environ
    cles = (
        "MT5_BRIDGE_ENABLED",
        "MT5_BRIDGE_LIVE_ENABLED",
        "MT5_BRIDGE_MIN_CONFIDENCE",
        "MT5_BRIDGE_LIVE_MIN_CONFIDENCE",
        "MT5_BRIDGE_ALLOWED_PATTERNS",
        "MT5_BRIDGE_ALLOWED_ASSET_CLASSES",
        "MT5_BRIDGE_LIVE_WHITELIST_PAIRS",
        "MT5_BRIDGE_PATTERN_OVERRIDES",
        "MT5_BRIDGE_BLOCKED_PAIRS",
        "MT5_BRIDGE_BLOCKED_DIRECTIONS",
        "MT5_BRIDGE_MAX_POSITIONS_PER_PAIR",
        "MT5_LONG_HORIZON_ROUTES",
        "CHAINES_AUTORISEES",
        "WATCHED_PAIRS",
        "TRADING_CAP_EUR",
        "RISK_PCT_PAR_DESTINATION",
        "GLOBAL_EXECUTION_ENABLED",
    )
    payload = "\n".join(f"{k}={source.get(k, '')}" for k in cles)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _lire_brut(path: Path | None = None) -> tuple[dict | None, str]:
    p = path or manifest_path()
    if not p.exists():
        return None, MANIFEST_MISSING
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        logger.error("REM-003 manifest illisible (%s) : %s", p, e)
        return None, MANIFEST_UNREADABLE
    if not isinstance(data, dict):
        return None, MANIFEST_UNREADABLE
    manquants = [c for c in CHAMPS_REQUIS if not data.get(c)]
    if manquants:
        logger.error("REM-003 manifest incomplet, manque : %s", manquants)
        return data, MANIFEST_INCOMPLETE
    return data, OK


def read_manifest(path: Path | None = None) -> dict | None:
    """Le manifest tel qu'ecrit au build, ou None s'il est inutilisable."""
    data, status = _lire_brut(path)
    return data if status == OK else None


def check_integrity(
    expected_commit: str | None = None,
    path: Path | None = None,
) -> DeploymentIntegrity:
    """Le code qui tourne est-il celui qu'on croit ?

    `expected_commit` vient de l'environnement (`EXPECTED_GIT_COMMIT`), pose
    par le script de deploiement. Absent, on ne peut pas comparer — mais le
    manifest doit tout de meme etre lisible et complet, sinon on ne sait pas
    ce qui tourne.
    """
    data, status = _lire_brut(path)
    if status != OK:
        return DeploymentIntegrity(
            status=status, manifest=data,
            detail=f"manifest inutilisable : {status}",
        )

    running = str(data.get("git_commit_sha", ""))
    attendu = expected_commit or os.getenv("EXPECTED_GIT_COMMIT") or None
    if attendu:
        # Comparaison par prefixe : un sha court dans l'env doit matcher.
        court = min(len(running), len(attendu))
        if running[:court].lower() != attendu[:court].lower():
            logger.error(
                "REM-003 divergence de commit : image=%s attendu=%s",
                running[:12], attendu[:12])
            return DeploymentIntegrity(
                status=COMMIT_MISMATCH, running_commit=running,
                expected_commit=attendu, manifest=data,
                detail="le code qui tourne n'est pas celui qui est attendu",
            )

    return DeploymentIntegrity(
        status=OK, running_commit=running, expected_commit=attendu,
        manifest=data,
    )


def fingerprint(path: Path | None = None) -> str | None:
    """Empreinte d'IDENTITE DU CODE, pour armer un verrou sur CE code-la.

    ⛔ **DECISION DE PORTEE, prise le 2026-09-28 et a assumer.** Ma premiere
    version combinait le commit ET l'empreinte de configuration : tout
    changement de reglage invalidait l'armement. C'est plus fort, et c'est
    ce qui aurait attrape le rearmement silencieux du 22/09.

    Mais ce n'est pas ce que le cahier des charges met en P0 : il demande la
    fermeture sur « nouveau deploiement » et « incoherence de version » — deux
    faits d'IDENTITE DU CODE. Un changement de reglage n'est pas en soi une
    incoherence ; sa gouvernance est REM-023 (P2, « gestion controlee des
    configurations »).

    ⇒ L'armement porte donc sur le COMMIT. La derive de configuration est
    **mesuree et publiee** (`global_execution_switch.status()` rend
    `configuration_drift`), mais elle ne ferme pas encore la porte.

    🔴 CE N'EST PAS UNE PROTECTION COMPLETE, et il faut le dire : jusqu'a
    REM-023, editer `/opt/scalping/.env` puis redemarrer NE demande PAS de
    re-armer. C'est precisement le geste du 22/09. La derive se voit, elle
    n'arrete rien.
    """
    data = read_manifest(path)
    if not data:
        return None
    return str(data.get("git_commit_sha", ""))[:12] or None


def public_version(path: Path | None = None) -> dict:
    """Charge utile de `/system/version`. Ne contient aucun secret."""
    integrity = check_integrity(path=path)
    data = integrity.manifest or {}
    return {
        "status": integrity.status,
        "ok": integrity.ok,
        "git_commit_sha": data.get("git_commit_sha"),
        "git_branch": data.get("git_branch"),
        "build_timestamp": data.get("build_timestamp"),
        "docker_image_digest": data.get("docker_image_digest"),
        "configuration_hash_build": data.get("configuration_hash"),
        "configuration_hash_runtime": configuration_hash(),
        "database_schema_version": data.get("database_schema_version"),
        "research_rules_version": data.get("research_rules_version"),
        "risk_rules_version": data.get("risk_rules_version"),
        "build_environment": data.get("build_environment"),
        "deployment_timestamp": data.get("deployment_timestamp"),
        "expected_commit": integrity.expected_commit,
        "fingerprint": fingerprint(path),
    }
