"""À horizon long, un veto qui réduit ne suffit plus (2026-08-05).

Une position de scalping se ferme avant l'événement. Une position tenue
quatre heures ou un jour le traverse. Le multiplicateur ×0,60 devient donc
un refus, et le gel énergie du vendredi se généralise à toute détention
qui franchit la clôture.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from backend.services.mt5_bridge import _event_rejection


def _setup(horizon="4h", pair="AAPL"):
    return SimpleNamespace(pair=pair, horizon=horizon, entry_price=200.0,
                           stop_loss=198.0, confidence_score=80.0)


def _dest():
    return SimpleNamespace(destination_id="admin_live", auto_exec_enabled=True)


# ── Earnings ────────────────────────────────────────────────────────────

def test_earnings_bloque_a_horizon_long(monkeypatch):
    from backend.services import earnings_veto

    monkeypatch.setattr(earnings_veto, "blocks_at_long_horizon",
                        lambda pair, now=None: True)
    assert _event_rejection(_setup("4h"), _dest()) == "earnings_blackout"


def test_earnings_ne_bloque_pas_a_horizon_court(monkeypatch):
    # En scalping la position se ferme avant. Le veto doux existant
    # (multiplicateur x0,60) continue de s'appliquer en amont, au scoring.
    from backend.services import earnings_veto

    monkeypatch.setattr(earnings_veto, "blocks_at_long_horizon",
                        lambda pair, now=None: True)
    assert _event_rejection(_setup("5min"), _dest()) is None


def test_hors_fenetre_earnings_rien_ne_bloque(monkeypatch):
    from backend.services import earnings_veto

    monkeypatch.setattr(earnings_veto, "blocks_at_long_horizon",
                        lambda pair, now=None: False)
    assert _event_rejection(_setup("4h"), _dest()) is None


def test_blocks_at_long_horizon_est_best_effort(monkeypatch):
    # Le calendrier earnings depend de yfinance. Indisponible, il ne doit
    # ni lever ni bloquer tout le flux equity.
    from backend.services import earnings_veto

    def _casse(*a, **k):
        raise RuntimeError("yfinance down")

    monkeypatch.setattr(earnings_veto, "_next_earnings_at", _casse, raising=False)
    assert earnings_veto.blocks_at_long_horizon("AAPL") is False


# ── Gel de week-end ─────────────────────────────────────────────────────

def _vendredi_soir():
    # 2026-08-07 est un vendredi. 19h UTC > seuil par defaut de 18h.
    return datetime(2026, 8, 7, 19, 0, tzinfo=timezone.utc)


def _mardi_midi():
    return datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)


def test_detention_longue_bloquee_le_vendredi_soir(monkeypatch):
    monkeypatch.setattr("backend.services.mt5_bridge._now_utc", _vendredi_soir,
                        raising=False)
    assert _event_rejection(_setup("4h", "XAU/USD"), _dest()) == "weekend_hold_blocked"


def test_scalping_non_bloque_le_vendredi_soir(monkeypatch):
    # Le gel energie existant continue de traiter WTI a part ; le scalping
    # sur les autres classes se ferme avant la cloture.
    monkeypatch.setattr("backend.services.mt5_bridge._now_utc", _vendredi_soir,
                        raising=False)
    assert _event_rejection(_setup("5min", "XAU/USD"), _dest()) is None


def test_detention_longue_non_bloquee_en_semaine(monkeypatch):
    monkeypatch.setattr("backend.services.mt5_bridge._now_utc", _mardi_midi,
                        raising=False)
    assert _event_rejection(_setup("4h", "XAU/USD"), _dest()) is None


def test_la_crypto_ne_subit_pas_le_gel_de_week_end(monkeypatch):
    # Le marche crypto ne ferme pas : il n'y a pas de gap de reouverture.
    monkeypatch.setattr("backend.services.mt5_bridge._now_utc", _vendredi_soir,
                        raising=False)
    assert _event_rejection(_setup("4h", "BTC/USD"), _dest()) is None


def test_classification_indisponible_ne_bloque_pas_la_crypto(monkeypatch):
    # Revue tache 7, trouvaille 1 : si asset_class_for n'est plus importable
    # depuis config.settings, le repli ne doit PAS deviner "forex" et geler
    # une position crypto a tort. Classification indisponible => pas de gel.
    import config.settings as settings

    monkeypatch.setattr("backend.services.mt5_bridge._now_utc", _vendredi_soir,
                        raising=False)
    monkeypatch.delattr(settings, "asset_class_for", raising=False)
    assert _event_rejection(_setup("4h", "BTC/USD"), _dest()) is None


def test_drapeau_desactive_laisse_passer_le_gel_de_weekend(monkeypatch):
    # Revue tache 7, trouvaille 2 : interrupteur dedie, independant du gel
    # energie preexistant. Patch au point de lecture reel : config.settings,
    # relu a chaque appel par l'import local dans _event_rejection.
    monkeypatch.setattr("backend.services.mt5_bridge._now_utc", _vendredi_soir,
                        raising=False)
    monkeypatch.setattr("config.settings.WEEKEND_HOLD_BLOCK_ENABLED", False)
    assert _event_rejection(_setup("4h", "XAU/USD"), _dest()) is None


def test_drapeau_active_bloque_toujours_le_gel_de_weekend(monkeypatch):
    monkeypatch.setattr("backend.services.mt5_bridge._now_utc", _vendredi_soir,
                        raising=False)
    monkeypatch.setattr("config.settings.WEEKEND_HOLD_BLOCK_ENABLED", True)
    assert _event_rejection(_setup("4h", "XAU/USD"), _dest()) == "weekend_hold_blocked"


# ── Traçabilité et branchement ──────────────────────────────────────────

def test_les_codes_sont_publics_et_libelles():
    from backend.services.rejection_service import REASON_LABELS_FR

    for code in ("earnings_blackout", "weekend_hold_blocked"):
        assert not code.startswith("_")
        assert code in REASON_LABELS_FR


def test_la_porte_est_reellement_appelee():
    import ast
    import inspect

    from backend.services import mt5_bridge

    source = inspect.getsource(mt5_bridge._check_rejection)
    tree = ast.parse(source)
    appels = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "_event_rejection" in appels
