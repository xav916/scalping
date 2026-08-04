"""Barème de confiance v2 — nettoyage du 2026-08-04.

Autopsie de v1 sur 96 404 trades résolus hors WTI (jointure
`backtest.db.signals` × `trades`) :

    composante     barème   valeur dominante        verdict
    Pattern          30     24 pts sur 28,6 %       seule informative
    Risk/Reward      25     18 pts sur 100,0 %      constante
    Volatilité       20     12 pts sur 57,1 %       inversée
    Tendance         15      5 pts sur 99,1 %       volatilité déguisée
    Contexte éco     10      0 pt  sur 87,7 %       quasi constante, inversée

Corrélation de rang tranche/performance :

    période             v1        v2
    mai-juin (IN)     +0,46     +0,80
    juil-août (OUT)   -0,71     +0,90

v1 classait donc **à l'envers** hors échantillon. À sélectivité égale
(v1 ≥ 60 ↔ v2 ≥ 71) : +0,047 R/trade contre +0,030.
"""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from backend.models.schemas import VolatilityLevel, TrendDirection
from backend.services import analysis_engine as ae


def _setup(pattern_conf=0.80, rr=1.8, direction="buy"):
    return NS(
        pair="EUR/USD",
        direction=NS(value=direction),
        pattern=NS(confidence=pattern_conf, description="Rebond sur support"),
        risk_reward_1=rr, risk_pips=10.0, reward_pips_1=18.0,
    )


def _vol(level, ratio=1.0):
    return NS(level=level, volatility_ratio=ratio)


def _trend(direction=TrendDirection.NEUTRAL, strength=0.6):
    return NS(direction=direction, strength=strength)


def _score(factors):
    return sum(f.score for f in factors)


def _names(factors):
    return [f.name for f in factors]


# --- ce que v2 retire -------------------------------------------------------

def test_v2_ne_garde_que_deux_composantes():
    f = ae._factors_v2(_setup(), _vol(VolatilityLevel.MEDIUM), _trend(), [])
    assert _names(f) == ["Pattern", "Volatilite"]


def test_le_risk_reward_disparait():
    """96 401 signaux sur 96 404 recevaient 18 points — une constante."""
    assert "Risk/Reward" not in _names(
        ae._factors_v2(_setup(), _vol(VolatilityLevel.LOW), _trend(), []))


def test_le_risk_reward_ne_bouge_plus_le_score():
    """Preuve directe : deux R:R opposés donnent le même score."""
    a = _score(ae._factors_v2(_setup(rr=0.5), _vol(VolatilityLevel.LOW), _trend(), []))
    b = _score(ae._factors_v2(_setup(rr=3.0), _vol(VolatilityLevel.LOW), _trend(), []))
    assert a == b


def test_la_tendance_ne_bouge_plus_le_score():
    """`analyze_trend` dérive de la volatilité : elle la comptait deux fois."""
    s, v = _setup(), _vol(VolatilityLevel.MEDIUM)
    scores = {
        _score(ae._factors_v2(s, v, _trend(d, 0.85), []))
        for d in (TrendDirection.BULLISH, TrendDirection.BEARISH, TrendDirection.NEUTRAL)
    }
    assert len(scores) == 1


def test_le_contexte_eco_ne_bouge_plus_le_score():
    """Doublon du veto calendrier, et inversé (0 pt performait mieux)."""
    evt = NS(currency="EUR", impact="HIGH", event_name="FOMC", actual=None)
    s, v = _setup(), _vol(VolatilityLevel.MEDIUM)
    assert _score(ae._factors_v2(s, v, _trend(), [])) == \
           _score(ae._factors_v2(s, v, _trend(), [evt]))


# --- ce que v2 corrige ------------------------------------------------------

def test_la_volatilite_est_remise_a_lendroit():
    """v1 donnait 20 pts à HIGH et 3 à LOW ; HIGH est le pire bucket.

    Hors range_bounce : HIGH −0,052 / MEDIUM −0,017 / LOW +0,013 R/trade.
    """
    def vol_pts(level):
        f = ae._factors_v2(_setup(), _vol(level), _trend(), [])
        return next(x.score for x in f if x.name == "Volatilite")

    assert vol_pts(VolatilityLevel.LOW) > vol_pts(VolatilityLevel.MEDIUM) \
        > vol_pts(VolatilityLevel.HIGH)


def test_v1_notait_bien_la_volatilite_a_lenvers():
    """Test-témoin : sans lui, le précédent ne prouve pas qu'on a inversé."""
    def vol_pts(level):
        f = ae._factors_v1(_setup(), _vol(level), _trend(), [])
        return next(x.score for x in f if x.name == "Volatilite")

    assert vol_pts(VolatilityLevel.HIGH) > vol_pts(VolatilityLevel.LOW)


def test_lechelle_reste_sur_100():
    """Pattern 0-60 + Volatilité 0-40. Le maximum reste atteignable."""
    assert _score(ae._factors_v2(
        _setup(pattern_conf=1.0), _vol(VolatilityLevel.LOW), _trend(), [])) == 100.0


def test_volatilite_absente_ne_casse_pas():
    f = ae._factors_v2(_setup(), None, _trend(), [])
    assert next(x.score for x in f if x.name == "Volatilite") == 0.0


# --- le drapeau de bascule --------------------------------------------------

def test_le_drapeau_choisit_le_bareme(monkeypatch):
    import config.settings as st
    args = (_setup(), _vol(VolatilityLevel.HIGH), _trend(), [])

    monkeypatch.setattr(st, "CONFIDENCE_SCORE_V2", False)
    assert _names(ae._build_confidence_factors(*args)) == \
        ["Pattern", "Risk/Reward", "Volatilite", "Tendance", "Contexte eco"]

    monkeypatch.setattr(st, "CONFIDENCE_SCORE_V2", True)
    assert _names(ae._build_confidence_factors(*args)) == ["Pattern", "Volatilite"]


def test_le_defaut_est_v1(monkeypatch):
    """Déployer le code ne doit RIEN changer tant que les seuils n'ont pas bougé.

    v2 déplace la médiane du score de 57 à 70 : activer sans remonter les
    seuils rendrait le dispatch bien plus permissif, en argent réel.
    """
    import importlib, config.settings as st
    monkeypatch.delenv("CONFIDENCE_SCORE_V2", raising=False)
    importlib.reload(st)
    try:
        assert st.CONFIDENCE_SCORE_V2 is False
    finally:
        importlib.reload(st)


@pytest.mark.parametrize("raw,attendu", [
    ("true", True), ("1", True), ("YES", True),
    ("false", False), ("", False), ("nope", False),
])
def test_parsing_du_drapeau(monkeypatch, raw, attendu):
    import importlib, config.settings as st
    monkeypatch.setenv("CONFIDENCE_SCORE_V2", raw)
    importlib.reload(st)
    try:
        assert st.CONFIDENCE_SCORE_V2 is attendu
    finally:
        monkeypatch.delenv("CONFIDENCE_SCORE_V2", raising=False)
        importlib.reload(st)
