"""Redis-backed sliding window rate limiter for FastAPI."""
from __future__ import annotations

import time
from typing import Optional

import redis.asyncio as aioredis


class RateLimiter:
    """Sliding window rate limiter using Redis sorted sets.

    Works correctly across multiple uvicorn workers and Celery processes.
    """

    def __init__(self, redis: aioredis.Redis):
        self.redis = redis

    async def consume(
        self,
        scope: str,
        actor: str,
        limit: int,
        window_seconds: int,
    ) -> tuple[bool, int]:
        """Try to consume a rate limit token.

        Returns:
            (allowed, retry_after_seconds)
            - allowed=True, retry_after=0: request is allowed
            - allowed=False, retry_after=N: request is denied, retry after N seconds
        """
        key = f"ratelimit:{scope}:{actor}"
        now = time.time()
        cutoff = now - window_seconds

        pipe = self.redis.pipeline(transaction=True)
        # Remove expired entries
        pipe.zremrangebyscore(key, 0, cutoff)
        # Count current entries
        pipe.zcard(key)
        # Add current request (optimistically)
        pipe.zadd(key, {f"{now}:{id(pipe)}": now})
        # Set TTL to clean up the key eventually
        pipe.expire(key, window_seconds + 10)
        results = await pipe.execute()

        current_count = results[1]  # zcard result before adding

        if current_count >= limit:
            # Over limit — remove the entry we just added
            await self.redis.zremrangebyscore(key, now, now + 0.001)
            # Calculate retry-after from the oldest entry
            oldest = await self.redis.zrange(key, 0, 0, withscores=True)
            if oldest:
                retry_after = max(1, int(oldest[0][1] + window_seconds - now))
            else:
                retry_after = 1
            return False, retry_after

        return True, 0

    async def reset(self, scope: str, actor: str) -> None:
        """Clear rate limit for a specific scope+actor."""
        key = f"ratelimit:{scope}:{actor}"
        await self.redis.delete(key)


async def get_rate_limiter(redis: Optional[aioredis.Redis] = None) -> RateLimiter:
    """Create a rate limiter with the given Redis connection."""
    if redis is None:
        from app.config import get_settings
        settings = get_settings()
        redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return RateLimiter(redis)
