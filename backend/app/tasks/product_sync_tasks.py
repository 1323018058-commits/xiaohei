"""Product sync Celery tasks."""
from __future__ import annotations

import asyncio
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
        asyncio.set_event_loop(None)
        loop.close()


def _short_error_message(value: object) -> str:
    if value is None:
        return "sync failed"
    message = str(value).strip() or "sync failed"
    return message[:200]


def _normalize_offer_ids(offer_ids: list[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in offer_ids or []:
        offer_id = str(value).strip()
        if not offer_id or offer_id in seen:
            continue
        seen.add(offer_id)
        normalized.append(offer_id)
    return normalized


def _run_product_sync_with_scope(
    store_id: int,
    *,
    progress_scope: str,
    sync_mode: str,
):
    """Sync products from Takealot and enrich missing images/links."""
    async def _sync():
        import redis.asyncio as aioredis
        from app.config import get_settings
        from app.database import task_db_session
        from app.services.buybox_service import fetch_product_detail
        from app.services import bid_service, product_sync_progress_service, store_service

        settings = get_settings()
        redis = aioredis.from_url(settings.redis_url, decode_responses=True)

        try:
            async with task_db_session() as db:
                store = await store_service.get_store_admin(db, store_id)
                if not store:
                    await product_sync_progress_service.clear_progress(
                        redis,
                        store_id,
                        scope=progress_scope,
                        lock_scope=product_sync_progress_service.DEFAULT_LOCK_SCOPE,
                        result="error",
                        stage="error",
                        message="store not found",
                    )
                    return {"ok": False, "error": "store not found"}

                await product_sync_progress_service.set_progress(
                    redis,
                    store_id,
                    scope=progress_scope,
                    stage="syncing",
                    message="正在同步商品...",
                )

                result = await bid_service.sync_bid_products(db, store, sync_mode=sync_mode)
                await db.commit()

                if not result.get("ok"):
                    await product_sync_progress_service.clear_progress(
                        redis,
                        store_id,
                        scope=progress_scope,
                        lock_scope=product_sync_progress_service.DEFAULT_LOCK_SCOPE,
                        result="error",
                        stage="error",
                        message=_short_error_message(result.get("error")),
                    )
                    return result

                missing = _normalize_offer_ids(
                    result.get("missing_enrichment_offer_ids")
                    or result.get("missing_image_offer_ids")
                    or []
                )
                if missing:
                    run_product_image_enrichment.delay(store_id, missing, progress_scope)
                    await product_sync_progress_service.set_progress(
                        redis,
                        store_id,
                        scope=progress_scope,
                        stage="enriching_images",
                        message="正在补充图片信息...",
                        total=len(missing),
                        processed=0,
                    )
                else:
                    await product_sync_progress_service.clear_progress(
                        redis,
                        store_id,
                        scope=progress_scope,
                        lock_scope=product_sync_progress_service.DEFAULT_LOCK_SCOPE,
                        result="done",
                        payload=result,
                    )

                return result
        except Exception as exc:
            await product_sync_progress_service.clear_progress(
                redis,
                store_id,
                scope=progress_scope,
                lock_scope=product_sync_progress_service.DEFAULT_LOCK_SCOPE,
                result="error",
                stage="error",
                message=_short_error_message(exc),
            )
            raise
        finally:
            await redis.aclose()

    return _run_async(_sync())


@celery_app.task(
    bind=True,
    name="app.tasks.product_sync_tasks.run_product_sync",
    max_retries=2,
    default_retry_delay=30,
)
def run_product_sync(self, store_id: int):
    """Legacy sync entrypoint kept for backwards compatibility."""
    try:
        return _run_product_sync_with_scope(
            store_id,
            progress_scope="legacy",
            sync_mode="catalog",
        )
    except Exception as exc:
        logger.error("run_product_sync(%d) failed: %s", store_id, exc)
        raise self.retry(exc=exc)


@celery_app.task(
    bind=True,
    name="app.tasks.product_sync_tasks.run_catalog_product_sync",
    max_retries=2,
    default_retry_delay=30,
)
def run_catalog_product_sync(self, store_id: int):
    """商品管理：同步全部商品状态。"""
    try:
        return _run_product_sync_with_scope(
            store_id,
            progress_scope="products",
            sync_mode="catalog",
        )
    except Exception as exc:
        logger.error("run_catalog_product_sync(%d) failed: %s", store_id, exc)
        raise self.retry(exc=exc)


@celery_app.task(
    bind=True,
    name="app.tasks.product_sync_tasks.run_bid_product_sync",
    max_retries=2,
    default_retry_delay=30,
)
def run_bid_product_sync(self, store_id: int):
    """自动出价：仅同步可出价商品。"""
    try:
        return _run_product_sync_with_scope(
            store_id,
            progress_scope="bids",
            sync_mode="bid",
        )
    except Exception as exc:
        logger.error("run_bid_product_sync(%d) failed: %s", store_id, exc)
        raise self.retry(exc=exc)


@celery_app.task(
    bind=True,
    name="app.tasks.product_sync_tasks.run_product_image_enrichment",
    max_retries=2,
    default_retry_delay=30,
)
def run_product_image_enrichment(self, store_id: int, offer_ids: list[str], progress_scope: str = "legacy"):
    """Fill missing image/takealot URLs for synced products."""
    async def _enrich():
        import redis.asyncio as aioredis
        from app.config import get_settings
        from app.database import task_db_session
        from app.services import bid_service, product_sync_progress_service, store_service

        settings = get_settings()
        redis = aioredis.from_url(settings.redis_url, decode_responses=True)

        try:
            async with task_db_session() as db:
                store = await store_service.get_store_admin(db, store_id)
                if not store:
                    await product_sync_progress_service.clear_progress(
                        redis,
                        store_id,
                        scope=progress_scope,
                        lock_scope=product_sync_progress_service.DEFAULT_LOCK_SCOPE,
                        result="error",
                        stage="error",
                        message="store not found",
                    )
                    return {"ok": False, "error": "store not found"}

                api = store_service.get_takealot_api(store)
                normalized = _normalize_offer_ids(offer_ids)
                total = len(normalized)
                if total == 0:
                    result = {"ok": True, "updated": 0, "total": 0}
                    await product_sync_progress_service.clear_progress(
                        redis,
                        store_id,
                        scope=progress_scope,
                        lock_scope=product_sync_progress_service.DEFAULT_LOCK_SCOPE,
                        result="done",
                        payload=result,
                    )
                    return result

                batch_size = max(1, int(settings.product_image_enrich_batch_size or 1))
                updated = 0
                processed = 0
                failed = 0

                await product_sync_progress_service.set_progress(
                    redis,
                    store_id,
                    scope=progress_scope,
                    stage="enriching_images",
                    message="正在补充图片信息...",
                    total=total,
                    processed=processed,
                    updated=updated,
                    failed=failed,
                )

                for start in range(0, total, batch_size):
                    batch = normalized[start:start + batch_size]
                    for offer_id in batch:
                        product = await bid_service.get_bid_product(db, store_id, offer_id)
                        if not product:
                            processed += 1
                            continue
                        current_image_url = bid_service._normalize_trustworthy_url(product.image_url)
                        current_takealot_url = bid_service._normalize_trustworthy_url(product.takealot_url)
                        if current_image_url and current_takealot_url:
                            processed += 1
                            continue

                        detail = await api.get_offer_media_detail(offer_id)
                        if isinstance(detail, dict) and detail.get("_fetch_error"):
                            failed += 1
                            processed += 1
                            continue
                        offer_payload = detail
                        if isinstance(detail, dict) and isinstance(detail.get("offer"), dict):
                            offer_payload = detail["offer"]

                        image_url = bid_service._extract_offer_image_url(offer_payload)
                        takealot_url = bid_service._extract_offer_takealot_url(offer_payload)
                        plid = bid_service._extract_offer_plid(offer_payload) or product.plid or ""
                        if plid and (not takealot_url or "/x/PLID" in takealot_url):
                            public_detail = await fetch_product_detail(plid)
                            public_url = bid_service._normalize_trustworthy_url(
                                public_detail.get("takealot_url") if public_detail.get("ok") else ""
                            )
                            if public_url:
                                takealot_url = public_url
                        changed = False
                        if plid and not product.plid:
                            product.plid = plid
                            changed = True
                        if not current_image_url and image_url:
                            product.image_url = image_url
                            changed = True
                        if not current_takealot_url and takealot_url:
                            product.takealot_url = takealot_url
                            changed = True
                        if changed:
                            updated += 1
                        processed += 1

                    await db.flush()
                    await db.commit()

                    await product_sync_progress_service.set_progress(
                        redis,
                        store_id,
                        scope=progress_scope,
                        stage="enriching_images",
                        message="正在补充图片信息...",
                        total=total,
                        processed=processed,
                        updated=updated,
                        failed=failed,
                    )

                if failed and failed == total:
                    raise RuntimeError("image enrichment failed for all requested offers")

                result = {
                    "ok": True,
                    "updated": updated,
                    "total": total,
                    "failed": failed,
                }
                progress_result = "done"
                progress_stage = "done"
                progress_message = "图片信息部分补充完成" if failed else "图片信息补充完成"
                await product_sync_progress_service.clear_progress(
                    redis,
                    store_id,
                    scope=progress_scope,
                    lock_scope=product_sync_progress_service.DEFAULT_LOCK_SCOPE,
                    result=progress_result,
                    stage=progress_stage,
                    message=progress_message,
                    payload=result,
                )
                return result
        except Exception as exc:
            await product_sync_progress_service.clear_progress(
                redis,
                store_id,
                scope=progress_scope,
                lock_scope=product_sync_progress_service.DEFAULT_LOCK_SCOPE,
                result="error",
                stage="error",
                message=_short_error_message(exc),
            )
            raise
        finally:
            await redis.aclose()

    try:
        return _run_async(_enrich())
    except Exception as exc:
        logger.error("run_product_image_enrichment(%d) failed: %s", store_id, exc)
        raise self.retry(exc=exc)
