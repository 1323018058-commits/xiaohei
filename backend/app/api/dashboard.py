"""Dashboard API router — stats, selling points, activity."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query

from app.api.deps import ActiveUser, DbSession, RedisConn
from app.services import bid_service, store_service, snapshot_service
from app.models.store import StoreBinding
from app.models.product import BidProduct
from app.models.listing import ListingJob, DropshipJob

from sqlalchemy import func, select

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats")
async def dashboard_stats(user: ActiveUser, db: DbSession, redis: RedisConn):
    """Three-tier dashboard snapshot: fresh → return, stale → return + refresh, none → fallback."""
    cache_result = await snapshot_service.get_cached_payload(
        redis, "dashboard", user.id, ttl_seconds=600, usable_seconds=3600,
    )

    if cache_result["cached"] and not cache_result["snapshot_stale"]:
        return {"ok": True, **cache_result["payload"]}

    if cache_result["cached"] and cache_result["snapshot_stale"]:
        if cache_result["needs_refresh"]:
            from app.tasks.snapshot_tasks import refresh_dashboard_snapshot
            refresh_dashboard_snapshot.delay(user.id)
        payload = cache_result["payload"]
        payload["snapshot_stale"] = True
        payload["refreshing"] = True
        return {"ok": True, **payload}

    # Cold miss — build fallback from DB
    payload = await _build_fallback_payload(db, user.id)
    # Trigger async refresh
    from app.tasks.snapshot_tasks import refresh_dashboard_snapshot
    refresh_dashboard_snapshot.delay(user.id)
    return {"ok": True, **payload}


@router.get("/activity")
async def dashboard_activity(
    user: ActiveUser, db: DbSession,
    limit: int = Query(20, ge=1, le=50),
):
    """Recent activity feed."""
    activities = []

    # Recent listing jobs
    result = await db.execute(
        select(ListingJob)
        .where(ListingJob.user_id == user.id)
        .order_by(ListingJob.updated_at.desc())
        .limit(limit)
    )
    for j in result.scalars().all():
        activities.append({
            "module": "listing",
            "level": "error" if j.status == "failed" else "info",
            "title": f"AI铺货: {j.listing_title or j.amazon_url[:50]}",
            "detail": j.status,
            "created_at": str(j.updated_at) if j.updated_at else str(j.created_at),
        })

    # Recent dropship jobs
    result = await db.execute(
        select(DropshipJob)
        .where(DropshipJob.user_id == user.id)
        .order_by(DropshipJob.updated_at.desc())
        .limit(limit)
    )
    for j in result.scalars().all():
        activities.append({
            "module": "dropship",
            "level": "error" if j.status == "failed" else "info",
            "title": f"关键词铺货: {j.source_keyword or j.amazon_url[:50]}",
            "detail": j.status,
            "created_at": str(j.updated_at) if j.updated_at else str(j.created_at),
        })

    # Sort by time
    activities.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return {"ok": True, "activities": activities[:limit]}


async def _build_fallback_payload(db, user_id: int) -> dict:
    """Build a DB-only dashboard payload (no API calls)."""
    # Store count
    store_count = (await db.execute(
        select(func.count()).select_from(StoreBinding).where(
            StoreBinding.user_id == user_id, StoreBinding.is_active == 1,
        )
    )).scalar_one()

    total_offers = (await db.execute(
        select(func.coalesce(func.sum(StoreBinding.offer_count), 0))
        .where(StoreBinding.user_id == user_id, StoreBinding.is_active == 1)
    )).scalar_one()

    # Bid products
    stores = await store_service.list_stores(db, user_id)
    store_ids = [s.id for s in stores]

    total_bid = 0
    active_bid = 0
    if store_ids:
        total_bid = (await db.execute(
            select(func.count()).select_from(BidProduct).where(
                BidProduct.store_binding_id.in_(store_ids)
            )
        )).scalar_one()
        active_bid = (await db.execute(
            select(func.count()).select_from(BidProduct).where(
                BidProduct.store_binding_id.in_(store_ids),
                BidProduct.auto_bid_enabled == 1,
                BidProduct.floor_price_zar > 0,
            )
        )).scalar_one()

    # Fulfillment stats
    submitted = (await db.execute(
        select(func.count()).select_from(DropshipJob).where(
            DropshipJob.user_id == user_id,
            DropshipJob.submission_id.isnot(None),
            DropshipJob.submission_id != "",
        )
    )).scalar_one()

    failed = (await db.execute(
        select(func.count()).select_from(DropshipJob).where(
            DropshipJob.user_id == user_id, DropshipJob.status == "failed",
        )
    )).scalar_one()

    # 15-day empty daily data
    today = datetime.utcnow().date()
    daily_data = [
        {"date": (today - timedelta(days=i)).isoformat(), "sales": 0, "orders": 0}
        for i in range(14, -1, -1)
    ]

    return {
        "store_count": store_count,
        "total_offers": total_offers,
        "total_bid_products": total_bid,
        "active_bid_products": active_bid,
        "dropship_submitted": submitted,
        "fulfillment_failed": failed,
        "total_sales_zar": 0,
        "total_orders": 0,
        "daily_data": daily_data,
        "snapshot_fallback": True,
        "snapshot_stale": True,
        "refreshing": True,
        "alerts": [],
    }
