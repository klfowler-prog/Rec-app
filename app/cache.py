"""Simple in-memory cache with TTL for expensive AI/API results.

Recommendations are cached with long TTLs (24h) and only refreshed when:
1. The user explicitly clicks "Refresh recommendations"
2. The cache has expired AND the profile changed since last generation
3. No cached results exist yet (first time)
"""

import threading
import time
from typing import Any

MAX_CACHE_SIZE = 500

_cache: dict[str, tuple[float, Any]] = {}
_profile_changed_at: float = 0.0
_recs_generated_at: float = 0.0
# Per-user rolling log of recently-recommended titles (lowercased). Used
# to diversify related_items so the AI can't keep serving the same
# prestige-TV fallbacks (Fleabag, Succession, The Bear…) across every
# detail page a user opens.
_recent_recs: dict[int, list[str]] = {}
_RECENT_RECS_MAX = 60
_lock = threading.Lock()


def _cleanup_expired() -> None:
    """Remove expired entries to prevent unbounded growth."""
    if len(_cache) < MAX_CACHE_SIZE:
        return
    now = time.time()
    expired = [k for k, (exp, _) in _cache.items() if exp < now]
    for k in expired:
        _cache.pop(k, None)
    # If still too large, remove oldest entries
    if len(_cache) >= MAX_CACHE_SIZE:
        sorted_keys = sorted(_cache.items(), key=lambda x: x[1][0])
        for k, _ in sorted_keys[: len(_cache) - MAX_CACHE_SIZE + 50]:
            _cache.pop(k, None)


def get(key: str) -> Any | None:
    """Get a cached value if it exists and hasn't expired."""
    with _lock:
        if key in _cache:
            expires_at, value = _cache[key]
            if time.time() < expires_at:
                return value
            # Expired — but only regenerate if profile changed since last generation
            if (
                key.startswith("top_picks")
                or key.startswith("suggestions_home")
                or key.startswith("home_bundle")
                or key.startswith("related_items")
            ):
                if _profile_changed_at <= _recs_generated_at:
                    _cache[key] = (time.time() + 86400, value)
                    return value
            _cache.pop(key, None)
        return None


def set(key: str, value: Any, ttl_seconds: int = 86400) -> None:
    """Cache a value. Default TTL is 24 hours."""
    global _recs_generated_at
    with _lock:
        _cleanup_expired()
        _cache[key] = (time.time() + ttl_seconds, value)
        if (
            key.startswith("top_picks")
            or key.startswith("suggestions_home")
            or key.startswith("home_bundle")
            or key.startswith("related_items")
        ):
            _recs_generated_at = time.time()


def mark_profile_changed() -> None:
    """Record that the profile was modified. Does NOT bust the cache."""
    global _profile_changed_at
    with _lock:
        _profile_changed_at = time.time()


def force_refresh() -> None:
    """Explicitly clear recommendation caches. Called by user action only."""
    with _lock:
        prefixes = ("top_picks", "suggestions_home", "home_bundle", "related_items", "insights")
        keys_to_delete = [k for k in _cache if any(k.startswith(p) for p in prefixes)]
        for k in keys_to_delete:
            _cache.pop(k, None)


def invalidate(prefix: str = "") -> None:
    """Invalidate all cache entries matching a prefix, or all if empty."""
    with _lock:
        if not prefix:
            _cache.clear()
            return
        keys_to_delete = [k for k in _cache if k.startswith(prefix)]
        for k in keys_to_delete:
            _cache.pop(k, None)


def get_recent_recs(user_id: int) -> list[str]:
    """Return the list of titles recently surfaced to this user (lowercased).
    Used to diversify subsequent recommendations — the caller passes these
    to the AI as an avoid list and post-filters the response."""
    with _lock:
        return list(_recent_recs.get(user_id, []))


def add_recent_recs(user_id: int, titles: list[str]) -> None:
    """Append freshly-recommended titles to the user's rolling log.
    Caps at _RECENT_RECS_MAX; oldest entries fall off first."""
    if not titles:
        return
    with _lock:
        bucket = _recent_recs.setdefault(user_id, [])
        seen = set(bucket)
        for t in titles:
            key = (t or "").lower().strip()
            if not key or key in seen:
                continue
            bucket.append(key)
            seen.add(key)
        # Keep only the most recent N
        if len(bucket) > _RECENT_RECS_MAX:
            del bucket[: len(bucket) - _RECENT_RECS_MAX]
