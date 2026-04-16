"""Scrape Celery tasks — product library scraping, cleanup.

The scrape task runs on the 'scrape' queue with its own worker pool.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from uuid import uuid4

from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)
LIBRARY_SCRAPE_LOCK_KEY = "library_scrape_lock"
AUTO_LIBRARY_SCRAPE_STATUS_KEY = "library:auto_scrape:status"
_UNSET = object()


def _scrape_progress_key(user_id: int) -> str:
    return f"scrape_progress:{user_id}"


def _scrape_stop_key(user_id: int) -> str:
    return f"scrape_stop:{user_id}"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_auto_scrape_status() -> dict:
    return {
        "running": False,
        "status": "idle",
        "last_started_at": None,
        "last_finished_at": None,
        "last_task_id": None,
        "last_total_scraped": 0,
        "last_new_products": 0,
        "last_error": None,
    }


async def get_auto_scrape_status(redis) -> dict:
    payload = _default_auto_scrape_status()
    raw = await redis.get(AUTO_LIBRARY_SCRAPE_STATUS_KEY)
    if not raw:
        return payload
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return payload
    if isinstance(data, dict):
        payload.update({key: data[key] for key in payload.keys() if key in data})
    return payload


async def update_auto_scrape_status(
    redis,
    *,
    running=_UNSET,
    status=_UNSET,
    last_started_at=_UNSET,
    last_finished_at=_UNSET,
    last_task_id=_UNSET,
    last_total_scraped=_UNSET,
    last_new_products=_UNSET,
    last_error=_UNSET,
) -> dict:
    payload = await get_auto_scrape_status(redis)
    updates = {
        "running": running,
        "status": status,
        "last_started_at": last_started_at,
        "last_finished_at": last_finished_at,
        "last_task_id": last_task_id,
        "last_total_scraped": last_total_scraped,
        "last_new_products": last_new_products,
        "last_error": last_error,
    }
    for key, value in updates.items():
        if value is not _UNSET:
            payload[key] = value
    await redis.set(AUTO_LIBRARY_SCRAPE_STATUS_KEY, json.dumps(payload))
    return payload


async def reserve_library_scrape(redis, *, user_id: int, owner: str, ttl: int) -> bool:
    await redis.delete(_scrape_stop_key(user_id))
    acquired = await redis.set(LIBRARY_SCRAPE_LOCK_KEY, owner, ex=ttl, nx=True)
    return bool(acquired)


async def claim_library_scrape_lock(
    redis,
    *,
    owner: str,
    ttl: int,
    pending_owner: str | None = None,
) -> bool:
    current_owner = await redis.get(LIBRARY_SCRAPE_LOCK_KEY)
    if current_owner is None:
        acquired = await redis.set(LIBRARY_SCRAPE_LOCK_KEY, owner, ex=ttl, nx=True)
        return bool(acquired)
    if pending_owner and current_owner == pending_owner:
        await redis.set(LIBRARY_SCRAPE_LOCK_KEY, owner, ex=ttl)
        return True
    return False


async def release_library_scrape_lock(redis, *, owner: str) -> bool:
    current_owner = await redis.get(LIBRARY_SCRAPE_LOCK_KEY)
    if current_owner != owner:
        return False
    await redis.delete(LIBRARY_SCRAPE_LOCK_KEY)
    return True


async def refresh_library_scrape_lock(redis, *, owner: str, ttl: int) -> bool:
    current_owner = await redis.get(LIBRARY_SCRAPE_LOCK_KEY)
    if current_owner != owner:
        return False
    await redis.set(LIBRARY_SCRAPE_LOCK_KEY, owner, ex=ttl)
    return True


def _run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(bind=True, max_retries=0, queue="scrape")
def run_library_scrape(
    self,
    user_id: int,
    lead_min: int = 7,
    lead_max: int = 21,
    price_min: float = 0,
    price_max: float = 100000,
    max_per_cat: int = 500,
    categories: list[str] | None = None,
    lock_owner: str = "",
    is_auto: bool = False,
):
    """Scrape Takealot product library — full pipeline.

    dept x price_slices x cursor_pagination -> upsert library_products.
    Progress stored in Redis for frontend polling, stop signal via Redis key.
    """
    async def _scrape():
        import redis.asyncio as aioredis
        from app.config import get_settings
        from app.database import task_db_session
        from app.services import library_service

        settings = get_settings()
        redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        progress_key = _scrape_progress_key(user_id)
        task_owner = str(self.request.id or lock_owner or f"library-scrape:{user_id}")
        execution_owner = f"{task_owner}:{uuid4().hex}"

        async def _refresh_lock() -> bool:
            return await refresh_library_scrape_lock(
                redis,
                owner=execution_owner,
                ttl=settings.library_scrape_lock_ttl_seconds,
            )

        try:
            await redis.delete(_scrape_stop_key(user_id))
            acquired = await claim_library_scrape_lock(
                redis,
                owner=execution_owner,
                ttl=settings.library_scrape_lock_ttl_seconds,
                pending_owner=lock_owner or None,
            )
            if not acquired:
                logger.warning("Library scrape lock already held, skipping user_id=%d", user_id)
                if is_auto:
                    current_status = await get_auto_scrape_status(redis)
                    if not current_status.get("running"):
                        await update_auto_scrape_status(
                            redis,
                            running=False,
                            status="skipped",
                            last_task_id=task_owner,
                            last_error=None,
                        )
                return {"ok": False, "error": "Scrape already running", "skipped": True}

            if is_auto:
                await update_auto_scrape_status(
                    redis,
                    running=True,
                    status="running",
                    last_started_at=_utc_now_iso(),
                    last_task_id=task_owner,
                    last_error=None,
                )

            async with task_db_session() as db:
                before_total = await library_service.count_library_products(db)
                total = await library_service.scrape_to_library(
                    db=db,
                    redis=redis,
                    user_id=user_id,
                    categories=categories,
                    lead_min=lead_min,
                    lead_max=lead_max,
                    min_price=price_min if price_min > 0 else None,
                    max_price=price_max if price_max < 100000 else None,
                    max_per_cat=max_per_cat,
                    lock_heartbeat=_refresh_lock,
                )
                await db.commit()
                after_total = await library_service.count_library_products(db)

            new_products = max(after_total - before_total, 0)

            if is_auto:
                await update_auto_scrape_status(
                    redis,
                    running=False,
                    status="success",
                    last_finished_at=_utc_now_iso(),
                    last_task_id=task_owner,
                    last_total_scraped=total,
                    last_new_products=new_products,
                    last_error=None,
                )
            return {"ok": True, "total_scraped": total, "new_products": new_products}

        except Exception as exc:
            logger.error("Library scrape failed: %s", exc, exc_info=True)
            await redis.setex(progress_key, 3600, json.dumps({
                "running": False, "mode": "error",
                "total_scraped": 0,
                "error": str(exc)[:500],
            }))
            if is_auto:
                await update_auto_scrape_status(
                    redis,
                    running=False,
                    status="error",
                    last_finished_at=_utc_now_iso(),
                    last_task_id=task_owner,
                    last_error=str(exc)[:500],
                )
            return {"ok": False, "error": str(exc)[:500]}
        finally:
            # Always release the lock and close redis
            await release_library_scrape_lock(redis, owner=execution_owner)
            await redis.aclose()

    return _run_async(_scrape())


@celery_app.task(name="app.tasks.scrape_tasks.enqueue_auto_library_scrape")
def enqueue_auto_library_scrape():
    """Periodic task: enqueue one background library top-up scrape."""

    async def _enqueue():
        import redis.asyncio as aioredis
        from app.config import get_settings

        settings = get_settings()
        redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        pending_owner = f"auto-pending:{uuid4().hex}"

        try:
            reserved = await reserve_library_scrape(
                redis,
                user_id=settings.library_auto_scrape_user_id,
                owner=pending_owner,
                ttl=settings.library_scrape_pending_ttl_seconds,
            )
            if not reserved:
                current_status = await get_auto_scrape_status(redis)
                if not current_status.get("running"):
                    await update_auto_scrape_status(
                        redis,
                        running=False,
                        status="skipped",
                        last_error=None,
                    )
                return {"ok": True, "skipped": True, "reason": "already_running"}

            try:
                task = run_library_scrape.delay(
                    user_id=settings.library_auto_scrape_user_id,
                    lead_min=settings.library_auto_scrape_lead_min,
                    lead_max=settings.library_auto_scrape_lead_max,
                    price_min=settings.library_auto_scrape_price_min,
                    price_max=settings.library_auto_scrape_price_max,
                    max_per_cat=settings.library_auto_scrape_max_per_cat,
                    categories=None,
                    lock_owner=pending_owner,
                    is_auto=True,
                )
                await update_auto_scrape_status(
                    redis,
                    running=False,
                    status="queued",
                    last_task_id=task.id,
                    last_error=None,
                )
            except Exception:
                await release_library_scrape_lock(redis, owner=pending_owner)
                await update_auto_scrape_status(
                    redis,
                    running=False,
                    status="error",
                    last_finished_at=_utc_now_iso(),
                    last_error="Failed to enqueue auto scrape task",
                )
                raise

            return {"ok": True, "queued": True, "task_id": task.id}
        finally:
            await redis.aclose()

    return _run_async(_enqueue())


@celery_app.task(name="app.tasks.scrape_tasks.cleanup_library")
def cleanup_library_products():
    """Periodic task: quarantine products with invalid categories."""
    async def _cleanup():
        from app.database import task_db_session
        from app.services import library_service

        async with task_db_session() as db:
            result = await library_service.cleanup_invalid_categories(db)
            await db.commit()
            logger.info("Library cleanup: %s", result)
            return result

    return _run_async(_cleanup())
