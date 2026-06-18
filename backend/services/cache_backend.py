"""Cache backend abstraction — in-memory (default) ou Redis (multi-instance).

Chantier #27 Tier 5 (2026-06-18) — préparation au scaling horizontal.

Les modules Binance scoring (funding/LSR/orderbook/orderflow/OI/MTF) ont
chacun un cache module-global qui fonctionne tant qu'on tourne sur une
seule instance scalping-radar. Pour multi-instance (load balancing, blue
green deploy), un cache partagé évite N×fetches Binance et baisse le
risque de rate-limit.

Cette abstraction expose un get/set/delete uniforme avec TTL.
- CACHE_BACKEND=memory (default) : dict in-process, comportement actuel
- CACHE_BACKEND=redis : Redis externe, key-value avec TTL natif

Si CACHE_BACKEND=redis mais Redis injoignable au boot ou en runtime,
on dégrade silencieusement vers memory (logged warning). Le système
ne tombe jamais à cause du cache.

Usage :
    from backend.services.cache_backend import get_cache
    cache = get_cache("funding")  # namespace pour éviter collisions
    cache.set("BTCUSDT", {"rate": 0.0001}, ttl_sec=1800)
    val = cache.get("BTCUSDT")  # None si miss ou expired
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

CACHE_BACKEND = os.getenv("CACHE_BACKEND", "memory").strip().lower()
REDIS_URL = os.getenv("CACHE_REDIS_URL", "redis://localhost:6379/0")


class _MemoryCache:
    """In-process cache : dict avec TTL. Thread-safe via lock."""

    def __init__(self, namespace: str) -> None:
        self._ns = namespace
        self._store: dict[str, tuple[Any, float]] = {}  # key → (value, expires_at)
        self._lock = threading.Lock()

    def get(self, key: str) -> Any:
        with self._lock:
            row = self._store.get(key)
            if row is None:
                return None
            value, expires_at = row
            if expires_at and time.time() >= expires_at:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: Any, ttl_sec: float | None = None) -> None:
        expires_at = (time.time() + ttl_sec) if ttl_sec else 0.0
        with self._lock:
            self._store[key] = (value, expires_at)

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._store)


class _RedisCache:
    """Cache Redis avec sérialisation JSON et TTL natif.

    Si import redis fail ou ping fail au constructeur, raise RuntimeError
    pour que le factory dégrade vers _MemoryCache.
    """

    def __init__(self, namespace: str) -> None:
        try:
            import redis  # noqa: F401
        except ImportError as e:
            raise RuntimeError(f"redis package not installed: {e}")
        import redis as redis_mod
        self._ns = namespace
        self._client = redis_mod.Redis.from_url(REDIS_URL, decode_responses=True)
        # Ping pour valider connection (raise sinon)
        self._client.ping()

    def _full_key(self, key: str) -> str:
        return f"cache:{self._ns}:{key}"

    def get(self, key: str) -> Any:
        try:
            raw = self._client.get(self._full_key(key))
            return json.loads(raw) if raw else None
        except Exception as e:
            logger.debug(f"redis get {self._ns}:{key}: {e}")
            return None

    def set(self, key: str, value: Any, ttl_sec: float | None = None) -> None:
        try:
            raw = json.dumps(value, default=str)
            if ttl_sec and ttl_sec > 0:
                self._client.setex(self._full_key(key), int(ttl_sec), raw)
            else:
                self._client.set(self._full_key(key), raw)
        except Exception as e:
            logger.debug(f"redis set {self._ns}:{key}: {e}")

    def delete(self, key: str) -> None:
        try:
            self._client.delete(self._full_key(key))
        except Exception:
            pass

    def clear(self) -> None:
        try:
            keys = self._client.keys(f"cache:{self._ns}:*")
            if keys:
                self._client.delete(*keys)
        except Exception:
            pass

    def size(self) -> int:
        try:
            return len(self._client.keys(f"cache:{self._ns}:*"))
        except Exception:
            return 0


_instances: dict[str, _MemoryCache | _RedisCache] = {}
_factory_lock = threading.Lock()


def get_cache(namespace: str) -> _MemoryCache | _RedisCache:
    """Retourne le cache du namespace donné. Singleton par namespace.

    Si CACHE_BACKEND=redis échoue (lib absente, ping fail), fallback
    vers _MemoryCache + warning log unique. Le caller n'a pas besoin
    de gérer l'erreur.
    """
    with _factory_lock:
        if namespace in _instances:
            return _instances[namespace]
        if CACHE_BACKEND == "redis":
            try:
                instance = _RedisCache(namespace)
                logger.info(f"cache[{namespace}] redis backend OK url={REDIS_URL}")
            except Exception as e:
                logger.warning(
                    f"cache[{namespace}] redis init failed ({e}) — fallback memory"
                )
                instance = _MemoryCache(namespace)
        else:
            instance = _MemoryCache(namespace)
        _instances[namespace] = instance
        return instance


def get_status() -> dict[str, Any]:
    """Snapshot lisible pour cockpit / debug."""
    return {
        "backend": CACHE_BACKEND,
        "redis_url": REDIS_URL if CACHE_BACKEND == "redis" else None,
        "namespaces": {ns: c.size() for ns, c in _instances.items()},
        "instance_types": {ns: type(c).__name__ for ns, c in _instances.items()},
    }
