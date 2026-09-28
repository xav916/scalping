"""Porte d'execution des chaines — REM-001, fail-CLOSED et EXPLICITE.

## Le defaut que ce module supprime

Jusqu'au 2026-09-28, la decision « cette chaine peut-elle trader ? » etait
portee par la VALEUR DE RETOUR de `mt5_bridge._patterns_autorises` : un
`set()` vide signifiait « rien ne peut partir ». Le consommateur ecrivait
`if allowed_patterns and ...` — et **un ensemble vide est faux en Python**,
donc le filtre entier etait SAUTE.

⇒ Une etiquette de chaine non armee ne fermait pas la porte : elle
**supprimait la liste blanche**. Neuf des dix ordres de chaine du 16 au
25/09 n'auraient jamais du exister.

🔑 Aggravant : dans le MEME fichier, `dest.allowed_patterns = frozenset()`
signifie « desactiver le filtre pour cette destination ». Deux sens opposes
pour la meme valeur. C'est cette ambiguite de TYPE que ce module retire —
pas seulement le bug.

## La regle (PR-01, PR-02)

La decision ne voyage plus dans un type ambigu. Elle voyage dans un objet
qui la NOMME, et qui porte son motif. Tout ce qui n'est pas un `ALLOW`
explicite est un `DENY` :

    pas de chaine            -> ALLOW  / NO_CHAIN        (setup ordinaire)
    chaine armee + motif     -> ALLOW  / CHAIN_ARMED
    chaine non armee         -> DENY   / CHAIN_NOT_ARMED
    registre illisible       -> DENY   / CHAIN_REGISTRY_UNREADABLE
    motif indeterminable     -> DENY   / CHAIN_PATTERN_INDETERMINATE
    exception interne        -> DENY   / CONTROL_ERROR

⛔ Aucun chemin de ce module ne rend `ALLOW` par defaut. Le defaut est
`DENY`, et il est ecrit comme valeur initiale, pas comme branche finale.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ─── Etats explicites (PR-02) ──────────────────────────────────────────
ALLOW = "ALLOW"
DENY = "DENY"

# ─── Motifs, chacun auditable ──────────────────────────────────────────
NO_CHAIN = "NO_CHAIN"
CHAIN_ARMED = "CHAIN_ARMED"
CHAIN_NOT_ARMED = "CHAIN_NOT_ARMED"
CHAIN_REGISTRY_UNREADABLE = "CHAIN_REGISTRY_UNREADABLE"
CHAIN_PATTERN_INDETERMINATE = "CHAIN_PATTERN_INDETERMINATE"
CONTROL_ERROR = "CONTROL_ERROR"

#: Motif de refus expose au journal des refus (`signal_rejections`).
#: ⛔ Il ne commence PAS par `_` : un refus prive ne laisse aucune trace, et
#: c'est exactement ce qui a rendu ce defaut invisible dix jours.
REJECTION_REASON = "chaine_non_armee"


@dataclass(frozen=True)
class ChainDecision:
    """Decision d'execution d'une chaine. `decision` vaut ALLOW ou DENY."""

    decision: str
    reason_code: str
    chain_id: str | None = None
    trigger_id: str | None = None
    destination_id: str | None = None
    horizon: str | None = None
    configuration_version: str | None = None
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def allowed(self) -> bool:
        """⛔ Vrai UNIQUEMENT sur un ALLOW explicite. Jamais par defaut."""
        return self.decision == ALLOW

    def as_details(self) -> dict:
        """Forme journalisable, pour les `details` d'une rejection."""
        return {
            "decision": self.decision,
            "reason_code": self.reason_code,
            "chain_id": self.chain_id,
            "trigger_id": self.trigger_id,
            "destination_id": self.destination_id,
            "horizon": self.horizon,
            "configuration_version": self.configuration_version,
            "timestamp": self.timestamp,
        }


