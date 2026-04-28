"""Tests Phase D.1 — endpoints `/api/user/broker` étendus pour auto-exec.

Vérifie :
- ``GET /api/user/broker`` expose ``auto_exec_enabled``
- ``POST /api/user/broker/auto-exec`` :
  - exige ``demo_confirmed`` pour passer à ``True``
  - exige un ``bridge_url + api_key`` configurés avant activation
  - permet la désactivation sans confirmation
  - rejette les users legacy env (``user_id is None``)

Les handlers sont appelés directement (pas TestClient) — pattern utilisé
dans les autres tests endpoint du repo.
"""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from backend import app as app_module
from backend.auth import AuthContext
from backend.services import users_service


@pytest.fixture
def db(tmp_path: Path):
    db_file = tmp_path / "trades.db"
    with patch.object(users_service, "_DB_PATH", db_file):
        users_service.init_users_schema()
        yield db_file


def _ctx(user_id: int | None) -> AuthContext:
    return AuthContext(username=f"user_{user_id}", user_id=user_id)


def _create_user_with_bridge(email: str = "alice@test.com") -> int:
    uid = users_service.create_user(email, "password123")
    users_service.update_broker_config(
        uid,
        bridge_url="http://user-bridge:8787",
        bridge_api_key="u" * 32,
    )
    return uid


# ─── GET /api/user/broker ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_broker_includes_auto_exec_default_false(db):
    uid = _create_user_with_bridge()
    result = await app_module.api_user_broker_get(ctx=_ctx(uid))
    assert result["auto_exec_enabled"] is False
    assert result["bridge_url"] == "http://user-bridge:8787"
    assert result["api_key_set"] is True


@pytest.mark.asyncio
async def test_get_broker_includes_auto_exec_true_when_enabled(db):
    uid = _create_user_with_bridge()
    users_service.update_auto_exec_enabled(uid, True)
    result = await app_module.api_user_broker_get(ctx=_ctx(uid))
    assert result["auto_exec_enabled"] is True


# ─── POST /api/user/broker/auto-exec — activation ────────────────────


@pytest.mark.asyncio
async def test_enable_requires_demo_confirmed(db):
    uid = _create_user_with_bridge()
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await app_module.api_user_broker_auto_exec(
            payload={"enabled": True},  # manque demo_confirmed
            ctx=_ctx(uid),
        )
    assert exc.value.status_code == 400
    assert "demo_confirmed" in exc.value.detail.lower()
    # Toggle non muté
    cfg = users_service.get_broker_config(uid)
    assert cfg.get("auto_exec_enabled") in (None, False)


@pytest.mark.asyncio
async def test_enable_requires_bridge_configured(db):
    """User sans bridge → 400, pas de toggle."""
    uid = users_service.create_user("alice@test.com", "password123")
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await app_module.api_user_broker_auto_exec(
            payload={"enabled": True, "demo_confirmed": True},
            ctx=_ctx(uid),
        )
    assert exc.value.status_code == 400
    assert "bridge_url" in exc.value.detail or "api_key" in exc.value.detail


@pytest.mark.asyncio
async def test_enable_with_demo_confirmed_and_bridge_succeeds(db):
    uid = _create_user_with_bridge()
    result = await app_module.api_user_broker_auto_exec(
        payload={"enabled": True, "demo_confirmed": True},
        ctx=_ctx(uid),
    )
    assert result["auto_exec_enabled"] is True
    cfg = users_service.get_broker_config(uid)
    assert cfg["auto_exec_enabled"] is True


# ─── POST /api/user/broker/auto-exec — désactivation ─────────────────


@pytest.mark.asyncio
async def test_disable_does_not_require_confirmation(db):
    uid = _create_user_with_bridge()
    users_service.update_auto_exec_enabled(uid, True)
    result = await app_module.api_user_broker_auto_exec(
        payload={"enabled": False},
        ctx=_ctx(uid),
    )
    assert result["auto_exec_enabled"] is False
    cfg = users_service.get_broker_config(uid)
    assert cfg["auto_exec_enabled"] is False


@pytest.mark.asyncio
async def test_disable_works_even_without_bridge(db):
    """User sans bridge peut quand même clear le toggle (idempotent safe)."""
    uid = users_service.create_user("alice@test.com", "password123")
    result = await app_module.api_user_broker_auto_exec(
        payload={"enabled": False},
        ctx=_ctx(uid),
    )
    assert result["auto_exec_enabled"] is False


# ─── legacy env user (user_id=None) ──────────────────────────────────


@pytest.mark.asyncio
async def test_legacy_user_rejected_on_get(db):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await app_module.api_user_broker_get(ctx=_ctx(None))
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_legacy_user_rejected_on_toggle(db):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await app_module.api_user_broker_auto_exec(
            payload={"enabled": False},
            ctx=_ctx(None),
        )
    assert exc.value.status_code == 400
