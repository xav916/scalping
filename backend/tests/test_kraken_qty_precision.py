"""Taille d'ordre Kraken Futures : la précision d'instrument (2026-08-04).

Kraken rejette toute taille hors précision avec ``invalidSize`` — un message
qui ne dit ni quelle précision était attendue, ni que le problème vient de
là. Cinq ordres ont échoué de suite le 2026-08-04 avant que la cause soit
identifiée : le bridge lisait ``tickSize`` (le pas de PRIX) mais jamais
``contractValueTradePrecision`` (le pas de TAILLE).

Précisions réelles relevées sur l'API le 2026-08-04 :
PF_XBTUSD 4 · PF_ETHUSD 3 · PF_SOLUSD 2 · PF_AAPLXUSD 2
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

_BRIDGE = (pathlib.Path(__file__).resolve().parents[2]
           / "kraken-futures-bridge" / "bridge.py")


def _charger():
    """Importe le bridge, qui vit hors du package backend."""
    spec = importlib.util.spec_from_file_location("kraken_futures_bridge", _BRIDGE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bridge = pytest.importorskip("flask") and _charger()
arrondi = bridge.round_qty_to_precision


# --- le cas qui a réellement échoué ---------------------------------------

def test_la_taille_qui_a_fait_echouer_cinq_ordres():
    """`risk 1,034 USD / SL 180 USD` sur BTC — six décimales de trop."""
    assert arrondi(0.005744444444444, 4) == 0.0057


def test_le_resultat_tient_dans_la_precision_demandee():
    """C'est la propriété que Kraken vérifie, pas une valeur particulière."""
    for brut, prec in ((0.005744444, 4), (0.11883561, 3), (7.4999, 2)):
        r = arrondi(brut, prec)
        assert round(r, prec) == r, f"{r} depasse {prec} decimales"


# --- ne jamais augmenter le risque ----------------------------------------

@pytest.mark.parametrize("brut,prec", [
    (0.005744444, 4), (0.11883561, 3), (0.0001999, 4), (12.99999, 2),
])
def test_on_tronque_toujours_vers_le_bas(brut, prec):
    """Arrondir au plus proche engagerait plus que le sizing n'autorise."""
    assert arrondi(brut, prec) <= brut


def test_une_taille_deja_valide_est_inchangee():
    assert arrondi(0.0057, 4) == 0.0057
    assert arrondi(0.119, 3) == 0.119


# --- sous le pas minimum ---------------------------------------------------

def test_sous_le_pas_minimum_retourne_zero():
    """À l'appelant de refuser explicitement : `invalidSize` ne dit rien."""
    assert arrondi(0.00009, 4) == 0.0
    assert arrondi(0.0009, 3) == 0.0


@pytest.mark.parametrize("mauvais", [0.0, -1.0, -0.005])
def test_une_taille_absurde_retourne_zero(mauvais):
    assert arrondi(mauvais, 4) == 0.0


# --- les précisions réelles des instruments tradés ------------------------

@pytest.mark.parametrize("symbole,prec,pas", [
    ("PF_XBTUSD", 4, 0.0001),
    ("PF_ETHUSD", 3, 0.001),
    ("PF_SOLUSD", 2, 0.01),
])
def test_le_pas_minimum_de_chaque_instrument(symbole, prec, pas):
    assert arrondi(pas, prec) == pytest.approx(pas)
    assert arrondi(pas * 0.99, prec) == 0.0


# --- le cache de specs doit exposer le champ ------------------------------

def test_le_cache_de_specs_lit_la_precision_de_taille():
    """Le champ manquait : c'est l'oubli qui a produit `invalidSize`."""
    import inspect
    src = inspect.getsource(bridge._refresh_specs_cache)
    assert "contractValueTradePrecision" in src
    assert "qtyPrecision" in src


def test_le_chemin_d_ordre_utilise_bien_l_arrondi():
    """Sans cet appel, la fonction existerait sans rien protéger."""
    import inspect
    src = inspect.getsource(bridge.place_order)
    assert "round_qty_to_precision" in src
    assert "qtyPrecision" in src


# --- de bout en bout : ce que le sizing produit doit passer ---------------

@pytest.mark.parametrize("pair,entry,sl_pct,prec", [
    ("BTC", 60000.0, 0.003, 4),
    ("ETH", 1868.0, 0.005, 3),
])
def test_le_sizing_reel_du_compte_produit_une_taille_valide(pair, entry, sl_pct, prec):
    """Compte Kraken réel : 103,43 USD, risque 1 % ⇒ 1,03 USD par trade."""
    risque_usd = 103.43 * 0.01
    qty = risque_usd / (entry * sl_pct)
    r = arrondi(qty, prec)
    assert r > 0, f"{pair}: compte trop petit, taille {qty} sous le pas"
    assert round(r, prec) == r
