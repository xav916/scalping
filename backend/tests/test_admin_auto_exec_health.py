"""Tests pour l'endpoint /api/admin/auto-exec/health.

Couvre les cas : aucun user auto-exec, user LIVE avec orders mixed
(EXECUTED/FAILED/EXPIRED), heartbeat OFFLINE, détection zombies SENT > 5min.
"""
import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.services import users_service, mt5_pending_orders_service as svc
from backend.services import trade_log_service


@pytest.fixture
def db(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "trades.db"
    # Seed minimal — la table personal_trades existe avant init users_schema
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE personal_trades (id INTEGER PRIMARY KEY, user TEXT)")
    conn.commit()
    conn.close()
    # Patcher les deux services qui pointent sur le même fichier
    monkeypatch.setattr(users_service, "_DB_PATH", db_file)
    monkeypatch.setattr(trade_log_service, "_DB_PATH", db_file)
    users_service.init_users_schema()
    svc._ensure_schema()
    return db_file


def _admin_ctx(monkeypatch):
    from backend import app as app_module
    from backend.auth import AuthContext

    monkeypatch.setattr(app_module, "ADMIN_EMAILS", [])
    return AuthContext(username="legacy-admin", user_id=None)


def _set_broker_config(user_id: int, *, auto_exec: bool, heartbeat_age_sec: int | None):
    """Helper : écrit broker_config avec un heartbeat à un âge donné."""
    cfg: dict = {"bridge_api_key": f"key_{user_id}", "auto_exec_enabled": auto_exec}
    if heartbeat_age_sec is not None:
        hb = datetime.now(timezone.utc) - timedelta(seconds=heartbeat_age_sec)
        cfg["last_ea_heartbeat"] = hb.isoformat()
    with sqlite3.connect(users_service._DB_PATH) as c:
        c.execute(
            "UPDATE users SET broker_config = ? WHERE id = ?",
            (json.dumps(cfg), user_id),
        )


def _payload(pair="XAU/USD", direction="buy"):
    return {"pair": pair, "direction": direction, "entry": 1.0, "sl": 0.9, "tp": 1.1}


def test_health_empty_when_no_auto_exec_user(db, monkeypatch):
    """Aucun user n'a auto_exec_enabled → totals à 0, users vide."""
    from backend import app as app_module

    uid = users_service.create_user("u1@test.com", "pw12345678", tier="premium")
    _set_broker_config(uid, auto_exec=False, heartbeat_age_sec=60)

    ctx = _admin_ctx(monkeypatch)
    result = asyncio.run(app_module.api_admin_auto_exec_health(_ctx=ctx))

    assert result["users"] == []
    assert result["totals"]["users_with_auto_exec"] == 0
    assert result["totals"]["orders_24h"] == 0
    assert result["totals"]["executed_rate_24h"] is None
    assert "thresholds" in result


def test_health_classifies_heartbeat_status(db, monkeypatch):
    """Heartbeat <5min = LIVE, 5-30min = STALE, >30min = OFFLINE."""
    from backend import app as app_module

    uid_live = users_service.create_user("live@test.com", "pw12345678", tier="premium")
    _set_broker_config(uid_live, auto_exec=True, heartbeat_age_sec=60)
    uid_stale = users_service.create_user("stale@test.com", "pw12345678", tier="premium")
    _set_broker_config(uid_stale, auto_exec=True, heartbeat_age_sec=600)
    uid_offline = users_service.create_user("offline@test.com", "pw12345678", tier="premium")
    _set_broker_config(uid_offline, auto_exec=True, heartbeat_age_sec=3600)
    uid_never = users_service.create_user("never@test.com", "pw12345678", tier="premium")
    _set_broker_config(uid_never, auto_exec=True, heartbeat_age_sec=None)

    ctx = _admin_ctx(monkeypatch)
    result = asyncio.run(app_module.api_admin_auto_exec_health(_ctx=ctx))

    by_email = {u["email"]: u["heartbeat"]["status"] for u in result["users"]}
    assert by_email["live@test.com"] == "LIVE"
    assert by_email["stale@test.com"] == "STALE"
    assert by_email["offline@test.com"] == "OFFLINE"
    assert by_email["never@test.com"] == "OFFLINE"

    t = result["totals"]
    assert t["users_with_auto_exec"] == 4
    assert t["users_live"] == 1
    assert t["users_stale"] == 1
    assert t["users_offline"] == 2


def test_health_orders_breakdown_and_executed_rate(db, monkeypatch):
    """3 EXECUTED + 1 FAILED + 1 EXPIRED → executed_rate = 0.6 (3/5)."""
    from backend import app as app_module

    uid = users_service.create_user("u@test.com", "pw12345678", tier="premium")
    _set_broker_config(uid, auto_exec=True, heartbeat_age_sec=60)
    api_key = f"key_{uid}"

    # 3 EXECUTED, 1 FAILED, 1 EXPIRED, 1 PENDING (le PENDING ne compte pas dans rate)
    for _ in range(3):
        oid = svc.enqueue(uid, api_key, _payload())
        svc.fetch_for_api_key(api_key)
        svc.record_result(oid, api_key, ok=True, mt5_ticket=12345)
    oid_fail = svc.enqueue(uid, api_key, _payload())
    svc.fetch_for_api_key(api_key)
    svc.record_result(oid_fail, api_key, ok=False, error="rejected")
    # EXPIRED : on simule en mettant un TTL court puis purge
    svc.enqueue(uid, api_key, _payload(), ttl_seconds=1)
    import time
    time.sleep(1.1)
    svc.purge_expired()
    # PENDING toujours valide
    svc.enqueue(uid, api_key, _payload())

    ctx = _admin_ctx(monkeypatch)
    result = asyncio.run(app_module.api_admin_auto_exec_health(_ctx=ctx))

    user = result["users"][0]
    bs = user["orders_24h"]["by_status"]
    assert bs.get("EXECUTED") == 3
    assert bs.get("FAILED") == 1
    assert bs.get("EXPIRED") == 1
    assert bs.get("PENDING") == 1
    # executed_rate = EXECUTED / (EXECUTED + FAILED + EXPIRED) = 3/5 = 0.6
    assert abs(user["orders_24h"]["executed_rate"] - 0.6) < 0.01


def test_health_detects_sent_zombie(db, monkeypatch):
    """Un ordre SENT depuis > 5min est compté comme zombie."""
    from backend import app as app_module

    uid = users_service.create_user("u@test.com", "pw12345678", tier="premium")
    _set_broker_config(uid, auto_exec=True, heartbeat_age_sec=60)
    api_key = f"key_{uid}"

    oid = svc.enqueue(uid, api_key, _payload())
    svc.fetch_for_api_key(api_key)  # marque SENT
    # Backdate fetched_at à 10 min ago pour simuler zombie
    old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    with sqlite3.connect(db) as c:
        c.execute("UPDATE mt5_pending_orders SET fetched_at = ? WHERE id = ?", (old, oid))

    ctx = _admin_ctx(monkeypatch)
    result = asyncio.run(app_module.api_admin_auto_exec_health(_ctx=ctx))

    user = result["users"][0]
    assert user["zombies"]["sent_stale"] == 1
    assert user["zombies"]["total"] == 1
    assert result["totals"]["zombies_total"] == 1


def test_health_last_order_preview(db, monkeypatch):
    """last_order doit refléter l'ordre le plus récent avec pair, direction, status."""
    from backend import app as app_module

    uid = users_service.create_user("u@test.com", "pw12345678", tier="premium")
    _set_broker_config(uid, auto_exec=True, heartbeat_age_sec=60)
    api_key = f"key_{uid}"
    svc.enqueue(uid, api_key, _payload(pair="EUR/USD", direction="buy"))
    # Le plus récent (insertion la plus récente)
    oid_last = svc.enqueue(uid, api_key, _payload(pair="XAU/USD", direction="sell"))

    ctx = _admin_ctx(monkeypatch)
    result = asyncio.run(app_module.api_admin_auto_exec_health(_ctx=ctx))

    last = result["users"][0]["last_order"]
    assert last is not None
    assert last["id"] == oid_last
    assert last["pair"] == "XAU/USD"
    assert last["direction"] == "sell"
    assert last["status"] == "PENDING"
