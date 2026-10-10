"""⛔ Les exceptions avalées par `asyncio.gather` doivent SE DIRE.

## Ce que ce fichier épingle (2026-10-09)

`send_setup` et `send_setups` font tous deux
`asyncio.gather(..., return_exceptions=True)`. **Toute** exception levée dans la
chaîne d'admission ou dans le push y disparaissait : aucun ordre, aucun refus
enregistré, **aucune ligne de journal**.

🔑 C'est ainsi qu'un `UnboundLocalError` a vécu deux heures dans la porte de la
fenêtre hebdomadaire sans laisser la moindre trace — il n'a été trouvé que
parce qu'un test d'un autre sujet est tombé. Le défaut suivant dans cette
chaîne aurait été tout aussi invisible.

⚠️ **On ne change PAS le flot d'exécution.** Une exception continue de ne pas
remonter : `return_exceptions=True` reste, et une destination qui échoue ne
doit pas empêcher les autres. On ajoute uniquement la **parole**. Transformer
ce fail-closed silencieux en exception propagée serait un autre changement,
avec un autre risque, et ce n'est pas ce qui manque ici.

⚠️ Et `CancelledError` n'est **pas** une anomalie : l'annulation d'une tâche
est normale à l'arrêt du processus. La journaliser en `ERROR` noierait les
vraies dans du bruit, et un journal bruyant ne se lit plus — c'est comme s'il
était muet.
"""
from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, patch

import pytest


def _dest(nom="admin_live"):
    class D:
        destination_id = nom
        user_id = None
        bridge_url = ""
    return D()


class _Setup:
    pair = "XAU/USD"
    direction = "buy"


@pytest.fixture()
def MB():
    from backend.services import mt5_bridge
    return mt5_bridge


# ─────────────────────────────────────────────────────────────────────────
# 1. send_setup : une destination qui lève doit se LIRE
# ─────────────────────────────────────────────────────────────────────────

def test_une_exception_dans_le_push_est_JOURNALISEE(MB, caplog):
    """⛔ LE DÉFAUT. Elle disparaissait sans un mot."""
    boum = AsyncMock(side_effect=UnboundLocalError(
        "cannot access local variable 'dest_id'"))

    with caplog.at_level(logging.ERROR, logger=MB.logger.name), \
         patch("backend.services.bridge_destinations.resolve_destinations",
               return_value=[_dest()]), \
         patch.object(MB, "_push_to_destination", boum):
        asyncio.run(MB.send_setup(_Setup()))

    assert caplog.records, "l'exception a ete avalee SANS UN MOT"
    texte = " ".join(r.getMessage() for r in caplog.records)
    assert "UnboundLocalError" in texte, texte
    assert "dest_id" in texte, texte


def test_le_journal_NOMME_la_paire_et_la_destination(MB, caplog):
    """🔑 << une exception a eu lieu >> n'aide personne : il faut savoir OÙ."""
    with caplog.at_level(logging.ERROR, logger=MB.logger.name), \
         patch("backend.services.bridge_destinations.resolve_destinations",
               return_value=[_dest("admin_live")]), \
         patch.object(MB, "_push_to_destination",
                      AsyncMock(side_effect=ValueError("x"))):
        asyncio.run(MB.send_setup(_Setup()))

    texte = " ".join(r.getMessage() for r in caplog.records)
    assert "XAU/USD" in texte, texte
    assert "admin_live" in texte, texte


def test_l_exception_ne_REMONTE_toujours_pas(MB, caplog):
    """⚠️ On ajoute la parole, pas un changement de flot. Une destination qui
    echoue ne doit pas empecher les autres ni faire tomber le cycle."""
    appels = []

    async def _faux(setup, dest):
        appels.append(dest.destination_id)
        if dest.destination_id == "admin_live":
            raise RuntimeError("boum")

    with caplog.at_level(logging.ERROR, logger=MB.logger.name), \
         patch("backend.services.bridge_destinations.resolve_destinations",
               return_value=[_dest("admin_live"), _dest("admin_legacy")]), \
         patch.object(MB, "_push_to_destination", _faux):
        asyncio.run(MB.send_setup(_Setup()))      # ne doit PAS lever

    assert "admin_legacy" in appels, (
        "une destination en echec a empeche les autres")


def test_sans_exception_le_journal_reste_MUET(MB, caplog):
    """⛔ Sinon le signal se noie : un journal qui parle a chaque cycle ne se
    lit plus, et c'est comme s'il etait muet."""
    with caplog.at_level(logging.ERROR, logger=MB.logger.name), \
         patch("backend.services.bridge_destinations.resolve_destinations",
               return_value=[_dest()]), \
         patch.object(MB, "_push_to_destination", AsyncMock(return_value=None)):
        asyncio.run(MB.send_setup(_Setup()))

    assert not caplog.records, [r.getMessage() for r in caplog.records]


def test_une_ANNULATION_n_est_pas_une_anomalie(MB, caplog):
    """⚠️ `CancelledError` arrive normalement a l'arret du processus. En
    `ERROR`, elle noierait les vraies anomalies."""
    with caplog.at_level(logging.ERROR, logger=MB.logger.name), \
         patch("backend.services.bridge_destinations.resolve_destinations",
               return_value=[_dest()]), \
         patch.object(MB, "_push_to_destination",
                      AsyncMock(side_effect=asyncio.CancelledError())):
        asyncio.run(MB.send_setup(_Setup()))

    assert not caplog.records, [r.getMessage() for r in caplog.records]


# ─────────────────────────────────────────────────────────────────────────
# 2. send_setups : le MÊME piège, un étage plus haut
# ─────────────────────────────────────────────────────────────────────────

def test_send_setups_dit_AUSSI_ce_qu_il_avale(MB, caplog):
    """⛔ Deux `gather` avalent, pas un. Celui-ci attrape ce qui echappe a
    `send_setup` lui-meme -- par exemple `resolve_destinations` qui leve."""
    with caplog.at_level(logging.ERROR, logger=MB.logger.name), \
         patch.object(MB, "is_configured", return_value=True), \
         patch.object(MB, "send_setup",
                      AsyncMock(side_effect=KeyError("entry_price"))):
        asyncio.run(MB.send_setups([_Setup()]))

    texte = " ".join(r.getMessage() for r in caplog.records)
    assert "KeyError" in texte, texte or "(journal vide)"
