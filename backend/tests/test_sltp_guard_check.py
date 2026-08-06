"""Tests pour backend/services/sltp_guard_check.py — l'orchestrateur du
garde-fou SL/TP (cf. mt5-bridge/bridge.py pour le fix de fond, incident
2026-08-05).

Prouve par mutation que le garde-fou ne pose JAMAIS de stop tant que
`SLTP_GUARD_AUTO_PROTECT_ENABLED` n'est pas explicitement activé (défaut :
détection + rapport seulement, comportement historique). httpx est
monkeypatché — aucun réseau réel.
"""
import pytest

from backend.services import sltp_guard_check as guard


# ─────────────────────────────────────────────────────────────────────
# is_naked — logique pure
# ─────────────────────────────────────────────────────────────────────

def test_is_naked_true_when_sl_zero():
    assert guard.is_naked({"sl": 0.0, "tp": 2660.0}) is True


def test_is_naked_true_when_sl_missing():
    assert guard.is_naked({"tp": 2660.0}) is True


def test_is_naked_false_when_sl_set():
    assert guard.is_naked({"sl": 2640.0, "tp": 2660.0}) is False


def test_is_naked_fails_closed_on_unreadable_sl():
    """Un sl illisible est traité comme nu — mieux vaut une fausse alerte
    qu'une position réellement nue passée sous silence."""
    assert guard.is_naked({"sl": "n/a"}) is True


# ─────────────────────────────────────────────────────────────────────
# check_all_bridges — orchestration, avec httpx monkeypatché
# ─────────────────────────────────────────────────────────────────────

class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self.headers = {"content-type": "application/json"}

    def json(self):
        return self._payload


def _fake_async_client(get_handler=None, post_handler=None):
    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            return get_handler(url, headers) if get_handler else _FakeResponse(200, {"positions": []})

        async def post(self, url, json=None, headers=None):
            return post_handler(url, json, headers) if post_handler else _FakeResponse(200, {"ok": True})

    return _Client


@pytest.mark.asyncio
async def test_check_all_bridges_unconfigured_bridges_are_unreachable(monkeypatch):
    monkeypatch.setattr(guard, "_BRIDGES", (("legacy", "", ""), ("live", "", "")))
    report = await guard.check_all_bridges()
    assert report["bridges"]["legacy"]["reachable"] is False
    assert report["bridges"]["live"]["reachable"] is False
    assert report["naked_total"] == 0


@pytest.mark.asyncio
async def test_check_all_bridges_detects_naked_without_acting_by_default(monkeypatch):
    """SLTP_GUARD_AUTO_PROTECT_ENABLED est False par défaut : le garde-fou
    doit DÉTECTER la position nue mais ne JAMAIS appeler /position/sltp."""
    monkeypatch.setattr(guard, "_BRIDGES", (("legacy", "http://bridge", "key"),))
    monkeypatch.setattr(guard, "SLTP_GUARD_AUTO_PROTECT_ENABLED", False)

    post_calls = []

    def _get(url, headers):
        assert url.endswith("/positions")
        return _FakeResponse(200, {"positions": [{"ticket": 1, "symbol": "XAUUSD", "sl": 0.0, "price_open": 2650.0}]})

    def _post(url, json, headers):
        post_calls.append((url, json))
        return _FakeResponse(200, {"ok": True})

    monkeypatch.setattr(guard.httpx, "AsyncClient", _fake_async_client(_get, _post))

    report = await guard.check_all_bridges()

    assert report["naked_total"] == 1
    assert report["protected_total"] == 0
    assert report["bridges"]["legacy"]["naked"][0]["ticket"] == 1
    assert post_calls == []  # LA preuve : aucun appel /position/sltp n'est parti


@pytest.mark.asyncio
async def test_check_all_bridges_protects_when_auto_protect_enabled(monkeypatch):
    monkeypatch.setattr(guard, "_BRIDGES", (("legacy", "http://bridge", "key"),))
    monkeypatch.setattr(guard, "SLTP_GUARD_AUTO_PROTECT_ENABLED", True)
    monkeypatch.setattr(guard, "SLTP_GUARD_EMERGENCY_SL_PCT", 1.0)

    post_calls = []

    def _get(url, headers):
        return _FakeResponse(200, {"positions": [{"ticket": 1, "symbol": "XAUUSD", "sl": 0.0, "price_open": 2650.0}]})

    def _post(url, json, headers):
        post_calls.append((url, json))
        assert url.endswith("/position/sltp")
        assert json["ticket"] == 1
        assert json["sl_dist"] == pytest.approx(2650.0 * 0.01)
        return _FakeResponse(200, {"ok": True, "sl": 2623.5})

    monkeypatch.setattr(guard.httpx, "AsyncClient", _fake_async_client(_get, _post))

    report = await guard.check_all_bridges()

    assert report["naked_total"] == 1
    assert report["protected_total"] == 1
    assert len(post_calls) == 1


@pytest.mark.asyncio
async def test_check_all_bridges_reports_but_does_not_double_count_protect_failure(monkeypatch):
    monkeypatch.setattr(guard, "_BRIDGES", (("legacy", "http://bridge", "key"),))
    monkeypatch.setattr(guard, "SLTP_GUARD_AUTO_PROTECT_ENABLED", True)
    monkeypatch.setattr(guard, "SLTP_GUARD_EMERGENCY_SL_PCT", 1.0)

    def _get(url, headers):
        return _FakeResponse(200, {"positions": [{"ticket": 1, "symbol": "XAUUSD", "sl": 0.0, "price_open": 2650.0}]})

    def _post(url, json, headers):
        # Le bridge refuse (ex: position exclue par son propre garde-fou).
        return _FakeResponse(403, {"ok": False, "excluded": True, "reason": "ticket gelé"})

    monkeypatch.setattr(guard.httpx, "AsyncClient", _fake_async_client(_get, _post))

    report = await guard.check_all_bridges()

    assert report["naked_total"] == 1
    assert report["protected_total"] == 0
    assert report["bridges"]["legacy"]["protect_results"][0]["ok"] is False


@pytest.mark.asyncio
async def test_check_all_bridges_unreachable_bridge_does_not_crash_scan(monkeypatch):
    monkeypatch.setattr(guard, "_BRIDGES", (("legacy", "http://bridge", "key"),))

    def _get(url, headers):
        raise ConnectionError("bridge down")

    monkeypatch.setattr(guard.httpx, "AsyncClient", _fake_async_client(_get))

    report = await guard.check_all_bridges()
    assert report["bridges"]["legacy"]["reachable"] is False
    assert report["naked_total"] == 0
