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
    from backend.services import price_service, shadow_v2_core_long
    price_service._twelvedata_seau = None
    # ⚠️ QUATRIEME etat global de module a polluer la suite le meme jour :
    # caches de solde, schema d'admission, limiteur, et maintenant le cache
    # des bougies journalieres. Toujours la meme signature — vert isole,
    # rouge en suite, et le test qui tombe n'est jamais celui qui pollue.
    shadow_v2_core_long._CACHE_1D.clear()
    yield
    price_service._twelvedata_seau = None
    shadow_v2_core_long._CACHE_1D.clear()


# ─── REM-002 / REM-003 : le harnais ARME, il n'exempte pas ──────────────
# ⛔ Le verrou d'execution global est fail-closed : sans manifest lisible et
# sans etat arme, `_check_rejection` refuse tout. C'est le comportement voulu
# EN PRODUCTION.
#
# 🔑 La tentation etait d'ajouter un drapeau « ne pas appliquer en test ».
# C'eut ete un fail-OPEN de plus, et exactement le defaut que REM-001 vient de
# supprimer : un chemin ou la porte ne s'applique pas. Le harnais pose donc un
# VRAI manifest et un VRAI armement dans un dossier temporaire, et les tests
# traversent le code de production sans exception.
#
# ⚠️ Un test qui veut eprouver la FERMETURE desarme explicitement (voir
# `test_rem002_global_execution_switch.py`).
@pytest.fixture(autouse=True)
def _armer_execution_globale(tmp_path, monkeypatch):
    import json

    manifest = tmp_path / "deployment_manifest.json"
    etat = tmp_path / "global_execution_switch.json"
    monkeypatch.setenv("DEPLOYMENT_MANIFEST_PATH", str(manifest))
    monkeypatch.setenv("GLOBAL_EXECUTION_STATE_PATH", str(etat))
    monkeypatch.delenv("EXPECTED_GIT_COMMIT", raising=False)

    manifest.write_text(json.dumps({
        "git_commit_sha": "0" * 40,
        "git_branch": "test",
        "git_dirty": False,
        "build_timestamp": "2026-01-01T00:00:00+00:00",
        "configuration_hash": "test",
        "build_environment": "pytest",
        "manifest_schema": 1,
    }), encoding="utf-8")

    from backend.services import deployment_manifest, global_execution_switch

    etat.write_text(json.dumps({
        "armed": True,
        "armed_fingerprint": deployment_manifest.fingerprint(),
        "armed_at": "2026-01-01T00:00:00+00:00",
        "armed_by": "pytest",
        "armed_reason": "harnais de test",
        "blocages": {},
    }), encoding="utf-8")

    # Garde-fou du harnais : si l'armement ne prend pas, on veut le savoir ici
    # et non dans 4 000 echecs incomprehensibles ailleurs.
    d = global_execution_switch.execution_allowed()
    assert d.allowed, (
        f"le harnais n'a pas su armer l'execution : {d.reason_code} "
        f"({d.detail}). Corriger la fixture, ne PAS exempter la porte."
    )
    yield
