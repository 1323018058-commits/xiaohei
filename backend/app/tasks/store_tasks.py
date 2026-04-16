"""Store sync and maintenance Celery tasks."""
from __future__ import annotations

import asyncio
import json
import logging

from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Run an async coroutine from sync Celery context."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def sync_store_task(self, store_id: int):
    """Sync a single store with Takealot API (offer count, status)."""
    async def _sync():
        from app.database import task_db_session
        from app.services import store_service

        async with task_db_session() as db:
            store = await store_service.get_store_admin(db, store_id)
            if not store:
                logger.warning("Store %d not found for sync", store_id)
                return {"ok": False, "error": "store not found"}
            result = await store_service.sync_store(db, store)
            await db.commit()
            return result

    try:
        return _run_async(_sync())
    except Exception as exc:
        logger.error("sync_store_task(%d) failed: %s", store_id, exc)
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=1, default_retry_delay=10)
def refresh_snapshot(self, store_id: int, kind: str, params: dict | None = None):
    """Refresh a cached Takealot API snapshot in the background."""
    async def _refresh():
        import redis.asyncio as aioredis
        from app.config import get_settings
        from app.database import task_db_session
        from app.services import snapshot_service, store_service

        settings = get_settings()
        redis = aioredis.from_url(settings.redis_url, decode_responses=True)

        try:
            # Acquire refresh lock
            if not await snapshot_service.try_acquire_refresh_lock(redis, kind, store_id):
                logger.info("Snapshot refresh already running: %s:%d", kind, store_id)
                return {"ok": True, "skipped": True}

            async with task_db_session() as db:
                store = await store_service.get_store_admin(db, store_id)
                if not store or store.is_active != 1:
                    return {"ok": False, "error": "store not found or inactive"}

                api = store_service.get_takealot_api(store)

                # Dispatch to the right fetch function based on kind
                data = await _fetch_by_kind(api, kind, params)
                await snapshot_service.save_snapshot(redis, kind, store_id, data, params)
                return {"ok": True}
        finally:
            await snapshot_service.release_refresh_lock(redis, kind, store_id)
            await redis.aclose()

    try:
        return _run_async(_refresh())
    except Exception as exc:
        logger.error("refresh_snapshot(%d, %s) failed: %s", store_id, kind, exc)
        raise self.retry(exc=exc)


async def _fetch_by_kind(api, kind: str, params: dict | None = None):
    """Dispatch fetch to the appropriate TakealotSellerAPI method."""
    p = params or {}

    if kind == "offers":
        return await api.get_offers(page=p.get("page", 1), page_size=p.get("page_size", 100))
    elif kind == "sales_orders":
        return await api.get_sales_orders(
            start_date=p.get("start_date", ""), end_date=p.get("end_date", ""),
            page=p.get("page", 1), page_size=p.get("page_size", 100),
        )
    elif kind == "financial_statements":
        return await api.get_financial_statements(page=p.get("page", 1), page_size=p.get("page_size", 50))
    elif kind == "financial_balance":
        return await api.get_seller_balances()
    elif kind == "financial_transactions":
        return await api.get_seller_transactions(
            date_from=p.get("date_from", ""), date_to=p.get("date_to", ""),
            page=p.get("page", 1), page_size=p.get("page_size", 100),
        )
    elif kind == "merchant_warehouses":
        return await api.get_merchant_warehouses()
    elif kind == "shipment_facilities":
        return await api.get_shipment_facilities()
    elif kind == "leadtime_orders":
        return await api.get_leadtime_order_items(page=p.get("page", 1), page_size=p.get("page_size", 100))
    elif kind == "shipments":
        return await api.get_shipments(
            shipment_state=p.get("shipment_state", ""),
            page=p.get("page", 1), page_size=p.get("page_size", 50),
        )
    else:
        raise ValueError(f"Unknown snapshot kind: {kind}")


@celery_app.task
def cleanup_expired_tokens():
    """Clean up expired extension auth tokens."""
    async def _cleanup():
        from datetime import datetime, timezone
        from sqlalchemy import delete
        from app.database import task_db_session
        from app.models.extension import ExtensionAuthToken

        async with task_db_session() as db:
            now = datetime.utcnow()
            result = await db.execute(
                delete(ExtensionAuthToken).where(ExtensionAuthToken.expires_at < now)
            )
            await db.commit()
            count = result.rowcount
            logger.info("Cleaned up %d expired extension tokens", count)
            return {"ok": True, "deleted": count}

    return _run_async(_cleanup())
