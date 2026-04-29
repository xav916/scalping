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


# ─── Phase MQL.E — mode EA + génération api_key ──────────────────────


def _create_user_ea_only(email: str = "ea@test.com") -> int:
    """User Premium avec un api_key généré (mode EA, pas de bridge_url legacy)."""
    uid = users_service.create_user(email, "password123")
    api_key = users_service.generate_api_key_for_user(uid)
    with users_service._conn() as c:
        c.execute(
            "UPDATE users SET tier='premium', stripe_subscription_id='sub_x' WHERE id=?",
            (uid,),
        )
    return uid


@pytest.mark.asyncio
async def test_get_broker_mode_none_when_nothing_set(db):
    uid = users_service.create_user("blank@test.com", "password123")
    result = await app_module.api_user_broker_get(ctx=_ctx(uid))
    assert result["mode"] == "none"
    assert result["api_key_set"] is False
    assert result["last_ea_heartbeat"] is None


@pytest.mark.asyncio
async def test_get_broker_mode_ea_when_only_api_key(db):
    uid = _create_user_ea_only()
    result = await app_module.api_user_broker_get(ctx=_ctx(uid))
    assert result["mode"] == "ea"
    assert result["api_key_set"] is True
    assert result["bridge_url"] == ""


@pytest.mark.asyncio
async def test_get_broker_mode_bridge_when_url_and_key(db):
    uid = _create_user_with_bridge()
    result = await app_module.api_user_broker_get(ctx=_ctx(uid))
    assert result["mode"] == "bridge"
    assert result["bridge_url"] == "http://user-bridge:8787"


@pytest.mark.asyncio
async def test_get_broker_includes_last_ea_heartbeat(db):
    uid = _create_user_ea_only()
    users_service.update_ea_heartbeat(uid)
    result = await app_module.api_user_broker_get(ctx=_ctx(uid))
    assert result["last_ea_heartbeat"] is not None
    assert "T" in result["last_ea_heartbeat"]  # ISO format avec T


@pytest.mark.asyncio
async def test_generate_api_key_returns_value_and_persists(db):
    uid = users_service.create_user("gen@test.com", "password123")
    with users_service._conn() as c:
        c.execute(
            "UPDATE users SET tier='premium', stripe_subscription_id='sub_x' WHERE id=?",
            (uid,),
        )

    result = await app_module.api_user_broker_generate_api_key(ctx=_ctx(uid))
    assert result["api_key_set"] is True
    assert len(result["api_key"]) >= 16
    cfg = users_service.get_broker_config(uid)
    assert cfg["bridge_api_key"] == result["api_key"]


@pytest.mark.asyncio
async def test_generate_api_key_overwrites_existing(db):
    uid = _create_user_ea_only()
    cfg_before = users_service.get_broker_config(uid)
    old_key = cfg_before["bridge_api_key"]

    result = await app_module.api_user_broker_generate_api_key(ctx=_ctx(uid))
    assert result["api_key"] != old_key

    cfg_after = users_service.get_broker_config(uid)
    assert cfg_after["bridge_api_key"] == result["api_key"]
    assert cfg_after["bridge_api_key"] != old_key


@pytest.mark.asyncio
async def test_generate_api_key_preserves_auto_exec_flag(db):
    """Régen ne doit PAS clear auto_exec_enabled — sinon UX cassée."""
    uid = _create_user_ea_only()
    users_service.update_auto_exec_enabled(uid, True)
    await app_module.api_user_broker_generate_api_key(ctx=_ctx(uid))
    cfg = users_service.get_broker_config(uid)
    assert cfg["auto_exec_enabled"] is True


@pytest.mark.asyncio
async def test_enable_auto_exec_with_api_key_only_succeeds(db):
    """Mode EA : api_key seul (pas de bridge_url) suffit pour activer."""
    uid = _create_user_ea_only()
    result = await app_module.api_user_broker_auto_exec(
        payload={"enabled": True, "demo_confirmed": True},
        ctx=_ctx(uid),
    )
    assert result["auto_exec_enabled"] is True


@pytest.mark.asyncio
async def test_enable_without_api_key_still_blocked(db):
    """User sans aucune config → 400, message mentionne api_key."""
    uid = users_service.create_user("noconfig@test.com", "password123")
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await app_module.api_user_broker_auto_exec(
            payload={"enabled": True, "demo_confirmed": True},
            ctx=_ctx(uid),
        )
    assert exc.value.status_code == 400
    assert "api_key" in exc.value.detail
