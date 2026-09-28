"""Verrou d'execution global — REM-002. Fail-CLOSED, independant des strategies.

## Ce qu'il fait, et ce qu'il ne fait PAS

Il interdit **l'envoi de nouveaux ordres**. Il n'empeche jamais :

- la surveillance des positions ouvertes ;
- leur fermeture (y compris la fermeture d'urgence) ;
- la recuperation des donnees du courtier ;
- l'audit, les sondes, la reconciliation.

🔑 C'est la distinction qui compte : un verrou qui couperait aussi les
fermetures transformerait une precaution en piege. Les positions ouvertes
doivent pouvoir mourir proprement pendant que la porte d'entree est fermee.

## Pourquoi il est distinct de `kill_switch`

`kill_switch` existe depuis avril et fait autre chose : pauses par paire sur
rafale de stops, plafond de perte journaliere par compte, coupure manuelle.
Ses declencheurs sont des faits de MARCHE.

Ce verrou-ci a des declencheurs d'INTEGRITE : est-ce qu'on sait quel code
tourne, est-ce que la comptabilite se reconcilie, est-ce que la surveillance
parle. Melanger les deux rendrait impossible de dire pourquoi on est coupe.

⚠️ Les deux s'appliquent. Ce module ne remplace ni ne contourne `kill_switch`.

## La regle (PR-01)

    etat persistant absent / illisible    -> DENY  (on ne sait pas)
    empreinte de deploiement differente   -> DENY  (nouveau deploiement)
    manifest absent / incoherent          -> DENY  (code inconnu)
    desarme a la main                     -> DENY
    blocage d'integrite declare           -> DENY
    arme POUR CE deploiement, rien d'autre-> ALLOW

⛔ Le defaut est `DENY`. Un nouveau deploiement doit etre **re-arme
explicitement**, parce que c'est exactement le moment ou l'on ne sait plus ce
qui tourne — et c'est le moment ou le fail-open du 2026-09-25 est parti en
production.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# ⛔ DANS LE VOLUME MONTE, pas dans /var/lib/scalping (2026-09-28).
#
# `/var/lib/scalping` est un chemin de l'HOTE, utilise par les crons de l'hote.
# Le conteneur ne le voit PAS : `scalping.service` ne monte que
# `-v /opt/scalping/data:/app/data`. Y ecrire l'etat d'armement l'aurait fait
# disparaitre a chaque redemarrage — donc `STATE_MISSING`, donc DENY, donc un
# re-armement exige apres chaque restart. Un restart n'est pas un
# deploiement : c'est l'empreinte de commit qui doit invalider l'armement,
# pas la perte du fichier.
#
# 🔑 `/opt/scalping/data` est aussi le seul chemin protege du `rsync --delete`
# du deploiement (incident du 2026-05-18).
ETAT_PATH_DEFAUT = "/app/data/global_execution_switch.json"


def etat_path() -> Path:
    """⛔ Resolu a l'APPEL, pas a l'import — voir `deployment_manifest`."""
    return Path(os.getenv("GLOBAL_EXECUTION_STATE_PATH", ETAT_PATH_DEFAUT))

# ─── Etats explicites (PR-02) ──────────────────────────────────────────
ALLOW = "ALLOW"
DENY = "DENY"

# ─── Motifs de refus, chacun auditable ─────────────────────────────────
ARMED = "ARMED"
STATE_MISSING = "STATE_MISSING"
STATE_UNREADABLE = "STATE_UNREADABLE"
DISARMED_MANUALLY = "DISARMED_MANUALLY"
NEW_DEPLOYMENT = "NEW_DEPLOYMENT"
DEPLOYMENT_INTEGRITY = "DEPLOYMENT_INTEGRITY"
INTEGRITY_BLOCK = "INTEGRITY_BLOCK"
CONTROL_ERROR = "CONTROL_ERROR"

#: Motif expose au journal des refus.
REJECTION_REASON = "execution_globale_fermee"

#: Blocages d'integrite que d'autres sous-systemes peuvent poser.
#: ⚠️ Chacun doit etre leve EXPLICITEMENT, jamais par expiration.
BLOCAGES_CONNUS = (
    "reconciliation_error",      # divergence comptable (REM-005)
    "monitoring_down",           # plus de heartbeat (LOT 4)
    "broker_unreachable",        # le pont ne repond pas
    "configuration_error",       # reglage invalide
    "critical_anomaly",          # anomalie critique ouverte
)


@dataclass(frozen=True)
class ExecutionDecision:
    decision: str
    reason_code: str
    fingerprint_running: str | None = None
    fingerprint_armed: str | None = None
    blocages: tuple[str, ...] = ()
    detail: str | None = None
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def allowed(self) -> bool:
        """⛔ Vrai UNIQUEMENT sur ALLOW explicite."""
        return self.decision == ALLOW

    def as_details(self) -> dict:
        return {
            "decision": self.decision,
            "reason_code": self.reason_code,
            "fingerprint_running": self.fingerprint_running,
            "fingerprint_armed": self.fingerprint_armed,
            "blocages": list(self.blocages),
            "detail": self.detail,
            "timestamp": self.timestamp,
        }


def _defaut() -> dict:
    return {
        "armed": False,
        "armed_fingerprint": None,
        "armed_at": None,
        "armed_by": None,
        "armed_reason": None,
        "blocages": {},
    }


def _lire_etat() -> tuple[dict | None, str]:
    p = etat_path()
    if not p.exists():
        return None, STATE_MISSING
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None, STATE_UNREADABLE
        return data, ARMED
    except Exception as e:  # noqa: BLE001
        logger.error("REM-002 etat du verrou illisible : %s", e)
        return None, STATE_UNREADABLE


def _ecrire_etat(data: dict) -> None:
    p = etat_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(p)


def execution_allowed() -> ExecutionDecision:
    """La seule fonction autorisee a dire si un ordre NEUF peut partir.

    ⛔ Ne leve jamais : une exception devient DENY/CONTROL_ERROR.
    """
    try:
        from backend.services import deployment_manifest as dm

        empreinte = dm.fingerprint()
        integrite = dm.check_integrity()

        # 1) Le code qui tourne doit etre identifiable ET attendu.
        if not integrite.ok:
            logger.error(
                "REM-002 execution fermee : integrite du deploiement = %s",
                integrite.status)
            return ExecutionDecision(
                decision=DENY, reason_code=DEPLOYMENT_INTEGRITY,
                fingerprint_running=empreinte,
                detail=integrite.detail or integrite.status,
            )

        # 2) L'etat persistant doit exister et etre lisible.
        etat, lecture = _lire_etat()
        if etat is None:
            return ExecutionDecision(
                decision=DENY, reason_code=lecture,
                fingerprint_running=empreinte,
                detail="aucun etat d'armement lisible : on ne sait pas",
            )

        # 3) Un blocage d'integrite pose par un autre sous-systeme ferme.
        blocages = tuple(
            sorted(k for k, v in (etat.get("blocages") or {}).items() if v)
        )
        if blocages:
            return ExecutionDecision(
                decision=DENY, reason_code=INTEGRITY_BLOCK,
                fingerprint_running=empreinte,
                fingerprint_armed=etat.get("armed_fingerprint"),
                blocages=blocages,
                detail="blocage(s) d'integrite en cours",
            )

        # 4) Desarme a la main.
        if not etat.get("armed"):
            return ExecutionDecision(
                decision=DENY, reason_code=DISARMED_MANUALLY,
                fingerprint_running=empreinte,
                fingerprint_armed=etat.get("armed_fingerprint"),
                detail=etat.get("armed_reason"),
            )

        # 5) ⛔ L'armement porte sur UN deploiement. Un nouveau build, ou un
        #    changement de reglage de decision, invalide l'armement.
        arme_pour = etat.get("armed_fingerprint")
        if not arme_pour or not empreinte or arme_pour != empreinte:
            logger.error(
                "REM-002 execution fermee : arme pour %s, tourne %s",
                arme_pour, empreinte)
            return ExecutionDecision(
                decision=DENY, reason_code=NEW_DEPLOYMENT,
                fingerprint_running=empreinte, fingerprint_armed=arme_pour,
                detail="ce deploiement n'a pas ete arme explicitement",
            )

        return ExecutionDecision(
            decision=ALLOW, reason_code=ARMED,
            fingerprint_running=empreinte, fingerprint_armed=arme_pour,
        )
    except Exception as e:  # noqa: BLE001
        logger.error("REM-002 verrou global : erreur interne (%s) -> DENY", e)
        return ExecutionDecision(
            decision=DENY, reason_code=CONTROL_ERROR, detail=str(e))


# ─── Gestes explicites ─────────────────────────────────────────────────


def arm(reason: str, by: str = "manual") -> ExecutionDecision:
    """Arme l'execution POUR LE DEPLOIEMENT EN COURS, et lui seul.

    ⛔ Refuse d'armer si l'integrite du deploiement n'est pas OK : on
    n'autorise pas un code qu'on ne sait pas identifier.
    """
    from backend.services import deployment_manifest as dm

    integrite = dm.check_integrity()
    if not integrite.ok:
        logger.error("REM-002 armement REFUSE : integrite = %s",
                     integrite.status)
        return ExecutionDecision(
            decision=DENY, reason_code=DEPLOYMENT_INTEGRITY,
            detail=f"armement refuse : {integrite.status}",
        )
    empreinte = dm.fingerprint()
    if not empreinte:
        return ExecutionDecision(
            decision=DENY, reason_code=DEPLOYMENT_INTEGRITY,
            detail="empreinte de deploiement indisponible",
        )

    etat, _ = _lire_etat()
    etat = etat or _defaut()
    etat.update({
        "armed": True,
        "armed_fingerprint": empreinte,
        # ⚠️ Enregistre mais PAS applique en P0 — cf. la note de portee dans
        # `deployment_manifest.fingerprint`. Il sert a PUBLIER la derive.
        "armed_configuration_hash": dm.configuration_hash(),
        "armed_at": datetime.now(timezone.utc).isoformat(),
        "armed_by": by,
        "armed_reason": reason,
    })
    _ecrire_etat(etat)
    logger.warning("REM-002 execution ARMEE pour %s par %s (%s)",
                   empreinte, by, reason)
    return execution_allowed()


def disarm(reason: str, by: str = "manual") -> ExecutionDecision:
    """Ferme l'execution. Toujours autorise — une coupure ne se negocie pas."""
    etat, _ = _lire_etat()
    etat = etat or _defaut()
    etat.update({
        "armed": False,
        "armed_reason": reason,
        "armed_by": by,
        "disarmed_at": datetime.now(timezone.utc).isoformat(),
    })
    _ecrire_etat(etat)
    logger.warning("REM-002 execution FERMEE par %s (%s)", by, reason)
    return execution_allowed()


