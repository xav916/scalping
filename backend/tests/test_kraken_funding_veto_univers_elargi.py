"""Le veto funding doit couvrir le MÊME univers que le coût de portage.

Le 2026-08-08, la parade « dériver ``PF_XXXUSD``, mais n'accepter que si
Kraken publie réellement le symbole » a été posée sur
``get_funding_rate_for_pair`` — le chemin du **coût**, celui qui bloquait de
l'argent réel sur une donnée manquante.

Elle n'a PAS été posée sur ``apply_kraken_funding`` — le chemin du **score**.
Ce dernier sort en amont sur ``is_crypto_pair``, c'est-à-dire l'appartenance à
la carte codée en dur de neuf entrées. Mesuré en prod le 2026-08-09 :

- 9 paires couvertes sur 24 surveillées ;
- 8 des 15 non couvertes étaient **au-delà** du seuil extrême (2,0e-05) au
  moment de la mesure — dont ETHFI à +4,44e-05 côté achat, soit exactement le
  trade parti la nuit précédente ;
- sur tout l'historique du journal, le veto ne s'est jamais déclenché que sur
  BCH, XRP, ADA, DOT, SOL et LTC : les six paires de la carte.

⛔ **Un veto déclaré, calibré sur un p95 mesuré, et qui ne tourne que sur un
tiers de l'univers.** Le silence est permissif : rien n'échoue, le score passe
simplement sans être pondéré. Même motif que les trois cartes codées en dur du
2026-08-08 — sauf que celle-ci avait été oubliée lors de la même passe.
"""
import pytest

from backend.services import kraken_funding_scoring as kfs

SEUIL = kfs._EXTREME_THRESHOLD


@pytest.fixture
def taux(monkeypatch):
    """Taux publiés par Kraken, tels que ``_fetch_all_rates`` les rend.

    ETHFI reprend la valeur réellement mesurée en prod le 2026-08-09.
    """
    faux = {
        "PF_XBTUSD": 1.85e-06,
        "PF_ETHFIUSD": 4.44e-05,   # au-dela du seuil, cote achat
        "PF_MANAUSD": -4.31e-05,   # au-dela du seuil, cote vente
        "PF_XLMUSD": 2.91e-06,     # sous le seuil
    }
    monkeypatch.setattr(kfs, "_fetch_all_rates", lambda: faux)
    monkeypatch.setattr(kfs, "_get_funding_rate", lambda s: faux.get(s))
    return faux


def test_le_veto_couvre_un_instrument_absent_de_la_carte(taux):
    """ETHFI n'est dans aucune des neuf entrées, et son funding est extrême."""
    score, meta = kfs.apply_kraken_funding("ETHFI/USD", "buy", 70.0)
    assert meta["multiplier"] == 0.85
    assert meta["symbol"] == "PF_ETHFIUSD"
    assert meta["rate"] == pytest.approx(4.44e-05)
    assert score == pytest.approx(59.5)


def test_le_veto_couvre_aussi_le_cote_vente(taux):
    score, meta = kfs.apply_kraken_funding("MANA/USD", "sell", 70.0)
    assert meta["multiplier"] == 0.85
    assert "négatif" in meta["reason"]


def test_sous_le_seuil_aucun_veto_mais_le_taux_est_rendu(taux):
    """Le taux doit remonter même sans veto : c'est une feature de scoring."""
    score, meta = kfs.apply_kraken_funding("XLM/USD", "buy", 70.0)
    assert meta["multiplier"] == 1.0
    assert meta["reason"] is None
    assert meta["rate"] == pytest.approx(2.91e-06)
    assert score == 70.0


def test_la_carte_explicite_prime_toujours(taux):
    """BTC/USD -> PF_XBTUSD, jamais PF_BTCUSD."""
    _, meta = kfs.apply_kraken_funding("BTC/USD", "buy", 70.0)
    assert meta["symbol"] == "PF_XBTUSD"


def test_une_derivation_non_publiee_ne_vote_pas(taux):
    """Ce qui rend le repli sûr : jamais de taux fabriqué, jamais celui d'une
    autre paire."""
    score, meta = kfs.apply_kraken_funding("ZZZZ/USD", "buy", 70.0)
    assert meta["multiplier"] == 1.0
    assert meta["symbol"] is None
    assert meta["rate"] is None
    assert score == 70.0


def test_les_paires_non_USD_ne_sont_pas_derivees(taux):
    _, meta = kfs.apply_kraken_funding("ETH/BTC", "buy", 70.0)
    assert meta["multiplier"] == 1.0
    assert meta["symbol"] is None


def test_un_taux_exactement_au_seuil_ne_declenche_pas(monkeypatch):
    """Le seuil est une borne stricte — verrouille le sens de l'inégalité."""
    monkeypatch.setattr(kfs, "_fetch_all_rates", lambda: {"PF_AAAUSD": SEUIL})
    monkeypatch.setattr(kfs, "_get_funding_rate", lambda s: {"PF_AAAUSD": SEUIL}.get(s))
    _, meta = kfs.apply_kraken_funding("AAA/USD", "buy", 70.0)
    assert meta["multiplier"] == 1.0


def test_le_veto_et_le_cout_couvrent_le_meme_univers(taux):
    """L'invariant qui empêche la dérive de revenir.

    Toute paire dont le coût de portage est calculable doit pouvoir être
    vetoée, et réciproquement. Deux univers différents, c'est la situation
    qu'on corrige ici.
    """
    for pair in ("BTC/USD", "ETHFI/USD", "MANA/USD", "XLM/USD", "ZZZZ/USD", "ETH/BTC"):
        cout_connu = kfs.get_funding_rate_for_pair(pair) is not None
        veto_possible = kfs.apply_kraken_funding(pair, "buy", 70.0)[1]["symbol"] is not None
        assert cout_connu == veto_possible, pair
