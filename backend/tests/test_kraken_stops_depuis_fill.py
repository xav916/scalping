"""Kraken : les stops doivent être posés depuis le prix de REMPLISSAGE.

Les prix absolus envoyés par le radar sont calculés sur le prix du SIGNAL.
Entre le signal et l'exécution le marché bouge, et poser les stops au prix du
signal déforme le rapport risque/gain réel — mesuré 0,7-1,3 au lieu de 1,8 sur
ETH/USD le 2026-05-18. Le correctif existait côté MT5 depuis cette date
(`sl_dist`/`tp_dist` dans `_build_order_payload`) mais manquait côté Kraken,
alors que le bridge calculait déjà `avg_price` sans jamais s'en servir.

Ce qui est verrouillé ici : le recalage lui-même, sa symétrie achat/vente, la
conservation exacte du rapport risque/gain, et les trois replis qui doivent
laisser le comportement historique intact.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

_BRIDGE = (pathlib.Path(__file__).resolve().parents[2]
           / "kraken-bridge" / "bridge.py")


@pytest.fixture(scope="module")
def bridge():
    """Importe le bridge, qui vit hors du package backend."""
    spec = importlib.util.spec_from_file_location("kraken_futures_bridge", _BRIDGE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── Le recalage ────────────────────────────────────────────────────────────

def test_achat_stops_reposes_sur_le_fill(bridge):
    """Le marché a monté de 10 entre le signal et le fill : les stops suivent."""
    # signal : entrée 100, SL 90 (risque 10), TP 118 (1,8 R)
    sl, tp, source = bridge.stops_depuis_fill(
        "buy", avg_price=110.0, sl_dist=10.0, tp_dist=18.0,
        sl_signal=90.0, tp_signal=118.0,
    )
    assert source == "fill"
    assert sl == pytest.approx(100.0)   # 110 - 10
    assert tp == pytest.approx(128.0)   # 110 + 18


def test_vente_symetrique(bridge):
    """En vente le stop est AU-DESSUS du fill et l'objectif en dessous."""
    sl, tp, source = bridge.stops_depuis_fill(
        "sell", avg_price=90.0, sl_dist=10.0, tp_dist=18.0,
        sl_signal=110.0, tp_signal=82.0,
    )
    assert source == "fill"
    assert sl == pytest.approx(100.0)   # 90 + 10
    assert tp == pytest.approx(72.0)    # 90 - 18


@pytest.mark.parametrize("direction,fill", [
    ("buy", 110.0), ("buy", 95.0), ("sell", 90.0), ("sell", 105.0),
])
def test_le_rapport_risque_gain_est_preserve(bridge, direction, fill):
    """C'est la RAISON D'ÊTRE du correctif : 1,8 doit rester 1,8.

    Sans recalage, un fill à 110 sur un signal à 100 donnait un risque de 20
    (110-90) pour un gain de 8 (118-110), soit 0,4 au lieu de 1,8.
    """
    sl, tp, source = bridge.stops_depuis_fill(
        direction, avg_price=fill, sl_dist=10.0, tp_dist=18.0,
        sl_signal=999.0, tp_signal=999.0,
    )
    assert source == "fill"
    assert abs(tp - fill) / abs(fill - sl) == pytest.approx(1.8)


# ── Les replis : le comportement historique doit rester intact ─────────────

def test_sans_fill_on_garde_les_prix_du_signal(bridge):
    sl, tp, source = bridge.stops_depuis_fill(
        "buy", avg_price=0.0, sl_dist=10.0, tp_dist=18.0,
        sl_signal=90.0, tp_signal=118.0,
    )
    assert (sl, tp, source) == (90.0, 118.0, "signal")


def test_sans_distances_on_garde_les_prix_du_signal(bridge):
    """Radar plus ancien : aucune distance transmise."""
    sl, tp, source = bridge.stops_depuis_fill(
        "buy", avg_price=110.0, sl_dist=None, tp_dist=None,
        sl_signal=90.0, tp_signal=118.0,
    )
    assert (sl, tp, source) == (90.0, 118.0, "signal")


@pytest.mark.parametrize("mauvais", ["", "abc", object()])
def test_distances_illisibles_ne_cassent_rien(bridge, mauvais):
    sl, tp, source = bridge.stops_depuis_fill(
        "buy", avg_price=110.0, sl_dist=mauvais, tp_dist=18.0,
        sl_signal=90.0, tp_signal=118.0,
    )
    assert (sl, tp, source) == (90.0, 118.0, "signal")


def test_distance_nulle_n_est_jamais_utilisee(bridge):
    """Une distance à 0 collerait le stop sur le prix d'entrée."""
    sl, tp, source = bridge.stops_depuis_fill(
        "buy", avg_price=110.0, sl_dist=0.0, tp_dist=0.0,
        sl_signal=90.0, tp_signal=118.0,
    )
    assert (sl, tp, source) == (90.0, 118.0, "signal")


def test_une_seule_distance_fournie(bridge):
    """Le TP est recalé, le SL garde sa valeur du signal."""
    sl, tp, source = bridge.stops_depuis_fill(
        "buy", avg_price=110.0, sl_dist=None, tp_dist=18.0,
        sl_signal=90.0, tp_signal=118.0,
    )
    assert source == "fill"
    assert sl == 90.0
    assert tp == pytest.approx(128.0)


# ── Le payload du radar doit porter les distances ──────────────────────────

def test_le_radar_envoie_bien_les_distances():
    """Sans elles, le bridge retombe en silence sur le comportement d'avant."""
    from backend.services.kraken_bridge_client import _build_kraken_payload

    class _Setup:
        pair = "ETH/USD"
        entry_price = 100.0
        stop_loss = 90.0
        take_profit_1 = 118.0
        direction = "buy"

    payload = _build_kraken_payload(_Setup(), {"risk_money": 20.0}, dest=None)
    assert payload["sl_dist"] == pytest.approx(10.0)
    assert payload["tp_dist"] == pytest.approx(18.0)
    assert payload["entry"] == pytest.approx(100.0)
    # Les prix absolus restent le repli du bridge : ils ne doivent pas partir.
    assert payload["sl"] == pytest.approx(90.0)
    assert payload["tp"] == pytest.approx(118.0)
    assert payload["qty"] == pytest.approx(2.0)   # 20 / 10