def set_blocage(nom: str, actif: bool, detail: str | None = None) -> None:
    """Pose ou leve un blocage d'integrite nomme.

    ⚠️ `nom` hors `BLOCAGES_CONNUS` est accepte et journalise : un blocage
    inconnu doit fermer, pas etre ignore. Refuser un nom inconnu reviendrait
    a rendre un garde-fou silencieux.
    """
    if nom not in BLOCAGES_CONNUS:
        logger.warning("REM-002 blocage NON declare : %s (accepte quand meme)",
                       nom)
    etat, _ = _lire_etat()
    etat = etat or _defaut()
    blocages = dict(etat.get("blocages") or {})
    if actif:
        blocages[nom] = {
            "detail": detail,
            "at": datetime.now(timezone.utc).isoformat(),
        }
        logger.error("REM-002 blocage POSE : %s (%s)", nom, detail)
    else:
        blocages.pop(nom, None)
        logger.warning("REM-002 blocage LEVE : %s", nom)
    etat["blocages"] = blocages
    _ecrire_etat(etat)


def status() -> dict:
    """Etat lisible, pour le tableau de bord d'audit et `/system/version`."""
    from backend.services import deployment_manifest as dm

    d = execution_allowed()
    etat, lecture = _lire_etat()
    hash_arme = (etat or {}).get("armed_configuration_hash")
    hash_courant = dm.configuration_hash()
    return {
        # 🔴 REM-023 non livre : la derive se VOIT, elle n'arrete rien.
        "configuration_drift": bool(
            hash_arme and hash_arme != hash_courant),
        "configuration_hash_armed": hash_arme,
        "configuration_hash_current": hash_courant,
        "live_execution": "ON" if d.allowed else "OFF",
        "decision": d.decision,
        "reason_code": d.reason_code,
        "fingerprint_running": d.fingerprint_running,
        "fingerprint_armed": d.fingerprint_armed,
        "blocages": list(d.blocages),
        "detail": d.detail,
        "state_readable": etat is not None,
        "state_status": lecture,
        "armed_at": (etat or {}).get("armed_at"),
        "armed_by": (etat or {}).get("armed_by"),
        "armed_reason": (etat or {}).get("armed_reason"),
    }
