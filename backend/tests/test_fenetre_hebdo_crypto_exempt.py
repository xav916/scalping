"""La fenêtre hebdo NE S'APPLIQUE PAS à la crypto.

## Pourquoi

La fenêtre hebdo (lun 00:05 → ven 22:40 Paris) est modelée sur la semaine
forex : FX, métaux et énergie ferment le weekend chez le courtier. La crypto
est 24/7 chez Kraken Futures ; appliquer cette porte lui coûte 100 % du flux
weekend.

Mesure 2026-11-15 (samedi 02h UTC) : **5951 rejets Kraken en 4 h, 0 trade**.
Toutes les paires de la whitelist Kraken (BTC/ETH/ADA/XRP/SOL/DOT/LTC)
étaient retoquées en `hors_fenetre_hebdo`.

Ces deux tests figent :
1. une paire crypto hors fenêtre NE DOIT PAS être refusée pour ce motif ;
2. une paire forex hors fenêtre DOIT rester refusée (non-régression).

Le pattern suit celui de ``test_fenetre_hebdo.py`` qui réutilise les
constructeurs de ``test_bridge_tick_validator`` : un setup abrégé ne
franchirait pas les portes situées AVANT celle-ci, et le test serait vert
sans rien prouver.
"""
from __future__ import annotations


def test_crypto_PASSE_hors_fenetre_hebdo(monkeypatch):
    """BTC/USD hors fenêtre hebdo ne doit plus rendre `hors_fenetre_hebdo`.

    La crypto est 24/7 ; le filtre hebdo ne s'applique qu'au forex/métal/
    énergie (courtiers fermés le weekend).
    """
    from unittest.mock import patch

    from backend.services import mt5_bridge
    from backend.tests.test_bridge_tick_validator import (
        TestMt5BridgeIntegration as T,
    )

    monkeypatch.delenv("FENETRE_HEBDO_ENABLED", raising=False)
    cas = T()
    setup = cas._full_setup(pair="BTC/USD", entry=65000.0)
    dest = cas._dest_admin()

    with patch("backend.services.mt5_bridge.is_market_open_for_destination",
               return_value=True), \
         patch("backend.services.mt5_bridge._count_open_trades_for_pair",
               return_value=0), \
         patch("backend.services.mt5_bridge.MT5_BRIDGE_BLOCKED_DIRECTIONS",
               set()), \
         patch("backend.services.mt5_bridge.MT5_BRIDGE_AVOID_HOURS_UTC",
               set()), \
         patch("backend.services.mt5_bridge.MT5_BRIDGE_BLOCKED_PAIRS",
               frozenset()), \
         patch("backend.services.fenetre_hebdo.ouverte", return_value=False), \
         patch("config.settings.asset_class_for", return_value="crypto"):
        motif = mt5_bridge._check_rejection(setup, dest)

    assert motif != "hors_fenetre_hebdo", (
        f"crypto refusée par fenetre_hebdo alors qu'elle est 24/7. "
        f"motif obtenu = {motif!r}"
    )


def test_forex_RESTE_bloquee_hors_fenetre_hebdo(monkeypatch):
    """Non-régression : EUR/USD hors fenêtre reste refusée pour ce motif."""
    from unittest.mock import patch

    from backend.services import mt5_bridge
    from backend.tests.test_bridge_tick_validator import (
        TestMt5BridgeIntegration as T,
    )

    monkeypatch.delenv("FENETRE_HEBDO_ENABLED", raising=False)
    cas = T()
    setup = cas._full_setup(pair="EUR/USD", entry=1.08)
    dest = cas._dest_admin()

    with patch("backend.services.mt5_bridge.is_market_open_for_destination",
               return_value=True), \
         patch("backend.services.mt5_bridge._count_open_trades_for_pair",
               return_value=0), \
         patch("backend.services.mt5_bridge.MT5_BRIDGE_BLOCKED_DIRECTIONS",
               set()), \
         patch("backend.services.mt5_bridge.MT5_BRIDGE_AVOID_HOURS_UTC",
               set()), \
         patch("backend.services.mt5_bridge.MT5_BRIDGE_BLOCKED_PAIRS",
               frozenset()), \
         patch("backend.services.fenetre_hebdo.ouverte", return_value=False), \
         patch("config.settings.asset_class_for", return_value="forex"):
        motif = mt5_bridge._check_rejection(setup, dest)

    assert motif == "hors_fenetre_hebdo", (
        f"forex devrait rester bloquée hors fenêtre. motif = {motif!r}"
    )
