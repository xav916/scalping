"""Ingestion des signaux d'un bot tiers, pour les juger dans NOS conditions.

Posé le 2026-08-26. Un bot externe envoie ses setups, **nous** exécutons — sur le
démo seul. C'est le seul montage qui isole sa **sélection** : notre sizing, nos
stops, nos portes, notre comptabilité. Observer son compte à lui aurait mesuré le
package complet, sans pouvoir séparer ce qu'il choisit de ce qu'il exécute.

## Ce que ce module fait, et ce qu'il ne fait pas

Il valide, dédoublonne, et construit un setup. **Il ne décide de rien d'autre** :
le setup part ensuite dans `mt5_bridge.send_setup()` et traverse toutes les
portes existantes — admission, whitelist, confiance, horizon, motifs, coût,
plafond de risque, banc d'essai. Aucune n'est contournée, aucune n'est dupliquée.

⛔ **Le verrou qui interdit l'argent réel n'est PAS ici.** Il est dans
`bridge_destinations.resolve_destinations`, qui écarte toute destination réelle
dès que `setup.source` désigne un tiers. Une garde placée dans l'ingestion serait
contournée par le premier appelant qui construirait un setup autrement.

## ⛔ Le motif du refus est toujours rendu

Un fournisseur qui ne sait pas pourquoi il est filtré croit qu'on l'ignore. Et de
notre côté, « il n'émet rien » deviendrait indiscernable de « on jette tout » —
la forme de silence que ce dépôt a déjà payée quatre fois.

Conception : `docs/superpowers/specs/2026-08-26-bot-externe-demo-design.md`
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_SCHEMA_ENSURED = False

_OBLIGATOIRES = ("source", "external_id", "pair", "direction",
                 "entry_price", "stop_loss")
_NUMERIQUES = ("entry_price", "stop_loss", "take_profit")
_SENS = ("buy", "sell")


class _Direction:
    """Le dispatch lit `setup.direction.value` — on lui donne cette forme."""

    __slots__ = ("value",)

    def __init__(self, value: str) -> None:
        self.value = value


class ExternalSetup:
    """Setup issu d'un bot tiers, dans la forme que le dispatch sait lire.

    ⛔ `source` n'est pas décoratif : c'est lui que `resolve_destinations` lit
    pour interdire l'argent réel, et lui que le sélecteur du banc filtre. Un
    setup externe sans `source` serait traité comme le nôtre.
    """

    def __init__(self, charge: dict[str, Any]) -> None:
        self.source = str(charge["source"]).strip()
        self.external_id = str(charge["external_id"])
        self.pair = str(charge["pair"]).strip().upper()
        self.direction = _Direction(str(charge["direction"]).strip().lower())
        self.entry_price = float(charge["entry_price"])
        self.stop_loss = float(charge["stop_loss"])
        self.take_profit = (float(charge["take_profit"])
                            if charge.get("take_profit") is not None else None)
        self.horizon = charge.get("horizon")
        self.pattern = charge.get("pattern")
        self.confidence = (float(charge["confidence"])
                           if charge.get("confidence") is not None else None)
        self.emitted_at = charge.get("emitted_at")
        # Un signal tiers n'est pas une simulation : il engage un ordre réel sur
        # le démo. `is_simulated=True` le ferait écarter par `_check_rejection`.
        self.is_simulated = False


# ─── Socle ──────────────────────────────────────────────────────────────


def _db_path() -> str:
    from backend.services.trade_log_service import _DB_PATH
    return str(_DB_PATH)


def _ensure_schema() -> None:
    global _SCHEMA_ENSURED
    if _SCHEMA_ENSURED:
        return
    with sqlite3.connect(_db_path()) as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS external_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                external_id TEXT NOT NULL,
                pair TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price REAL,
                stop_loss REAL,
                take_profit REAL,
                horizon TEXT,
                pattern TEXT,
                confidence REAL,
                emitted_at TEXT,
                received_at TEXT NOT NULL,
                UNIQUE(source, external_id)
            )
        """)
    _SCHEMA_ENSURED = True


