"""Library service — product library CRUD, scraping engine, quarantine, memory.

Ported from the old scrape_api.py + database.py library functions.
Architecture: async SQLAlchemy (PostgreSQL) + httpx for Takealot API.

Performance optimizations for 2000 concurrent users:
- completeness_score pre-computed in upsert (index-backed ORDER BY)
- Periodic commit during long scrapes (no hour-long transactions)
- Redis caching for stats/filters
- N+1 query elimination in remember_selection_batch
- LIKE wildcard escaping for keyword searches
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime

import httpx
from sqlalchemy import String, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.library import (
    AutoSelectionProduct,
    LibraryProduct,
    LibraryProductQuarantine,
    SelectionMemory,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — ported from scrape_api.py
# ---------------------------------------------------------------------------

TAKEALOT_API_BASE = "https://api.takealot.com/rest/v-1-10-0/searches/products"
PAGE_SIZE = 100
REQUEST_DELAY = 0.6
MAX_RETRIES = 5
HTTP_429_COOLDOWN = 90

HEADERS = {
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.takealot.com/",
}

# 25 official Takealot departments
DEPARTMENTS = [
    "Books", "Home & Kitchen", "Fashion", "Garden, Pool & Patio",
    "Office & Stationery", "Computers & Tablets", "Toys",
    "Cellphones & Wearables", "Beauty", "DIY Tools & Machinery",
    "Automotive", "Health", "Sport", "Camping & Outdoors",
    "Baby & Toddler", "Cameras", "Luggage & Travel", "Pets",
    "Household, Food & Beverages", "Music", "TV, Audio & Video",
    "Gaming", "Movies & Series", "Liquor", "Vouchers",
]

OFFICIAL_CATEGORIES = set(DEPARTMENTS)
DEPARTMENT_SLUGS = {
    label: re.sub(r"[^a-z0-9]+", "-", label.lower().replace("&", " ").replace(",", " ")).strip("-")
    for label in DEPARTMENTS
}

# Redis cache TTLs
_STATS_CACHE_TTL = 60       # stats refreshed every 60s
_FILTERS_CACHE_TTL = 300    # filter dropdowns refreshed every 5min
_AUTO_SCRAPE_STATUS_KEY = "library:auto_scrape:status"


def _gen_price_slices() -> list[tuple[int, int]]:
    """Generate ~1,080 fine-grained price slices for full-site coverage."""
    slices = []
    for i in range(0, 200, 2):
        slices.append((i, i + 2))
    for i in range(200, 1000, 5):
        slices.append((i, i + 5))
    for i in range(1000, 3000, 10):
        slices.append((i, i + 10))
    for i in range(3000, 10000, 25):
        slices.append((i, i + 25))
    for i in range(10000, 30000, 100):
        slices.append((i, i + 100))
    for i in range(30000, 100000, 500):
        slices.append((i, i + 500))
    return slices


PRICE_SLICES = _gen_price_slices()


def _compute_completeness_score(p: dict) -> int:
    """Pre-compute completeness score for indexed sorting.

    Score 0-4 based on data completeness: reviews, rating, brand, latest_review.
    """
    score = 0
    if (p.get("reviews_total") or 0) > 0:
        score += 1
    if (p.get("star_rating") or 0) > 0:
        score += 1
    if p.get("brand"):
        score += 1
    if p.get("latest_review_at"):
        score += 1
    return score


def _escape_like(s: str) -> str:
    """Escape LIKE/ILIKE special characters to prevent wildcard injection."""
    return re.sub(r'([%_\\])', r'\\\1', s)


def _resolve_department_slug(label: str) -> str:
    value = str(label or "").strip()
    return DEPARTMENT_SLUGS.get(value, "")


def _extract_leadtime_bounds(status_text: str) -> tuple[int, int] | None:
    status = str(status_text or "").strip()
    if not status:
        return None

    normalized = status.lower()
    if normalized in {"available now", "in stock"}:
        return (0, 0)
    if normalized.startswith("pre-order"):
        return None

    match = re.search(r"ships in\s+(\d+)\s*-\s*(\d+)\s*work day", normalized)
    if match:
        return (int(match.group(1)), int(match.group(2)))

    match = re.search(r"ships in\s+(\d+)\s*work day", normalized)
    if match:
        day = int(match.group(1))
        return (day, day)

    return None


def _matches_leadtime_window(status_text: str, lead_min: int, lead_max: int) -> bool:
    if lead_min <= 0 and lead_max >= 999:
        return True

    bounds = _extract_leadtime_bounds(status_text)
    if bounds is None:
        return False

    low, high = bounds
    return not (high < lead_min or low > lead_max)


# ---------------------------------------------------------------------------
# Takealot API fetching (async httpx)
# ---------------------------------------------------------------------------

async def _fetch_api(
    client: httpx.AsyncClient,
    params: dict,
    retries: int = MAX_RETRIES,
) -> dict | None:
    """Fetch from Takealot search API with retry and 429 handling."""
    url = TAKEALOT_API_BASE
    for attempt in range(retries):
        try:
            resp = await client.get(url, params=params, timeout=25)
            if resp.status_code == 429:
                wait = min(HTTP_429_COOLDOWN, 30 * (attempt + 1))
                logger.warning("Takealot 429 rate limit, attempt %d/%d, sleeping %ds", attempt + 1, retries, wait)
                await _async_sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            if attempt < retries - 1:
                await _async_sleep(2 ** attempt + 0.5)
                continue
            logger.error("API fetch failed after %d attempts: %s", retries, e)
        except Exception as e:
            if attempt < retries - 1:
                await _async_sleep(2 ** attempt + 0.5)
                continue
            logger.error("API fetch error after %d attempts: %s", retries, e)
    logger.warning("All %d API fetch retries exhausted, returning None", retries)
    return None


async def _async_sleep(seconds: float):
    """Async sleep helper."""
    import asyncio
    await asyncio.sleep(seconds)


# ---------------------------------------------------------------------------
# Product parsing — ported from _parse_product_full()
# ---------------------------------------------------------------------------

def _parse_product_full(raw: dict) -> dict | None:
    """Parse Takealot API result into library_products schema."""
    try:
        pv = raw["product_views"]
        core = pv["core"]
        stock = pv["stock_availability_summary"]
        buybox = pv["buybox_summary"]
        gallery = pv["gallery"]
        rs = pv.get("review_summary") or {}
        dist = rs.get("distribution") or {}

        prices = buybox.get("prices") or []
        sell_price = float(prices[0]) if prices else 0.0
        if sell_price <= 0:
            return None

        tid = core.get("id") or buybox.get("product_id")
        if not tid:
            return None
        tsin = buybox.get("tsin")
        slug = core.get("slug", "")

        images = gallery.get("images") or []
        image_raw = images[0] if images else ""
        image_url = image_raw.replace("{size}", "zoom") if image_raw else ""

        # Build Takealot product URL
        takealot_url = f"https://www.takealot.com/{slug}/PLID{tid}" if slug else ""

        status_text = stock.get("status", "")
        is_preorder = 1 if buybox.get("is_preorder") else 0
        original_price = float(buybox.get("listing_price") or sell_price)
        pretty_price = str(buybox.get("pretty_price") or f"R {sell_price:.2f}")
        saving = str(buybox.get("saving") or "")

        # Category hierarchy
        category_data = core.get("category") or {}
        category_main = category_data.get("name") or ""

        return {
            "product_id": int(tid),
            "tsin": int(tsin) if tsin else None,
            "title": core.get("title", ""),
            "brand": core.get("brand") or "",
            "slug": slug,
            "url": takealot_url,
            "image": image_url,
            "category_main": category_main,
            "category_l1": None,
            "category_l2": None,
            "category_l3": None,
            "price_min": sell_price,
            "price_max": original_price,
            "pretty_price": pretty_price,
            "saving": saving,
            "star_rating": float(rs.get("star_rating") or core.get("star_rating") or 0),
            "reviews_total": int(rs.get("review_count") or core.get("reviews") or 0),
            "reviews_5": int(dist.get("num_5_star_ratings") or 0),
            "reviews_4": int(dist.get("num_4_star_ratings") or 0),
            "reviews_3": int(dist.get("num_3_star_ratings") or 0),
            "reviews_2": int(dist.get("num_2_star_ratings") or 0),
            "reviews_1": int(dist.get("num_1_star_ratings") or 0),
            "latest_review_at": None,
            "in_stock": status_text,
            "stock_dist": None,
            "is_preorder": is_preorder,
            "best_store": None,
            "offer_count": 0,
            "updated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        }
    except Exception as e:
        logger.warning("parse product failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Core scraping engine — ported from scrape_to_library()
# ---------------------------------------------------------------------------

async def scrape_to_library(
    db: AsyncSession,
    redis,
    user_id: int,
    categories: list[str] | None = None,
    lead_min: int = 0,
    lead_max: int = 999,
    min_price: float | None = None,
    max_price: float | None = None,
    max_per_cat: int = 0,
    lock_heartbeat=None,
) -> int:
    """Full-site HTTP API scraping: department x price slices x cursor pagination.

    Writes to library_products via PostgreSQL upsert.
    Progress is stored in Redis for frontend polling.
    Stop signal is checked via Redis key.

    IMPORTANT: Commits periodically to avoid long-running transactions that
    block other users and cause WAL bloat (C-2 fix).
    """
    progress_key = f"scrape_progress:{user_id}"
    stop_key = f"scrape_stop:{user_id}"

    depts = categories if categories else DEPARTMENTS

    # Build price slices
    if max_per_cat and max_per_cat > 0:
        active_slices = [(0, 100000)]
    else:
        active_slices = list(PRICE_SLICES)

    if min_price is not None or max_price is not None:
        lo_bound = min_price or 0
        hi_bound = max_price or 100000
        active_slices = [
            (lo, hi) for lo, hi in active_slices
            if hi > lo_bound and lo < hi_bound
        ]

    total_depts = len(depts)
    total = 0
    start_time = time.time()

    async def ensure_lock_alive():
        if not lock_heartbeat:
            return
        ok = await lock_heartbeat()
        if ok is False:
            raise RuntimeError("Library scrape lock lost")

    async def update_progress(**kw):
        await ensure_lock_alive()
        data = {
            "running": True,
            "mode": "scraping",
            "total_scraped": total,
            "round": 1,
            "current_cat": "",
            "total_cats": total_depts,
            "done_cats": 0,
            "error": None,
            "elapsed_sec": round(time.time() - start_time, 1),
            "last_event": "",
        }
        data.update(kw)
        await redis.setex(progress_key, 7200, json.dumps(data))

    async def check_stop() -> bool:
        val = await redis.get(stop_key)
        return bool(val)

    await update_progress(current_cat="Preparing...", last_event="Starting library scrape")

    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True) as client:
        for dept_idx, dept in enumerate(depts):
            await ensure_lock_alive()
            if await check_stop():
                break

            dept_scraped = 0
            batch: list[dict] = []
            dept_slug = _resolve_department_slug(dept)
            if not dept_slug:
                logger.warning("Skipping unknown Takealot department label: %s", dept)
                continue

            await update_progress(
                current_cat=f"{dept} (0/{max_per_cat if max_per_cat > 0 else '...'})",
                done_cats=dept_idx,
            )

            for lo, hi in active_slices:
                await ensure_lock_alive()
                if await check_stop():
                    break

                if max_per_cat > 0 and dept_scraped >= max_per_cat:
                    break

                # Build filter string using current Takealot public API format.
                filter_str = ",".join([
                    "Available:true",
                    f"Price:{lo}-{hi}",
                ])

                is_after = ""
                seen_cursors: set[str] = set()
                while True:
                    await ensure_lock_alive()
                    if await check_stop():
                        break
                    if max_per_cat > 0 and dept_scraped >= max_per_cat:
                        break

                    params = {
                        "qsearch": "*",
                        "rows": PAGE_SIZE,
                        "sort": "ReleaseDate Descending",
                        "department_slug": dept_slug,
                        "filter": filter_str,
                    }
                    if is_after:
                        params["is_after"] = is_after

                    data = await _fetch_api(client, params)
                    if not data:
                        break

                    sec = data.get("sections", {}).get("products", {})
                    results = sec.get("results") or []
                    if not results:
                        break

                    for raw in results:
                        if max_per_cat > 0 and dept_scraped >= max_per_cat:
                            break
                        p = _parse_product_full(raw)
                        if p and _matches_leadtime_window(p.get("in_stock") or "", lead_min, lead_max):
                            p["category_main"] = dept
                            batch.append(p)
                            dept_scraped += 1

                    # Flush batch every 500 + COMMIT to release transaction (C-2 fix)
                    if len(batch) >= 500:
                        n = await _upsert_library_batch(db, batch)
                        total += n
                        batch = []
                        await db.commit()
                        await update_progress(total_scraped=total)

                    # Cursor pagination
                    paging = sec.get("paging") or {}
                    next_cursor = paging.get("next_is_after", "")
                    if not next_cursor or next_cursor == is_after or next_cursor in seen_cursors:
                        if next_cursor and next_cursor in seen_cursors:
                            logger.warning(
                                "Library scrape cursor loop detected: dept=%s price=%s-%s cursor=%s",
                                dept_slug,
                                lo,
                                hi,
                                next_cursor,
                            )
                        break
                    seen_cursors.add(next_cursor)
                    is_after = next_cursor
                    await _async_sleep(REQUEST_DELAY)

                await _async_sleep(REQUEST_DELAY * 0.5)

            # Flush remaining batch for this department + commit
            if batch:
                n = await _upsert_library_batch(db, batch)
                total += n
                batch = []
                await db.commit()

            await update_progress(
                done_cats=dept_idx + 1,
                total_scraped=total,
                current_cat=f"{dept} done ({dept_scraped})",
            )
            logger.info(
                "Library scrape: dept=%s scraped=%d total=%d",
                dept, dept_scraped, total,
            )

    # Invalidate stats/filters cache after scrape
    try:
        await redis.delete("library:stats:cache", "library:filters:brands")
    except Exception:
        pass

    # Done
    await update_progress(
        running=False,
        mode="done",
        done_cats=total_depts,
        total_scraped=total,
        current_cat="Complete",
        last_event=f"Scraped {total} products from {total_depts} departments",
    )
    return total


async def _upsert_library_batch(
    db: AsyncSession,
    batch: list[dict],
) -> int:
    """Bulk upsert products into library_products using PostgreSQL ON CONFLICT.

    Pre-computes completeness_score for indexed sorting (C-1 fix).
    Deduplicates by product_id to avoid CardinalityViolationError.
    """
    if not batch:
        return 0

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    # Deduplicate by product_id — keep last occurrence (most recent data)
    seen: dict[int, dict] = {}
    for p in batch:
        p["updated_at"] = now
        # Auto-compute reviews_total from distribution if missing
        if not p.get("reviews_total"):
            dist_sum = sum(
                int(p.get(f"reviews_{i}", 0) or 0) for i in range(1, 6)
            )
            if dist_sum > 0:
                p["reviews_total"] = dist_sum
        # Pre-compute completeness score (C-1: enables indexed ORDER BY)
        p["completeness_score"] = _compute_completeness_score(p)
        pid = p.get("product_id")
        if pid is not None:
            seen[pid] = p
    rows = list(seen.values())
    if not rows:
        return 0

    from sqlalchemy import case

    stmt = pg_insert(LibraryProduct).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["product_id"],
        set_={
            "tsin": func.coalesce(stmt.excluded.tsin, LibraryProduct.tsin),
            "title": func.coalesce(stmt.excluded.title, LibraryProduct.title),
            "brand": case(
                (stmt.excluded.brand != "", stmt.excluded.brand),
                else_=func.coalesce(LibraryProduct.brand, stmt.excluded.brand),
            ),
            "slug": stmt.excluded.slug,
            "url": stmt.excluded.url,
            "image": stmt.excluded.image,
            "category_main": stmt.excluded.category_main,
            "category_l1": func.coalesce(stmt.excluded.category_l1, LibraryProduct.category_l1),
            "category_l2": func.coalesce(stmt.excluded.category_l2, LibraryProduct.category_l2),
            "category_l3": func.coalesce(stmt.excluded.category_l3, LibraryProduct.category_l3),
            "price_min": stmt.excluded.price_min,
            "price_max": stmt.excluded.price_max,
            "pretty_price": stmt.excluded.pretty_price,
            "saving": case(
                (stmt.excluded.saving != "", stmt.excluded.saving),
                else_=func.coalesce(LibraryProduct.saving, stmt.excluded.saving),
            ),
            "star_rating": stmt.excluded.star_rating,
            "reviews_total": stmt.excluded.reviews_total,
            "reviews_5": stmt.excluded.reviews_5,
            "reviews_4": stmt.excluded.reviews_4,
            "reviews_3": stmt.excluded.reviews_3,
            "reviews_2": stmt.excluded.reviews_2,
            "reviews_1": stmt.excluded.reviews_1,
            "latest_review_at": func.coalesce(
                stmt.excluded.latest_review_at, LibraryProduct.latest_review_at
            ),
            "in_stock": stmt.excluded.in_stock,
            "stock_dist": func.coalesce(stmt.excluded.stock_dist, LibraryProduct.stock_dist),
            "is_preorder": stmt.excluded.is_preorder,
            "best_store": func.coalesce(stmt.excluded.best_store, LibraryProduct.best_store),
            "offer_count": stmt.excluded.offer_count,
            "updated_at": stmt.excluded.updated_at,
            "completeness_score": stmt.excluded.completeness_score,
        },
    )
    await db.execute(stmt)
    await db.flush()
    return len(rows)


async def count_library_products(db: AsyncSession) -> int:
    result = await db.execute(select(func.count()).select_from(LibraryProduct))
    return int(result.scalar_one() or 0)


# ---------------------------------------------------------------------------
# Library product queries
# ---------------------------------------------------------------------------

async def query_library_products(
    db: AsyncSession,
    *,
    user_id: int | None = None,
    keyword: str = "",
    category_main: str = "",
    brand: str = "",
    min_price: float | None = None,
    max_price: float | None = None,
    min_rating: float | None = None,
    min_reviews: int | None = None,
    stock_type: str = "",
    review_after: str = "",
    page: int = 1,
    page_size: int = 50,
) -> dict:
    """Query library products with comprehensive filters, matching old UI capabilities.

    Performance: Uses pre-computed completeness_score column for ORDER BY
    instead of runtime CASE expressions (C-1 fix). This allows PostgreSQL
    to use an index for sorting, critical for 2000 concurrent users.
    """
    # H-4 fix: Don't add useless IN(25 depts) filter that covers 99%+ of rows.
    # Invalid categories are cleaned by cleanup_invalid_categories() periodic task.
    query = select(LibraryProduct)

    if keyword:
        # M-7 fix: Escape LIKE wildcards to prevent injection
        kw = f"%{_escape_like(keyword)}%"
        query = query.where(
            LibraryProduct.title.ilike(kw)
            | func.cast(LibraryProduct.product_id, String).ilike(kw)
        )
    if category_main:
        query = query.where(LibraryProduct.category_main == category_main)
    if brand == "has_brand":
        query = query.where(
            LibraryProduct.brand.isnot(None),
            LibraryProduct.brand != "",
        )
    elif brand == "no_brand":
        query = query.where(
            (LibraryProduct.brand.is_(None)) | (LibraryProduct.brand == "")
        )
    elif brand:
        query = query.where(LibraryProduct.brand.ilike(f"%{_escape_like(brand)}%"))
    if min_price is not None:
        query = query.where(LibraryProduct.price_min >= min_price)
    if max_price is not None:
        query = query.where(LibraryProduct.price_min <= max_price)
    if min_rating is not None and min_rating > 0:
        query = query.where(LibraryProduct.star_rating >= min_rating)
    if min_reviews is not None and min_reviews > 0:
        query = query.where(LibraryProduct.reviews_total >= min_reviews)

    # Stock type filters
    if stock_type == "in_stock":
        query = query.where(
            (LibraryProduct.in_stock == "In stock")
            | (LibraryProduct.in_stock == "Available now")
        )
    elif stock_type == "ships":
        query = query.where(LibraryProduct.in_stock.ilike("Ships in%"))
    elif stock_type == "preorder":
        query = query.where(LibraryProduct.in_stock.ilike("Pre-order%"))
    elif stock_type == "out":
        query = query.where(LibraryProduct.in_stock.ilike("%out of stock%"))

    # Review date filter — compare actual date, not just non-null check
    if review_after:
        query = query.where(
            LibraryProduct.latest_review_at.isnot(None),
            LibraryProduct.latest_review_at != "",
            LibraryProduct.latest_review_at >= review_after,
        )

    # Count
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar_one()

    # C-1 fix: Use pre-computed completeness_score for ORDER BY (index-backed)
    query = query.order_by(
        LibraryProduct.completeness_score.desc(),
        LibraryProduct.reviews_total.desc().nullslast(),
        LibraryProduct.star_rating.desc().nullslast(),
        LibraryProduct.updated_at.desc().nullslast(),
    )

    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    products = list(result.scalars().all())

    items = []
    for p in products:
        items.append({
            "product_id": p.product_id,
            "tsin": p.tsin,
            "title": p.title,
            "brand": p.brand or "",
            "slug": p.slug,
            "url": p.url,
            "image": p.image,
            "category_main": p.category_main,
            "category_l1": p.category_l1,
            "price_min": p.price_min,
            "price_max": p.price_max,
            "pretty_price": p.pretty_price,
            "saving": p.saving,
            "star_rating": p.star_rating,
            "reviews_total": p.reviews_total or 0,
            "reviews_5": p.reviews_5,
            "reviews_4": p.reviews_4,
            "reviews_3": p.reviews_3,
            "reviews_2": p.reviews_2,
            "reviews_1": p.reviews_1,
            "latest_review_at": p.latest_review_at,
            "in_stock": p.in_stock,
            "is_preorder": p.is_preorder,
            "offer_count": p.offer_count,
            "updated_at": p.updated_at,
        })

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    }


async def get_library_stats(db: AsyncSession, redis=None) -> dict:
    """Return comprehensive library statistics with Redis caching (M-2 fix).

    Stats are expensive (5 COUNT queries). Cache for 60s to avoid
    hammering PostgreSQL with 2000 concurrent page loads.
    """
    cache_key = "library:stats:cache"

    stats = None

    # Try Redis cache first
    if redis:
        try:
            cached = await redis.get(cache_key)
            if cached:
                stats = json.loads(cached)
        except Exception:
            pass

    if stats is None:
        # Single query for total + categories + brands + last_updated (M-2 optimization)
        result = await db.execute(
            select(
                func.count(),
                func.count(func.distinct(LibraryProduct.category_main)),
                func.count(func.distinct(
                    func.nullif(LibraryProduct.brand, "")
                )),
                func.max(LibraryProduct.updated_at),
            ).select_from(LibraryProduct)
        )
        row = result.one()
        total, categories, brands, last_updated = row

        quarantined = (await db.execute(
            select(func.count()).select_from(LibraryProductQuarantine)
        )).scalar_one()

        stats = {
            "total_products": total,
            "quarantined": quarantined,
            "categories": categories,
            "brands": brands,
            "last_updated": last_updated,
        }

        # Cache in Redis
        if redis:
            try:
                await redis.setex(cache_key, _STATS_CACHE_TTL, json.dumps(stats))
            except Exception:
                pass

    auto_scrape = {
        "running": False,
        "status": "idle",
        "last_started_at": None,
        "last_finished_at": None,
        "last_task_id": None,
        "last_total_scraped": 0,
        "last_new_products": 0,
        "last_error": None,
    }
    if redis:
        try:
            raw = await redis.get(_AUTO_SCRAPE_STATUS_KEY)
            if raw:
                payload = json.loads(raw)
                if isinstance(payload, dict):
                    auto_scrape.update({
                        key: payload[key]
                        for key in auto_scrape.keys()
                        if key in payload
                    })
        except Exception:
            pass

    return {**stats, "auto_scrape": auto_scrape}


async def get_library_filters(db: AsyncSession, redis=None) -> dict:
    """Return distinct categories and brands for filter dropdowns (M-1 fix).

    Brands are cached in Redis for 5 minutes since they change slowly.
    """
    cache_key = "library:filters:brands"

    # Try Redis cache for brands
    cached_brands = None
    if redis:
        try:
            raw = await redis.get(cache_key)
            if raw:
                cached_brands = json.loads(raw)
        except Exception:
            pass

    if cached_brands is not None:
        return {"categories": list(DEPARTMENTS), "brands": cached_brands}

    # Query brands from DB
    result = await db.execute(
        select(func.distinct(LibraryProduct.brand))
        .where(
            LibraryProduct.brand.isnot(None),
            LibraryProduct.brand != "",
        )
        .order_by(LibraryProduct.brand)
        .limit(500)
    )
    brands = [row[0] for row in result.all()]

    # Cache in Redis
    if redis:
        try:
            await redis.setex(cache_key, _FILTERS_CACHE_TTL, json.dumps(brands))
        except Exception:
            pass

    return {"categories": list(DEPARTMENTS), "brands": brands}


# ---------------------------------------------------------------------------
# Quarantine
# ---------------------------------------------------------------------------

async def quarantine_products(
    db: AsyncSession,
    product_ids: list[int],
    reason: str,
) -> dict:
    """Move products to quarantine with JSON snapshot, then delete from library."""
    if not product_ids:
        return {"requested": 0, "removed": 0, "reason": reason}

    # Deduplicate
    unique_ids = list(set(pid for pid in product_ids if pid > 0))
    result = await db.execute(
        select(LibraryProduct).where(LibraryProduct.product_id.in_(unique_ids))
    )
    products = list(result.scalars().all())

    removed = 0
    for p in products:
        snapshot = {
            "product_id": p.product_id, "tsin": p.tsin, "title": p.title,
            "brand": p.brand, "category_main": p.category_main,
            "price_min": p.price_min, "star_rating": p.star_rating,
            "reviews_total": p.reviews_total, "in_stock": p.in_stock,
            "updated_at": p.updated_at,
        }
        q_entry = LibraryProductQuarantine(
            product_id=p.product_id,
            removed_reason=reason,
            snapshot_json=json.dumps(snapshot, ensure_ascii=False),
        )
        db.add(q_entry)
        await db.delete(p)
        removed += 1

    await db.flush()
    return {
        "requested": len(unique_ids),
        "removed": removed,
        "missing": len(unique_ids) - removed,
        "reason": reason,
    }


async def cleanup_invalid_categories(db: AsyncSession) -> dict:
    """Archive products with invalid categories to quarantine."""
    result = await db.execute(
        select(LibraryProduct.product_id).where(
            ~LibraryProduct.category_main.in_(DEPARTMENTS)
            | LibraryProduct.category_main.is_(None)
            | (LibraryProduct.category_main == "")
        )
    )
    invalid_ids = [row[0] for row in result.all()]
    if not invalid_ids:
        return {"removed": 0}
    return await quarantine_products(db, invalid_ids, "invalid_category")


# ---------------------------------------------------------------------------
# Selection memory
# ---------------------------------------------------------------------------

async def remember_selection_batch(
    db: AsyncSession,
    user_id: int,
) -> int:
    """Copy current auto_selection_products to selection_memory for deduplication.

    H-3 fix: Batch query existing IDs instead of N+1 individual SELECTs.
    """
    result = await db.execute(
        select(AutoSelectionProduct)
        .where(AutoSelectionProduct.user_id == user_id)
    )
    products = list(result.scalars().all())
    if not products:
        return 0

    # Batch fetch existing memory IDs (H-3 fix: eliminates N+1 query)
    product_ids = [p.product_id for p in products]
    existing_result = await db.execute(
        select(SelectionMemory.product_id).where(
            SelectionMemory.user_id == user_id,
            SelectionMemory.product_id.in_(product_ids),
        )
    )
    existing_ids = {row[0] for row in existing_result.all()}

    inserted = 0
    for p in products:
        if p.product_id in existing_ids:
            continue

        mem = SelectionMemory(
            user_id=user_id,
            product_id=p.product_id,
            plid=f"PLID{p.product_id}",
            title=p.title or "",
            category_main=p.category_main or "",
        )
        db.add(mem)
        inserted += 1

    await db.flush()
    return inserted


async def get_remembered_ids(db: AsyncSession, user_id: int) -> set[int]:
    """Get all remembered product IDs for a user."""
    result = await db.execute(
        select(SelectionMemory.product_id)
        .where(SelectionMemory.user_id == user_id)
    )
    return {row[0] for row in result.all()}


# ---------------------------------------------------------------------------
# Library product detail
# ---------------------------------------------------------------------------

async def get_library_product(
    db: AsyncSession, product_id: int,
) -> dict | None:
    """Get a single library product by ID."""
    result = await db.execute(
        select(LibraryProduct).where(LibraryProduct.product_id == product_id)
    )
    p = result.scalar_one_or_none()
    if not p:
        return None
    return {
        "product_id": p.product_id,
        "tsin": p.tsin,
        "title": p.title,
        "brand": p.brand,
        "slug": p.slug,
        "url": p.url,
        "image": p.image,
        "category_main": p.category_main,
        "category_l1": p.category_l1,
        "category_l2": p.category_l2,
        "category_l3": p.category_l3,
        "price_min": p.price_min,
        "price_max": p.price_max,
        "pretty_price": p.pretty_price,
        "saving": p.saving,
        "star_rating": p.star_rating,
        "reviews_total": p.reviews_total,
        "reviews_5": p.reviews_5,
        "reviews_4": p.reviews_4,
        "reviews_3": p.reviews_3,
        "reviews_2": p.reviews_2,
        "reviews_1": p.reviews_1,
        "latest_review_at": p.latest_review_at,
        "in_stock": p.in_stock,
        "stock_dist": p.stock_dist,
        "is_preorder": p.is_preorder,
        "best_store": p.best_store,
        "offer_count": p.offer_count,
        "updated_at": p.updated_at,
    }
