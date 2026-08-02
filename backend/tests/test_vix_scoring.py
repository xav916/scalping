"""Tests du module vix_scoring — soft veto VIX pour signaux equity.

Gap 1 MVP (2026-08-02). Utilise unittest.mock.patch pour simuler
vix_service.get_current() sans accès SQLite ni réseau.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

import backend.services.vix_scoring as vix_scoring_mod
from backend.services.vix_scoring import apply_vix_veto


def _snap(value: float, age_sec: float = 10.0) -> dict:
    """Helper : construit un snapshot vix_service.get_current() factice."""
    return {
        "available": True,
        "value": value,
        "change_pct": 0.5,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "age_sec": age_sec,
        "is_fresh": age_sec < 300,
    }


def _unavailable(reason: str = "no data") -> dict:
    return {"available": False, "reason": reason}


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_mem_cache():
    """Vide le cache mémoire entre chaque test pour isolation parfaite."""
    vix_scoring_mod._MEM_CACHE = None
    yield
    vix_scoring_mod._MEM_CACHE = None


# ─── Tests régimes VIX ───────────────────────────────────────────────────────

@pytest.mark.parametrize("vix_val,expected_mult", [
    (15.0, 1.0),    # calme
    (19.9, 1.0),    # juste sous 20 → calme
    (20.0, 0.95),   # seuil modéré
    (25.0, 0.95),   # modéré
    (29.9, 0.95),   # juste sous 30 → modéré
    (30.0, 0.85),   # seuil stress
    (35.0, 0.85),   # stress
    (39.9, 0.85),   # juste sous 40 → stress
    (40.0, 0.70),   # seuil panique
    (45.0, 0.70),   # panique
    (80.0, 0.70),   # panique extrême
])
def test_vix_multiplier_regimes(vix_val: float, expected_mult: float):
    """Chaque seuil VIX applique le bon multiplicateur sur AAPL (equity)."""
    with patch("backend.services.vix_scoring.vix_service") as mock_svc:
        mock_svc.get_current.return_value = _snap(vix_val)
        new_score, meta = apply_vix_veto("AAPL", "buy", 80.0)

    assert meta["vix_multiplier"] == expected_mult
    assert new_score == round(80.0 * expected_mult, 1)
    assert meta["vix_value"] == round(vix_val, 2)


def test_vix_15_score_unchanged():
    """VIX=15 (calme) → multiplier 1.0, score inchangé."""
    with patch("backend.services.vix_scoring.vix_service") as mock_svc:
        mock_svc.get_current.return_value = _snap(15.0)
        new_score, meta = apply_vix_veto("AAPL", "buy", 80.0)

    assert new_score == 80.0
    assert meta["vix_multiplier"] == 1.0
    assert meta["vix_regime"] == "calm"


def test_vix_25_multiplier_095():
    """VIX=25 → multiplier 0.95."""
    with patch("backend.services.vix_scoring.vix_service") as mock_svc:
        mock_svc.get_current.return_value = _snap(25.0)
        new_score, meta = apply_vix_veto("TSLA", "buy", 70.0)

    assert meta["vix_multiplier"] == 0.95
    assert new_score == round(70.0 * 0.95, 1)
    assert meta["vix_regime"] == "moderate"


def test_vix_35_multiplier_085():
    """VIX=35 → multiplier 0.85."""
    with patch("backend.services.vix_scoring.vix_service") as mock_svc:
        mock_svc.get_current.return_value = _snap(35.0)
        new_score, meta = apply_vix_veto("NVDA", "buy", 72.0)

    assert meta["vix_multiplier"] == 0.85
    assert new_score == round(72.0 * 0.85, 1)
    assert meta["vix_regime"] == "stress"


def test_vix_45_multiplier_070():
    """VIX=45 → multiplier 0.70 (panique)."""
    with patch("backend.services.vix_scoring.vix_service") as mock_svc:
        mock_svc.get_current.return_value = _snap(45.0)
        new_score, meta = apply_vix_veto("MSFT", "buy", 68.0)

    assert meta["vix_multiplier"] == 0.70
    assert new_score == round(68.0 * 0.70, 1)
    assert meta["vix_regime"] == "panic"


# ─── Test no-op sur autres asset classes ─────────────────────────────────────

@pytest.mark.parametrize("pair", [
    "BTC/USD", "ETH/USD", "XAU/USD", "EUR/USD", "WTI/USD",
])
def test_non_equity_pair_is_noop(pair: str):
    """Les paires non-equity ne sont pas affectées (retour immédiat sans VIX)."""
    # Pas de patch vix_service : si apply_vix_veto appelle le service, le test
    # plantera — ce qui est le comportement attendu (ne doit pas appeler).
    new_score, meta = apply_vix_veto(pair, "buy", 75.0)
    assert new_score == 75.0
    assert meta == {}


# ─── Test best-effort sur erreur fetch ───────────────────────────────────────

def test_vix_fetch_failed_best_effort():
    """Si vix_service lève une exception → score inchangé + error metadata."""
    with patch("backend.services.vix_scoring.vix_service") as mock_svc:
        mock_svc.get_current.side_effect = RuntimeError("DB locked")
        new_score, meta = apply_vix_veto("AAPL", "buy", 65.0)

    assert new_score == 65.0
    assert "vix_error" in meta


def test_vix_unavailable_best_effort():
    """Si vix_service retourne available=False → score inchangé + error metadata."""
    with patch("backend.services.vix_scoring.vix_service") as mock_svc:
        mock_svc.get_current.return_value = _unavailable("no data")
        new_score, meta = apply_vix_veto("AAPL", "buy", 65.0)

    assert new_score == 65.0
    assert meta.get("vix_error") == "no data"


def test_vix_twelvedata_timeout_best_effort():
    """Timeout réseau simulé (import vix_service échoue) → score inchangé."""
    import sys
    # Retire temporairement le module pour simuler un échec d'import
    original = sys.modules.pop("backend.services.vix_service", None)
    vix_scoring_mod._MEM_CACHE = None  # force re-fetch

    try:
        # Patch l'import interne pour qu'il lève ImportError
        with patch.dict(sys.modules, {"backend.services.vix_service": None}):
            new_score, meta = apply_vix_veto("AAPL", "buy", 62.0)
    finally:
        if original is not None:
            sys.modules["backend.services.vix_service"] = original

    assert new_score == 62.0
    assert "vix_error" in meta


# ─── Test cache mémoire (5 min) ──────────────────────────────────────────────

def test_mem_cache_hit_single_vix_service_call():
    """5 appels consécutifs → vix_service.get_current() appelé 1 seule fois."""
    call_count = 0

    def fake_get_current():
        nonlocal call_count
        call_count += 1
        return _snap(18.0, age_sec=5.0)

    with patch("backend.services.vix_scoring.vix_service") as mock_svc:
        mock_svc.get_current.side_effect = fake_get_current
        for _ in range(5):
            apply_vix_veto("AAPL", "buy", 70.0)

    assert call_count == 1, f"Expected 1 call, got {call_count}"


def test_mem_cache_expired_refetches():
    """Cache expiré (simulé via manipulation timestamp) → re-fetch."""
    call_count = 0

    def fake_get_current():
        nonlocal call_count
        call_count += 1
        return _snap(22.0, age_sec=10.0)

    with patch("backend.services.vix_scoring.vix_service") as mock_svc:
        mock_svc.get_current.side_effect = fake_get_current

        # Premier appel
        apply_vix_veto("AAPL", "buy", 70.0)
        assert call_count == 1

        # Expire le cache mémoire
        val, _ = vix_scoring_mod._MEM_CACHE
        old_ts = time.monotonic() - vix_scoring_mod._MEM_CACHE_TTL - 1
        vix_scoring_mod._MEM_CACHE = (val, old_ts)

        # Deuxième appel doit refetch
        apply_vix_veto("AAPL", "buy", 70.0)
        assert call_count == 2


# ─── Test stale VIX (> 60 min) : utilisé avec warning ───────────────────────

def test_stale_vix_used_with_warning(caplog):
    """VIX âgé de >60 min → log warning mais applique quand même le veto."""
    import logging
    with patch("backend.services.vix_scoring.vix_service") as mock_svc:
        mock_svc.get_current.return_value = _snap(35.0, age_sec=3700.0)
        with caplog.at_level(logging.WARNING, logger="backend.services.vix_scoring"):
            new_score, meta = apply_vix_veto("AAPL", "buy", 80.0)

    assert meta["vix_multiplier"] == 0.85  # veto stress appliqué malgré stale
    assert "stale" in caplog.text.lower()


# ─── Test SPX (equity_index) ─────────────────────────────────────────────────

def test_equity_index_spx_gets_veto():
    """SPX (equity_index) doit aussi recevoir le veto VIX."""
    with patch("backend.services.vix_scoring.vix_service") as mock_svc:
        mock_svc.get_current.return_value = _snap(42.0)
        new_score, meta = apply_vix_veto("SPX", "buy", 75.0)

    assert meta["vix_multiplier"] == 0.70
    assert meta["asset_class"] == "equity_index"
    assert new_score == round(75.0 * 0.70, 1)
