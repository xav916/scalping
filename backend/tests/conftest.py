"""Shared pytest fixtures for the Scalping Radar backend."""
import pytest
import pytest_asyncio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def _clear_analytics_cache():
    """Cache in-memory de build_analytics (TTL 60s) doit être vidé entre
    tests sinon les mutations DB ne sont pas reflétées dans la réponse."""
    from backend.services import analytics_service
    analytics_service.invalidate_analytics_cache()
    yield
    analytics_service.invalidate_analytics_cache()
