"""Résolution de symbole du bridge Kraken Futures (2026-08-25).

Ce repli existait déjà : ajouté le 2026-08-08, **disparu** depuis. Le fichier
`/opt/kraken-bridge/bridge.py` vivait hors git, et une édition manuelle du 19
ou du 23/08 l'a écrasé sans que rien ne le signale. Coût mesuré : **13 ordres
refusés** entre le 20 et le 24/08 en `unsupported pair`, sur 8 instruments
pourtant présents au catalogue du courtier — la carte codée en dur en connaît
16, Kraken en cote 280.

Ces tests existent autant pour la fonction que pour **empêcher la disparition
de recommencer** : le bridge est désormais sous git, et un test qui tombe est
la seule chose qui rende un écrasement bruyant.

⚠️ Ce qu'ils verrouillent :
  - la carte explicite PRIME — `BTC/USD` est `PF_XBTUSD`, jamais `PF_BTCUSD` ;
  - un symbole dérivé n'est rendu **que s'il est validé** contre le catalogue ;
  - un catalogue vide ne fait jamais passer un symbole non validé ;
  - « absent du catalogue » et « catalogue illisible » se journalisent
    différemment, même s'ils refusent tous les deux.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
SOURCE = RACINE / "kraken-bridge" / "bridge.py"


@pytest.fixture
def bridge(monkeypatch):
    """Charge le bridge par chemin — « kraken-bridge » n'est pas importable."""
    pytest.importorskip("flask")
    monkeypatch.setenv("KRAKEN_API_KEY", "")
    monkeypatch.setenv("KRAKEN_API_SECRET", "")
    spec = importlib.util.spec_from_file_location("kraken_bridge_sous_test", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def catalogue(bridge, monkeypatch):
    """Règle le catalogue d'instruments négociables sans appeler le réseau."""
    def _set(symboles):
        monkeypatch.setattr(
            bridge, "_specs_cache",
            {s.upper(): {"symbol": s.upper(), "tradeable": True} for s in symboles},
        )
        # Cache frais : `_get_specs` ne doit pas partir chercher le réseau.
        monkeypatch.setattr(bridge, "_specs_cache_ts", float(2 ** 40))
    return _set


# ── La carte explicite prime ──────────────────────────────────────────

def test_le_bitcoin_ne_se_derive_PAS(bridge, catalogue):
    """Le piège qui justifie de garder une carte : Kraken dit XBT, pas BTC."""
    catalogue(["PF_XBTUSD", "PF_BTCUSD"])
    assert bridge._resolve_symbol("BTC/USD") == "PF_XBTUSD"


def test_les_entrees_connues_restent_servies(bridge, catalogue):
    catalogue([])  # même catalogue vide, la carte explicite répond
    assert bridge._resolve_symbol("ETH/USD") == "PF_ETHUSD"
    assert bridge._resolve_symbol("SOL/USD") == "PF_SOLUSD"


# ── Le repli : dérivé, mais VALIDÉ ────────────────────────────────────

def test_un_instrument_hors_carte_mais_cote_est_resolu(bridge, catalogue):
    """Le cas des 13 ordres perdus."""
    catalogue(["PF_HBARUSD", "PF_XLMUSD", "PF_SEIUSD", "PF_AAVEUSD",
               "PF_ALGOUSD", "PF_ARBUSD", "PF_BNBUSD", "PF_MANAUSD"])
    for paire, attendu in [("HBAR/USD", "PF_HBARUSD"), ("XLM/USD", "PF_XLMUSD"),
                           ("SEI/USD", "PF_SEIUSD"), ("AAVE/USD", "PF_AAVEUSD"),
                           ("ALGO/USD", "PF_ALGOUSD"), ("ARB/USD", "PF_ARBUSD"),
                           ("BNB/USD", "PF_BNBUSD"), ("MANA/USD", "PF_MANAUSD")]:
        assert bridge._resolve_symbol(paire) == attendu, paire


def test_un_derive_NON_cote_est_refuse(bridge, catalogue):
    """⛔ Jamais de symbole deviné : un ordre sur un symbole non validé se fait
    refuser au mieux, exécuter sur le mauvais instrument au pire."""
    catalogue(["PF_ETHUSD"])
    assert bridge._resolve_symbol("NEXISTEPAS/USD") is None


def test_la_casse_est_indifferente(bridge, catalogue):
    catalogue(["PF_HBARUSD"])
    assert bridge._resolve_symbol("hbar/usd") == "PF_HBARUSD"


# ── Ce qui n'est pas dérivable ────────────────────────────────────────

@pytest.mark.parametrize("paire", ["ETH/EUR", "XAU/USD/EXTRA", "", "USD", None,
                                   "/USD", "ETH/", "E TH/USD"])
def test_les_formes_non_derivables_sont_refusees(bridge, catalogue, paire):
    catalogue(["PF_ETHEUR", "PF_USDUSD"])
    if paire == "ETH/EUR":
        assert bridge._resolve_symbol(paire) is None, "seul l'USD est dérivable"
    else:
        assert bridge._resolve_symbol(paire) is None


# ── Catalogue illisible ≠ instrument absent ───────────────────────────

def test_un_catalogue_VIDE_ne_fait_passer_personne(bridge, monkeypatch):
    """Refus par prudence : on n'envoie pas d'ordre sur un symbole non validé."""
    monkeypatch.setattr(bridge, "_specs_cache", {})
    monkeypatch.setattr(bridge, "_specs_cache_ts", float(2 ** 40))
    assert bridge._resolve_symbol("HBAR/USD") is None


def test_les_deux_refus_se_journalisent_DIFFEREMMENT(bridge, monkeypatch, caplog):
    """⚠️ Sinon une panne réseau se diagnostique comme un instrument absent.

    Les deux rendent `None` — c'est voulu. Mais le journal doit permettre de
    les distinguer, sans quoi on cherchera l'erreur au mauvais endroit.
    """
    monkeypatch.setattr(bridge, "_specs_cache_ts", float(2 ** 40))

    caplog.clear()
    with caplog.at_level("INFO"):
        monkeypatch.setattr(bridge, "_specs_cache", {})
        bridge._resolve_symbol("HBAR/USD")
    vide = caplog.text

    caplog.clear()
    with caplog.at_level("INFO"):
        monkeypatch.setattr(bridge, "_specs_cache", {"PF_ETHUSD": {"tradeable": True}})
        bridge._resolve_symbol("HBAR/USD")
    absent = caplog.text

    assert vide != absent, "les deux causes doivent se lire différemment"
    assert "VIDE" in vide
    assert "absent" in absent


# ── Garde-fou contre la disparition ───────────────────────────────────

def test_le_repli_est_toujours_present_dans_la_source():
    """Ce test n'appelle rien : il monte la garde sur le fichier.

    Le repli a déjà disparu une fois, silencieusement. Un écrasement qui
    supprime la validation par le catalogue doit faire tomber un test.
    """
    source = SOURCE.read_text(encoding="utf-8")
    debut = source.index("def _resolve_symbol")
    corps = source[debut:debut + 2500]
    assert "_get_specs(" in corps, (
        "la validation contre le catalogue a disparu de _resolve_symbol — "
        "c'est exactement la regression du 19-23/08"
    )
    assert "PF_" in corps, "la dérivation a disparu de _resolve_symbol"
