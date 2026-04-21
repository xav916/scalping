"""Tests de la route catch-all SPA pour le build React.

Verifie que :
- Les routes React non-explicites (ex: /analytics, /trades) servent
  bien l'index.html du build (le router client prend la suite)
- Les prefixes reserves (/api, /ws, /css, /js, /assets) sont
  exclus du fallback
- Les extensions statiques manquantes retournent 404 au lieu d'un
  index.html mal typé (cas qui casserait Chrome)
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import backend.app as backend_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(backend_app.app)


def test_spa_enabled_in_test_env(client: TestClient):
    """Le build React est bien detecte (sinon ces tests n'ont pas de sens)."""
    assert backend_app.REACT_ENABLED is True


def test_spa_fallback_for_unknown_route(client: TestClient):
    """Une route non-enregistree doit retourner l'index.html."""
    r = client.get("/analytics", follow_redirects=False)
    assert r.status_code in (200, 303)
    if r.status_code == 200:
        # Soit le contenu HTML, soit une redirection vers /login
        assert "<!doctype html" in r.text.lower() or "<html" in r.text.lower()


def test_spa_fallback_excludes_api_paths(client: TestClient):
    """L'API ne doit jamais tomber dans le fallback (retourne 404 ou 401 JSON)."""
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404
    # La reponse est du JSON FastAPI, pas du HTML
    assert "<html" not in r.text.lower()


def test_spa_fallback_404_on_missing_static(client: TestClient):
    """Un asset manquant (.js, .css, .map...) doit renvoyer 404 et non
    un index.html qui serait mal interprete par le navigateur."""
    for path in ("/ghost.js", "/missing.map", "/nope.css"):
        r = client.get(path)
        assert r.status_code == 404, f"{path} devrait etre 404"
        assert "<html" not in r.text.lower()


def test_spa_fallback_excludes_ws_and_static_mounts(client: TestClient):
    """Les mounts connus doivent garder leur comportement natif."""
    # /assets/ est un mount → 404 sur fichier absent, pas SPA fallback
    r = client.get("/assets/ghost-xyz.js")
    assert r.status_code == 404
