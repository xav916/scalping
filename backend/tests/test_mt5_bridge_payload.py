"""Tests pour la construction du payload envoyé à l'EA / bridge.

Régression 2026-05-18 : les SL/TP étaient envoyés en prix absolus calculés
depuis l'entry du signal. Si le market bougeait entre signal et fill, le
broker plaçait quand même les SL/TP à leurs valeurs absolues, donc le
risk/reward réel divergeait du théorique (RR 0.70-1.26 observé au lieu
de 1.80). Le payload doit aussi inclure les distances relatives pour
permettre à l'EA de recalculer SL/TP à partir du fill price effectif.
"""

from types import SimpleNamespace

import pytest

from backend.services import mt5_bridge


def _setup(direction="sell", entry=2144.5, sl=2152.0, tp1=2131.0, tp2=2122.0):
    s = SimpleNamespace()
    s.pair = "ETH/USD"
    s.direction = direction
    s.entry_price = entry
    s.stop_loss = sl
    s.take_profit_1 = tp1
    s.take_profit_2 = tp2
    s.confidence_score = 72
    return s


def test_payload_includes_legacy_absolute_prices():
    """Backward compat : sl/tp absolus restent dans le payload pour les
    consumers legacy (EA v1.04 et antérieurs)."""
    sz = {"risk_money": 10.0, "lots": 0.01}
    p = mt5_bridge._build_order_payload(_setup(), sz)
    assert p["entry"] == 2144.5
    assert p["sl"] == 2152.0
    assert p["tp"] == 2131.0
    assert p["tp2"] == 2122.0


def test_payload_includes_relative_distances_sell():
    """Forward compat : sl_dist / tp_dist / tp2_dist (distances positives en
    unités de prix) permettent à l'EA v1.05 de recalculer SL/TP à partir du
    fill price effectif."""
    sz = {"risk_money": 10.0, "lots": 0.01}
    p = mt5_bridge._build_order_payload(_setup(direction="sell"), sz)
    assert p["sl_dist"] == pytest.approx(7.5)   # 2152.0 - 2144.5
    assert p["tp_dist"] == pytest.approx(13.5)  # 2144.5 - 2131.0
    assert p["tp2_dist"] == pytest.approx(22.5) # 2144.5 - 2122.0


def test_payload_includes_relative_distances_buy():
    s = _setup(direction="buy", entry=2000.0, sl=1990.0, tp1=2018.0, tp2=2030.0)
    sz = {"risk_money": 10.0, "lots": 0.01}
    p = mt5_bridge._build_order_payload(s, sz)
    assert p["sl_dist"] == pytest.approx(10.0)  # 2000 - 1990
    assert p["tp_dist"] == pytest.approx(18.0)  # 2018 - 2000
    assert p["tp2_dist"] == pytest.approx(30.0) # 2030 - 2000


def test_payload_tp2_dist_none_when_no_tp2():
    s = _setup(tp2=None)
    sz = {"risk_money": 10.0, "lots": 0.01}
    p = mt5_bridge._build_order_payload(s, sz)
    assert p["tp2"] is None
    assert p["tp2_dist"] is None


def test_payload_no_broker_symbol_without_dest():
    """Backward compat : sans dest, pas de champ ``broker_symbol`` ajouté."""
    sz = {"risk_money": 10.0, "lots": 0.01}
    p = mt5_bridge._build_order_payload(_setup(), sz)
    assert "broker_symbol" not in p


def test_payload_no_broker_symbol_without_map():
    """``dest`` fourni mais ``symbol_map=None`` : pas de ``broker_symbol``."""
    sz = {"risk_money": 10.0, "lots": 0.01}
    dest = SimpleNamespace(symbol_map=None)
    p = mt5_bridge._build_order_payload(_setup(), sz, dest=dest)
    assert "broker_symbol" not in p


def test_payload_no_broker_symbol_when_pair_absent_from_map():
    """``dest.symbol_map`` ne contient pas la pair : pas de ``broker_symbol``."""
    sz = {"risk_money": 10.0, "lots": 0.01}
    dest = SimpleNamespace(symbol_map={"XAU/USD": "GOLD"})
    # _setup() utilise ETH/USD
    p = mt5_bridge._build_order_payload(_setup(), sz, dest=dest)
    assert "broker_symbol" not in p


def test_payload_includes_broker_symbol_when_mapped():
    """``dest.symbol_map[pair]`` présent : ``broker_symbol`` injecté.

    Cas Cédric Pepperstone UK Demo : ETH/USD doit être mappé pour OrderSend.
    Sans ce mapping, OrderSend retourne retcode=10031 ou 0 selon le symbole
    qui n'existe pas chez le broker (cf. project_cedric_zero_exec_diagnostic).
    """
    sz = {"risk_money": 10.0, "lots": 0.01}
    dest = SimpleNamespace(symbol_map={"ETH/USD": "ETHUSD", "WTI/USD": "USOIL"})
    p = mt5_bridge._build_order_payload(_setup(), sz, dest=dest)
    assert p["broker_symbol"] == "ETHUSD"


def test_payload_no_broker_symbol_with_empty_map():
    """``dest.symbol_map={}`` (dict vide) : traité comme None, pas d'injection."""
    sz = {"risk_money": 10.0, "lots": 0.01}
    dest = SimpleNamespace(symbol_map={})
    p = mt5_bridge._build_order_payload(_setup(), sz, dest=dest)
    assert "broker_symbol" not in p
