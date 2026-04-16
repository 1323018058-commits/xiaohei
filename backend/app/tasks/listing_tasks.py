"""Listing job Celery tasks — process listing jobs, recovery, submission sync."""
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


@celery_app.task(bind=True, max_retries=1, default_retry_delay=30, queue="listing")
def process_listing_job(self, job_id: int):
    """Process a single listing job: scrape → AI rewrite → submit loadsheet.

    This is the Celery equivalent of listing_module.process_listing_job().
    The actual heavy lifting (Playwright, DeepSeek API) will be imported
    from the listing_module when fully ported.
    """
    async def _process():
        from app.database import task_db_session
        from app.services import listing_service

        async with task_db_session() as db:
            job = await listing_service.get_listing_job(db, job_id)
            if not job:
                return {"ok": False, "error": "job not found"}

            if job.status not in ("pending", "dispatching"):
                return {"ok": False, "error": f"job in unexpected state: {job.status}"}

            await listing_service.update_listing_job_status(db, job_id, "scraping")
            await db.commit()

            # TODO: Port the full pipeline from listing_module.py:
            # 1. scrape_amazon_product(job.amazon_url)
            # 2. ai_analyze_and_rewrite(scraped, category_tree)
            # 3. fill_loadsheet_excel(template, ai, job)
            # 4. api.submit_loadsheet(template_id, excel_bytes, name)
            # For now, mark as pending for manual processing
            await listing_service.update_listing_job_status(
                db, job_id, "pending",
                error_code="NOT_IMPLEMENTED",
                error_msg="Listing pipeline not yet ported to Celery",
            )
            await db.commit()
            return {"ok": True, "job_id": job_id, "status": "pending"}

    try:
        return _run_async(_process())
    except Exception as exc:
        logger.error("process_listing_job(%d) failed: %s", job_id, exc)
        raise self.retry(exc=exc)


@celery_app.task(name="app.tasks.listing_tasks.recover_stale_jobs")
def recover_stale_listing_jobs():
    """Periodic task: recover listing jobs stuck in running states."""
    async def _recover():
        from app.database import task_db_session
        from app.services import listing_service

        async with task_db_session() as db:
            recovered = await listing_service.recover_stale_jobs(db)
            await db.commit()
            if recovered:
                logger.info("Recovered %d stale listing jobs: %s", len(recovered), recovered)
                for jid in recovered:
                    process_listing_job.delay(jid)
            return {"recovered": len(recovered)}

    return _run_async(_recover())
