"""Simple in-memory cache with TTL for expensive AI/API results.

Recommendations are cached with long TTLs (24h) and only refreshed when:
1. The user explicitly clicks "Refresh recommendations"
2. The cache has expired AND the profile changed since last generation
3. No cached results exist yet (first time)
"""

import time
from typing import Any

_cache: dict[str, tuple[float, Any]] = {}
_profile_changed_at: float = 0.0
_recs_generated_at: float = 0.0


def get(key: str) -> Any | None:
    """Get a cached value if it exists and hasn't expired."""
    if key in _cache:
        expires_at, value = _cache[key]
        if time.time() < expires_at:
            return value
        # Expired — but only regenerate if profile changed since last generation
        if key in ("top_picks", "suggestions_home") and _profile_changed_at <= _recs_generated_at:
            # Profile hasn't changed, extend the cache another 24h
            _cache[key] = (time.time() + 86400, value)
            return value
        del _cache[key]
    return None


def set(key: str, value: Any, ttl_seconds: int = 86400) -> None:
    """Cache a value. Default TTL is 24 hours."""
    global _recs_generated_at
    _cache[key] = (time.time() + ttl_seconds, value)
    if key in ("top_picks", "suggestions_home"):
        _recs_generated_at = time.time()


def mark_profile_changed() -> None:
    """Record that the profile was modified. Does NOT bust the cache."""
    global _profile_changed_at
    _profile_changed_at = time.time()


def force_refresh() -> None:
    """Explicitly clear recommendation caches. Called by user action only."""
    for key in ("top_picks", "suggestions_home"):
        _cache.pop(key, None)


def invalidate(prefix: str = "") -> None:
    """Invalidate all cache entries matching a prefix, or all if empty."""
    if not prefix:
        _cache.clear()
        return
    keys_to_delete = [k for k in _cache if k.startswith(prefix)]
    for k in keys_to_delete:
        del _cache[k]
