"""Two-tier cache: fast in-memory dict + persistent DB fallback.

The in-memory tier is identical to the previous implementation — fast,
thread-safe, no I/O. The DB tier (CacheEntry table) catches misses
after a deploy or instance restart so expensive AI results don't need
to be recomputed. Writes go to both tiers; reads check memory first,
then DB, then return None.
"""

import json
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Any

log = logging.getLogger(__name__)

MAX_CACHE_SIZE = 500

_cache: dict[str, tuple[float, Any]] = {}
_profile_changed_at: float = 0.0
_recs_generated_at: float = 0.0
_recent_recs: dict[int, list[str]] = {}
_RECENT_RECS_MAX = 60
_lock = threading.Lock()

# Prefixes that get smart re-use (don't regenerate if profile unchanged)
_SMART_PREFIXES = ("top_picks", "suggestions_home", "home_bundle", "related_items")


def _cleanup_expired() -> None:
    if len(_cache) < MAX_CACHE_SIZE:
        return
    now = time.time()
    expired = [k for k, (exp, _) in _cache.items() if exp < now]
    for k in expired:
        _cache.pop(k, None)
    if len(_cache) >= MAX_CACHE_SIZE:
        sorted_keys = sorted(_cache.items(), key=lambda x: x[1][0])
        for k, _ in sorted_keys[: len(_cache) - MAX_CACHE_SIZE + 50]:
            _cache.pop(k, None)


def _db_get(key: str) -> Any | None:
    """Try to read from the persistent DB cache."""
    try:
        from app.database import SessionLocal
        from app.models import CacheEntry
        db = SessionLocal()
        try:
            entry = db.query(CacheEntry).filter(CacheEntry.key == key).first()
            if entry and entry.expires_at > datetime.utcnow():
                value = json.loads(entry.value)
                # Warm the in-memory cache so subsequent reads are fast
                with _lock:
                    _cache[key] = (entry.expires_at.timestamp(), value)
                return value
            elif entry:
                db.delete(entry)
                db.commit()
        finally:
            db.close()
    except Exception as e:
        log.debug("DB cache read failed for %s: %s", key, e)
    return None


def _db_set(key: str, value: Any, ttl_seconds: int) -> None:
    """Persist to the DB cache. Fire-and-forget — failures don't break the caller."""
    try:
        from app.database import SessionLocal
        from app.models import CacheEntry
        db = SessionLocal()
        try:
            expires = datetime.utcnow() + timedelta(seconds=ttl_seconds)
            entry = db.query(CacheEntry).filter(CacheEntry.key == key).first()
            serialized = json.dumps(value, default=str)
            if entry:
                entry.value = serialized
                entry.expires_at = expires
            else:
                db.add(CacheEntry(key=key, value=serialized, expires_at=expires))
            db.commit()
        finally:
            db.close()
    except Exception as e:
        log.debug("DB cache write failed for %s: %s", key, e)


def _db_invalidate(prefix: str) -> None:
    """Remove DB cache entries by prefix."""
    try:
        from app.database import SessionLocal
        from app.models import CacheEntry
        db = SessionLocal()
        try:
            if not prefix:
                db.query(CacheEntry).delete()
            else:
                db.query(CacheEntry).filter(CacheEntry.key.startswith(prefix)).delete()
            db.commit()
        finally:
            db.close()
    except Exception as e:
        log.debug("DB cache invalidate failed: %s", e)


def get(key: str) -> Any | None:
    """Get a cached value. Checks in-memory first, then DB."""
    with _lock:
        if key in _cache:
            expires_at, value = _cache[key]
            if time.time() < expires_at:
                return value
            if any(key.startswith(p) for p in _SMART_PREFIXES):
                if _profile_changed_at <= _recs_generated_at:
                    _cache[key] = (time.time() + 86400, value)
                    return value
            _cache.pop(key, None)

    # Miss in memory — try DB
    return _db_get(key)


def set(key: str, value: Any, ttl_seconds: int = 86400) -> None:
    """Cache a value in both memory and DB."""
    global _recs_generated_at
    with _lock:
        _cleanup_expired()
        _cache[key] = (time.time() + ttl_seconds, value)
        if any(key.startswith(p) for p in _SMART_PREFIXES):
            _recs_generated_at = time.time()

    # Persist to DB for cross-deploy survival
    _db_set(key, value, ttl_seconds)


def mark_profile_changed() -> None:
    global _profile_changed_at
    with _lock:
        _profile_changed_at = time.time()


def force_refresh() -> None:
    """Clear all recommendation caches (memory + DB)."""
    with _lock:
        # Don't clear new_releases — those are weekly external data that
        # shouldn't regenerate on every rating change
        prefixes = ("top_picks", "suggestions_home", "home_bundle", "related_items", "insights", "best_bet", "taste_dna", "taste_fit", "missing", "new_on_services", "friends_enjoying", "hidden_gems", "tonight_welcome")
        keys_to_delete = [k for k in _cache if any(k.startswith(p) for p in prefixes)]
        for k in keys_to_delete:
            _cache.pop(k, None)
    # Also clear from DB
    for p in ("top_picks", "suggestions_home", "home_bundle", "related_items", "insights", "best_bet", "taste_dna", "taste_fit", "missing", "new_on_services", "friends_enjoying", "hidden_gems", "tonight_welcome"):
        _db_invalidate(p)


def invalidate(prefix: str = "") -> None:
    with _lock:
        if not prefix:
            _cache.clear()
        else:
            keys_to_delete = [k for k in _cache if k.startswith(prefix)]
            for k in keys_to_delete:
                _cache.pop(k, None)
    _db_invalidate(prefix)


def get_predicted_rating(user_id: int, media_type: str, external_id: str) -> float | None:
    """Get the authoritative predicted rating for a user+item."""
    key = f"pr:{user_id}:{media_type}:{external_id}"
    val = get(key)
    return val if isinstance(val, (int, float)) else None


def set_predicted_rating(user_id: int, media_type: str, external_id: str, rating: float) -> None:
    """Store an authoritative predicted rating for a user+item. Long TTL since these are expensive to compute."""
    key = f"pr:{user_id}:{media_type}:{external_id}"
    set(key, rating, ttl_seconds=604800)  # 7 days


def get_recent_recs(user_id: int) -> list[str]:
    with _lock:
        return list(_recent_recs.get(user_id, []))


def add_recent_recs(user_id: int, titles: list[str]) -> None:
    if not titles:
        return
    with _lock:
        bucket = _recent_recs.setdefault(user_id, [])
        seen = {*bucket}
        for t in titles:
            key = (t or "").lower().strip()
            if not key or key in seen:
                continue
            bucket.append(key)
            seen.add(key)
        if len(bucket) > _RECENT_RECS_MAX:
            del bucket[: len(bucket) - _RECENT_RECS_MAX]
