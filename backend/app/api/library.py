"""Product library API router — scraping, browsing, filtering, quarantine, memory.

Endpoints:
  GET    /api/library/products       — query with filters + pagination
  GET    /api/library/products/{id}  — single product detail
  GET    /api/library/stats          — comprehensive stats
  GET    /api/library/filters        — category/brand dropdowns
  POST   /api/library/scrape/start   — start background scrape
  GET    /api/library/scrape/progress — poll scrape progress
  POST   /api/library/scrape/stop    — stop running scrape
  POST   /api/library/quarantine     — move products to quarantine
  GET    /api/library/quarantine     — list quarantined products
  POST   /api/library/import         — bulk import products
"""
from __future__ import annotations

import csv
import io
import json
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.api.deps import ActiveUser, DbSession, RedisConn
from app.config import get_settings
from app.schemas.common import OkResponse
from app.schemas.library import ImportRequest, QuarantineRequest, ScrapeStartRequest

router = APIRouter(prefix="/api/library", tags=["library"])


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

@router.get("/products")
async def list_library_products(
    user: ActiveUser, db: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    q: str = "",
    category: str = "",
    brand: str = "",
    min_price: float | None = None,
    max_price: float | None = None,
    min_rating: float | None = None,
    min_reviews: int | None = None,
    stock_type: str = "",
    review_after: str = "",
):
    """Query library products with comprehensive filters and pagination."""
    from app.services import library_service

    result = await library_service.query_library_products(
        db,
        user_id=user.id,
        keyword=q,
        category_main=category,
        brand=brand,
        min_price=min_price,
        max_price=max_price,
        min_rating=min_rating,
        min_reviews=min_reviews,
        stock_type=stock_type,
        review_after=review_after,
        page=page,
        page_size=page_size,
    )
    return {"ok": True, **result}


@router.get("/products/{product_id}")
async def get_library_product(product_id: int, user: ActiveUser, db: DbSession):
    """Get a single library product by ID."""
    from app.services import library_service

    product = await library_service.get_library_product(db, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"ok": True, "product": product}


# ---------------------------------------------------------------------------
# Stats & Filters
# ---------------------------------------------------------------------------

@router.get("/stats")
async def library_stats(user: ActiveUser, db: DbSession, redis: RedisConn):
    """Return comprehensive library statistics (Redis-cached for 60s)."""
    from app.services import library_service

    stats = await library_service.get_library_stats(db, redis=redis)
    return {"ok": True, **stats}


@router.get("/filters")
async def library_filters(user: ActiveUser, db: DbSession, redis: RedisConn):
    """Return distinct categories and brands for filter dropdowns (Redis-cached for 5min)."""
    from app.services import library_service

    filters = await library_service.get_library_filters(db, redis=redis)
    return {"ok": True, **filters}


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

@router.post("/scrape/start")
async def start_scrape(user: ActiveUser, redis: RedisConn, body: ScrapeStartRequest):
    """Start background library scrape via Celery task."""
    settings = get_settings()
    pending_owner = f"manual-pending:{user.id}:{uuid4().hex}"
    try:
        from app.tasks.scrape_tasks import (
            reserve_library_scrape,
            run_library_scrape,
        )

        acquired = await reserve_library_scrape(
            redis,
            user_id=user.id,
            owner=pending_owner,
            ttl=settings.library_scrape_pending_ttl_seconds,
        )
        if not acquired:
            return {"ok": False, "error": "Scrape already running", "running": True}

        task = run_library_scrape.delay(
            user_id=user.id,
            lead_min=body.lead_min,
            lead_max=body.lead_max,
            price_min=body.price_min,
            price_max=body.price_max,
            max_per_cat=body.max_per_cat,
            categories=body.categories if body.categories else None,
            lock_owner=pending_owner,
        )
        return {"ok": True, "task_id": task.id}
    except Exception:
        # Roll back the lock if task dispatch fails
        try:
            from app.tasks.scrape_tasks import release_library_scrape_lock

            await release_library_scrape_lock(redis, owner=pending_owner)
        except Exception:
            pass
        raise


