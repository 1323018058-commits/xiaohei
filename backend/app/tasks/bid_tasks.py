"""Bid engine Celery tasks — periodic auto-bid cycle, sync, BuyBox refresh."""
from __future__ import annotations

import asyncio
import logging

from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


def _run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(bind=True, name="app.tasks.bid_tasks.run_autobid_cycle")
def run_autobid_cycle(self):
    """Periodic task: run one bid cycle for all stores with running engines.

    Full cycle per store:
      1. Refresh BuyBox prices via Takealot public API
      2. Execute bid decisions (buybox-1, floor protection, target cap)
      3. Update engine stats
    """
    async def _run():
        from app.database import task_db_session
        from app.models.product import BidEngineState
        from app.services import bid_service, store_service
        from sqlalchemy import select
        from datetime import datetime
        import redis.asyncio as aioredis
        from app.config import get_settings

        settings = get_settings()
        redis = aioredis.from_url(settings.redis_url, decode_responses=True)

        try:
            async with task_db_session() as db:
                result = await db.execute(
                    select(BidEngineState).where(BidEngineState.running == 1)
                )
                active_engines = list(result.scalars().all())

                for engine in active_engines:
                    store_id = engine.store_id
                    lock_key = f"bid_lock:{store_id}"

                    # Distributed lock via Redis
                    acquired = await redis.set(lock_key, "1", ex=280, nx=True)
                    if not acquired:
                        logger.info("Bid cycle for store %d already locked, skipping", store_id)
                        continue

                    try:
                        store = await store_service.get_store_admin(db, store_id)
                        if not store or store.is_active != 1:
                            engine.running = 0
                            continue

                        now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                        stats = await bid_service.run_bid_cycle(db, store)

                        engine.last_run = now_str
                        engine.last_raised = stats.get("raised", 0)
                        engine.last_lowered = stats.get("lowered", 0)
                        engine.last_floored = stats.get("floored", 0)
                        engine.last_unchanged = stats.get("unchanged", 0)
                        engine.last_errors = stats.get("errors", 0)
                        engine.total_checked += stats.get("checked", 0)
                        engine.total_updated += stats.get("updated", 0)
                        engine.last_result = "ok"
                        engine.last_buybox_refresh_count = stats.get("buybox_refreshed", 0)

                        if stats.get("checked", 0) > 0 and stats.get("updated", 0) == 0 and stats.get("errors", 0) > 0:
                            engine.consecutive_error_cycles += 1
                        else:
                            engine.consecutive_error_cycles = 0

                        logger.info("Bid cycle store=%d: %s", store_id, stats)
                    except Exception as exc:
                        logger.error("Bid cycle failed for store %d: %s", store_id, exc)
                        engine.last_result = f"error: {exc}"
                        engine.consecutive_error_cycles += 1
                    finally:
                        await redis.delete(lock_key)

                await db.commit()
        finally:
            await redis.aclose()

    return _run_async(_run())


@celery_app.task(bind=True, name="app.tasks.bid_tasks.sync_buyable_bid_products")
def sync_buyable_bid_products(self):
    """Periodic task: sync buyable bid products for all active stores every 30 minutes."""
    async def _sync():
        from app.database import task_db_session
        from app.models.store import StoreBinding
        from app.services import bid_service
        from sqlalchemy import select

        stats = {
            "stores": 0,
            "synced": 0,
            "failed": 0,
            "products_synced": 0,
            "products_skipped": 0,
            "errors": 0,
        }

        async with task_db_session() as db:
            result = await db.execute(
                select(StoreBinding).where(StoreBinding.is_active == 1)
            )
            stores = list(result.scalars().all())
            stats["stores"] = len(stores)

            for store in stores:
                try:
                    sync_result = await bid_service.sync_bid_products(db, store)
                    await db.commit()
                    stats["synced"] += 1
                    stats["products_synced"] += int(sync_result.get("synced", 0))
                    stats["products_skipped"] += int(sync_result.get("skipped", 0))
                    stats["errors"] += int(sync_result.get("errors", 0))
                except Exception as exc:
                    await db.rollback()
                    stats["failed"] += 1
                    logger.error(
                        "Periodic buyable product sync failed for store %d: %s",
                        store.id,
                        exc,
                    )

        logger.info("Periodic buyable product sync stats: %s", stats)
        return stats

    return _run_async(_sync())


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def sync_bid_products_task(self, store_id: int):
    """Sync all offers from Takealot API into bid_products table."""
    async def _sync():
        from app.database import task_db_session
        from app.services import bid_service, store_service

        async with task_db_session() as db:
            store = await store_service.get_store_admin(db, store_id)
            if not store:
                return {"ok": False, "error": "store not found"}
            result = await bid_service.sync_bid_products(db, store)
            await db.commit()
            return result

    try:
        return _run_async(_sync())
    except Exception as exc:
        logger.error("sync_bid_products_task(%d) failed: %s", store_id, exc)
        raise self.retry(exc=exc)
