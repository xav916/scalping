"""Le flux long-horizon doit être scoré, sinon il est invisible (2026-08-05).

`calculate_trade_setup` ne renseigne pas `confidence_score`. Et le barème v2
conditionne sa composante Volatilité à `if volatility:` — enrichir sans
`VolatilityData` plafonne le score à 60, un point SOUS le seuil Telegram de 61.

Brancher le flux long-horizon sans sa volatilité le rendrait invisible sans
produire le moindre refus.
"""
from datetime import datetime, timedelta, timezone

import pytest

from backend.models.schemas import (
    Candle, PatternDetection, PatternType, TradeDirection, TradeSetup,
)
from backend.services.backtest_engine import compute_volatility


def _bougies(n=60, base=2000.0, pas=1.0):
    t0 = datetime(2026, 8, 5, tzinfo=timezone.utc)
    return [
        Candle(
            timestamp=t0 + timedelta(hours=4 * i),
            open=base + i * pas, high=base + i * pas + 5,
            low=base + i * pas - 5, close=base + i * pas + 1, volume=100,
        )
        for i in range(n)
    ]


def _setup(horizon="4h"):
    pattern = PatternDetection(
        pair="XAU/USD", pattern=PatternType.MOMENTUM_UP, confidence=0.9,
        description="momentum haussier", detected_at=datetime.now(timezone.utc),
    )
    return TradeSetup(
        pair="XAU/USD", direction=TradeDirection.BUY, pattern=pattern,
        entry_price=2000.0, stop_loss=1990.0, take_profit_1=2015.0,
        take_profit_2=2025.0, risk_pips=10.0, reward_pips_1=15.0,
        reward_pips_2=25.0, risk_reward_1=1.5, risk_reward_2=2.5,
        message="test", timestamp=datetime.now(timezone.utc), horizon=horizon,
    )


def test_le_piege_sans_volatilite_le_score_plafonne_a_60(monkeypatch):
    # CE test documente POURQUOI la tache existe. S'il se met a echouer,
    # c'est que le bareme a change : relire la tache avant de le "reparer".
    #
    # ⚠️ Le drapeau doit etre bascule sur l'attribut VIVANT de config.settings :
    # `_build_confidence_factors` refait `from config.settings import
    # CONFIDENCE_SCORE_V2` a chaque appel, donc monkeypatcher `analysis_engine`
    # (ou passer par `setenv`, deja lu a l'import du module) est sans effet.
    # Meme motif que `test_le_drapeau_choisit_le_bareme`
    # (test_confidence_score_v2.py).
    import config.settings as st
    from backend.services import analysis_engine

    monkeypatch.setattr(st, "CONFIDENCE_SCORE_V2", True)
    enrichi = analysis_engine.enrich_trade_setup(_setup(), None, None, [])
    # Verifie qu'on exerce bien le bareme v2 a deux composantes (Pattern +
    # Volatilite) et pas l'ancien bareme v1 a cinq composantes — sinon le
    # plafond a 60 serait atteint par une autre voie (Risk/Reward, Tendance,
    # Contexte eco) et ne prouverait rien sur le piege documente ici.
    noms_facteurs = {f.name for f in enrichi.confidence_factors}
    assert noms_facteurs == {"Pattern", "Volatilite"}, (
        "le test doit exercer le bareme v2 (Pattern + Volatilite uniquement), "
        f"pas: {noms_facteurs}"
    )
    assert enrichi.confidence_score <= 60.0, (
        "sans volatilite le bareme v2 plafonne a 60 — un point sous le seuil "
        "Telegram de 61"
    )


def test_avec_sa_volatilite_le_score_peut_depasser_le_seuil_telegram(monkeypatch):
    import config.settings as st
    from backend.services import analysis_engine

    monkeypatch.setattr(st, "CONFIDENCE_SCORE_V2", True)
    vol = compute_volatility(_bougies(), "XAU/USD", timeframe="4h")

    sans_volatilite = analysis_engine.enrich_trade_setup(_setup(), None, None, [])
    avec_volatilite = analysis_engine.enrich_trade_setup(_setup(), vol, None, [])

    assert avec_volatilite.confidence_score > 60.0
    # La composante Volatilite doit etre la cause du depassement, pas une
    # coincidence arithmetique : sans elle, le meme setup reste sous le seuil.
    assert sans_volatilite.confidence_score <= 60.0
    vol_score = next(
        f.score for f in avec_volatilite.confidence_factors if f.name == "Volatilite"
    )
    assert vol_score > 0.0, "le depassement doit venir de la composante Volatilite"
    assert avec_volatilite.confidence_score - sans_volatilite.confidence_score == vol_score


def test_compute_volatility_etiquette_le_timeframe_qu_on_lui_donne():
    # Meme lecon que le correctif d'etiquette du shadow V1 : une etiquette
    # qui ment se propage. Ici elle irait dans le score d'un setup 4h en
    # pretendant decrire du 1H.
    vol = compute_volatility(_bougies(), "XAU/USD", timeframe="4h")
    assert vol.timeframe == "4h"


def test_compute_volatility_garde_son_defaut_historique():
    # Les appelants existants ne passent pas de timeframe et doivent
    # continuer a produire "1H".
    assert compute_volatility(_bougies(), "XAU/USD").timeframe == "1H"


def test_compute_volatility_etiquette_meme_sur_serie_trop_courte():
    # La branche "moins de 15 bougies" construisait un VolatilityData en dur
    # avec timeframe="1H" — elle doit honorer le parametre elle aussi.
    assert compute_volatility(_bougies(3), "XAU/USD", timeframe="1d").timeframe == "1d"


def test_le_setup_porte_le_systeme_qui_l_a_produit():
    s = _setup()
    s.shadow_system_id = "V2_CORE_LONG_XAUUSD_4H"
    assert s.shadow_system_id == "V2_CORE_LONG_XAUUSD_4H"


def test_shadow_system_id_vaut_none_par_defaut():
    assert _setup().shadow_system_id is None


def test_run_shadow_log_score_et_juge_avant_de_persister():
    # Verification par inspection : l'enrichissement et le verdict doivent
    # exister dans la fonction, et la volatilite doit etre calculee sur les
    # bougies de detection (signal_candles), pas ailleurs.
    import inspect

    from backend.services import shadow_v2_core_long

    src = inspect.getsource(shadow_v2_core_long.run_shadow_log)
    assert "enrich_trade_setup" in src, "le flux V2 n'est pas score"
    assert "compute_verdict" in src, "le flux V2 n'a pas de verdict"
    assert "compute_volatility(signal_candles" in src, (
        "la volatilite doit etre calculee sur les bougies de detection"
    )
    assert "shadow_system_id" in src
