"""Registre des pushes : réserver avant l'ordre, trancher après (2026-08-04).

⚠️ **Pourquoi ce module existe.** Le client Kraken appelait
``mt5_pushes_service.record_push(...)`` — une fonction qui n'existe pas — et
il l'appelait **dans la branche succès, après le fill**. L'``AttributeError``
remontait au ``except Exception`` du client et devenait un banal
``kraken_bridge_exception``.

Conséquence, sur de l'argent réel :

- l'ordre était exécuté chez Kraken,
- aucune ligne ``mt5_pushes`` n'était écrite,
- donc aucune notification, aucun suivi SL/TP, aucune trace,
- et, faute de réservation, **le même setup se rejouait au cycle suivant**.

C'est la position orpheline observée le 2026-08-04. Le compte n'a jamais
été débité au-delà, mais uniquement parce que les paires ont été démises
sept minutes plus tard.

Le motif correct existait déjà côté MT5 : réserver la clé **avant** l'appel
HTTP, puis confirmer ou relâcher. Il vivait éparpillé dans
``mt5_bridge`` en sept appels nus. Ce module le nomme, pour que brancher
IBKR n'oblige pas à le redécouvrir une troisième fois.

Les quatre issues d'un push
---------------------------

``reserve()``      avant l'envoi. ``False`` ⇒ déjà tenté aujourd'hui pour ce
                   (paire, sens, prix d'entrée) : ne pas envoyer.
``confirm()``      le broker a accepté : la ligne passe à ``ok=1``.
``release()``      l'ordre n'a **prouvablement pas** atteint le marché
                   (connexion refusée, kill-switch du bridge, rejet
                   explicite). La réservation est levée, un cycle suivant
                   pourra retenter.
``flag_unknown()`` on ne sait pas. Timeout après envoi, exception
                   inattendue : le fill a pu passer. La réservation est
                   **conservée** — un doublon sur un compte réel coûte plus
                   cher qu'un trade manqué.

La distinction ``release`` / ``flag_unknown`` est le cœur du module. MT5
relâche sur timeout ; c'est tolérable sur un CFD de démo, pas sur un compte
au comptant chez un exchange.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

from backend.services import mt5_pushes_service

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PushLedger:
    """Clé d'un push et opérations de cycle de vie associées.

    La clé ``(destination, jour, paire, sens, prix d'entrée à 5 décimales)``
    est celle de la contrainte ``UNIQUE`` de ``mt5_pushes`` : c'est elle qui
    fait la déduplication, pas un cache mémoire.
    """

    destination_id: str
    push_date: str
    pair: str
    direction: str
    entry_5dp: str

    @classmethod
    def for_setup(cls, dest, setup, direction: str) -> PushLedger:
        """Construit la clé depuis un setup et sa destination résolue."""
        return cls(
            destination_id=dest.destination_id,
            push_date=date.today().isoformat(),
            pair=setup.pair,
            direction=direction,
            entry_5dp=f"{float(setup.entry_price):.5f}",
        )

    @property
    def _args(self) -> tuple[str, str, str, str, str]:
        return (self.destination_id, self.push_date, self.pair,
                self.direction, self.entry_5dp)

    def reserve(self) -> bool:
        """Réserve la clé **avant** l'envoi. ``False`` ⇒ ne pas envoyer.

        À appeler juste avant l'appel HTTP, jamais après : c'est ce qui
        garantit qu'un fill non confirmé laisse quand même une trace.
        """
        return mt5_pushes_service.try_register_push(*self._args)

    def confirm(self, response: dict[str, Any] | None = None) -> None:
        """Le broker a accepté l'ordre."""
        mt5_pushes_service.update_push_result(*self._args, ok=True,
                                              response=response)

    def release(self) -> None:
        """L'ordre n'a pas atteint le marché : autoriser un retry."""
        mt5_pushes_service.discard_push(*self._args)

    def flag_unknown(self, response: dict[str, Any] | None = None) -> None:
        """Issue indéterminée : garder la réservation, marquer la ligne.

        La ligne reste à ``ok=0`` avec la réponse partielle, ce qui la rend
        visible au récap sans autoriser un second envoi.
        """
        mt5_pushes_service.update_push_result(*self._args, ok=False,
                                              response=response)
        logger.warning(
            "push %s %s %s : issue indeterminee, reservation conservee "
            "(un fill a pu passer)",
            self.destination_id, self.pair, self.direction,
        )
