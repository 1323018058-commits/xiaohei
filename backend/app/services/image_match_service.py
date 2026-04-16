"""1688 image matching service — search 1688 by image to find product sources.

Uses a self-hosted image search API that matches Amazon product images
against 1688.com (Alibaba China) products via pHash similarity.
"""
from __future__ import annotations

import io
import json
import logging
import re
import ssl
import uuid
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# 1688 API endpoints
IMAGE_SEARCH_ENDPOINT = "http://8.129.22.94:9090/offer/allegro/updateProductImg"
OFFER_DETAILS_ENDPOINT = "http://8.129.22.94:9090/offer/allegro/getOfferDetails"

try:
    import imagehash
    from PIL import Image
    _IMAGEHASH_AVAILABLE = True
except ImportError:
    _IMAGEHASH_AVAILABLE = False


def _phash_from_bytes(image_bytes: bytes) -> Any | None:
    if not _IMAGEHASH_AVAILABLE:
        return None
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        return imagehash.phash(img)
    except Exception:
        return None


def _to_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value) if float(value) == float(value) else default
    text = str(value).strip().replace(",", "")
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    return float(match.group(0)) if match else default


def _dig(obj: Any, path: str) -> Any:
    """Read nested value by dotted path, e.g. 'data.items[0].price'."""
    if not path:
        return None
    current = obj
    for part in path.split("."):
        if not part:
            return None
        for m in re.finditer(r"([^\[\]]+)|\[(\d+)\]", part):
            key, idx = m.group(1), m.group(2)
            if key is not None:
                if not isinstance(current, dict) or key not in current:
                    return None
                current = current[key]
            else:
                if not isinstance(current, list):
                    return None
                i = int(idx)
                if i < 0 or i >= len(current):
                    return None
                current = current[i]
    return current


async def _download_image(url: str) -> bytes | None:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200:
                return resp.content
    except Exception:
        pass
    return None


async def _fetch_offer_details(offer_id: str) -> dict[str, Any]:
    """Get SKU-level price and weight from 1688."""
    if not offer_id:
        return {"price_cny": 0.0, "weight_kg": 0.0}
    url = f"{OFFER_DETAILS_ENDPOINT}/{offer_id}"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, content=b"{}", headers={"Content-Type": "application/json"})
            d = resp.json()

        result = _dig(d, "data.result.result") or {}

        # Find cheapest SKU
        sku_infos = result.get("skuInfos") or []
        min_price = None
        min_price_sku = None
        all_skus = []
        for sku in sku_infos:
            if not isinstance(sku, dict):
                continue
            price = _to_float(sku.get("price") or sku.get("retailPrice"), 0.0)
            if price > 0:
                sku_data = {"price": price, "spec": sku.get("specAttrs", ""), "sku_id": sku.get("skuId", "")}
                all_skus.append(sku_data)
                if min_price is None or price < min_price:
                    min_price = price
                    min_price_sku = sku_data

        # Weight
        weight_kg = 0.0
        shipping = result.get("productShippingInfo") or {}
        sku_details = shipping.get("skuShippingDetails") or []
        if min_price_sku and sku_details:
            for detail in sku_details:
                if isinstance(detail, dict) and detail.get("skuId") == min_price_sku.get("sku_id"):
                    w = detail.get("weight")
                    if w is not None:
                        weight_kg = _to_float(w, 0.0)
                        break
        if weight_kg == 0.0 and sku_details and isinstance(sku_details[0], dict):
            w = sku_details[0].get("weight")
            if w is not None:
                weight_kg = _to_float(w, 0.0)

        return {"price_cny": min_price or 0.0, "weight_kg": weight_kg}
    except Exception:
        return {"price_cny": 0.0, "weight_kg": 0.0}


async def search_by_image(image_url: str) -> dict[str, Any]:
    """Upload an image to 1688 image search API, return best match with pHash scoring."""
    img_bytes = await _download_image(image_url)
    if not img_bytes:
        return {"ok": False, "error": f"Failed to download image: {image_url}"}

    # Multipart upload
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="image.jpg"\r\n'
        f"Content-Type: image/jpeg\r\n\r\n"
    ).encode() + img_bytes + f"\r\n--{boundary}--\r\n".encode()

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                IMAGE_SEARCH_ENDPOINT,
                content=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )
            payload = resp.json()
    except Exception as exc:
        return {"ok": False, "error": f"Image search API error: {exc}"}

    items = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(items, list) or not items:
        return {"ok": False, "error": "No results from 1688 image search"}

    # Score by pHash similarity
    query_hash = _phash_from_bytes(img_bytes)
    scored = []
    for item in items[:10]:  # Only check top 10
        thumb_url = item.get("imgUrl") or item.get("imageUrl") or ""
        dist = 999
        if query_hash is not None and thumb_url:
            thumb_bytes = await _download_image(thumb_url)
            if thumb_bytes:
                h = _phash_from_bytes(thumb_bytes)
                if h is not None:
                    dist = query_hash - h
        scored.append((dist, item))
    scored.sort(key=lambda x: x[0])

    best_dist = scored[0][0]
    best = scored[0][1]

    # Get price from best match
    offer_id = best.get("offerId", "")
    price_raw = _dig(best, "priceInfo.price") or best.get("price", "")
    price_cny = _to_float(price_raw, 0.0)
    weight_kg = 0.0

    if offer_id:
        details = await _fetch_offer_details(str(offer_id))
        if details.get("price_cny", 0) > 0:
            price_cny = details["price_cny"]
        weight_kg = details.get("weight_kg", 0.0)

    title = best.get("subjectTrans") or best.get("subject", "")
    link = f"https://detail.1688.com/offer/{offer_id}.html" if offer_id else ""
    similarity_pct = max(0, round((1 - best_dist / 64) * 100)) if best_dist < 999 else 0

    return {
        "ok": True,
        "price_cny": price_cny,
        "weight_kg": weight_kg,
        "title": str(title),
        "link": link,
        "offer_id": str(offer_id),
        "similarity_pct": similarity_pct,
        "result_count": len(items),
    }


async def match_best_amazon_image(
    image_urls: list[str], max_images: int = 4,
) -> dict[str, Any]:
    """Try several Amazon images and return the best 1688 match."""
    images = list(dict.fromkeys(image_urls))[:max_images]
    best_result = None
    best_similarity = -1

    for image_url in images:
        result = await search_by_image(image_url)
        similarity = result.get("similarity_pct", 0)
        if result.get("ok") and similarity > best_similarity:
            best_result = dict(result)
            best_result["matched_image_url"] = image_url
            best_similarity = similarity

    if best_result:
        best_result["tested_image_count"] = len(images)
        return best_result

    return {
        "ok": False,
        "error": "No usable Amazon images for matching",
        "similarity_pct": 0,
        "tested_image_count": len(images),
    }
