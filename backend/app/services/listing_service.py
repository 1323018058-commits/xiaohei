"""Listing service — AI listing job management.

Handles listing job CRUD. The actual Playwright automation and AI rewrite
logic runs inside Celery tasks (tasks/listing_tasks.py).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.listing import ListingJob

logger = logging.getLogger(__name__)

RUNNING_STATES = ("dispatching", "scraping", "ai_rewriting", "searching_catalogue", "submitting")


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

async def create_listing_job(
    db: AsyncSession,
    user_id: int,
    store_id: int,
    amazon_url: str,
    price_zar: float | None = None,
    notes: str = "",
) -> ListingJob:
    job = ListingJob(
        user_id=user_id,
        store_id=store_id,
        amazon_url=amazon_url,
        price_zar=price_zar,
        status="pending",
    )
    db.add(job)
    await db.flush()
    return job


async def get_listing_job(db: AsyncSession, job_id: int) -> ListingJob | None:
    result = await db.execute(select(ListingJob).where(ListingJob.id == job_id))
    return result.scalar_one_or_none()


async def list_listing_jobs(
    db: AsyncSession,
    user_id: int,
    page: int = 1,
    page_size: int = 20,
    status: str = "",
) -> tuple[list[ListingJob], int]:
    query = select(ListingJob).where(ListingJob.user_id == user_id)
    if status:
        query = query.where(ListingJob.status == status)

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar_one()

    query = query.order_by(ListingJob.id.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return list(result.scalars().all()), total


async def update_listing_job_status(
    db: AsyncSession, job_id: int, status: str, **fields
) -> None:
    job = await get_listing_job(db, job_id)
    if job:
        job.status = status
        job.updated_at = datetime.utcnow()
        for k, v in fields.items():
            if hasattr(job, k):
                setattr(job, k, v)
        await db.flush()


async def recover_stale_jobs(db: AsyncSession, max_age_seconds: int = 600) -> list[int]:
    """Reset jobs stuck in running states back to pending."""
    cutoff = datetime.utcnow()
    result = await db.execute(
        select(ListingJob)
        .where(
            ListingJob.status.in_(RUNNING_STATES),
            ListingJob.updated_at < cutoff,
        )
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
# Aggregation
# ---------------------------------------------------------------------------

async def get_listing_stats(db: AsyncSession, user_id: int) -> dict:
    total = (await db.execute(
        select(func.count()).select_from(ListingJob).where(ListingJob.user_id == user_id)
    )).scalar_one()

    submitted = (await db.execute(
        select(func.count()).select_from(ListingJob).where(
            ListingJob.user_id == user_id,
            ListingJob.submission_id.isnot(None),
            ListingJob.submission_id != "",
        )
    )).scalar_one()

    failed = (await db.execute(
        select(func.count()).select_from(ListingJob).where(
            ListingJob.user_id == user_id, ListingJob.status == "failed",
        )
    )).scalar_one()

    running = (await db.execute(
        select(func.count()).select_from(ListingJob).where(
            ListingJob.user_id == user_id, ListingJob.status.in_(RUNNING_STATES),
        )
    )).scalar_one()

    return {
        "total": total,
        "submitted": submitted,
        "failed": failed,
        "running": running,
        "pending": total - submitted - failed - running,
    }


async def reset_job_for_retry(db: AsyncSession, job_id: int) -> None:
    """Reset a failed listing job so it can be re-dispatched."""
    job = await get_listing_job(db, job_id)
    if job:
        job.status = "pending"
        job.error_code = None
        job.error_msg = None
        job.updated_at = datetime.utcnow()
        await db.flush()
