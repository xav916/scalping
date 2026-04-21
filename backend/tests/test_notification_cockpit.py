"""Tests pour le broadcast cockpit via WebSocket."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from backend.services import notification_service


class _FakeWS:
    def __init__(self):
        self.sent: list[str] = []

    async def send_text(self, msg: str):
        self.sent.append(msg)


@pytest.fixture(autouse=True)
def _reset_clients():
    notification_service._connected_clients.clear()
    yield
    notification_service._connected_clients.clear()


def test_register_client_stores_user():
    ws = _FakeWS()
    notification_service.register_client(ws, user="alice")
    assert notification_service._connected_clients[ws] == "alice"


def test_register_client_default_user_is_anonymous():
    ws = _FakeWS()
    notification_service.register_client(ws)
    assert notification_service._connected_clients[ws] == "anonymous"


def test_unregister_client_removes_entry():
    ws = _FakeWS()
    notification_service.register_client(ws, user="bob")
    notification_service.unregister_client(ws)
    assert ws not in notification_service._connected_clients


@pytest.mark.asyncio
async def test_broadcast_cockpit_noop_when_no_clients():
    """Pas de clients connectes → no-op, pas de build gaspille."""
    build = AsyncMock()
    with patch(
        "backend.services.cockpit_service.build_cockpit", build
    ):
        await notification_service.broadcast_cockpit()
    build.assert_not_called()


@pytest.mark.asyncio
async def test_broadcast_cockpit_groups_by_user_and_sends_once_per_user():
    """2 clients user alice + 1 client user bob → 2 builds, 3 sends."""
    ws_a1, ws_a2, ws_b = _FakeWS(), _FakeWS(), _FakeWS()
    notification_service.register_client(ws_a1, user="alice")
    notification_service.register_client(ws_a2, user="alice")
    notification_service.register_client(ws_b, user="bob")

    # Snapshot trivial : on se contente de verifier le routage, pas le contenu.
    async def fake_build(user: str):
        return {"user": user, "ping": 1}

    with patch(
        "backend.services.cockpit_service.build_cockpit",
        side_effect=fake_build,
    ) as build:
        await notification_service.broadcast_cockpit()

    # Une seule construction par user unique.
    assert build.await_count == 2
    users_built = {call.kwargs["user"] for call in build.await_args_list}
    assert users_built == {"alice", "bob"}

    # Chaque client a recu exactement 1 message, avec le user correspondant.
    for ws, expected_user in [(ws_a1, "alice"), (ws_a2, "alice"), (ws_b, "bob")]:
        assert len(ws.sent) == 1
        payload = json.loads(ws.sent[0])
        assert payload["type"] == "cockpit"
        assert payload["data"]["user"] == expected_user


@pytest.mark.asyncio
async def test_broadcast_cockpit_drops_disconnected_client():
    """Un client qui leve a send_text est supprime silencieusement."""
    class _BrokenWS(_FakeWS):
        async def send_text(self, msg: str):
            raise RuntimeError("disconnected")

    ws_ok = _FakeWS()
    ws_broken = _BrokenWS()
    notification_service.register_client(ws_ok, user="alice")
    notification_service.register_client(ws_broken, user="alice")

    async def fake_build(user: str):
        return {"user": user}

    with patch(
        "backend.services.cockpit_service.build_cockpit",
        side_effect=fake_build,
    ):
        await notification_service.broadcast_cockpit()

    assert ws_ok in notification_service._connected_clients
    assert ws_broken not in notification_service._connected_clients
