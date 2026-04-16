"""BuyBox price scraping service — Takealot public API.

Fetches current BuyBox prices via the Takealot public product-details API.
No authentication required — uses the same public endpoint as the website.

API: https://api.takealot.com/rest/v-1-16-0/product-details/{PLID}

Ported from old codebase scrape_buybox.py, adapted for async + httpx.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

_DETAIL_URL = "https://api.takealot.com/rest/v-1-16-0/product-details/{plid}"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://www.takealot.com/",
}

# Concurrent scrape settings
BUYBOX_MAX_CONCURRENT = 8
BUYBOX_REQUEST_DELAY = 0.12  # seconds between requests to avoid rate limiting


def _normalize_plid(plid: str) -> str:
    plid_str = str(plid or "").strip()
    if plid_str and not plid_str.upper().startswith("PLID"):
        plid_str = "PLID" + plid_str
    return plid_str


def _safe_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _safe_str(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _normalize_url(value: object) -> str:
    if not isinstance(value, str):
        return ""
    candidate = value.strip()
    if not candidate:
        return ""
    if candidate.startswith("//"):
        candidate = f"https:{candidate}"
    parsed = urlparse(candidate)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    return candidate


def _extract_takealot_url(payload: dict[str, Any], plid: str) -> str:
    for value in (
        payload.get("desktop_href"),
        (payload.get("sharing") or {}).get("url"),
        (payload.get("seo") or {}).get("canonical"),
    ):
        url = _normalize_url(value)
        if url:
            return url

    core = payload.get("core") or {}
    slug = _safe_str(core.get("slug"))
    core_id = _safe_str(core.get("id")) or plid.replace("PLID", "")
    if slug and core_id:
        return f"https://www.takealot.com/{slug}/PLID{core_id}"

    return f"https://www.takealot.com/x/{plid}" if plid else ""


def _lowest_other_offer(payload: dict[str, Any]) -> dict[str, Any]:
    lowest: dict[str, Any] = {}
    for condition in (payload.get("other_offers") or {}).get("conditions") or []:
        condition_price = _safe_float(condition.get("from_price"))
        if condition_price is not None and (
            not lowest or condition_price < float(lowest["price"])
        ):
            lowest = {"price": condition_price}

        for item in condition.get("items") or []:
            item_price = _safe_float(item.get("price"))
            if item_price is None:
                continue
            seller = item.get("seller") or {}
            if not lowest or item_price < float(lowest["price"]):
                lowest = {
                    "price": item_price,
                    "seller_id": _safe_str(seller.get("seller_id")),
                    "seller_name": _safe_str(seller.get("display_name")),
                    "offer_id": _safe_str(item.get("product_id")),
                }
    return lowest


async def fetch_product_detail(plid: str) -> dict[str, Any]:
    """Fetch brand, buybox price, and seller info for a PLID.

    Args:
        plid: Product Listing ID, e.g. "PLID12345678" or bare "12345678"

    Returns:
        dict with keys: brand, buybox_price, buybox_seller,
        buybox_seller_id, buybox_offer_id, next_offer_price,
        takealot_url, ok
    """
    if not plid:
        return {"ok": False, "error": "empty PLID"}

    # Normalize PLID format
    plid_str = _normalize_plid(plid)

    url = _DETAIL_URL.format(plid=plid_str)

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers=_HEADERS)
            if resp.status_code == 404:
                return {"ok": False, "error": f"PLID {plid_str} not found"}
            if not resp.is_success:
                return {"ok": False, "error": f"HTTP {resp.status_code}"}
            d = resp.json()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    # --- Extract brand ---
    brand = ""
    try:
        ee_prods = (
            (d.get("enhanced_ecommerce_detail") or {})
            .get("ecommerce", {})
            .get("detail", {})
            .get("products", [])
        )
        if ee_prods and ee_prods[0].get("brand"):
            brand = str(ee_prods[0]["brand"])
    except Exception:
        pass
    if not brand:
        brand = str((d.get("core") or {}).get("brand") or "")

    # --- Extract BuyBox price ---
    buybox_price = None
    buybox_offer_id = ""
    buybox = d.get("buybox") or {}
    items = buybox.get("items") or []
    for item in items:
        buybox_offer_id = _safe_str(item.get("sku"))
        buybox_price = _safe_float(item.get("price"))
        if buybox_price is not None:
            break

    # --- Extract seller info ---
    buybox_seller = ""
    buybox_seller_id = ""
    seller_detail = d.get("seller_detail") or {}
    if seller_detail:
        buybox_seller = _safe_str(seller_detail.get("display_name"))
        buybox_seller_id = _safe_str(seller_detail.get("seller_id"))
    if not buybox_seller:
        try:
            ev = (d.get("event_data") or {}).get("documents", {}).get("product", {})
            is_marketplace = ev.get("market_place_listing", False)
            buybox_seller = "Marketplace" if is_marketplace else "Takealot"
        except Exception:
            pass

    other_offer = _lowest_other_offer(d)

    return {
        "ok": True,
        "brand": brand,
        "buybox_price": buybox_price,
        "buybox_seller": buybox_seller,
        "buybox_seller_id": buybox_seller_id,
        "buybox_offer_id": buybox_offer_id,
        "next_offer_price": other_offer.get("price"),
        "next_offer_seller_id": other_offer.get("seller_id", ""),
        "next_offer_seller_name": other_offer.get("seller_name", ""),
        "next_offer_id": other_offer.get("offer_id", ""),
        "takealot_url": _extract_takealot_url(d, plid_str),
    }


async def get_buybox_price(plid: str) -> float | None:
    """Return the current BuyBox price for a PLID, or None on failure.

    Convenience wrapper for use in bid loops.
    """
    result = await fetch_product_detail(plid)
    return result.get("buybox_price") if result.get("ok") else None


async def batch_refresh_buybox(
    products: list[dict],
    max_concurrent: int = BUYBOX_MAX_CONCURRENT,
) -> list[dict]:
    """Batch-refresh BuyBox prices for a list of products.

    Args:
        products: list of dicts, each must have 'plid' key.
                  Optionally 'offer_id' for result correlation.
        max_concurrent: max concurrent HTTP requests

    Returns:
        list of dicts with keys: offer_id, plid, buybox_price, brand, buybox_seller, ok
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    results = []

    async def _fetch_one(product: dict) -> dict:
        plid = product.get("plid", "")
        offer_id = product.get("offer_id", "")

        if not plid:
            return {
                "offer_id": offer_id,
                "plid": plid,
                "ok": False,
                "error": "no PLID",
            }

        async with semaphore:
            result = await fetch_product_detail(plid)
            # Small delay to avoid rate limiting
            await asyncio.sleep(BUYBOX_REQUEST_DELAY)

        return {
            "offer_id": offer_id,
            "plid": plid,
            **result,
        }

    tasks = [_fetch_one(p) for p in products]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    final = []
    for r in results:
        if isinstance(r, Exception):
            final.append({"ok": False, "error": str(r)})
        else:
            final.append(r)

    return final
