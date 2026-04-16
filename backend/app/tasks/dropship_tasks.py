"""Dropship job Celery tasks — keyword import, job processing, recovery."""
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


@celery_app.task(bind=True, max_retries=1, default_retry_delay=60, queue="listing")
def process_dropship_job(self, job_id: int):
    """Process a single dropship job: scrape → match → AI → fill → submit.

    Full pipeline:
      1. Scrape Amazon product via 886it API
      2. Match images against 1688 (pHash similarity)
      3. DeepSeek AI rewrite for Takealot
      4. Download loadsheet template + fill Excel
      5. Submit loadsheet to Takealot Seller API
    """
    async def _process():
        import json as _json
        from sqlalchemy import select

        from app.database import task_db_session
        from app.models.store import StoreBinding
        from app.services import amazon_886it, dropship_service
        from app.services.ai_rewrite_service import ai_analyze_and_rewrite
        from app.services.image_match_service import match_best_amazon_image
        from app.services.loadsheet_service import fill_loadsheet_excel
        from app.services.takealot_api import TakealotSellerAPI
        from app.utils.encryption import decrypt

        async with task_db_session() as db:
            job = await dropship_service.get_dropship_job(db, job_id)
            if not job:
                return {"ok": False, "error": "job not found"}

            if job.status not in ("pending", "dispatching"):
                return {"ok": False, "error": f"job in unexpected state: {job.status}"}

            # ── Step 1: Scrape Amazon product ──
            await dropship_service.update_dropship_job_status(db, job_id, "scraping")
            await db.commit()

            scraped = await amazon_886it.fetch_listing(job.amazon_url)
            if not scraped.get("ok"):
                await dropship_service.update_dropship_job_status(
                    db, job_id, "failed",
                    error_code="SCRAPE_FAILED",
                    error_msg=f"Amazon 抓取失败: {scraped.get('error', 'unknown')}",
                )
                await db.commit()
                return {"ok": False, "job_id": job_id, "error": "scrape failed"}

            # Save scraped data to job
            await dropship_service.update_dropship_job_status(
                db, job_id, "matching",
                orig_title=scraped.get("title", "")[:500],
                orig_brand=scraped.get("brand", "")[:200],
                orig_description=scraped.get("description", "")[:2000],
                orig_bullets="\n".join(scraped.get("bullets", []))[:2000],
                barcode=scraped.get("barcode", ""),
            )
            await db.commit()

            # Collect image URLs (amazon_886it returns "image_urls")
            image_urls = list(scraped.get("image_urls") or scraped.get("images") or [])
            main_img = scraped.get("main_image") or scraped.get("image_url") or ""
            if main_img and main_img not in image_urls:
                image_urls.insert(0, main_img)
            if job.image_url and job.image_url not in image_urls:
                image_urls.insert(0, job.image_url)

            if not image_urls:
                await dropship_service.update_dropship_job_status(
                    db, job_id, "failed",
                    error_code="NO_IMAGES",
                    error_msg="Amazon 商品没有可用图片",
                )
                await db.commit()
                return {"ok": False, "job_id": job_id, "error": "no images"}

            # ── Step 2: 1688 Image matching ──
            match_result = await match_best_amazon_image(image_urls, max_images=4)
            similarity = match_result.get("similarity_pct", 0)
            threshold = job.similarity_threshold or 65

            await dropship_service.update_dropship_job_status(
                db, job_id, "matching",
                matched_similarity=similarity,
                matched_image_url=match_result.get("matched_image_url", ""),
                matched_1688_url=match_result.get("link", ""),
                matched_1688_title=match_result.get("title", "")[:500],
                purchase_price_cny=match_result.get("price_cny", 0),
                weight_kg=match_result.get("weight_kg", 0) or scraped.get("weight_kg", 0.5),
                image_urls_json=_json.dumps(image_urls[:6]),
            )
            await db.commit()

            if similarity < threshold:
                await dropship_service.update_dropship_job_status(
                    db, job_id, "failed",
                    error_code="LOW_SIMILARITY",
                    error_msg=f"1688 匹配相似度 {similarity}% 低于阈值 {threshold}%",
                )
                await db.commit()
                return {"ok": False, "job_id": job_id, "error": f"similarity {similarity}% < {threshold}%"}

            logger.info("job %d: 1688 match OK, similarity=%d%%", job_id, similarity)

            # ── Step 3: AI rewrite ──
            await dropship_service.update_dropship_job_status(db, job_id, "ai_rewriting")
            await db.commit()

            # Try to get category tree from Takealot API
            category_tree = None
            store = None
            if job.store_id:
                result = await db.execute(
                    select(StoreBinding).where(StoreBinding.id == job.store_id)
                )
                store = result.scalar_one_or_none()

            ai_result = await ai_analyze_and_rewrite(scraped, category_tree)

            if ai_result.get("error_code"):
                await dropship_service.update_dropship_job_status(
                    db, job_id, "failed",
                    error_code=ai_result.get("error_code", "AI_REWRITE_FAILED"),
                    error_msg=ai_result.get("error", "AI改写失败"),
                )
                await db.commit()
                return {"ok": False, "job_id": job_id, "error": "AI rewrite failed"}

            template_id = ai_result.get("template_id", 107)

            await dropship_service.update_dropship_job_status(
                db, job_id, "filling",
                template_id=template_id,
                top_category=ai_result.get("top_category", ""),
                lowest_category=ai_result.get("lowest_category", ""),
                listing_title=ai_result.get("listing_title", ""),
                listing_description=ai_result.get("listing_description", ""),
                package_contents=ai_result.get("package_contents", ""),
                ai_attributes=_json.dumps({
                    k: v for k, v in ai_result.items()
                    if k.startswith("is_") or k.startswith("has_") or k in (
                        "fast_charging", "warranty_months", "weight_grams",
                        "packaged_weight_grams", "color_main", "model_number",
                    )
                }),
            )
            await db.commit()

            logger.info(
                "job %d: AI rewrite OK, template=%d, title=%s",
                job_id, template_id, ai_result.get("listing_title", "")[:40],
            )

            # ── Step 4: Download template + fill loadsheet ──
            if not store:
                await dropship_service.update_dropship_job_status(
                    db, job_id, "failed",
                    error_code="NO_STORE",
                    error_msg="未关联店铺，无法提交 Loadsheet",
                )
                await db.commit()
                return {"ok": False, "job_id": job_id, "error": "no store binding"}

            raw_key = decrypt(store.api_key)
            api = TakealotSellerAPI(raw_key)

            try:
                template_bytes = await api.download_template_excel(template_id)
            except Exception as e:
                await dropship_service.update_dropship_job_status(
                    db, job_id, "failed",
                    error_code="TEMPLATE_DOWNLOAD_FAILED",
                    error_msg=f"下载模板失败: {e}",
                )
                await db.commit()
                return {"ok": False, "job_id": job_id, "error": f"template download: {e}"}

            # Prepare job data dict for loadsheet filling
            job_data = {
                "id": job.id,
                "asin": job.asin,
                "price_zar": job.price_zar,
                "weight_kg": job.weight_kg or match_result.get("weight_kg", 0.5),
                "barcode": job.barcode,
                "image_url": image_urls[0] if image_urls else "",
            }
            filled_bytes = fill_loadsheet_excel(template_bytes, ai_result, job_data)

            logger.info("job %d: loadsheet filled, size=%d bytes", job_id, len(filled_bytes))

            # ── Step 5: Submit to Takealot ──
            await dropship_service.update_dropship_job_status(db, job_id, "submitting")
            await db.commit()

            submission_name = f"DS_{job.asin or job.id}_{job_id}"
            try:
                submit_resp = await api.submit_loadsheet(
                    template_id, filled_bytes, submission_name,
                )
                submission_id = str(
                    submit_resp.get("submission_id")
                    or submit_resp.get("id")
                    or ""
                )
            except Exception as e:
                await dropship_service.update_dropship_job_status(
                    db, job_id, "failed",
                    error_code="SUBMIT_FAILED",
                    error_msg=f"提交 Loadsheet 失败: {e}",
                )
                await db.commit()
                return {"ok": False, "job_id": job_id, "error": f"submit: {e}"}

            # ── Done! ──
            await dropship_service.update_dropship_job_status(
                db, job_id, "submitted",
                submission_id=submission_id,
                error_code="",
                error_msg="",
            )
            await db.commit()

            logger.info(
                "job %d: submitted OK, submission_id=%s", job_id, submission_id,
            )
            return {"ok": True, "job_id": job_id, "submission_id": submission_id}

    try:
        return _run_async(_process())
    except Exception as exc:
        logger.error("process_dropship_job(%d) failed: %s", job_id, exc)
        # Mark as pending so retry can pick it up, store error for diagnostics
        try:
            async def _mark_for_retry():
                from app.database import task_db_session
                from app.services import dropship_service
                async with task_db_session() as db:
                    await dropship_service.update_dropship_job_status(
                        db, job_id, "pending",
                        error_code="RETRY",
                        error_msg=f"重试中: {str(exc)[:400]}",
                    )
                    await db.commit()
            _run_async(_mark_for_retry())
        except Exception:
            pass
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            # All retries exhausted — mark as permanently failed
            try:
                async def _mark_final_fail():
                    from app.database import task_db_session
                    from app.services import dropship_service
                    async with task_db_session() as db:
                        await dropship_service.update_dropship_job_status(
                            db, job_id, "failed",
                            error_code="MAX_RETRIES",
                            error_msg=f"重试耗尽: {str(exc)[:400]}",
                        )
                        await db.commit()
                _run_async(_mark_final_fail())
            except Exception:
                pass