@router.get("/scrape/progress")
async def scrape_progress(user: ActiveUser, redis: RedisConn):
    """Poll scrape progress from Redis."""
    key = f"scrape_progress:{user.id}"
    raw = await redis.get(key)
    if not raw:
        return {"ok": True, "running": False, "mode": "idle"}
    try:
        data = json.loads(raw)
        return {"ok": True, **data}
    except (json.JSONDecodeError, TypeError):
        return {"ok": True, "running": False, "mode": "idle"}


@router.post("/scrape/stop", response_model=OkResponse)
async def stop_scrape(user: ActiveUser, redis: RedisConn):
    """Stop running scrape by setting a stop signal in Redis."""
    key = f"scrape_stop:{user.id}"
    await redis.setex(key, 300, "1")
    return OkResponse()


# ---------------------------------------------------------------------------
# Quarantine
# ---------------------------------------------------------------------------

@router.post("/quarantine")
async def quarantine_products(
    user: ActiveUser, db: DbSession, body: QuarantineRequest,
):
    """Move products to quarantine by IDs."""
    from app.services import library_service

    if not body.product_ids:
        raise HTTPException(status_code=400, detail="product_ids required")

    result = await library_service.quarantine_products(db, body.product_ids, body.reason)
    await db.commit()
    return {"ok": True, **result}


@router.get("/quarantine")
async def list_quarantine(
    user: ActiveUser, db: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """List quarantined products."""
    from app.models.library import LibraryProductQuarantine
    from sqlalchemy import func, select

    count_q = select(func.count()).select_from(LibraryProductQuarantine)
    total = (await db.execute(count_q)).scalar_one()

    result = await db.execute(
        select(LibraryProductQuarantine)
        .order_by(LibraryProductQuarantine.removed_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = []
    for q in result.scalars().all():
        # Handle removed_at safely — could be datetime or string
        removed_at_str = None
        if q.removed_at:
            removed_at_str = (
                q.removed_at.isoformat()
                if hasattr(q.removed_at, "isoformat")
                else str(q.removed_at)
            )
        items.append({
            "id": q.id,
            "product_id": q.product_id,
            "removed_reason": q.removed_reason,
            "removed_at": removed_at_str,
            "snapshot": json.loads(q.snapshot_json) if q.snapshot_json else None,
        })

    return {"ok": True, "total": total, "page": page, "items": items}


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

@router.get("/export")
async def library_export(
    user: ActiveUser, db: DbSession,
    category: str = "",
    min_price: float | None = None,
    max_price: float | None = None,
    min_rating: float | None = None,
    limit: int = Query(5000, ge=1, le=50000),
):
    """Export library products as CSV."""
    from app.services import library_service

    result = await library_service.query_library_products(
        db, user_id=user.id, category_main=category,
        min_price=min_price, max_price=max_price,
        min_rating=min_rating, page=1, page_size=limit,
    )

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "product_id", "title", "brand", "category", "price_min", "price_max",
        "star_rating", "reviews_total", "in_stock", "url",
    ])
    for item in result["items"]:
        writer.writerow([
            item["product_id"], item["title"], item["brand"],
            item["category_main"], item["price_min"], item["price_max"],
            item["star_rating"], item["reviews_total"], item["in_stock"],
            item["url"],
        ])

    content = buf.getvalue().encode("utf-8-sig")
    return StreamingResponse(
        io.BytesIO(content),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=library_products.csv"},
    )


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

@router.post("/import")
async def library_import(user: ActiveUser, db: DbSession, body: ImportRequest):
    """Bulk import products (JSON array). Max 1000 per request."""
    from app.services import library_service

    # Process in chunks of 500 to avoid oversized SQL statements
    total = 0
    for i in range(0, len(body.products), 500):
        chunk = body.products[i:i + 500]
        n = await library_service._upsert_library_batch(db, chunk)
        total += n
    await db.commit()
    return {"ok": True, "imported": total}
