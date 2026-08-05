"""Tests for macro_context_service: fetch, cache, stale fallback."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from backend.models.macro_schemas import MacroContext, MacroDirection, VixLevel, RiskRegime
from backend.services import macro_context_service as svc


@pytest.fixture(autouse=True)
def reset_cache():
    """Ensure each test starts with a clean cache."""
    svc._cache_snapshot = None
    yield
    svc._cache_snapshot = None


def _fake_candles(values: list[float]) -> list[dict]:
    """Mock Twelve Data time_series response shape."""
    return [{"close": str(v)} for v in values]


class TestZScoreComputation:
    def test_zscore_zero_when_price_equals_mean(self):
        closes = [100.0] * 20
        assert svc._compute_zscore(100.0, closes) == 0.0

    def test_zscore_positive_when_price_above_mean(self):
        closes = [100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0,
                  101.0, 101.0, 101.0, 101.0, 101.0, 101.0, 101.0, 101.0, 101.0, 101.0]
        z = svc._compute_zscore(102.0, closes)
        assert z > 0

    def test_zscore_zero_when_series_is_flat(self):
        # stddev=0 — should return 0 instead of dividing by zero
        closes = [50.0] * 20
        assert svc._compute_zscore(55.0, closes) == 0.0


class TestRiskRegimeDerivation:
    def test_risk_off_when_vix_high_and_spx_down(self):
        regime = svc._derive_risk_regime(VixLevel.ELEVATED, MacroDirection.DOWN)
        assert regime == RiskRegime.RISK_OFF

    def test_risk_on_when_vix_low_and_spx_up(self):
        regime = svc._derive_risk_regime(VixLevel.LOW, MacroDirection.UP)
        assert regime == RiskRegime.RISK_ON

    def test_neutral_otherwise(self):
        regime = svc._derive_risk_regime(VixLevel.NORMAL, MacroDirection.NEUTRAL)
        assert regime == RiskRegime.NEUTRAL


class TestCache:
    def test_get_returns_none_before_first_fetch(self):
        assert svc.get_macro_snapshot() is None

    def test_get_returns_cached_after_set(self):
        ctx = MacroContext(
            fetched_at=datetime.now(timezone.utc),
            dxy_direction=MacroDirection.UP,
            spx_direction=MacroDirection.NEUTRAL,
            vix_level=VixLevel.NORMAL,
            vix_value=17.0,
            us10y_trend=MacroDirection.NEUTRAL,
            de10y_trend=MacroDirection.NEUTRAL,
            us_de_spread_trend="flat",
            oil_direction=MacroDirection.NEUTRAL,
            nikkei_direction=MacroDirection.NEUTRAL,
            gold_direction=MacroDirection.NEUTRAL,
            risk_regime=RiskRegime.NEUTRAL,
            raw_values={},
        )
        svc._cache_snapshot = ctx
        assert svc.get_macro_snapshot() is ctx

    def test_is_fresh_returns_false_when_older_than_max_age(self):
        old = datetime.now(timezone.utc) - timedelta(hours=3)
        assert svc.is_fresh(old) is False

    def test_is_fresh_returns_true_when_recent(self):
        recent = datetime.now(timezone.utc) - timedelta(minutes=30)
        assert svc.is_fresh(recent) is True


class TestVixFallbackSources:
    """Tests unitaires des deux fonctions de repli, isolées de
    refresh_macro_context(). Piège classique : patcher le mauvais module —
    ces fonctions font un import paresseux de `vix_service` / `macro_data`
    à l'intérieur de leur corps, donc le monkeypatch doit viser le module
    SOURCE (`backend.services.vix_service`, `backend.services.macro_data`),
    pas un attribut inexistant sur `macro_context_service`."""

    def test_vix_from_service_returns_value_when_available(self):
        fake_snap = {"available": True, "value": 18.7, "is_fresh": True}
        with patch("backend.services.vix_service.get_current", return_value=fake_snap):
            v = svc._vix_from_service()
        assert v == 18.7

    def test_vix_from_service_returns_none_when_unavailable(self):
        with patch("backend.services.vix_service.get_current",
                   return_value={"available": False, "reason": "no data"}):
            v = svc._vix_from_service()
        assert v is None

    def test_vix_from_service_best_effort_on_exception(self):
        """Une source en panne ne doit jamais lever — best-effort strict."""
        with patch("backend.services.vix_service.get_current", side_effect=RuntimeError("boom")):
            v = svc._vix_from_service()
        assert v is None

    def test_vix_from_macro_daily_returns_value_when_available(self):
        with patch("backend.services.macro_data.get_macro_features_at",
                   return_value={"vix_level": 21.9}):
            v = svc._vix_from_macro_daily()
        assert v == 21.9

    def test_vix_from_macro_daily_returns_none_when_absent(self):
        with patch("backend.services.macro_data.get_macro_features_at", return_value={}):
            v = svc._vix_from_macro_daily()
        assert v is None

    def test_vix_from_macro_daily_best_effort_on_exception(self):
        with patch("backend.services.macro_data.get_macro_features_at",
                   side_effect=RuntimeError("db locked")):
            v = svc._vix_from_macro_daily()
        assert v is None

    def test_vix_from_macro_daily_never_uses_a_future_timestamp(self):
        """Non look-ahead : le repli interroge toujours 'maintenant', jamais
        un instant arbitraire fourni par l'appelant ou figé dans le passé
        lointain — cohérent avec la règle asof déjà en place dans
        macro_data.get_macro_features_at (T-1 jour calendaire plein)."""
        captured = {}

        def fake_get_features_at(ts):
            captured["ts"] = ts
            return {"vix_level": 16.0}

        before = datetime.now(timezone.utc)
        with patch("backend.services.macro_data.get_macro_features_at", side_effect=fake_get_features_at):
            svc._vix_from_macro_daily()
        after = datetime.now(timezone.utc)

        assert before <= captured["ts"] <= after


class TestRefreshFromMockedTwelveData:
    @pytest.mark.asyncio
    async def test_refresh_populates_cache_on_success(self):
        fake_candles = _fake_candles([100.0] * 19 + [102.0])
        with patch("backend.services.macro_context_service.MACRO_SCORING_ENABLED", True):
            with patch("backend.services.macro_context_service._fetch_candles_for_symbol",
                       new=AsyncMock(return_value=fake_candles)):
                ok = await svc.refresh_macro_context()
        assert ok is True
        assert svc.get_macro_snapshot() is not None

    @pytest.mark.asyncio
    async def test_refresh_returns_false_when_all_symbols_fail(self):
        with patch("backend.services.macro_context_service.MACRO_SCORING_ENABLED", True):
            with patch("backend.services.macro_context_service._fetch_candles_for_symbol",
                       new=AsyncMock(return_value=[])):
                ok = await svc.refresh_macro_context()
        assert ok is False

    @pytest.mark.asyncio
    async def test_flag_off_keeps_constant_fallback_unchanged(self):
        """MACRO_VIX_REAL_SOURCE_ENABLED=False (défaut) : comportement
        strictement inchangé — spot.get('vix', 17.0), les nouvelles sources
        de repli ne sont même pas consultées. Un autre symbole (ex: SPX)
        doit répondre pour que le snapshot se construise (spot non vide) —
        sinon on ne teste que le chemin préexistant "tout a échoué"."""
        fake_candles = _fake_candles([100.0] * 20)

        async def fake_fetch(symbol, outputsize=21):
            return [] if symbol == "VIX" else fake_candles

        with patch("backend.services.macro_context_service.MACRO_SCORING_ENABLED", True), \
             patch("backend.services.macro_context_service.MACRO_VIX_REAL_SOURCE_ENABLED", False), \
             patch("backend.services.macro_context_service._fetch_candles_for_symbol",
                   new=fake_fetch), \
             patch("backend.services.macro_context_service._vix_from_service") as m_service, \
             patch("backend.services.macro_context_service._vix_from_macro_daily") as m_daily:
            ok = await svc.refresh_macro_context()
        assert ok is True
        snap = svc.get_macro_snapshot()
        assert snap.vix_value == 17.0
        assert snap.vix_level == VixLevel.NORMAL
        m_service.assert_not_called()
        m_daily.assert_not_called()

    @pytest.mark.asyncio
    async def test_flag_on_uses_direct_fetch_when_available(self):
        """Drapeau activé + Twelve Data répond pour VIX : on garde la valeur
        directe, sans passer par les replis. Twelve Data renvoie les
        bougies du plus récent au plus ancien (`current = floats[0]`)."""
        fake_candles = _fake_candles([24.0] + [17.0] * 19)

        async def fake_fetch(symbol, outputsize=21):
            return fake_candles if symbol == "VIX" else []

        with patch("backend.services.macro_context_service.MACRO_SCORING_ENABLED", True), \
             patch("backend.services.macro_context_service.MACRO_VIX_REAL_SOURCE_ENABLED", True), \
             patch("backend.services.macro_context_service._fetch_candles_for_symbol",
                   new=fake_fetch), \
             patch("backend.services.macro_context_service._vix_from_service") as m_service, \
             patch("backend.services.macro_context_service._vix_from_macro_daily") as m_daily:
            ok = await svc.refresh_macro_context()
        assert ok is True
        snap = svc.get_macro_snapshot()
        assert snap.vix_value == 24.0
        m_service.assert_not_called()
        m_daily.assert_not_called()

    @pytest.mark.asyncio
    async def test_flag_on_falls_back_to_vix_service_when_direct_fetch_missing(self):
        """Drapeau activé, Twelve Data ne renvoie rien pour VIX (cas réel en
        prod, symbole non supporté — les autres symboles répondent) : repli
        sur vix_service (Yahoo, déjà vivant en prod pour le veto equity),
        macro_daily n'est même pas consulté."""
        fake_candles = _fake_candles([100.0] * 20)

        async def fake_fetch(symbol, outputsize=21):
            return [] if symbol == "VIX" else fake_candles

        with patch("backend.services.macro_context_service.MACRO_SCORING_ENABLED", True), \
             patch("backend.services.macro_context_service.MACRO_VIX_REAL_SOURCE_ENABLED", True), \
             patch("backend.services.macro_context_service._fetch_candles_for_symbol",
                   new=fake_fetch), \
             patch("backend.services.macro_context_service._vix_from_service", return_value=19.4), \
             patch("backend.services.macro_context_service._vix_from_macro_daily") as m_daily:
            ok = await svc.refresh_macro_context()
        assert ok is True
        snap = svc.get_macro_snapshot()
        assert snap.vix_value == 19.4
        assert snap.vix_level == VixLevel.NORMAL
        m_daily.assert_not_called()

    @pytest.mark.asyncio
    async def test_flag_on_all_vix_sources_fail_gives_none_never_constant(self):
        """Le cas central de la réparation : si Twelve Data, vix_service ET
        macro_daily échouent tous, vix_value doit être None — jamais un
        retour furtif à 17.0."""
        fake_candles = _fake_candles([100.0] * 19 + [101.0])  # SPX ou autre symbole non-VIX

        async def fake_fetch(symbol, outputsize=21):
            return [] if symbol == "VIX" else fake_candles

        with patch("backend.services.macro_context_service.MACRO_SCORING_ENABLED", True), \
             patch("backend.services.macro_context_service.MACRO_VIX_REAL_SOURCE_ENABLED", True), \
             patch("backend.services.macro_context_service._fetch_candles_for_symbol",
                   new=fake_fetch), \
             patch("backend.services.macro_context_service._vix_from_service", return_value=None), \
             patch("backend.services.macro_context_service._vix_from_macro_daily", return_value=None):
            ok = await svc.refresh_macro_context()
        assert ok is True  # d'autres symboles ont répondu -> snapshot construit quand même
        snap = svc.get_macro_snapshot()
        assert snap.vix_value is None
        assert snap.vix_level is None
        assert snap.risk_regime == RiskRegime.NEUTRAL  # dérivé sans lever

    @pytest.mark.asyncio
    async def test_flag_on_falls_back_to_macro_daily_when_vix_service_unavailable(self):
        fake_candles = _fake_candles([100.0] * 19 + [101.0])

        async def fake_fetch(symbol, outputsize=21):
            return [] if symbol == "VIX" else fake_candles

        with patch("backend.services.macro_context_service.MACRO_SCORING_ENABLED", True), \
             patch("backend.services.macro_context_service.MACRO_VIX_REAL_SOURCE_ENABLED", True), \
             patch("backend.services.macro_context_service._fetch_candles_for_symbol",
                   new=fake_fetch), \
             patch("backend.services.macro_context_service._vix_from_service", return_value=None), \
             patch("backend.services.macro_context_service._vix_from_macro_daily", return_value=21.3):
            ok = await svc.refresh_macro_context()
        assert ok is True
        snap = svc.get_macro_snapshot()
        assert snap.vix_value == 21.3
        assert snap.vix_level == VixLevel.ELEVATED

    @pytest.mark.asyncio
    async def test_refresh_preserves_existing_cache_on_failure(self):
        existing = MacroContext(
            fetched_at=datetime.now(timezone.utc) - timedelta(minutes=30),
            dxy_direction=MacroDirection.UP,
            spx_direction=MacroDirection.NEUTRAL,
            vix_level=VixLevel.NORMAL,
            vix_value=17.0,
            us10y_trend=MacroDirection.NEUTRAL,
            de10y_trend=MacroDirection.NEUTRAL,
            us_de_spread_trend="flat",
            oil_direction=MacroDirection.NEUTRAL,
            nikkei_direction=MacroDirection.NEUTRAL,
            gold_direction=MacroDirection.NEUTRAL,
            risk_regime=RiskRegime.NEUTRAL,
            raw_values={},
        )
        svc._cache_snapshot = existing

        with patch("backend.services.macro_context_service.MACRO_SCORING_ENABLED", True):
            with patch("backend.services.macro_context_service._fetch_candles_for_symbol",
                       new=AsyncMock(return_value=[])):
                await svc.refresh_macro_context()

        assert svc.get_macro_snapshot() is existing
