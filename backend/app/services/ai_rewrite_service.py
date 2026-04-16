"""DeepSeek AI product listing rewrite service for Takealot.

Selects the best Takealot loadsheet template, chooses categories,
and rewrites Amazon product info into Takealot-ready listing data.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"

DEFAULT_WEIGHT_KG = 0.5
DEFAULT_DIMENSIONS_CM = [20, 15, 10]

# All 37 Takealot loadsheet templates
TEMPLATE_LIST = [
    {"id": 104, "name": "Cameras", "group": "Consumer Electronics", "desc": "Digital, DSLR, Instant & Video Cameras, Drones & Accessories"},
    {"id": 105, "name": "Computer Components", "group": "Consumer Electronics", "desc": "Data Storage, Networking & Accessories"},
    {"id": 106, "name": "Computers & Laptops", "group": "Consumer Electronics", "desc": "Computers, Laptops & Monitors"},
    {"id": 107, "name": "Electronic Accessories", "group": "Consumer Electronics", "desc": "Cellular Accessories, Tablet Accessories & Laptop Accessories"},
    {"id": 108, "name": "Mobile", "group": "Consumer Electronics", "desc": "Cellphones, Tablets and Kindles"},
    {"id": 109, "name": "Musical Instruments", "group": "Consumer Electronics", "desc": "DJ, Live Sound, Microphones, Musical Instruments"},
    {"id": 112, "name": "TV & Audio", "group": "Consumer Electronics", "desc": "Car, Home & Portable Audio & Video Equipment"},
    {"id": 120, "name": "Gaming", "group": "Consumer Electronics", "desc": "Consoles, Video Games, Gaming Merchandise & Accessories"},
    {"id": 258, "name": "Wearable Tech", "group": "Consumer Electronics", "desc": "GPS & Wearable Tech"},
    {"id": 136, "name": "Automotive", "group": "Home", "desc": "Automotive & Motorcycle Accessories, Parts"},
    {"id": 113, "name": "DIY", "group": "Home", "desc": "Power & Hand Tools, Hardware, Electrical, Plumbing"},
    {"id": 114, "name": "Garden, Pool & Patio", "group": "Home", "desc": "Outdoor Furniture, Garden Tools, Pool Equipment"},
    {"id": 115, "name": "Home & Kitchen", "group": "Home", "desc": "Cookware, Cutlery, Kitchen Storage, Home Decor"},
    {"id": 116, "name": "Large Appliances", "group": "Home", "desc": "Washing Machines, Fridges, Dishwashers, Ovens"},
    {"id": 117, "name": "Small Appliances", "group": "Home", "desc": "Coffee Machines, Toasters, Blenders, Microwaves"},
    {"id": 97,  "name": "Beauty", "group": "Health & Beauty", "desc": "Skincare, Haircare, Cosmetics, Fragrances"},
    {"id": 101, "name": "Health", "group": "Health & Beauty", "desc": "Vitamins, Medical Devices, Personal Care"},
    {"id": 100, "name": "Baby", "group": "Kids & Toys", "desc": "Baby Gear, Nursery, Baby Clothing"},
    {"id": 96,  "name": "Toys", "group": "Kids & Toys", "desc": "Toys, Games, Educational Toys"},
    {"id": 90,  "name": "Cycling", "group": "Sport", "desc": "Bicycles, Cycling Accessories"},
    {"id": 99,  "name": "Camping", "group": "Sport", "desc": "Tents, Sleeping Bags, Camping Gear"},
    {"id": 243, "name": "Sport: Equipment", "group": "Sport", "desc": "Fitness Equipment, Team Sports, Racket Sports"},
    {"id": 244, "name": "Sport: Clothing & Footwear", "group": "Sport", "desc": "Athletic Clothing and Shoes"},
    {"id": 98,  "name": "Luggage", "group": "Sport", "desc": "Suitcases, Travel Bags, Backpacks"},
    {"id": 103, "name": "Pets", "group": "Pets", "desc": "Pet Food, Accessories, Grooming"},
    {"id": 118, "name": "Books", "group": "Entertainment", "desc": "Fiction, Non-fiction, Educational Books"},
    {"id": 125, "name": "Movies", "group": "Entertainment", "desc": "DVDs, Blu-ray"},
    {"id": 121, "name": "Music", "group": "Entertainment", "desc": "CDs, Vinyl Records"},
    {"id": 110, "name": "Office & Office Furniture", "group": "Office", "desc": "Office Chairs, Desks, Filing"},
    {"id": 122, "name": "Stationery", "group": "Office", "desc": "Pens, Paper, Art Supplies"},
    {"id": 123, "name": "Non Perishable", "group": "Food & Grocery", "desc": "Packaged Food, Beverages, Cleaning Products"},
    {"id": 236, "name": "Industrial, Business & Scientific", "group": "Industrial", "desc": "Industrial Tools, Lab Equipment, Safety"},
    {"id": 246, "name": "Fashion: Clothing", "group": "Fashion", "desc": "Men & Women Clothing"},
    {"id": 247, "name": "Fashion: Footwear", "group": "Fashion", "desc": "Shoes, Boots, Sandals"},
    {"id": 248, "name": "Fashion: Accessories", "group": "Fashion", "desc": "Bags, Wallets, Belts, Jewellery"},
    {"id": 256, "name": "Homeware: Bed & Bathroom", "group": "Home", "desc": "Bedding, Towels, Bath Accessories"},
    {"id": 257, "name": "Homeware: Decor & Lighting", "group": "Home", "desc": "Home Decor, Lighting, Rugs"},
]

TEMPLATE_BY_ID = {t["id"]: t for t in TEMPLATE_LIST}


def _sanitize_ai_output(result: dict, scraped: dict) -> dict:
    """Clean up AI output: strip brand names, enforce length limits."""
    # Ensure template_id is valid
    tid = result.get("template_id")
    if tid not in TEMPLATE_BY_ID:
        # Default to Electronic Accessories
        result["template_id"] = 107

    # Strip brand from title/description
    brand = (scraped.get("brand") or "").strip()
    title = result.get("listing_title", "")
    if brand and brand.lower() != "generic":
        title = re.sub(re.escape(brand), "", title, flags=re.IGNORECASE).strip()
    # Remove common filler
    for word in ["Generic", "generic", "Unbranded", "unbranded"]:
        title = title.replace(word, "").strip()
    result["listing_title"] = title[:75].strip()

    # Force brand to empty
    result["brand"] = ""

    # Enforce subtitle length
    subtitle = result.get("subtitle", "")
    result["subtitle"] = subtitle[:60].strip()

    return result


async def ai_analyze_and_rewrite(
    scraped: dict[str, Any],
    category_tree: list[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Call DeepSeek to select template, categories, and rewrite the listing.

    Args:
        scraped: Dict with keys: title, brand, description, bullets, weight_kg,
                 package_dimensions_cm
        category_tree: Optional list of (TopCategory, Category) tuples from
                       the Takealot template schema.

    Returns:
        Dict with template_id, categories, rewritten listing fields, and attributes.
        On error, returns {"error_code": "...", "error": "..."}.
    """
    settings = get_settings()
    key = settings.deepseek_api_key
    if not key:
        return {"error_code": "AI_REWRITE_FAILED", "error": "未配置 DeepSeek API Key"}

    templates_text = "\n".join(
        f"  template_id={t['id']}: [{t['group']}] {t['name']} — {t['desc']}"
        for t in TEMPLATE_LIST
    )

    # Build category candidates text
    if category_tree:
        cats_text = "\n".join(
            f"  TopCategory: {top} | Category: {low}"
            for top, low in category_tree[:80]
        )
    else:
        cats_text = "(No specific category tree provided — choose the best TopCategory and Category based on template)"

    title = scraped.get("title", "")
    desc = str(scraped.get("description", ""))[:600]
    bullets = scraped.get("bullets", [])
    if isinstance(bullets, str):
        bullets = [b.strip() for b in bullets.split("\n") if b.strip()]
    bullets_text = "\n".join(f"- {b}" for b in bullets[:8])

    weight_kg = scraped.get("weight_kg") or DEFAULT_WEIGHT_KG
    dims = scraped.get("package_dimensions_cm") or DEFAULT_DIMENSIONS_CM

    prompt = f"""You are a Takealot marketplace product listing expert.
Analyze the Amazon product below and return a JSON object for uploading to Takealot.

== AMAZON PRODUCT ==
Title: {title}
Brand: {scraped.get("brand", "")}
Description: {desc}
Detected Weight KG: {weight_kg}
Detected Package Dimensions CM: {dims}
Bullet Points:
{bullets_text}

== AVAILABLE TAKEALOT LOADSHEET TEMPLATES ==
{templates_text}

== AVAILABLE CATEGORIES ==
{cats_text}

== YOUR TASKS ==
1. Choose the best template_id from the list above.
2. Choose TopCategory and Category that best fit the product.
3. Rewrite the listing title: max 75 characters, clear English, no brand/trademark.
4. Write a subtitle: max 60 characters.
5. Write Key Selling Features (description): min 200 characters, professional English, use hyphens for bullet points.
6. Write package_contents: list what's in the box (e.g. "1 x Product, 1 x User Manual").
7. Brand name: ALWAYS return empty string "".
8. NEVER use any brand name, trademark, store name, "Generic", "generic", or "unbranded" in listing_title, subtitle, listing_description, or package_contents.
9. Fill relevant boolean/value attributes from the list below as best you can from the product info:
   is_wireless, is_portable, is_waterproof, is_water_resistant, is_rechargeable,
   has_bluetooth, has_noise_cancelling, has_gps, is_lightweight, is_ergonomic,
   has_memory_card_slot, fast_charging, is_foldable, is_adjustable,
   warranty_months (integer, default 12),
   weight_grams (integer, product weight in grams),
   packaged_weight_grams (integer, packaged weight in grams),
   color_main (e.g. Black, White, Blue, Red, Silver, Gold, Green, Pink, Grey, Multi-colour)

Respond ONLY with valid JSON (no markdown fences):
{{
  "template_id": <integer>,
  "top_category": "<exact string>",
  "lowest_category": "<exact string>",
  "listing_title": "<max 75 chars>",
  "subtitle": "<max 60 chars>",
  "listing_description": "<min 200 chars>",
  "package_contents": "<what's in the box>",
  "brand": "",
  "model_number": "<model number or empty>",
  "color_main": "<color>",
  "is_wireless": <true/false/null>,
  "is_portable": <true/false/null>,
  "is_waterproof": <true/false/null>,
  "is_water_resistant": <true/false/null>,
  "is_rechargeable": <true/false/null>,
  "has_bluetooth": <true/false/null>,
  "has_noise_cancelling": <true/false/null>,
  "has_gps": <true/false/null>,
  "is_lightweight": <true/false/null>,
  "is_ergonomic": <true/false/null>,
  "has_memory_card_slot": <true/false/null>,
  "fast_charging": <true/false/null>,
  "is_foldable": <true/false/null>,
  "is_adjustable": <true/false/null>,
  "warranty_months": <integer or null>,
  "weight_grams": <integer or null>,
  "packaged_weight_grams": <integer or null>
}}"""

    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    body = {
        "model": DEEPSEEK_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 1200,
    }

    import asyncio as _asyncio
    max_retries = 3
    last_error = ""

    for attempt in range(1, max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(DEEPSEEK_API_URL, headers=headers, json=body)
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"].strip()
                # Strip markdown code fences if present
                content = re.sub(r"^```json\s*|^```\s*|\s*```$", "", content, flags=re.M).strip()
                result = json.loads(content)
                result = _sanitize_ai_output(result, scraped)
                logger.info("AI rewrite OK: template=%s title=%s", result.get("template_id"), result.get("listing_title", "")[:40])
                return result
        except Exception as e:
            last_error = str(e)
            if attempt < max_retries:
                logger.warning("DeepSeek retry %d/%d: %s", attempt, max_retries, e)
                await _asyncio.sleep(3 * attempt)
                continue
            logger.error("DeepSeek AI rewrite failed after %d attempts: %s", max_retries, e)
            return {"error_code": "AI_REWRITE_FAILED", "error": f"AI改写失败: {e}"}
