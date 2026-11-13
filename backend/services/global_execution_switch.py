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

# ─── REM-002-LIVE : motifs de refus du double verrou compte RÉEL ────────
LIVE_AUTHORIZED = "LIVE_AUTHORIZED"
LIVE_NOT_AUTHORIZED = "LIVE_NOT_AUTHORIZED"
LIVE_FINGERPRINT_MISMATCH = "LIVE_FINGERPRINT_MISMATCH"
LIVE_EXPIRED = "LIVE_EXPIRED"
LIVE_MAX_AGE_EXCEEDED = "LIVE_MAX_AGE_EXCEEDED"

#: Âge max absolu d'une autorisation live, applique MEME si expires_at est
#: absent ou lointain. Blackout de sécurité : si on oublie de révoquer, le
#: verrou se referme tout seul après 24h. Configurable via env var.
LIVE_AUTHORIZATION_MAX_AGE_SEC_DEFAULT = 86400


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
    live_ok, live_code, live_detail = live_destination_authorized()
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
        # ─── REM-002-LIVE : double verrou compte RÉEL ─────────────────
        "live_account_execution": "ON" if live_ok else "OFF",
        "live_account_reason_code": live_code,
        "live_account_detail": live_detail,
        "live_authorized_at": (etat or {}).get("live_authorized_at"),
        "live_authorized_by": (etat or {}).get("live_authorized_by"),
        "live_authorized_reason": (etat or {}).get("live_authorized_reason"),
        "live_authorized_fingerprint": (etat or {}).get(
            "live_authorized_fingerprint"),
        "live_authorized_expires_at": (etat or {}).get(
            "live_authorized_expires_at"),
    }


# ─── REM-002-LIVE : double verrou compte RÉEL ──────────────────────────
#
# ⛔ Le flag .env `MT5_BRIDGE_LIVE_ENABLED=true` seul ne suffit PLUS à
# activer la destination `admin_live` (compte RÉEL). Il faut EN PLUS une
# autorisation explicite dans cet état, portée sur le fingerprint du build
# en cours, qui expire à chaque re-deploy.
#
# 🔑 Raison d'être : le soir du 2026-11-13, un trade XAU/USD a été envoyé
# sur le compte RÉEL IC Markets (login 13137475) par le pipeline legacy
# `scheduler.py:509/882` → `mt5_bridge.send_setups` → `resolve_destinations`
# → destination `admin_live`. Le seul garde-fou était le flag .env, lequel
# avait été activé depuis au moins 2026-08-28 (`sltp_guard_activated_at`).
# Un simple `echo MT5_BRIDGE_LIVE_ENABLED=true` + restart était suffisant
# pour envoyer des ordres sur de l'argent réel sans trace d'autorisation.