def _registry_version() -> str | None:
    """Empreinte du registre des chaines armees, pour tracer la config active.

    ⚠️ Rend None si le registre est illisible — l'appelant a deja refuse a ce
    stade, la version n'est qu'une information de journal.
    """
    try:
        from backend.services.chaines_autorisees import armees

        noms = sorted(armees() or [])
        return f"{len(noms)}:{'|'.join(noms)}" if noms else "0:"
    except Exception:  # noqa: BLE001
        return None


def chain_execution_gate(setup, dest=None) -> ChainDecision:
    """La seule fonction autorisee a dire si un setup de chaine peut partir.

    ⛔ Ne rend JAMAIS un type ambigu. Ne leve JAMAIS : une exception devient
    un DENY/CONTROL_ERROR, parce qu'un controle qui casse doit fermer.
    """
    chain_id = None
    trigger_id = None
    destination_id = None
    horizon = None
    try:
        chain_id = getattr(setup, "chaine", None)
        destination_id = getattr(dest, "destination_id", None) if dest else None
        horizon = getattr(setup, "horizon", None)

        if not chain_id:
            # Setup ordinaire : cette porte n'a rien a dire. Les autres portes
            # (liste blanche, confiance, cout...) restent en vigueur.
            return ChainDecision(
                decision=ALLOW,
                reason_code=NO_CHAIN,
                destination_id=destination_id,
                horizon=horizon,
            )

        try:
            from backend.services.chaines_autorisees import autorisee

            # ⚠️ Ordre des arguments PIEGEUX : (nom, destination_id, horizon).
            # Une inversion rend False « a raison » et ne prouve rien — piege
            # tombe le 2026-09-25 en verifiant la fermeture.
            armee = bool(autorisee(chain_id, destination_id, horizon))
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "REM-001 porte de chaine : registre illisible (%s) -> DENY", e
            )
            return ChainDecision(
                decision=DENY,
                reason_code=CHAIN_REGISTRY_UNREADABLE,
                chain_id=str(chain_id),
                destination_id=destination_id,
                horizon=horizon,
            )

        if not armee:
            logger.warning(
                "REM-001 porte de chaine : %s NON armee sur %s (%s/%s) -> DENY",
                chain_id,
                destination_id,
                getattr(setup, "pair", None),
                horizon,
            )
            return ChainDecision(
                decision=DENY,
                reason_code=CHAIN_NOT_ARMED,
                chain_id=str(chain_id),
                destination_id=destination_id,
                horizon=horizon,
                configuration_version=_registry_version(),
            )

        # Chaine armee : le motif de son declencheur doit etre LISIBLE, sinon
        # on ne sait pas ce qu'on ouvrirait.
        from backend.services.mt5_bridge import _pattern_value

        trigger_id = _pattern_value(setup)
        if not trigger_id:
            logger.warning(
                "REM-001 porte de chaine : %s armee mais motif indeterminable "
                "(%s) -> DENY",
                chain_id,
                type(getattr(setup, "pattern", None)).__name__,
            )
            return ChainDecision(
                decision=DENY,
                reason_code=CHAIN_PATTERN_INDETERMINATE,
                chain_id=str(chain_id),
                destination_id=destination_id,
                horizon=horizon,
                configuration_version=_registry_version(),
            )

        return ChainDecision(
            decision=ALLOW,
            reason_code=CHAIN_ARMED,
            chain_id=str(chain_id),
            trigger_id=str(trigger_id),
            destination_id=destination_id,
            horizon=horizon,
            configuration_version=_registry_version(),
        )
    except Exception as e:  # noqa: BLE001
        # ⛔ Un controle qui casse FERME. Jamais l'inverse.
        logger.error("REM-001 porte de chaine : erreur interne (%s) -> DENY", e)
        return ChainDecision(
            decision=DENY,
            reason_code=CONTROL_ERROR,
            chain_id=str(chain_id) if chain_id else None,
            destination_id=destination_id,
            horizon=horizon,
        )
