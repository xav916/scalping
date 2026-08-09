"""Le garde de corrélation doit dire ce qu'il ne sait pas.

Constat du 2026-08-09. ``CORRELATIONS`` est une table de 16 couples mesurés le
2026-08-04 : elle couvre **6 paires crypto sur les 24 surveillées**. Pour les
18 autres, ``correlation()`` rend ``None``, ``exposition()`` rend ``None``, et
``pari_deja_pris`` ne les compte pas.

⇒ ``max_correlated_positions=1`` est déclaré sur ``admin_kraken``, et pourtant
**trois positions crypto étaient ouvertes simultanément** — ETHFI, SEI, CRV —
avec des corrélations croisées toutes inconnues. Le garde dégénérait en « une
position par paire », soit exactement le motif qu'il devait empêcher : le short
BTC + short ETH du 2026-08-04, un seul pari pris deux fois.

⚠️ Le repli permissif reste **délibéré** : « non mesuré » et « décorrélé » sont
deux choses différentes, et fabriquer une corrélation serait pire que de ne pas
en avoir.

Ce que ces tests verrouillent : **le trou est journalisé**. Un garde qui laisse
passer sans le dire est indiscernable d'un garde qui a vérifié.

## ✅ Le trou du jour a été comblé le jour même

Les 23 instruments crypto ont été mesurés quelques heures plus tard
(``test_correlations_mesurees_kraken``), donc ETHFI, SEI et CRV ne sont plus
des couples inconnus. Ces tests portent désormais sur des symboles
**volontairement absents de toute mesure** : le mécanisme garde tout son sens
pour le prochain instrument ajouté, puisque la mesure couvre un univers figé au
2026-08-09 et qu'un ajout ultérieur y sera de nouveau muet.
"""
import logging
from types import SimpleNamespace

import pytest

from backend.services import correlation_guard as cg

DEST = SimpleNamespace(destination_id="admin_kraken")


@pytest.fixture
def limite_a_un(monkeypatch):
    monkeypatch.setattr(cg, "limite", lambda d: 1)


def _ouvertes(monkeypatch, positions):
    monkeypatch.setattr(cg, "positions_ouvertes", lambda _id: positions)


def test_un_couple_non_mesure_est_journalise(monkeypatch, caplog, limite_a_un):
    """Deux positions ouvertes sur des symboles hors de toute mesure."""
    _ouvertes(monkeypatch, [("ZZZ/USD", "buy"), ("YYY/USD", "buy")])

    with caplog.at_level(logging.WARNING, logger="backend.services.correlation_guard"):
        bloque, en_cause = cg.pari_deja_pris(DEST, "XXX/USD", "buy")

    assert bloque is False          # comportement inchange : on ne bloque pas
    assert en_cause == []
    message = " ".join(r.message for r in caplog.records)
    assert "XXX/USD" in message
    assert "ZZZ/USD" in message and "YYY/USD" in message


def test_le_journal_dit_combien_ont_ete_comptees_et_combien_non(
    monkeypatch, caplog, limite_a_un
):
    """Sans les deux nombres, on ne peut pas juger de la portée du trou."""
    _ouvertes(monkeypatch, [("ETH/USD", "buy"), ("ZZZ/USD", "buy")])

    with caplog.at_level(logging.WARNING, logger="backend.services.correlation_guard"):
        cg.pari_deja_pris(DEST, "BTC/USD", "buy")

    message = " ".join(r.message for r in caplog.records)
    # BTC/ETH est mesuree (0,889) et compte ; BTC/ZZZ ne l'est pas.
    assert "1" in message


def test_aucun_journal_quand_tout_est_mesure(monkeypatch, caplog, limite_a_un):
    """Pas de bruit quand le garde sait ce qu'il fait."""
    _ouvertes(monkeypatch, [("ETH/USD", "buy")])

    with caplog.at_level(logging.WARNING, logger="backend.services.correlation_guard"):
        cg.pari_deja_pris(DEST, "BTC/USD", "buy")

    assert not caplog.records


def test_aucun_journal_quand_le_garde_est_desactive(monkeypatch, caplog):
    """Limite à 0 ⇒ illimité : rien n'est vérifié, il n'y a donc pas de trou."""
    monkeypatch.setattr(cg, "limite", lambda d: 0)
    _ouvertes(monkeypatch, [("ZZZ/USD", "buy")])

    with caplog.at_level(logging.WARNING, logger="backend.services.correlation_guard"):
        cg.pari_deja_pris(DEST, "XXX/USD", "buy")

    assert not caplog.records


def test_aucun_journal_sans_position_ouverte(monkeypatch, caplog, limite_a_un):
    _ouvertes(monkeypatch, [])

    with caplog.at_level(logging.WARNING, logger="backend.services.correlation_guard"):
        cg.pari_deja_pris(DEST, "XXX/USD", "buy")

    assert not caplog.records


def test_le_blocage_reste_intact_sur_un_couple_mesure(monkeypatch, limite_a_un):
    """Le comportement du garde ne bouge pas — on ajoute une trace, rien d'autre."""
    _ouvertes(monkeypatch, [("ETH/USD", "buy")])

    bloque, en_cause = cg.pari_deja_pris(DEST, "BTC/USD", "buy")

    assert bloque is True
    assert en_cause == ["ETH/USD buy"]


def test_un_couple_mesure_de_sens_oppose_ne_bloque_pas_et_ne_journalise_pas(
    monkeypatch, caplog, limite_a_un
):
    """BTC acheteur + ETH vendeur : +0,81 × −1 = −0,81, les paris se compensent.

    Mesuré, donc pas un trou — et sous le seuil, donc pas un blocage.
    """
    _ouvertes(monkeypatch, [("ETH/USD", "sell")])

    with caplog.at_level(logging.WARNING, logger="backend.services.correlation_guard"):
        bloque, en_cause = cg.pari_deja_pris(DEST, "BTC/USD", "buy")

    assert bloque is False
    assert en_cause == []
    assert not caplog.records


def test_couples_non_mesures_est_exposable(monkeypatch, limite_a_un):
    """Accessible sans lire les logs, pour un futur comptage de fréquence."""
    _ouvertes(monkeypatch, [("ZZZ/USD", "buy"), ("ETH/USD", "buy")])

    manquants = cg.couples_non_mesures(DEST, "BTC/USD", "buy")

    assert manquants == ["ZZZ/USD buy"]
