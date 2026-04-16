"""Dashboard snapshot Celery tasks."""
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


@celery_app.task(name="app.tasks.snapshot_tasks.refresh_dashboard_snapshots")
def refresh_dashboard_snapshots():
    """Periodic task: refresh dashboard snapshots for all users."""
    async def _refresh_all():
        from app.database import task_db_session
        from app.models.user import User
        from sqlalchemy import select

        async with task_db_session() as db:
            result = await db.execute(select(User.id))
            user_ids = [row[0] for row in result.all()]

        for uid in user_ids:
            try:
                refresh_dashboard_snapshot.delay(uid)
            except Exception as exc:
                logger.error("Failed to enqueue dashboard refresh for user %d: %s", uid, exc)

        return {"ok": True, "users_queued": len(user_ids)}

    return _run_async(_refresh_all())


@celery_app.task(bind=True, max_retries=1, default_retry_delay=30)
def refresh_dashboard_snapshot(self, user_id: int):
    """Refresh dashboard snapshot for a single user."""
    async def _refresh():
        import redis.asyncio as aioredis
        from app.config import get_settings
        from app.database import task_db_session
        from app.services import snapshot_service, store_service
        from app.services.takealot_api import TakealotSellerAPI
        from app.utils.encryption import decrypt
        from datetime import datetime, timedelta, timezone

        settings = get_settings()
        redis = aioredis.from_url(settings.redis_url, decode_responses=True)

        try:
            # Acquire lock
            if not await snapshot_service.try_acquire_refresh_lock(redis, "dashboard", user_id, ttl=120):
                return {"ok": True, "skipped": True}

            async with task_db_session() as db:
                # Build core payload
                from app.api.dashboard import _build_fallback_payload
                payload = await _build_fallback_payload(db, user_id)

                # Fetch 14-day sales from all stores
                stores = await store_service.list_stores(db, user_id)
                total_sales = 0.0
                total_orders = 0
                daily_map: dict[str, dict] = {}

                today = datetime.utcnow().date()
                for i in range(14, -1, -1):
                    d = (today - timedelta(days=i)).isoformat()
                    daily_map[d] = {"date": d, "sales": 0.0, "orders": 0}

                for store in stores:
                    try:
                        raw_key = decrypt(store.api_key)
                        api = TakealotSellerAPI(raw_key)
                        start = (today - timedelta(days=14)).isoformat()
                        end = today.isoformat()
                        sales = await api.get_all_sales(start_date=start, end_date=end)

                        for sale in sales:
                            price = float(sale.get("selling_price", sale.get("total", sale.get("amount", 0))) or 0)
                            date_str = str(sale.get("order_date", sale.get("date", sale.get("created_at", ""))))[:10]
                            total_sales += price
                            total_orders += 1
                            if date_str in daily_map:
                                daily_map[date_str]["sales"] += price
                                daily_map[date_str]["orders"] += 1
                    except Exception as exc:
                        logger.warning("Failed to fetch sales for store %d: %s", store.id, exc)

                payload["total_sales_zar"] = round(total_sales, 2)
                payload["total_orders"] = total_orders
                payload["daily_data"] = sorted(daily_map.values(), key=lambda x: x["date"])
                payload["snapshot_fallback"] = False
                payload["snapshot_stale"] = False
                payload["refreshing"] = False

                await snapshot_service.save_snapshot(
                    redis, "dashboard", user_id, payload, redis_expire=7200,
                )

            return {"ok": True}
        finally:
            await snapshot_service.release_refresh_lock(redis, "dashboard", user_id)
            await redis.aclose()

    try:
        return _run_async(_refresh())
    except Exception as exc:
        logger.error("refresh_dashboard_snapshot(%d) failed: %s", user_id, exc)
        raise self.retry(exc=exc)