def _fournisseurs() -> dict[str, str]:
    """Table `{source: jeton}`. **Vide par défaut** : sans réglage, rien n'entre."""
    try:
        from config.settings import EXTERNAL_SIGNAL_TOKENS
        return dict(EXTERNAL_SIGNAL_TOKENS or {})
    except Exception:  # noqa: BLE001 — un réglage illisible n'ouvre rien
        return {}


# ─── Validation ─────────────────────────────────────────────────────────


def valider(charge: dict[str, Any], jeton: str) -> tuple[bool, str]:
    """``(accepté, motif)``. Le motif est renseigné **même en cas d'acceptation**.

    ⛔ L'ordre compte : l'authentification d'abord. Un fournisseur inconnu ne doit
    pas apprendre, par la différence des messages, quels champs on attend.
    """
    connus = _fournisseurs()
    if not connus:
        return False, ("aucun fournisseur déclaré sur cette installation "
                       "(EXTERNAL_SIGNAL_TOKENS est vide)")

    source = str(charge.get("source") or "").strip()
    if not source:
        return False, "champ obligatoire manquant : source"
    if source not in connus:
        return False, f"source inconnue : {source} — un fournisseur se déclare avant d'émettre"
    if not jeton or jeton != connus[source]:
        return False, f"jeton invalide pour la source {source}"

    for champ in _OBLIGATOIRES:
        if charge.get(champ) in (None, ""):
            return False, f"champ obligatoire manquant : {champ}"

    sens = str(charge.get("direction") or "").strip().lower()
    if sens not in _SENS:
        return False, f"direction inconnue : {charge.get('direction')} — attendu buy ou sell"

    for champ in _NUMERIQUES:
        v = charge.get(champ)
        if v is None:
            continue
        try:
            float(v)
        except (TypeError, ValueError):
            return False, f"{champ} n'est pas un nombre : {v!r}"

    return True, "accepté"


def enregistrer(charge: dict[str, Any]) -> bool:
    """``True`` si le signal est nouveau, ``False`` s'il a déjà été reçu.

    ⛔ L'unicité porte sur le COUPLE ``(source, external_id)`` : deux bots peuvent
    numéroter leurs signaux à partir de 1 sans s'écraser. Et un fournisseur qui
    rejoue sa file ne double pas les ordres.
    """
    _ensure_schema()
    try:
        with sqlite3.connect(_db_path()) as c:
            cur = c.execute(
                """INSERT OR IGNORE INTO external_signals
                       (source, external_id, pair, direction, entry_price,
                        stop_loss, take_profit, horizon, pattern, confidence,
                        emitted_at, received_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (str(charge["source"]).strip(), str(charge["external_id"]),
                 str(charge["pair"]).upper(), str(charge["direction"]).lower(),
                 charge.get("entry_price"), charge.get("stop_loss"),
                 charge.get("take_profit"), charge.get("horizon"),
                 charge.get("pattern"), charge.get("confidence"),
                 charge.get("emitted_at"),
                 datetime.now(timezone.utc).isoformat()))
            return cur.rowcount > 0
    except Exception as e:  # noqa: BLE001
        # ⚠️ Sur doute, on REFUSE le signal plutôt que de risquer un doublon
        # d'ordre. L'inverse perdrait de l'argent, pas seulement un signal.
        logger.warning("external_signals: enregistrement impossible (%s) — signal refusé", e)
        return False


def construire_setup(charge: dict[str, Any]) -> ExternalSetup:
    """Le setup, dans la forme que le dispatch sait lire."""
    return ExternalSetup(charge)


async def ingerer(charge: dict[str, Any], jeton: str) -> dict[str, Any]:
    """Valide, dédoublonne, dispatche. Rend toujours un motif lisible."""
    ok, motif = valider(charge, jeton)
    if not ok:
        logger.info("external_signals: refusé — %s", motif)
        return {"accepte": False, "motif": motif}

    if not enregistrer(charge):
        return {"accepte": False, "motif": "signal déjà reçu (external_id connu)"}

    setup = construire_setup(charge)
    from backend.services.mt5_bridge import send_setup
    await send_setup(setup)
    logger.warning("external_signals: %s %s %s dispatché (démo seul)",
                   setup.source, setup.pair, setup.direction.value)
    return {"accepte": True, "motif": "dispatché vers le démo",
            "source": setup.source, "external_id": setup.external_id}
