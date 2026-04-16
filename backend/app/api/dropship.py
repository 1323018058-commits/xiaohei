"""Dropship jobs API router — keyword import, job management."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import ActiveUser, DbSession, RedisConn
from app.schemas.listing import DropshipJobCreate
from app.services import dropship_service, store_service

router = APIRouter(prefix="/api/dropship", tags=["dropship"])


@router.get("/jobs")
async def list_dropship_jobs(
    user: ActiveUser, db: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str = "",
    keyword: str = "",
):
    jobs, total = await dropship_service.list_dropship_jobs(
        db, user.id, page=page, page_size=page_size, status=status, keyword=keyword,
    )
    items = []
    for j in jobs:
        items.append({
            "id": j.id, "amazon_url": j.amazon_url, "asin": j.asin,
            "source_keyword": j.source_keyword,
            "status": j.status, "error_code": j.error_code or "",
            "error_message": j.error_msg or "",
            "submission_id": j.submission_id, "review_status": j.review_status,
            "listing_title": j.listing_title or "",
            "orig_title": j.orig_title or "",
            "image_url": j.image_url or "",
            "matched_similarity": j.matched_similarity,
            "similarity_threshold": j.similarity_threshold,
            "category_confidence_label": j.category_confidence_label,
            "created_at": str(j.created_at) if j.created_at else None,
            "updated_at": str(j.updated_at) if j.updated_at else None,
        })
    return {"ok": True, "total": total, "page": page, "page_size": page_size, "jobs": items}


@router.post("/keyword-import")
async def start_keyword_import(body: DropshipJobCreate, user: ActiveUser, db: DbSession):
    store = await store_service.get_store(db, body.store_id, user.id)
    if not store:
        raise HTTPException(status_code=404, detail="店铺不存在")

    from app.tasks.dropship_tasks import run_keyword_import
    task = run_keyword_import.delay(
        user.id, body.store_id, body.keyword, body.pages,
        body.threshold, body.price_zar, body.max_items,
    )
    return {"ok": True, "task_id": task.id}


@router.get("/keyword-progress")
async def keyword_progress(user: ActiveUser, redis: RedisConn):
    progress = await dropship_service.get_keyword_progress(redis, user.id)
    return {"ok": True, **progress}


@router.get("/jobs/{job_id}")
async def get_dropship_job(job_id: int, user: ActiveUser, db: DbSession):
    job = await dropship_service.get_dropship_job(db, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {
        "ok": True,
        "job": {
            "id": job.id, "amazon_url": job.amazon_url, "asin": job.asin,
            "source_keyword": job.source_keyword, "store_id": job.store_id,
            "status": job.status, "error_code": job.error_code or "",
            "error_message": job.error_msg or "",
            "submission_id": job.submission_id,
            "submission_status": job.submission_status,
            "review_status": job.review_status,
            "listing_title": job.listing_title or "",
            "listing_description": job.listing_description or "",
            "package_contents": job.package_contents or "",
            "orig_title": job.orig_title or "",
            "orig_brand": job.orig_brand or "",
            "matched_similarity": job.matched_similarity,
            "similarity_threshold": job.similarity_threshold,
            "matched_1688_url": job.matched_1688_url,
            "matched_1688_title": job.matched_1688_title,
            "purchase_price_cny": job.purchase_price_cny,
            "image_url": job.image_url or "",
            "template_id": job.template_id,
            "template_name": job.template_name or "",
            "category_confidence_score": job.category_confidence_score,
            "category_confidence_label": job.category_confidence_label or "",
            "top_category": job.top_category, "lowest_category": job.lowest_category,
            "price_zar": job.price_zar,
            "weight_kg": job.weight_kg,
            "created_at": str(job.created_at) if job.created_at else None,
            "updated_at": str(job.updated_at) if job.updated_at else None,
        },
    }


@router.get("/stats")
async def dropship_stats(user: ActiveUser, db: DbSession):
    stats = await dropship_service.get_dropship_stats(db, user.id)
    return {"ok": True, **stats}


@router.post("/jobs/{job_id}/retry")
async def retry_dropship_job(job_id: int, user: ActiveUser, db: DbSession):
    """Retry a failed dropship job."""
    job = await dropship_service.get_dropship_job(db, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.status not in ("failed", "error"):
        raise HTTPException(status_code=400, detail="只能重试失败的任务")

    await dropship_service.reset_job_for_retry(db, job_id)
    await db.commit()

    from app.tasks.dropship_tasks import process_dropship_job
    process_dropship_job.delay(job_id)
    return {"ok": True, "job_id": job_id}
