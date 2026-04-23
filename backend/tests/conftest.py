"""Shared pytest fixtures for the Scalping Radar backend."""
import pytest
import pytest_asyncio


def mock_request():
    """Starlette Request factice pour les tests qui appellent directement
    les handlers async (sans TestClient). Permet de satisfaire la signature
    des routes rate-limited qui incluent maintenant `request: Request`.
    """
    from starlette.requests import Request
    return Request({
        "type": "http",
        "method": "GET",
        "headers": [],
        "client": ("testclient", 0),
        "server": ("testclient", 80),
        "scheme": "http",
        "path": "/",
        "query_string": b"",
    })


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


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Le limiter slowapi est désactivé par défaut en tests :
    - Beaucoup de tests existants appellent les handlers async directement
      (sans TestClient) et ne passent pas de `Request`, ce que slowapi
      exige dès qu'il est actif.
    - Les tests qui vérifient le rate limit lui-même (test_rate_limiting.py)
      réactivent explicitement via la fixture `rate_limit_on`.

    Storage reset avant/après pour isoler chaque test qui active le limiter.
    """
    from backend.rate_limit import limiter
    saved = limiter.enabled
    limiter.enabled = False
    limiter.reset()
    yield
    limiter.enabled = saved
    limiter.reset()


@pytest.fixture
def rate_limit_on():
    """Réactive slowapi pour un test donné. À combiner avec TestClient."""
    from backend.rate_limit import limiter
    limiter.enabled = True
    limiter.reset()
    yield limiter
    limiter.enabled = False
    limiter.reset()