def live_destination_authorized() -> tuple[bool, str, str | None]:
    """Autorise-t-on la destination `admin_live` (compte RÉEL) pour CE build ?

    Returns ``(allowed, reason_code, detail)``. Fail-closed : toute
    exception ou état illisible retourne ``False``.
    """
    try:
        from backend.services import deployment_manifest as dm

        empreinte = dm.fingerprint()
        etat, lecture = _lire_etat()
        if etat is None:
            return False, lecture, "aucun etat lisible"

        if not etat.get("live_authorized"):
            return False, LIVE_NOT_AUTHORIZED, etat.get(
                "live_authorized_revoked_reason")

        # L'autorisation live doit porter sur le build qui tourne.
        arme_pour = etat.get("live_authorized_fingerprint")
        if not arme_pour or not empreinte or arme_pour != empreinte:
            return False, LIVE_FINGERPRINT_MISMATCH, (
                f"live armed for {arme_pour}, running {empreinte}"
            )

        # Expiration optionnelle (ISO 8601 UTC).
        exp = etat.get("live_authorized_expires_at")
        if exp:
            try:
                exp_dt = datetime.fromisoformat(exp)
                if datetime.now(timezone.utc) >= exp_dt:
                    return False, LIVE_EXPIRED, f"expired at {exp}"
            except ValueError:
                return False, LIVE_EXPIRED, f"invalid expiry: {exp}"

        # ⛔ Plafond absolu : blackout auto si l'autorisation date de plus de
        # LIVE_AUTHORIZATION_MAX_AGE_SEC (défaut 24h). Protège contre l'oubli
        # de révoquer après une session de live. S'applique MÊME si
        # expires_at n'est pas défini ou est très lointain.
        try:
            max_age = int(os.getenv(
                "LIVE_AUTHORIZATION_MAX_AGE_SEC",
                str(LIVE_AUTHORIZATION_MAX_AGE_SEC_DEFAULT),
            ))
        except (TypeError, ValueError):
            max_age = LIVE_AUTHORIZATION_MAX_AGE_SEC_DEFAULT
        authorized_at = etat.get("live_authorized_at")
        if authorized_at:
            try:
                auth_dt = datetime.fromisoformat(authorized_at)
                age_sec = (datetime.now(timezone.utc) - auth_dt).total_seconds()
                if age_sec >= max_age:
                    return False, LIVE_MAX_AGE_EXCEEDED, (
                        f"autorisation vieille de {int(age_sec)}s "
                        f"(plafond {max_age}s)"
                    )
            except ValueError:
                return False, LIVE_MAX_AGE_EXCEEDED, (
                    f"live_authorized_at illisible: {authorized_at}"
                )

        return True, LIVE_AUTHORIZED, etat.get("live_authorized_reason")

    except Exception as e:  # noqa: BLE001
        logger.error("REM-002-LIVE erreur interne (%s) -> DENY", e)
        return False, CONTROL_ERROR, str(e)


def authorize_live(
    reason: str, by: str, expires_at: str | None = None,
) -> dict:
    """Autorise explicitement l'envoi d'ordres au compte RÉEL pour CE build.

    ⛔ Expire automatiquement dès que le fingerprint change (re-deploy).
    `expires_at` optionnel : ISO 8601 UTC, bornage temporel supplémentaire.

    ⚠️ Ne se substitue PAS à `arm()` : REM-002 doit aussi être armé pour
    que les ordres partent. Ce verrou est ADDITIONNEL, pas remplaçant.
    """
    from backend.services import deployment_manifest as dm

    integrite = dm.check_integrity()
    if not integrite.ok:
        logger.error(
            "REM-002-LIVE autorisation REFUSÉE : integrite = %s",
            integrite.status,
        )
        return {
            "ok": False, "reason": DEPLOYMENT_INTEGRITY,
            "detail": integrite.status,
        }
    empreinte = dm.fingerprint()
    if not empreinte:
        return {
            "ok": False, "reason": DEPLOYMENT_INTEGRITY,
            "detail": "empreinte indisponible",
        }

    etat, _ = _lire_etat()
    etat = etat or _defaut()
    etat.update({
        "live_authorized": True,
        "live_authorized_fingerprint": empreinte,
        "live_authorized_at": datetime.now(timezone.utc).isoformat(),
        "live_authorized_by": by,
        "live_authorized_reason": reason,
        "live_authorized_expires_at": expires_at,
    })
    _ecrire_etat(etat)
    logger.warning(
        "REM-002-LIVE compte RÉEL AUTORISÉ pour %s par %s (%s, expire=%s)",
        empreinte, by, reason, expires_at or "jamais",
    )
    return {
        "ok": True, "fingerprint": empreinte, "by": by,
        "reason": reason, "expires_at": expires_at,
    }


def revoke_live_authorization(reason: str, by: str) -> dict:
    """Révoque l'autorisation live. Toujours autorisé — ne se négocie pas."""
    etat, _ = _lire_etat()
    etat = etat or _defaut()
    etat.update({
        "live_authorized": False,
        "live_authorized_revoked_at": datetime.now(timezone.utc).isoformat(),
        "live_authorized_revoked_by": by,
        "live_authorized_revoked_reason": reason,
    })
    _ecrire_etat(etat)
    logger.warning(
        "REM-002-LIVE autorisation live RÉVOQUÉE par %s (%s)", by, reason,
    )
    return {"ok": True, "reason": reason, "by": by}
