"""Listing jobs API router."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import ActiveUser, DbSession
from app.schemas.listing import ListingJobCreate
from app.services import listing_service, store_service

router = APIRouter(prefix="/api/listings", tags=["listings"])


@router.get("/jobs")
async def list_listing_jobs(
    user: ActiveUser, db: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str = "",
):
    jobs, total = await listing_service.list_listing_jobs(
        db, user.id, page=page, page_size=page_size, status=status,
    )
    items = []
    for j in jobs:
        items.append({
            "id": j.id, "amazon_url": j.amazon_url, "asin": j.asin,
            "status": j.status, "error_code": j.error_code or "",
            "error_message": j.error_msg or "",
            "submission_id": j.submission_id, "review_status": j.review_status,
            "listing_title": j.listing_title or "", "image_url": j.image_url or "",
            "template_name": j.template_name,
            "category_confidence_label": j.category_confidence_label,
            "created_at": str(j.created_at) if j.created_at else None,
            "updated_at": str(j.updated_at) if j.updated_at else None,
        })
    return {"ok": True, "total": total, "page": page, "page_size": page_size, "jobs": items}


@router.post("/jobs", status_code=201)
async def create_listing_job(body: ListingJobCreate, user: ActiveUser, db: DbSession):
    store = await store_service.get_store(db, body.store_id, user.id)
    if not store:
        raise HTTPException(status_code=404, detail="店铺不存在")

    job = await listing_service.create_listing_job(
        db, user.id, body.store_id, body.amazon_url, body.price_zar, body.notes,
    )

    # Dispatch to Celery
    from app.tasks.listing_tasks import process_listing_job
    process_listing_job.delay(job.id)

    return {"ok": True, "job_id": job.id}


@router.get("/jobs/{job_id}")
async def get_listing_job(job_id: int, user: ActiveUser, db: DbSession):
    job = await listing_service.get_listing_job(db, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {
        "ok": True,
        "job": {
            "id": job.id, "amazon_url": job.amazon_url, "asin": job.asin,
            "status": job.status, "error_code": job.error_code or "",
            "error_message": job.error_msg or "",
            "submission_id": job.submission_id, "review_status": job.review_status,
            "listing_title": job.listing_title or "",
            "listing_description": job.listing_description or "",
            "top_category": job.top_category, "lowest_category": job.lowest_category,
            "template_name": job.template_name,
            "brand": job.brand, "barcode": job.barcode,
            "image_url": job.image_url or "",
            "price_zar": job.price_zar, "weight_kg": job.weight_kg,
            "category_confidence_score": job.category_confidence_score,
            "category_confidence_label": job.category_confidence_label,
            "created_at": str(job.created_at) if job.created_at else None,
            "updated_at": str(job.updated_at) if job.updated_at else None,
        },
    }


@router.get("/stats")
async def listing_stats(user: ActiveUser, db: DbSession):
    stats = await listing_service.get_listing_stats(db, user.id)
    return {"ok": True, **stats}


@router.post("/jobs/{job_id}/retry")
async def retry_listing_job(job_id: int, user: ActiveUser, db: DbSession):
    """Retry a failed listing job."""
    job = await listing_service.get_listing_job(db, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.status not in ("failed", "error"):
        raise HTTPException(status_code=400, detail="只能重试失败的任务")

    await listing_service.reset_job_for_retry(db, job_id)
    await db.commit()

    from app.tasks.listing_tasks import process_listing_job
    process_listing_job.delay(job_id)
    return {"ok": True, "job_id": job_id}
