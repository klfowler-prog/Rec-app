"""Simple in-memory cache with TTL for expensive AI/API results."""

import time
from typing import Any

_cache: dict[str, tuple[float, Any]] = {}


def get(key: str) -> Any | None:
    """Get a cached value if it exists and hasn't expired."""
    if key in _cache:
        expires_at, value = _cache[key]
        if time.time() < expires_at:
            return value
        del _cache[key]
    return None


def set(key: str, value: Any, ttl_seconds: int = 3600) -> None:
    """Cache a value with a TTL in seconds."""
    _cache[key] = (time.time() + ttl_seconds, value)


def invalidate(prefix: str = "") -> None:
    """Invalidate all cache entries matching a prefix, or all if empty."""
    if not prefix:
        _cache.clear()
        return
    keys_to_delete = [k for k in _cache if k.startswith(prefix)]
    for k in keys_to_delete:
        del _cache[k]
