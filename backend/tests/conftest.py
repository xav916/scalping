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


@pytest.fixture(autouse=True)
def soldes_caches_isoles():
    """Vide les caches de soldes entre chaque test.

    `sizing._cache_put` alimente deux dictionnaires de MODULE : celui du
    sizing (5 min) et le « dernier solde connu » qu'oppose le plafond de perte
    journalière (1 h, posé le 2026-09-03). Sans ce nettoyage, un solde écrit
    par un test de sizing survit à celui-ci et déplace le SEUIL du plafond
    dans les tests suivants — `test_dispatch_porte_de_cout` est tombé ainsi,
    en suite seulement, jamais isolé.

    ⚠️ Le symptôme est traître : le test qui échoue n'est pas celui qui
    pollue, et l'ordre d'exécution décide lequel tombe.
    """
    from backend.services import sizing
    sizing._BALANCE_CACHE.clear()
    sizing._SOLDE_CONNU.clear()
    yield
    sizing._BALANCE_CACHE.clear()
    sizing._SOLDE_CONNU.clear()


@pytest.fixture(autouse=True)
def limiteur_debit_neuf():
    """Remet le seau à jetons Twelve Data à zéro entre chaque test.

    `price_service._twelvedata_seau` est un singleton de MODULE. Les tests qui
    appellent `fetch_candles` ou `fetch_current_price` le vident, et ceux qui
    suivent se voient alors refuser ou retarder — `test_run_shadow_log_empty_input`
    et `test_e2e_no_data_pipeline` sont tombés ainsi, en suite seulement,
    jamais isolés.

    ⚠️ Troisième fois aujourd'hui que cet état global de module fait tomber un
    test innocent : les caches de solde, le schéma d'admission, maintenant le
    limiteur. La signature est toujours la même — vert isolé, rouge en suite.
    """
    from backend.services import price_service
    price_service._twelvedata_seau = None
    yield
    price_service._twelvedata_seau = None
