"""Tests du branchement macro_history_features dans
backend.services.ml_features.extract_features_for_setup, derrière le
drapeau MACRO_HISTORY_FEATURES_ENABLED (désactivé par défaut).

Le point le plus important : drapeau désactivé (comportement par défaut en
production) ⇒ sortie strictement inchangée, aucune clé "mh_" n'apparaît
même avec une valeur None. Drapeau activé ⇒ la valeur consommée varie.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

import config.settings as settings
from backend.models.schemas import PatternDetection, PatternType, TradeDirection, TradeSetup
from backend.services import ml_features


def _make_setup(ts: datetime) -> TradeSetup:
    pattern = PatternDetection(
        pattern=PatternType.MOMENTUM_UP,
        confidence=0.8,
        description="test",
        detected_at=ts,
    )
    return TradeSetup(
        pair="EUR/USD",
        direction=TradeDirection.BUY,
        pattern=pattern,
        entry_price=1.1000,
        stop_loss=1.0950,
        take_profit_1=1.1050,
        take_profit_2=1.1100,
        risk_pips=50,
        reward_pips_1=50,
        reward_pips_2=100,
        risk_reward_1=1.0,
        risk_reward_2=2.0,
        message="test",
        timestamp=ts,
    )


def _make_candles(ts: datetime, n: int = 5) -> list:
    from backend.models.schemas import Candle
    return [
        Candle(timestamp=ts, open=1.1, high=1.101, low=1.099, close=1.1, volume=100)
        for _ in range(n)
    ]


@pytest.fixture(autouse=True)
def _reset_flag(monkeypatch):
    """Le drapeau par défaut du dépôt (false) doit être garanti pour ces
    tests, indépendamment de l'environnement d'exécution."""
    monkeypatch.setattr(settings, "MACRO_HISTORY_FEATURES_ENABLED", False)


def test_flag_disabled_leaves_output_strictly_unchanged(monkeypatch):
    """Test le plus important pour la non-régression : drapeau off (défaut
    prod) ⇒ pas une seule clé "mh_" dans le dict, même à None."""
    monkeypatch.setattr(settings, "MACRO_HISTORY_FEATURES_ENABLED", False)
    ts = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
    setup = _make_setup(ts)
    candles = _make_candles(ts)

    feats = ml_features.extract_features_for_setup(setup, candles)

    mh_keys = [k for k in feats if k.startswith("mh_")]
    assert mh_keys == []


def test_flag_disabled_does_not_call_macro_history_features(monkeypatch):
    """Vérifie qu'on ne se contente pas de filtrer les clés en sortie : le
    module macro_history_features ne doit même pas être invoqué quand le
    drapeau est off."""
    monkeypatch.setattr(settings, "MACRO_HISTORY_FEATURES_ENABLED", False)
    calls = []

    def _spy(pair, ts):
        calls.append((pair, ts))
        return {}

    from backend.services import macro_history_features
    monkeypatch.setattr(macro_history_features, "get_features_at", _spy)

    ts = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
    ml_features.extract_features_for_setup(_make_setup(ts), _make_candles(ts))

    assert calls == []


def test_flag_enabled_wires_macro_history_features(monkeypatch):
    """Drapeau on ⇒ les clés mh_ apparaissent et reflètent bien la valeur
    retournée par macro_history_features (preuve que le code gardé est
    réellement exécuté, pas seulement importé)."""
    monkeypatch.setattr(settings, "MACRO_HISTORY_FEATURES_ENABLED", True)

    from backend.services import macro_history_features
    sentinel = {
        "mh_vix_level": 23.4,
        "mh_vix_delta_1d": 1.1,
        "mh_dxy_level": None,
        "mh_spx_level": None,
        "mh_tnx_level": None,
        "mh_btc_level": None,
        "mh_fear_greed_value": 38.0,
        "mh_fear_greed_code": 1,
    }
    monkeypatch.setattr(macro_history_features, "get_features_at", lambda pair, ts: dict(sentinel))

    ts = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
    feats = ml_features.extract_features_for_setup(_make_setup(ts), _make_candles(ts))

    assert feats["mh_vix_level"] == 23.4
    assert feats["mh_fear_greed_value"] == 38.0
    assert feats["mh_fear_greed_code"] == 1


def test_flag_enabled_varies_consumed_value_vs_disabled(monkeypatch):
    """La valeur réellement consommée diffère selon l'état du drapeau —
    preuve directe que le drapeau gouverne bien le comportement."""
    from backend.services import macro_history_features
    monkeypatch.setattr(
        macro_history_features, "get_features_at",
        lambda pair, ts: {"mh_vix_level": 99.9, "mh_vix_delta_1d": None,
                           "mh_dxy_level": None, "mh_spx_level": None,
                           "mh_tnx_level": None, "mh_btc_level": None,
                           "mh_fear_greed_value": None, "mh_fear_greed_code": None},
    )
    ts = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
    setup, candles = _make_setup(ts), _make_candles(ts)

    monkeypatch.setattr(settings, "MACRO_HISTORY_FEATURES_ENABLED", False)
    feats_off = ml_features.extract_features_for_setup(setup, candles)

    monkeypatch.setattr(settings, "MACRO_HISTORY_FEATURES_ENABLED", True)
    feats_on = ml_features.extract_features_for_setup(setup, candles)

    assert "mh_vix_level" not in feats_off
    assert feats_on["mh_vix_level"] == 99.9


def test_flag_enabled_never_raises_when_no_candles(monkeypatch):
    """Sans bougie, il n'y a pas de T exploitable — best-effort : pas de
    crash, simplement pas d'enrichissement mh_."""
    monkeypatch.setattr(settings, "MACRO_HISTORY_FEATURES_ENABLED", True)
    ts = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
    setup = _make_setup(ts)

    feats = ml_features.extract_features_for_setup(setup, [])

    assert isinstance(feats, dict)
