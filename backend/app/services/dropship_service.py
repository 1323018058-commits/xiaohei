"""Dropship service — keyword-based auto-listing job management.

Handles dropship job CRUD. The actual keyword search, scraping, image matching,
and submission logic runs inside Celery tasks (tasks/dropship_tasks.py).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.listing import DropshipJob

logger = logging.getLogger(__name__)

RUNNING_STATES = ("dispatching", "scraping", "matching", "ai_rewriting", "filling", "submitting")


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

async def create_dropship_job(
    db: AsyncSession,
    user_id: int,
    store_id: int,
    amazon_url: str,
    asin: str = "",
    source_keyword: str = "",
    similarity_threshold: int = 65,
    price_zar: float = 0,
) -> DropshipJob:
    job = DropshipJob(
        user_id=user_id,
        store_id=store_id,
        amazon_url=amazon_url,
        asin=asin,
        source_keyword=source_keyword,
        similarity_threshold=similarity_threshold,
        price_zar=price_zar,
        status="pending",
    )
    db.add(job)
    await db.flush()
    return job


async def get_dropship_job(db: AsyncSession, job_id: int) -> DropshipJob | None:
    result = await db.execute(select(DropshipJob).where(DropshipJob.id == job_id))
    return result.scalar_one_or_none()


async def list_dropship_jobs(
    db: AsyncSession,
    user_id: int,
    page: int = 1,
    page_size: int = 20,
    status: str = "",
    keyword: str = "",
) -> tuple[list[DropshipJob], int]:
    query = select(DropshipJob).where(DropshipJob.user_id == user_id)
    if status:
        query = query.where(DropshipJob.status == status)
    if keyword:
        query = query.where(DropshipJob.source_keyword.ilike(f"%{keyword}%"))

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar_one()

    query = query.order_by(DropshipJob.id.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return list(result.scalars().all()), total


async def update_dropship_job_status(
    db: AsyncSession, job_id: int, status: str, **fields
) -> None:
    job = await get_dropship_job(db, job_id)
    if job:
        job.status = status
        job.updated_at = datetime.utcnow()
        for k, v in fields.items():
            if hasattr(job, k):
                setattr(job, k, v)
        await db.flush()


async def recover_stale_jobs(db: AsyncSession, max_age_seconds: int = 600) -> list[int]:
    cutoff = datetime.utcnow()
    result = await db.execute(
        select(DropshipJob)
        .where(DropshipJob.status.in_(RUNNING_STATES))
    )
    stale = list(result.scalars().all())
    recovered = []
    for job in stale:
        if job.updated_at and (cutoff - job.updated_at).total_seconds() > max_age_seconds:
            job.status = "pending"
            job.updated_at = cutoff
            recovered.append(job.id)
    await db.flush()
    return recovered


# ---------------------------------------------------------------------------
# Keyword progress (Redis-backed)
# ---------------------------------------------------------------------------

async def get_keyword_progress(redis, user_id: int) -> dict:
    import json
    key = f"dropship_keyword_progress:{user_id}"
    raw = await redis.get(key)
    if not raw:
        return {"running": False}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"running": False}


async def set_keyword_progress(redis, user_id: int, **fields) -> None:
    import json
    key = f"dropship_keyword_progress:{user_id}"
    current = await get_keyword_progress(redis, user_id)
    current.update(fields)
    current["updated_at"] = datetime.utcnow().isoformat()
    await redis.setex(key, 3600, json.dumps(current, default=str))


async def clear_keyword_progress(redis, user_id: int) -> None:
    key = f"dropship_keyword_progress:{user_id}"
    await redis.delete(key)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

async def get_dropship_stats(db: AsyncSession, user_id: int) -> dict:
    total = (await db.execute(
        select(func.count()).select_from(DropshipJob).where(DropshipJob.user_id == user_id)
    )).scalar_one()

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

    running = (await db.execute(
        select(func.count()).select_from(DropshipJob).where(
            DropshipJob.user_id == user_id, DropshipJob.status.in_(RUNNING_STATES),
        )
    )).scalar_one()

    return {
        "total": total,
        "submitted": submitted,
        "failed": failed,
        "running": running,
    }


async def reset_job_for_retry(db: AsyncSession, job_id: int) -> None:
    """Reset a failed dropship job so it can be re-dispatched."""
    job = await get_dropship_job(db, job_id)
    if job:
        job.status = "pending"
        job.error_code = None
        job.error_msg = None
        job.updated_at = datetime.utcnow()
        await db.flush()
