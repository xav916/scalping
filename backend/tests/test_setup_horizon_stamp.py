"""L'horizon est estampillé à la source, et jamais écrasé (2026-08-05).

`enrich_trade_setup` est traversé par les deux générateurs. S'il estampillait
inconditionnellement, il écraserait le `4h` du flux V2 par le `CANDLE_INTERVAL`
global — et le routage par horizon enverrait des setups 4h sur la route
scalping. Le test `n_ecrase_pas` verrouille ce comportement.
"""
from datetime import datetime, timezone

from backend.models.schemas import (
    Candle, PatternDetection, PatternType, TradeDirection, TradeSetup,
)


def _setup(horizon=None) -> TradeSetup:
    pattern = PatternDetection(
        pair="XAU/USD",
        pattern=PatternType.MOMENTUM_UP,
        confidence=0.8,
        description="momentum haussier",
        detected_at=datetime.now(timezone.utc),
    )
    return TradeSetup(
        pair="XAU/USD",
        direction=TradeDirection.BUY,
        pattern=pattern,
        entry_price=2000.0,
        stop_loss=1990.0,
        take_profit_1=2015.0,
        take_profit_2=2025.0,
        risk_pips=10.0,
        reward_pips_1=15.0,
        reward_pips_2=25.0,
        risk_reward_1=1.5,
        risk_reward_2=2.5,
        message="test",
        timestamp=datetime.now(timezone.utc),
        horizon=horizon,
    )


def test_le_champ_horizon_existe_et_vaut_none_par_defaut():
    # None, pas "5min" : un setup non estampille est un setup d'horizon
    # inconnu, et la porte de la tache 3 doit pouvoir le voir comme tel.
    assert _setup().horizon is None


def test_enrich_estampille_l_horizon_v1_quand_il_est_vide(monkeypatch):
    from backend.services import analysis_engine

    monkeypatch.setattr(analysis_engine, "CANDLE_INTERVAL", "5min", raising=False)
    enrichi = analysis_engine.enrich_trade_setup(_setup(), None, None, [])
    assert enrichi.horizon == "5min"


def test_enrich_n_ecrase_pas_un_horizon_deja_pose(monkeypatch):
    # LE test de cette tache. Le flux V2 estampille "4h" AVANT d'enrichir.
    from backend.services import analysis_engine

    monkeypatch.setattr(analysis_engine, "CANDLE_INTERVAL", "5min", raising=False)
    enrichi = analysis_engine.enrich_trade_setup(_setup(horizon="4h"), None, None, [])
    assert enrichi.horizon == "4h"


def test_enrich_normalise_une_ecriture_exotique(monkeypatch):
    from backend.services import analysis_engine

    monkeypatch.setattr(analysis_engine, "CANDLE_INTERVAL", "5MIN", raising=False)
    assert analysis_engine.enrich_trade_setup(_setup(), None, None, []).horizon == "5min"


def test_enrich_laisse_none_si_candle_interval_est_inintelligible(monkeypatch):
    # Plutot un horizon absent qu'un horizon faux : la porte bloquera.
    from backend.services import analysis_engine

    monkeypatch.setattr(analysis_engine, "CANDLE_INTERVAL", "3min", raising=False)
    assert analysis_engine.enrich_trade_setup(_setup(), None, None, []).horizon is None


def test_le_flux_v2_estampille_son_propre_horizon():
    # Verification par inspection : run_shadow_log doit poser setup.horizon
    # depuis cfg["tf"] avant tout enrichissement. Une estampille posee apres
    # l'enrichissement arriverait trop tard — le score et le verdict de la
    # tache 5 en dependent.
    import inspect

    from backend.services import shadow_v2_core_long

    src = inspect.getsource(shadow_v2_core_long.run_shadow_log)
    assert "setup.horizon" in src, "run_shadow_log n'estampille pas l'horizon"
    i_stamp = src.index("setup.horizon")
    i_persist = src.index("_persist_setup")
    assert i_stamp < i_persist, "l'estampille doit precede la persistance"
