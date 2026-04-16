"""886it Amazon API client — keyword search and product detail fetching.

Uses the 886it third-party Amazon scraping service:
- Keyword search: search Amazon US by keyword, returns ASINs
- Detail fetch: get full product data (title, brand, images, bullets, etc.)
"""
from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

LISTING_PAGE_URL = "https://www.886it.cn/amazon-fast-spider"
DETAIL_API_URL = "https://www.886it.cn/api/amazon/get_info_ontime"
KEY_SEARCH_PAGE_URL = "https://www.886it.cn/amazon-fast-spider/keyword-search"
KEY_SEARCH_API_URL = "https://www.886it.cn/api/amazon/key_search"

# Module-level token cache
_token_cache: dict[str, Any] = {"token": "", "ts": 0.0}


def _get_api_key() -> str:
    return get_settings().amazon_886it_api_key


async def _fetch_token(page_url: str) -> str:
    """Fetch CSRF-like token from 886it page."""
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(page_url)
        match = re.search(r"var\s+token_php\s*=\s*'([^']+)'", resp.text)
        if not match:
            raise RuntimeError(f"886it token not found from {page_url}")
        return match.group(1)


async def _get_listing_token() -> str:
    import time
    if _token_cache["token"] and time.time() - float(_token_cache["ts"]) < 300:
        return str(_token_cache["token"])
    token = await _fetch_token(LISTING_PAGE_URL)
    _token_cache["token"] = token
    _token_cache["ts"] = time.time()
    return token


async def _get_key_search_token() -> str:
    return await _fetch_token(KEY_SEARCH_PAGE_URL)


def _pick_main_image(product_data: dict) -> str:
    main_image = product_data.get("main_image")
    if isinstance(main_image, dict):
        link = str(main_image.get("link") or "").strip()
        if link:
            return link
    images = product_data.get("images") or []
    for img in images:
        if isinstance(img, dict):
            link = str(img.get("link") or "").strip()
            if link:
                return link
        elif isinstance(img, str) and img.strip():
            return img.strip()
    return ""


async def key_search(
    keyword: str,
    country_code: str = "US",
    page: int = 1,
    timeout: int = 90,
) -> dict[str, Any]:
    """Search Amazon by keyword via 886it API. Returns list of ASINs."""
    key = _get_api_key()
    if not key:
        return {"ok": False, "error": "886it API key missing", "results": []}

    try:
        token = await _get_key_search_token()
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                KEY_SEARCH_API_URL,
                data={
                    "keyword": keyword,
                    "country_code": country_code,
                    "page": page,
                    "key": key,
                    "spider_type": "key_search",
                    "token": token,
                },
            )
            text = resp.text
            if not text.strip().startswith("{"):
                return {
                    "ok": False,
                    "error": f"886it key_search non-json response (HTTP {resp.status_code})",
                    "results": [],
                }
            payload = resp.json()
    except Exception as exc:
        return {"ok": False, "error": f"886it key_search exception: {exc}", "results": []}

    results = payload.get("search_results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return {"ok": False, "error": "886it key_search results missing", "results": []}

    normalized = []
    for item in results:
        asin = str(item.get("asin") or "").strip()
        if not asin:
            continue
        normalized.append({
            "asin": asin,
            "amazon_url": f"https://www.amazon.com/dp/{asin}",
            "image_url": str(item.get("img_url") or "").strip(),
            "price": str(item.get("price") or "").strip(),
            "rating": str(item.get("rating") or "").strip(),
            "review_count": item.get("review_count"),
            "is_sponsored": bool(item.get("is_sponsored")),
        })

    return {
        "ok": True,
        "keyword": payload.get("keyword", keyword),
        "country_code": payload.get("country_code", country_code),
        "page": payload.get("page", page),
        "total_results": payload.get("total_results"),
        "results": normalized,
    }


async def fetch_listing(url: str, timeout: int = 90, max_retries: int = 3) -> dict[str, Any]:
    """Fetch full Amazon product detail via 886it API (with retry)."""
    key = _get_api_key()
    if not key:
        return {"ok": False, "error": "886it API key missing"}

    import asyncio as _asyncio
    last_error = ""
    payload: dict[str, Any] | None = None

    for attempt in range(1, max_retries + 1):
        try:
            token = await _get_listing_token()
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    DETAIL_API_URL,
                    data={
                        "need_crawle_url": url,
                        "key": key,
                        "token": token,
                        "spider_type": "listing",
                    },
                )
                text = resp.text
                if not text.strip().startswith("{"):
                    last_error = f"886it detail non-json response (HTTP {resp.status_code})"
                    if resp.status_code >= 500 and attempt < max_retries:
                        logger.warning("886it HTTP %d, retry %d/%d ...", resp.status_code, attempt, max_retries)
                        await _asyncio.sleep(3 * attempt)
                        # Refresh token on retry
                        _token_cache["ts"] = 0.0
                        continue
                    return {"ok": False, "error": last_error}
                payload = resp.json()
                break  # success
        except Exception as exc:
            last_error = f"886it detail exception: {exc}"
            if attempt < max_retries:
                logger.warning("886it exception, retry %d/%d: %s", attempt, max_retries, exc)
                await _asyncio.sleep(3 * attempt)
                _token_cache["ts"] = 0.0
                continue
            return {"ok": False, "error": last_error}

    if not isinstance(payload, dict):
        return {"ok": False, "error": "886it returned non-dict JSON"}
    if payload.get("error"):
        return {"ok": False, "error": str(payload.get("info") or payload.get("message") or payload.get("error"))}

    product_data = payload.get("product_data")
    if not isinstance(product_data, dict):
        return {"ok": False, "error": "886it product_data missing"}

    title = str(product_data.get("title") or product_data.get("name") or "").strip()
    brand = str(product_data.get("brand") or "").strip()
    bullets = [str(x).strip() for x in (product_data.get("feature_bullets") or []) if str(x).strip()]
    description = str(
        product_data.get("description")
        or product_data.get("book_description")
        or product_data.get("product_description")
        or ""
    ).strip()

    image_urls = []
    for img in product_data.get("images") or []:
        if isinstance(img, dict):
            link = str(img.get("link") or "").strip()
        else:
            link = str(img or "").strip()
        if link and link not in image_urls:
            image_urls.append(link)
    main_image = _pick_main_image(product_data)
    if main_image and main_image not in image_urls:
        image_urls.insert(0, main_image)

    if not title:
        return {"ok": False, "error": "886it missing title"}
    if not description and bullets:
        description = " ".join(bullets)

    return {
        "ok": True,
        "source": "886it",
        "asin": str(payload.get("asin") or "").strip(),
        "title": title,
        "brand": brand,
        "description": description,
        "bullets": bullets,
        "image_url": main_image,
        "image_urls": image_urls,
        "amazon_url": url,
        "categories": product_data.get("categories") or [],
        "buybox_winner": product_data.get("buybox_winner") or {},
    }
