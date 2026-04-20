"""Tests pour le cache + semaphore de price_service.

Le scheduler lance ~32 appels Twelve Data en parallèle par cycle. Sans
cache ni semaphore, ça sature le plan Grow (55 req/min) et retourne 0
candles → 0 setups. Ces tests vérifient que :
  - un cache hit évite l'appel HTTP (pas de credit consommé)
  - le cache expire après TTL
  - le semaphore limite la concurrence sur les appels réels
"""
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.models.schemas import Candle
from backend.services import price_service


def _mk_candle(close: float) -> Candle:
    return Candle(
        timestamp=datetime.now(timezone.utc),
        open=close,
        high=close * 1.001,
        low=close * 0.999,
        close=close,
        volume=100.0,
    )


@pytest.fixture(autouse=True)
def _reset_caches():
    """Les caches sont des globales — reset avant chaque test."""
    price_service.invalidate_caches()
    price_service._twelvedata_sem = None
    yield
    price_service.invalidate_caches()
    price_service._twelvedata_sem = None


@pytest.mark.asyncio
async def test_cache_hit_skips_api_call():
    """Deuxième appel sur même (pair, interval) < TTL : pas de HTTP."""
    call_count = 0

    async def _fake_fetch(pair, interval, outputsize):
        nonlocal call_count
        call_count += 1
        return [_mk_candle(1.1), _mk_candle(1.2)]

    with patch.object(price_service, "_fetch_twelvedata", _fake_fetch), \
         patch.object(price_service, "PRICE_SOURCE", "twelvedata"):
        c1, _ = await price_service.fetch_candles("EUR/USD", "5min", 50)
        c2, _ = await price_service.fetch_candles("EUR/USD", "5min", 50)

    assert call_count == 1
    assert c1 == c2 and len(c1) == 2


@pytest.mark.asyncio
async def test_cache_miss_when_different_interval():
    """Même pair, interval différent = cache miss → 2 appels API."""
    call_count = 0

    async def _fake_fetch(pair, interval, outputsize):
        nonlocal call_count
        call_count += 1
        return [_mk_candle(1.1)]

    with patch.object(price_service, "_fetch_twelvedata", _fake_fetch), \
         patch.object(price_service, "PRICE_SOURCE", "twelvedata"):
        await price_service.fetch_candles("EUR/USD", "5min", 50)
        await price_service.fetch_candles("EUR/USD", "1h", 50)

    assert call_count == 2


@pytest.mark.asyncio
async def test_cache_expires_after_ttl():
    """Après expiration TTL, la clé disparaît du cache et re-fetch."""
    call_count = 0

    async def _fake_fetch(pair, interval, outputsize):
        nonlocal call_count
        call_count += 1
        return [_mk_candle(1.1)]

    with patch.object(price_service, "_fetch_twelvedata", _fake_fetch), \
         patch.object(price_service, "PRICE_SOURCE", "twelvedata"), \
         patch.dict(price_service._CANDLE_TTL_SEC, {"5min": 0}):
        await price_service.fetch_candles("EUR/USD", "5min", 50)
        # TTL=0 → tout est expiré à l'instant suivant
        await asyncio.sleep(0.01)
        await price_service.fetch_candles("EUR/USD", "5min", 50)

    assert call_count == 2


@pytest.mark.asyncio
async def test_empty_candles_not_cached():
    """Si l'API retourne [] (rate limit), NE PAS cacher le vide sinon
    on bloque les retries pendant TTL secondes."""
    call_count = 0

    async def _fake_fetch(pair, interval, outputsize):
        nonlocal call_count
        call_count += 1
        return []

    with patch.object(price_service, "_fetch_twelvedata", _fake_fetch), \
         patch.object(price_service, "PRICE_SOURCE", "twelvedata"):
        c1, _ = await price_service.fetch_candles("EUR/USD", "5min", 50)
        c2, _ = await price_service.fetch_candles("EUR/USD", "5min", 50)

    # Deux appels API car le vide n'est pas mis en cache
    assert call_count == 2
    assert c1 == [] and c2 == []


@pytest.mark.asyncio
async def test_semaphore_caps_parallel_twelvedata_calls():
    """Quand _fetch_twelvedata est appelé N fois en parallèle, la
    concurrence effective reste ≤ _TWELVEDATA_MAX_CONCURRENT."""
    max_concurrent = [0]
    current = [0]
    lock = asyncio.Lock()

    async def _fake_get(*args, **kwargs):
        async with lock:
            current[0] += 1
            if current[0] > max_concurrent[0]:
                max_concurrent[0] = current[0]
        await asyncio.sleep(0.05)
        async with lock:
            current[0] -= 1
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"values": []}
        return resp

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **kw):
            return await _fake_get(*a, **kw)

    with patch.object(price_service, "TWELVEDATA_API_KEY", "test"), \
         patch.object(price_service, "_TWELVEDATA_MAX_CONCURRENT", 3), \
         patch("backend.services.price_service.httpx.AsyncClient", _FakeClient):
        price_service._twelvedata_sem = None  # force recreate with patched value
        tasks = [
            price_service._fetch_twelvedata(f"P{i}", "5min", 50)
            for i in range(12)
        ]
        await asyncio.gather(*tasks)

    assert max_concurrent[0] <= 3, f"Observé {max_concurrent[0]} concurrentes, attendu ≤ 3"


@pytest.mark.asyncio
async def test_price_cache_hit_skips_api_call():
    """fetch_current_price cache aussi pour éviter le spam des /price."""
    call_count = 0

    async def _fake_get(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"price": "1.1787"}
        return resp

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **kw):
            return await _fake_get(*a, **kw)

    with patch.object(price_service, "TWELVEDATA_API_KEY", "test"), \
         patch.object(price_service, "PRICE_SOURCE", "twelvedata"), \
         patch("backend.services.price_service.httpx.AsyncClient", _FakeClient):
        p1 = await price_service.fetch_current_price("EUR/USD")
        p2 = await price_service.fetch_current_price("EUR/USD")

    assert call_count == 1
    assert p1 == p2 == 1.1787
