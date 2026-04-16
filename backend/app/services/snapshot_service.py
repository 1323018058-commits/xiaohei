"""Snapshot service — Redis-based stale-while-revalidate cache for Takealot API data.

Replaces the original _cached_takealot_payload() + runtime_state.db approach.

Cache key format: snapshot:{kind}:{store_id}:{params_hash}
Each cached entry stores JSON with:
  - payload: the actual API response data
  - generated_at: ISO timestamp of when data was fetched
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# Default TTLs (seconds)
DEFAULT_TTL = 120          # Fresh threshold
DEFAULT_USABLE = 1800      # Stale-but-usable threshold
DEFAULT_REDIS_EXPIRE = 7200  # Hard Redis expiry (cleanup)


def _cache_key(kind: str, store_id: int, params: dict | None = None) -> str:
    parts = f"{kind}:{store_id}"
    if params:
        h = hashlib.md5(json.dumps(params, sort_keys=True).encode()).hexdigest()[:12]
        parts += f":{h}"
    return f"snapshot:{parts}"


def _refresh_lock_key(kind: str, store_id: int) -> str:
    return f"snapshot_lock:{kind}:{store_id}"


async def get_snapshot(
    redis: aioredis.Redis,
    kind: str,
    store_id: int,
    params: dict | None = None,
) -> dict | None:
    """Load a cached snapshot from Redis. Returns None if not found."""
    key = _cache_key(kind, store_id, params)
    raw = await redis.get(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


async def save_snapshot(
    redis: aioredis.Redis,
    kind: str,
    store_id: int,
    payload: dict,
    params: dict | None = None,
    redis_expire: int = DEFAULT_REDIS_EXPIRE,
) -> None:
    """Save a snapshot to Redis with TTL."""
    key = _cache_key(kind, store_id, params)
    entry = {
        "payload": payload,
        "generated_at": datetime.utcnow().isoformat(),
    }
    await redis.setex(key, redis_expire, json.dumps(entry, default=str))


async def invalidate_snapshot(
    redis: aioredis.Redis,
    kind: str,
    store_id: int,
    params: dict | None = None,
) -> None:
    """Delete a specific snapshot."""
    key = _cache_key(kind, store_id, params)
    await redis.delete(key)


async def invalidate_store_snapshots(redis: aioredis.Redis, store_id: int) -> int:
    """Delete all snapshots for a given store. Returns count of deleted keys."""
    pattern = f"snapshot:*:{store_id}*"
    keys = [key async for key in redis.scan_iter(match=pattern, count=200)]
    if keys:
        await redis.delete(*keys)
    return len(keys)


def snapshot_age(snapshot: dict) -> float:
    """Return age in seconds of a snapshot entry."""
    generated = snapshot.get("generated_at", "")
    if not generated:
        return float("inf")
    try:
        gen_dt = datetime.fromisoformat(generated)
        return (datetime.utcnow() - gen_dt).total_seconds()
    except (ValueError, TypeError):
        return float("inf")


def is_fresh(snapshot: dict, ttl: int = DEFAULT_TTL) -> bool:
    return snapshot_age(snapshot) < ttl


def is_usable(snapshot: dict, usable: int = DEFAULT_USABLE) -> bool:
    return snapshot_age(snapshot) < usable


async def try_acquire_refresh_lock(
    redis: aioredis.Redis, kind: str, store_id: int, ttl: int = 60,
) -> bool:
    """Try to acquire a short-lived lock to prevent concurrent refreshes."""
    lock_key = _refresh_lock_key(kind, store_id)
    acquired = await redis.set(lock_key, "1", ex=ttl, nx=True)
    return bool(acquired)


async def release_refresh_lock(redis: aioredis.Redis, kind: str, store_id: int) -> None:
    lock_key = _refresh_lock_key(kind, store_id)
    await redis.delete(lock_key)


async def get_cached_payload(
    redis: aioredis.Redis,
    kind: str,
    store_id: int,
    params: dict | None = None,
    ttl_seconds: int = DEFAULT_TTL,
    usable_seconds: int = DEFAULT_USABLE,
) -> dict:
    """Three-tier cache read matching the original _cached_takealot_payload pattern.

    Returns a dict with:
      - payload: the data (or None if cold miss)
      - cached: bool
      - snapshot_stale: bool
      - needs_refresh: bool  (caller should trigger background refresh)
      - refreshing: bool     (a refresh lock is already held)
    """
    snapshot = await get_snapshot(redis, kind, store_id, params)

    if snapshot is None:
        return {
            "payload": None,
            "cached": False,
            "snapshot_stale": False,
            "needs_refresh": True,
            "refreshing": False,
        }

    if is_fresh(snapshot, ttl_seconds):
        return {
            "payload": snapshot["payload"],
            "cached": True,
            "snapshot_stale": False,
            "needs_refresh": False,
            "refreshing": False,
        }

    if is_usable(snapshot, usable_seconds):
        lock_key = _refresh_lock_key(kind, store_id)
        already_refreshing = await redis.exists(lock_key) > 0
        return {
            "payload": snapshot["payload"],
            "cached": True,
            "snapshot_stale": True,
            "needs_refresh": not already_refreshing,
            "refreshing": already_refreshing,
        }

    # Expired beyond usable window
    return {
        "payload": snapshot["payload"],
        "cached": True,
        "snapshot_stale": True,
        "needs_refresh": True,
        "refreshing": False,
    }