@celery_app.task(bind=True, max_retries=0)
def run_keyword_import(
    self,
    user_id: int,
    store_id: int,
    keyword: str,
    pages: int = 5,
    threshold: int = 65,
    price_zar: float = 0,
    max_items: int = 10,
):
    """Celery task: search Amazon by keyword via 886it, create dropship jobs."""
    async def _import():
        import redis.asyncio as aioredis
        from app.config import get_settings
        from app.database import task_db_session
        from app.services import dropship_service, amazon_886it
        from app.models.listing import DropshipJob

        settings = get_settings()
        redis = aioredis.from_url(settings.redis_url, decode_responses=True)

        try:
            await dropship_service.set_keyword_progress(
                redis, user_id,
                running=True, keyword=keyword, pages=pages,
                step="searching", scraped=0, created_jobs=0,
                skipped_existing=0, skipped_duplicate=0, error="",
            )

            # --- Phase 1: Search Amazon via 886it API ---
            seed_rows: list[dict] = []
            dedup: set[str] = set()

            for page_no in range(1, pages + 1):
                await dropship_service.set_keyword_progress(
                    redis, user_id,
                    step=f"正在搜索 Amazon 第 {page_no}/{pages} 页...",
                    scraped=len(seed_rows),
                )

                search_result = await amazon_886it.key_search(
                    keyword=keyword, country_code="US", page=page_no,
                )
                if not search_result.get("ok"):
                    logger.warning(
                        "886it page=%d error: %s", page_no, search_result.get("error")
                    )
                    if seed_rows:
                        # Partial results, stop searching
                        break
                    # First page failed, no results at all
                    continue

                for item in search_result.get("results", []):
                    asin = str(item.get("asin") or "").strip()
                    amazon_url = str(item.get("amazon_url") or "").strip()
                    if not asin or not amazon_url or asin in dedup:
                        continue
                    dedup.add(asin)
                    seed_rows.append({
                        "asin": asin,
                        "amazon_url": amazon_url,
                        "image_url": item.get("image_url", ""),
                        "price": item.get("price", ""),
                    })

                if len(seed_rows) >= max_items:
                    break

            logger.info("886it keyword=%r seeds=%d", keyword, len(seed_rows))

            if not seed_rows:
                await dropship_service.set_keyword_progress(
                    redis, user_id,
                    running=False, step="failed",
                    scraped=0, created_jobs=0,
                    error="886it 关键词搜索未返回可用 Amazon 结果，请把关键词改短一些并去掉特殊符号后重试",
                )
                return {"ok": False, "keyword": keyword, "error": "no results"}

            seed_rows = seed_rows[:max_items]

            await dropship_service.set_keyword_progress(
                redis, user_id,
                step=f"搜索完成，找到 {len(seed_rows)} 个 Amazon 商品，正在创建任务...",
                scraped=len(seed_rows),
            )

            # --- Phase 2: Create dropship jobs ---
            created = 0
            skipped = 0
            job_ids: list[int] = []

            async with task_db_session() as db:
                from sqlalchemy import select

                for idx, row in enumerate(seed_rows, 1):
                    amazon_url = row["amazon_url"]
                    asin = row["asin"]

                    # Check if already exists
                    existing = await db.execute(
                        select(DropshipJob.id).where(
                            DropshipJob.user_id == user_id,
                            DropshipJob.amazon_url == amazon_url,
                        ).limit(1)
                    )
                    if existing.scalar_one_or_none():
                        skipped += 1
                        continue

                    job = DropshipJob(
                        user_id=user_id,
                        store_id=store_id,
                        amazon_url=amazon_url,
                        asin=asin,
                        source_keyword=f"{keyword}|886it_key_search",
                        image_url=row.get("image_url", ""),
                        similarity_threshold=threshold,
                        price_zar=price_zar,
                        status="pending",
                    )
                    db.add(job)
                    created += 1
                    await db.flush()
                    job_ids.append(job.id)

                    await dropship_service.set_keyword_progress(
                        redis, user_id,
                        step=f"正在创建任务 {idx}/{len(seed_rows)}...",
                        created_jobs=created,
                        skipped_existing=skipped,
                    )

                await db.commit()

            logger.info(
                "keyword-import done: keyword=%r created=%d skipped=%d seeds=%d",
                keyword, created, skipped, len(seed_rows),
            )

            # --- Phase 3: Dispatch each job for processing ---
            for jid in job_ids:
                process_dropship_job.delay(jid)

            await dropship_service.set_keyword_progress(
                redis, user_id,
                running=False, step="done",
                scraped=len(seed_rows),
                created_jobs=created,
                skipped_existing=skipped,
                error="",
            )
            return {"ok": True, "keyword": keyword, "scraped": len(seed_rows), "created": created}
        finally:
            await redis.aclose()

    try:
        return _run_async(_import())
    except Exception as exc:
        logger.error("run_keyword_import failed: %s", exc)
        try:
            async def _mark_failed():
                import redis.asyncio as aioredis
                from app.config import get_settings
                settings = get_settings()
                redis = aioredis.from_url(settings.redis_url, decode_responses=True)
                try:
                    from app.services import dropship_service
                    await dropship_service.set_keyword_progress(
                        redis, user_id, running=False, step="failed", error=str(exc),
                    )
                finally:
                    await redis.aclose()
            _run_async(_mark_failed())
        except Exception:
            pass
        raise


@celery_app.task
def recover_stale_dropship_jobs():
    """Periodic task: recover dropship jobs stuck in running states."""
    async def _recover():
        from app.database import task_db_session
        from app.services import dropship_service

        async with task_db_session() as db:
            recovered = await dropship_service.recover_stale_jobs(db)
            await db.commit()
            if recovered:
                logger.info("Recovered %d stale dropship jobs", len(recovered))
                for jid in recovered:
                    process_dropship_job.delay(jid)
            return {"recovered": len(recovered)}

    try:
        return _run_async(_recover())
    except Exception as exc:
        logger.error("recover_stale_dropship_jobs failed: %s", exc)
