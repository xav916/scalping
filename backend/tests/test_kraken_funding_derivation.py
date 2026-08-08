"""Repli dérivé pour le taux de funding Kraken (2026-08-08).

`_fetch_all_rates()` récupère **tous** les taux publiés par Kraken, mais
`get_funding_rate_for_pair` les cherchait via une carte paire→symbole codée en
dur. Toute paire absente rendait `None` ⇒ coût de portage incalculable ⇒
`exceeds_edge` bloquait l'argent réel.

⛔ Un refus fondé sur une donnée manquante, pas sur un coût. Mesuré le
2026-08-08 : BNB, XLM, SEI, ENS et HBAR refusées en `fees_exceed_edge` alors
que leur coût réel valait 17,7 à 23,1 % de l'edge, sous le plafond de 30 %.

⚠️ Ces tests verrouillent le point qui rend le repli sûr : la dérivation n'est
acceptée QUE si Kraken publie réellement le symbole.
"""
import pytest

from backend.services import kraken_funding_scoring as kfs


@pytest.fixture
def taux(monkeypatch):
    """Taux publiés par Kraken, tels que `_fetch_all_rates` les rend."""
    faux = {"PF_XBTUSD": 3.2e-06, "PF_XLMUSD": 1.55e-07, "PF_SEIUSD": -9.1e-08}
    monkeypatch.setattr(kfs, "_fetch_all_rates", lambda: faux)
    return faux


def test_la_carte_explicite_prime(taux, monkeypatch):
    """BTC/USD -> PF_XBTUSD, jamais PF_BTCUSD."""
    monkeypatch.setattr(kfs, "_PAIR_TO_SYMBOL", {"BTC/USD": "PF_XBTUSD"})
    assert kfs.get_funding_rate_for_pair("BTC/USD") == pytest.approx(3.2e-06)


def test_une_paire_absente_de_la_carte_est_derivee(taux, monkeypatch):
    monkeypatch.setattr(kfs, "_PAIR_TO_SYMBOL", {})
    assert kfs.get_funding_rate_for_pair("XLM/USD") == pytest.approx(1.55e-07)
    assert kfs.get_funding_rate_for_pair("SEI/USD") == pytest.approx(-9.1e-08)


def test_une_derivation_NON_publiee_rend_None(taux, monkeypatch):
    """C'est ce qui rend le repli sûr : on ne fabrique jamais un taux."""
    monkeypatch.setattr(kfs, "_PAIR_TO_SYMBOL", {})
    assert kfs.get_funding_rate_for_pair("ZZZZ/USD") is None


def test_un_taux_de_zero_est_conserve_pas_confondu_avec_absent(monkeypatch):
    """0.0 est un taux valide ; le confondre avec `None` inverserait la
    décision de la porte de coût."""
    monkeypatch.setattr(kfs, "_PAIR_TO_SYMBOL", {})
    monkeypatch.setattr(kfs, "_fetch_all_rates", lambda: {"PF_XXXUSD": 0.0})
    assert kfs.get_funding_rate_for_pair("XXX/USD") == 0.0


def test_les_paires_non_USD_ne_sont_pas_derivees(taux, monkeypatch):
    monkeypatch.setattr(kfs, "_PAIR_TO_SYMBOL", {})
    assert kfs.get_funding_rate_for_pair("ETH/BTC") is None
    assert kfs.get_funding_rate_for_pair("SANSSLASH") is None
