"""Tests pour le cache_backend abstraction (chantier #27 Tier 5)."""
from __future__ import annotations

import time

from backend.services import cache_backend


def test_memory_cache_set_get():
    cache = cache_backend._MemoryCache("test_ns_1")
    cache.set("k", {"v": 42})
    assert cache.get("k") == {"v": 42}


def test_memory_cache_ttl_expires():
    cache = cache_backend._MemoryCache("test_ns_2")
    cache.set("k", "v", ttl_sec=0.01)
    assert cache.get("k") == "v"
    time.sleep(0.05)
    assert cache.get("k") is None


def test_memory_cache_no_ttl_persists():
    cache = cache_backend._MemoryCache("test_ns_3")
    cache.set("k", 1)
    time.sleep(0.01)
    assert cache.get("k") == 1


def test_memory_cache_delete():
    cache = cache_backend._MemoryCache("test_ns_4")
    cache.set("k", 1)
    cache.delete("k")
    assert cache.get("k") is None
    cache.delete("ghost")  # no-op, doesn't raise


def test_memory_cache_clear_and_size():
    cache = cache_backend._MemoryCache("test_ns_5")
    cache.set("a", 1)
    cache.set("b", 2)
    assert cache.size() == 2
    cache.clear()
    assert cache.size() == 0


def test_get_cache_singleton_per_namespace():
    cache_backend._instances.clear()
    c1 = cache_backend.get_cache("alpha")
    c2 = cache_backend.get_cache("alpha")
    c3 = cache_backend.get_cache("beta")
    assert c1 is c2
    assert c1 is not c3


def test_get_cache_redis_unavailable_falls_back_to_memory(monkeypatch):
    cache_backend._instances.clear()
    monkeypatch.setattr(cache_backend, "CACHE_BACKEND", "redis")

    class BrokenRedis:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("redis ping refused")

    def broken_init(self, ns):
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(cache_backend._RedisCache, "__init__", broken_init)
    cache = cache_backend.get_cache("redis_test")
    assert isinstance(cache, cache_backend._MemoryCache)


def test_get_status_reflects_state():
    cache_backend._instances.clear()
    monkeypatch_backend = cache_backend.CACHE_BACKEND
    cache_backend.get_cache("status_test").set("k", 1)
    s = cache_backend.get_status()
    assert "backend" in s
    assert "status_test" in s["namespaces"]
    assert s["namespaces"]["status_test"] == 1
