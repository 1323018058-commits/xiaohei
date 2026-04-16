"""Bid service — auto-bidding engine logic, product CRUD, state management.

In the new architecture, the bid engine runs as a Celery periodic task
instead of a subprocess + threading.Timer. State is stored in PostgreSQL
(bid_engine_state table) and Redis (distributed locks).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from sqlalchemy import case, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import BidEngineState, BidLog, BidProduct
from app.models.store import StoreBinding
from app.services.takealot_api import TakealotSellerAPI

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 300
BID_CYCLE_PRODUCT_LIMIT = 500

# Anti-manipulation: 单轮涨价不超过当前价的 3 倍
# 防止竞争对手恶意抬价钓鱼（抬到天价然后立刻降回来）
MAX_RAISE_RATIO = 3.0
EXCLUDED_SYNC_OFFER_STATUSES = (
    "Not Buyable",
    "Disabled by Seller",
    "Disabled by Takealot",
    "Offers with Stock at Takealot",
)
_EXCLUDED_SYNC_OFFER_STATUSES_NORMALIZED = {
    "not buyable",
    "disabled by seller",
    "disabled by takealot",
    "offers with stock at takealot",
    "offer with stock at takealot",
}
_OFF_SHELF_OFFER_STATUSES_NORMALIZED = {
    "disabled by seller",
    "disabled by takealot",
}

PRODUCT_STATUS_GROUP_BUYABLE = "Buyable"
PRODUCT_STATUS_GROUP_NOT_BUYABLE = "Not Buyable"
PRODUCT_STATUS_GROUP_OFF_SHELF = "OffShelf"
PRODUCT_SYNC_MODE_BID = "bid"
PRODUCT_SYNC_MODE_CATALOG = "catalog"

BID_PRODUCT_UPSERT_FIELDS = {
    "sku",
    "plid",
    "title",
    "floor_price_zar",
    "target_price_zar",
    "current_price_zar",
    "auto_bid_enabled",
    "notes",
}

BID_PRODUCT_PATCH_FIELDS = {
    "floor_price_zar",
    "target_price_zar",
    "auto_bid_enabled",
    "notes",
}


def _normalize_text(value: object) -> str:
    return str(value or "").strip().casefold()


def is_bid_product_syncable_status(offer_status: object) -> bool:
    normalized = _normalize_text(offer_status)
    if not normalized:
        return True
    return normalized not in _EXCLUDED_SYNC_OFFER_STATUSES_NORMALIZED


def _int_or_none(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def extract_leadtime_stock_quantity(offer: dict | None) -> int:
    if not isinstance(offer, dict):
        return 0
    stocks = offer.get("leadtime_stock") or []
    if not isinstance(stocks, list):
        return 0

    total = 0
    for item in stocks:
        if not isinstance(item, dict):
            continue
        quantity = _int_or_none(item.get("quantity_available"))
        if quantity and quantity > 0:
            total += quantity
    return total


def resolve_effective_offer_status(
    offer_status: object,
    leadtime_days: object = None,
    dropship_stock: object = None,
) -> str:
    status = str(offer_status or "").strip()
    if _normalize_text(status) != "buyable":
        return status

    parsed_leadtime = _int_or_none(leadtime_days)
    parsed_stock = _int_or_none(dropship_stock) or 0
    if parsed_leadtime == 14 and parsed_stock > 0:
        return "Buyable"
    return "Not Buyable"


def resolve_product_status_group(offer_status: object, api_status: object = "") -> str:
    normalized_offer_status = _normalize_text(offer_status)
    if normalized_offer_status in _OFF_SHELF_OFFER_STATUSES_NORMALIZED:
        return PRODUCT_STATUS_GROUP_OFF_SHELF
    if normalized_offer_status in ("", "buyable") and _normalize_text(api_status) != "disabled":
        return PRODUCT_STATUS_GROUP_BUYABLE
    return PRODUCT_STATUS_GROUP_NOT_BUYABLE


def resolve_product_status_label(status_group: object) -> str:
    if status_group == PRODUCT_STATUS_GROUP_BUYABLE:
        return "在售"
    if status_group == PRODUCT_STATUS_GROUP_OFF_SHELF:
        return "已下架"
    return "不可购买"


def _product_status_group_case(offer_status_col, api_status_col):
    normalized_offer_status = func.lower(func.trim(func.coalesce(offer_status_col, "")))
    normalized_api_status = func.lower(func.trim(func.coalesce(api_status_col, "")))
    return case(
        (
            normalized_offer_status.in_(tuple(_OFF_SHELF_OFFER_STATUSES_NORMALIZED)),
            PRODUCT_STATUS_GROUP_OFF_SHELF,
        ),
        (
            ((normalized_offer_status == "") | (normalized_offer_status == "buyable"))
            & (normalized_api_status != "disabled"),
            PRODUCT_STATUS_GROUP_BUYABLE,
        ),
        else_=PRODUCT_STATUS_GROUP_NOT_BUYABLE,
    )


def _store_products_query(store_id: int, sku: str = ""):
    query = select(BidProduct).where(BidProduct.store_binding_id == store_id)
    if sku:
        query = query.where(
            BidProduct.sku.ilike(f"%{sku}%") | BidProduct.title.ilike(f"%{sku}%")
        )
    return query


def _float_or_none(value: object) -> float | None:
    try:
        parsed = float(value) if value is not None else None
    except (ValueError, TypeError):
        return None
    return parsed


def _positive_float_or_none(value: object) -> float | None:
    parsed = _float_or_none(value)
    if parsed is None or parsed <= 0:
        return None
    return parsed


def resolve_target_price(current_price: object, target_price: object) -> float | int | None:
    existing_target = _positive_float_or_none(target_price)
    if existing_target is not None:
        return existing_target

    current = _float_or_none(current_price)
    if current is None or current < 0:
        return None
    return int(current * MAX_RAISE_RATIO)


def is_store_buybox_winner(store: StoreBinding, buybox_store: object) -> bool:
    winner = _normalize_text(buybox_store)
    if not winner:
        return False
    return winner in {
        _normalize_text(store.store_name),
        _normalize_text(store.store_alias),
    }


def resolve_buybox_display_price(
    current_price: object,
    buybox_price: object,
    *,
    store: StoreBinding | None = None,
    buybox_store: object = "",
) -> float | None:
    try:
        current = float(current_price) if current_price is not None else None
    except (ValueError, TypeError):
        current = None
    try:
        buybox = float(buybox_price) if buybox_price is not None else None
    except (ValueError, TypeError):
        buybox = None

    if (
        store is not None
        and current is not None
        and buybox is not None
        and buybox < current
        and is_store_buybox_winner(store, buybox_store)
    ):
        return current
    return buybox


# ---------------------------------------------------------------------------
# Bid engine state
# ---------------------------------------------------------------------------

async def get_engine_state(db: AsyncSession, store_id: int) -> dict:
    result = await db.execute(
        select(BidEngineState).where(BidEngineState.store_id == store_id)
    )
    state = result.scalar_one_or_none()
    if not state:
        return {
            "running": False, "last_run": None, "next_run": None,
            "last_raised": 0, "last_lowered": 0, "last_floored": 0,
            "last_unchanged": 0, "last_errors": 0,
            "total_checked": 0, "total_updated": 0,
            "consecutive_error_cycles": 0,
        }
    return {
        "running": bool(state.running),
        "last_run": state.last_run,
        "next_run": state.next_run,
        "last_raised": state.last_raised,
        "last_lowered": state.last_lowered,
        "last_floored": state.last_floored,
        "last_unchanged": state.last_unchanged,
        "last_errors": state.last_errors,
        "total_checked": state.total_checked,
        "total_updated": state.total_updated,
        "consecutive_error_cycles": state.consecutive_error_cycles,
        "last_result": state.last_result,
    }


async def set_engine_running(db: AsyncSession, store_id: int, running: bool) -> None:
    result = await db.execute(
        select(BidEngineState).where(BidEngineState.store_id == store_id)
    )
    state = result.scalar_one_or_none()
    if state:
        state.running = 1 if running else 0
    else:
        state = BidEngineState(store_id=store_id, running=1 if running else 0)
        db.add(state)
    await db.flush()


async def update_engine_state(db: AsyncSession, store_id: int, **fields) -> None:
    result = await db.execute(
        select(BidEngineState).where(BidEngineState.store_id == store_id)
    )
    state = result.scalar_one_or_none()
    if not state:
        state = BidEngineState(store_id=store_id)
        db.add(state)
    for k, v in fields.items():
        if hasattr(state, k):
            setattr(state, k, v)
    await db.flush()


# ---------------------------------------------------------------------------
# Bid products CRUD
# ---------------------------------------------------------------------------

async def list_bid_products(
    db: AsyncSession,
    store_id: int,
    page: int = 1,
    page_size: int = 50,
    sku: str = "",
    enabled: str = "",
    status: str = "",
) -> tuple[list[BidProduct], int]:
    query = (
        select(BidProduct)
        .where(BidProduct.store_binding_id == store_id)
        .where(
            or_(
                BidProduct.offer_status.is_(None),
                BidProduct.offer_status == "",
                ~BidProduct.offer_status.in_(EXCLUDED_SYNC_OFFER_STATUSES),
            )
        )
    )

    if sku:
        query = query.where(
            BidProduct.sku.ilike(f"%{sku}%") | BidProduct.title.ilike(f"%{sku}%")
        )
    if enabled in ("0", "1"):
        query = query.where(BidProduct.auto_bid_enabled == int(enabled))
    if status == "failed":
        query = query.where(BidProduct.last_action == "api_error")
    elif status in ("raised", "lowered", "floor", "unchanged"):
        query = query.where(BidProduct.last_action == status)

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar_one()

    query = query.order_by(BidProduct.last_checked_at.desc().nullslast())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)

    return list(result.scalars().all()), total


async def list_store_products(
    db: AsyncSession,
    store_id: int,
    page: int = 1,
    page_size: int = 50,
    sku: str = "",
    status: str = "",
) -> tuple[list[BidProduct], int]:
    query = _store_products_query(store_id, sku=sku)
    if status in (
        PRODUCT_STATUS_GROUP_BUYABLE,
        PRODUCT_STATUS_GROUP_NOT_BUYABLE,
        PRODUCT_STATUS_GROUP_OFF_SHELF,
    ):
        query = query.where(
            _product_status_group_case(BidProduct.offer_status, BidProduct.api_status) == status
        )

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar_one()

    query = query.order_by(BidProduct.last_checked_at.desc().nullslast(), BidProduct.id.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)

    return list(result.scalars().all()), total


async def count_store_products_by_status(
    db: AsyncSession,
    store_id: int,
    sku: str = "",
) -> dict[str, int]:
    base_query = _store_products_query(store_id, sku=sku)
    subquery = base_query.subquery()
    status_group = _product_status_group_case(subquery.c.offer_status, subquery.c.api_status)

    result = await db.execute(
        select(
            func.count().label("all"),
            func.coalesce(
                func.sum(case((status_group == PRODUCT_STATUS_GROUP_BUYABLE, 1), else_=0)),
                0,
            ).label("buyable"),
            func.coalesce(
                func.sum(case((status_group == PRODUCT_STATUS_GROUP_NOT_BUYABLE, 1), else_=0)),
                0,
            ).label("not_buyable"),
            func.coalesce(
                func.sum(case((status_group == PRODUCT_STATUS_GROUP_OFF_SHELF, 1), else_=0)),
                0,
            ).label("off_shelf"),
        ).select_from(subquery)
    )
    row = result.one()
    data = row._mapping
    return {
        "all": int(data["all"] or 0),
        "buyable": int(data["buyable"] or 0),
        "not_buyable": int(data["not_buyable"] or 0),
        "off_shelf": int(data["off_shelf"] or 0),
    }


async def get_bid_product(db: AsyncSession, store_id: int, offer_id: str) -> BidProduct | None:
    result = await db.execute(
        select(BidProduct).where(
            BidProduct.store_binding_id == store_id,
            BidProduct.offer_id == offer_id,
        )
    )
    return result.scalar_one_or_none()


async def upsert_bid_product(db: AsyncSession, store_id: int, data: dict) -> BidProduct:
    payload = {key: data[key] for key in BID_PRODUCT_UPSERT_FIELDS if key in data}
    default_target = resolve_target_price(
        payload.get("current_price_zar"),
        payload.get("target_price_zar"),
    )
    if default_target is not None:
        payload["target_price_zar"] = default_target
    stmt = pg_insert(BidProduct).values(
        store_binding_id=store_id,
        offer_id=data["offer_id"],
        **payload,
    )
    update_fields = {
        key: getattr(stmt.excluded, key)
        for key in payload
    }
    if not update_fields:
        update_fields["offer_id"] = getattr(stmt.excluded, "offer_id")
    stmt = stmt.on_conflict_do_update(
        index_elements=[BidProduct.offer_id, BidProduct.store_binding_id],
        set_=update_fields,
    ).returning(BidProduct.id)

    try:
        product_id = (await db.execute(stmt)).scalar_one()
    except IntegrityError:
        existing = await get_bid_product(db, store_id, data["offer_id"])
        if not existing:
            raise
        return existing

    result = await db.execute(select(BidProduct).where(BidProduct.id == product_id))
    return result.scalar_one()


async def patch_bid_product(
    db: AsyncSession, store_id: int, offer_id: str, **fields
) -> BidProduct | None:
    product = await get_bid_product(db, store_id, offer_id)
    if not product:
        return None

    if "floor_price_zar" in fields:
        floor = fields["floor_price_zar"]
        if floor is not None and floor <= 0:
            fields["auto_bid_enabled"] = 0
        elif floor is not None and floor > 0 and "auto_bid_enabled" not in fields:
            fields["auto_bid_enabled"] = 1

    for key in BID_PRODUCT_PATCH_FIELDS:
        value = fields.get(key)
        if value is not None:
            setattr(product, key, value)
    await db.flush()
    return product


# ---------------------------------------------------------------------------
# Bid log
# ---------------------------------------------------------------------------

async def list_bid_log(
    db: AsyncSession, store_id: int, limit: int = 100,
) -> list[BidLog]:
    result = await db.execute(
        select(BidLog)
        .where(BidLog.store_binding_id == store_id)
        .order_by(BidLog.created_at.desc())
        .limit(min(limit, 500))
    )
    return list(result.scalars().all())


async def list_bid_log_for_offer(
    db: AsyncSession,
    store_id: int,
    offer_id: str,
    limit: int = 5,
) -> list[BidLog]:
    result = await db.execute(
        select(BidLog)
        .where(
            BidLog.store_binding_id == store_id,
            BidLog.offer_id == offer_id,
        )
        .order_by(BidLog.created_at.desc())
        .limit(min(limit, 100))
    )
    return list(result.scalars().all())


async def add_bid_log(db: AsyncSession, **fields) -> BidLog:
    log = BidLog(**fields)
    db.add(log)
    await db.flush()
    return log


# ---------------------------------------------------------------------------
# Bid insights / aggregation
# ---------------------------------------------------------------------------

async def get_bid_insights(db: AsyncSession, store_id: int) -> dict:
    products = await db.execute(
        select(BidProduct).where(BidProduct.store_binding_id == store_id)
    )
    all_products = list(products.scalars().all())

    total = len(all_products)
    active = sum(1 for p in all_products if p.auto_bid_enabled == 1)
    paused = total - active
    has_floor = sum(1 for p in all_products if p.floor_price_zar and p.floor_price_zar > 0)
    at_floor = sum(1 for p in all_products if p.last_action == "floor")
    api_ok = sum(
        1
        for p in all_products
        if p.last_action != "api_error"
        and p.api_status not in ("fail", "error")
    )

    floor_rate = (has_floor / total * 100) if total else 0
    api_rate = (api_ok / total * 100) if total else 0

    gaps = [
        abs(p.current_price_zar - p.buybox_price_zar)
        for p in all_products
        if p.current_price_zar and p.buybox_price_zar
    ]
    avg_gap = sum(gaps) / len(gaps) if gaps else 0

    # 24h stats
    cutoff = datetime.utcnow() - timedelta(hours=24)
    log_24h = await db.execute(
        select(func.count()).select_from(BidLog)
        .where(
            BidLog.store_binding_id == store_id,
            BidLog.created_at >= cutoff,
            BidLog.action != "api_error",
        )
    )
    adjustments_24h = log_24h.scalar_one()

    failures_24h = await db.execute(
        select(func.count()).select_from(BidLog)
        .where(
            BidLog.store_binding_id == store_id,
            BidLog.created_at >= cutoff,
            BidLog.action == "api_error",
        )
    )

    return {
        "total_products": total,
        "active_bid_products": active,
        "paused_bid_products": paused,
        "floor_coverage_rate": round(floor_rate, 1),
        "at_floor_products": at_floor,
        "api_health_rate": round(api_rate, 1),
        "avg_price_gap": round(avg_gap, 2),
        "recent_24h_adjustments": adjustments_24h,
        "recent_24h_failures": failures_24h.scalar_one(),
    }


# ---------------------------------------------------------------------------
# Sync products from Takealot API
# ---------------------------------------------------------------------------

def _normalize_trustworthy_url(value: object) -> str:
    if not isinstance(value, str):
        return ""
    candidate = value.strip()
    if not candidate or any(char.isspace() for char in candidate):
        return ""
    if candidate.startswith("//"):
        candidate = f"https:{candidate}"
    parsed = urlparse(candidate)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    return candidate


def _first_trustworthy_url(value: object, nested_keys: tuple[str, ...]) -> str:
    normalized = _normalize_trustworthy_url(value)
    if normalized:
        return normalized
    if isinstance(value, dict):
        for nested_key in nested_keys:
            normalized = _normalize_trustworthy_url(value.get(nested_key))
            if normalized:
                return normalized
    return ""


def _extract_offer_plid(offer: dict) -> str:
    if not isinstance(offer, dict):
        return ""
    for key in ("plid", "productline_id", "product_line_id"):
        value = offer.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        match = re.search(r"PLID(\d+)", text, flags=re.IGNORECASE)
        if match:
            return "PLID" + match.group(1)
        if text.isdigit():
            return "PLID" + text

    for key in ("offer_url", "takealot_url", "product_url", "url"):
        value = offer.get(key)
        candidates = [value]
        if isinstance(value, dict):
            candidates.extend(value.get(k) for k in ("url", "href"))
        for candidate in candidates:
            if not isinstance(candidate, str):
                continue
            match = re.search(r"PLID(\d+)", candidate, flags=re.IGNORECASE)
            if match:
                return "PLID" + match.group(1)
    return ""


def _takealot_short_url(plid: str) -> str:
    return f"https://www.takealot.com/x/{plid}" if plid else ""


def resolve_takealot_url(takealot_url: object, plid: object) -> str:
    normalized = _normalize_trustworthy_url(takealot_url)
    if normalized:
        return normalized
    return _takealot_short_url(_extract_offer_plid({"plid": plid}))


def _extract_offer_takealot_url(offer: dict) -> str:
    if not isinstance(offer, dict):
        return ""
    for key in ("offer_url", "takealot_url", "product_url", "url"):
        value = _first_trustworthy_url(offer.get(key), ("url", "href"))
        if value:
            return value
    links = offer.get("links")
    if isinstance(links, dict):
        for key in ("offer_url", "product_url", "web_page", "url"):
            value = _first_trustworthy_url(links.get(key), ("url", "href"))
            if value:
                return value
    return _takealot_short_url(_extract_offer_plid(offer))


def _extract_offer_image_url(offer: dict) -> str:
    if not isinstance(offer, dict):
        return ""
    image_inner_keys = ("url", "src", "image_url", "main_image_url", "thumbnail_url", "thumbnail")
    for key in ("image_url", "main_image_url", "main_image", "thumbnail_url", "thumbnail"):
        value = _first_trustworthy_url(offer.get(key), image_inner_keys)
        if value:
            return value
    image_block = offer.get("image")
    if isinstance(image_block, dict):
        value = _first_trustworthy_url(image_block, image_inner_keys)
        if value:
            return value
    images = offer.get("images") or offer.get("image_urls") or offer.get("image_list")
    if isinstance(images, list):
        for item in images:
            value = _first_trustworthy_url(item, image_inner_keys)
            if value:
                return value
    return ""


async def sync_bid_products(
    db: AsyncSession,
    store: StoreBinding,
    *,
    sync_mode: str = PRODUCT_SYNC_MODE_BID,
) -> dict:
    """Fetch all offers from Takealot and upsert into bid_products."""
    from app.utils.encryption import decrypt

    raw_key = decrypt(store.api_key)
    api = TakealotSellerAPI(raw_key)

    try:
        all_offers = await api.get_all_offers()
    except RuntimeError as exc:
        raise RuntimeError(str(exc)) from exc

    normalized_mode = str(sync_mode or PRODUCT_SYNC_MODE_BID).strip().casefold()
    include_all_statuses = normalized_mode == PRODUCT_SYNC_MODE_CATALOG

    synced, skipped, errors = 0, 0, 0
    missing_enrichment_offer_ids: list[str] = []
    for offer in all_offers:
        try:
            offer_id = str(offer.get("offer_id", ""))
            if not offer_id:
                skipped += 1
                continue

            offer_url = _extract_offer_takealot_url(offer)
            image_url = _extract_offer_image_url(offer)

            plid = _extract_offer_plid(offer)

            # Extract stock info
            stock_total = offer.get("stock_at_takealot_total") or 0
            stock_on_way = offer.get("total_stock_on_way") or 0
            leadtime = offer.get("leadtime_days")
            dropship_stock = extract_leadtime_stock_quantity(offer)
            raw_offer_status = str(offer.get("status", "") or "").strip()
            offer_status = resolve_effective_offer_status(
                raw_offer_status,
                leadtime,
                dropship_stock,
            )
            if not include_all_statuses and not is_bid_product_syncable_status(offer_status):
                skipped += 1
                continue

            wh_stocks = offer.get("stock_at_takealot", [])
            stock_detail = " / ".join(
                f"{w['warehouse']['name']}:{w['quantity_available']}"
                for w in wh_stocks if isinstance(w, dict) and "warehouse" in w
            ) if wh_stocks else ""

            if leadtime is not None:
                stock_status = f"Ships in {leadtime} work days"
            elif stock_total > 0:
                stock_status = f"In stock ({stock_total})"
            elif stock_on_way > 0:
                stock_status = f"On way ({stock_on_way})"
            else:
                stock_status = "Out of stock"

            price = offer.get("selling_price") or 0
            try:
                price = float(price)
            except (ValueError, TypeError):
                price = 0.0

            rrp = offer.get("rrp") or offer.get("RRP") or 0
            try:
                rrp = float(rrp)
            except (ValueError, TypeError):
                rrp = 0.0

            existing = await get_bid_product(db, store.id, offer_id)
            data = {
                "offer_id": offer_id,
                "sku": offer.get("sku", ""),
                "plid": plid,
                "title": offer.get("product_title", offer.get("title", "")),
                "brand": offer.get("brand", ""),
                "target_price_zar": resolve_target_price(
                    price,
                    existing.target_price_zar if existing else None,
                ),
                "current_price_zar": price,
                "rrp_zar": rrp if rrp > 0 else price,
                "offer_status": offer_status,
                "buybox_store_stock": stock_status,
                "stock_detail": stock_detail,
                "official_stock_total": int(stock_total),
                "stock_on_way_total": int(stock_on_way),
                "dropship_stock": dropship_stock,
            }
            if image_url:
                data["image_url"] = image_url
            elif not existing:
                data["image_url"] = ""
            if offer_url:
                data["takealot_url"] = offer_url
            elif not existing:
                data["takealot_url"] = ""

            if existing:
                for k, v in data.items():
                    if k in ("image_url", "takealot_url") and not v:
                        continue
                    if k not in ("offer_id",) and v is not None:
                        setattr(existing, k, v)
            else:
                product = BidProduct(
                    store_binding_id=store.id,
                    auto_bid_enabled=0,  # New products start disabled
                    **data,
                )
                db.add(product)

            has_image_url = bool(image_url or (existing and _normalize_trustworthy_url(existing.image_url)))
            has_takealot_url = bool(offer_url or (existing and _normalize_trustworthy_url(existing.takealot_url)))
            if not has_image_url or not has_takealot_url:
                missing_enrichment_offer_ids.append(offer_id)
            synced += 1
        except Exception as exc:
            logger.warning("Failed to sync offer %s: %s", offer.get("offer_id"), exc)
            errors += 1

    await db.flush()
    store.offer_count = len(all_offers)
    store.last_synced_at = datetime.utcnow()
    await db.flush()

    return {
        "ok": True,
        "synced": synced,
        "skipped": skipped,
        "errors": errors,
        "missing_image_offer_ids": missing_enrichment_offer_ids,
        "missing_enrichment_offer_ids": missing_enrichment_offer_ids,
    }


async def refresh_store_buybox(db: AsyncSession, store: StoreBinding) -> dict:
    from app.services.buybox_service import batch_refresh_buybox

    result = await db.execute(
        select(BidProduct).where(BidProduct.store_binding_id == store.id)
    )
    products = list(result.scalars().all())

    stats = {
        "total": len(products),
        "refreshed": 0,
        "failed": 0,
        "skipped": 0,
    }
    if not products:
        return stats

    products_with_plid: list[dict] = []
    for product in products:
        if product.plid:
            products_with_plid.append({"offer_id": product.offer_id, "plid": product.plid})
        else:
            stats["skipped"] += 1

    if not products_with_plid:
        return stats

    buybox_results = await batch_refresh_buybox(products_with_plid)
    buybox_lookup = {
        str(item.get("offer_id") or ""): item
        for item in buybox_results
        if isinstance(item, dict) and item.get("offer_id")
    }
    checked_at = datetime.utcnow()

    for product in products:
        if not product.plid:
            continue

        result_item = buybox_lookup.get(str(product.offer_id))
        if not result_item or not result_item.get("ok") or result_item.get("buybox_price") is None:
            stats["failed"] += 1
            product.last_checked_at = checked_at
            continue

        refreshed_buybox = resolve_buybox_display_price(
            product.current_price_zar,
            result_item.get("buybox_price"),
            store=store,
            buybox_store=result_item.get("buybox_seller") or product.buybox_store,
        )
        if refreshed_buybox is not None:
            product.buybox_price_zar = refreshed_buybox
        if result_item.get("brand"):
            product.brand = str(result_item["brand"])
        if result_item.get("buybox_seller"):
            product.buybox_store = str(result_item["buybox_seller"])

        resolved_url = resolve_takealot_url(result_item.get("takealot_url"), product.plid)
        if resolved_url:
            product.takealot_url = resolved_url

        product.last_checked_at = checked_at
        stats["refreshed"] += 1

    await db.flush()
    return stats


# ---------------------------------------------------------------------------
# Core bid cycle logic (called by Celery task)
# ---------------------------------------------------------------------------

async def run_bid_cycle(db: AsyncSession, store: StoreBinding) -> dict:
    """Execute one bid cycle for a store. Returns cycle stats.

    Full cycle:
      1. Select enabled products with floor price
      2. Refresh BuyBox prices via Takealot public API (batch, 8 concurrent)
      3. Execute bid decisions: buybox-1, floor protection, target cap
      4. Update prices via Takealot Seller API
    """
    from app.services.buybox_service import batch_refresh_buybox
    from app.utils.encryption import decrypt

    raw_key = decrypt(store.api_key)
    api = TakealotSellerAPI(raw_key)

    # Select products for this cycle (priority: oldest checked first)
    result = await db.execute(
        select(BidProduct)
        .where(
            BidProduct.store_binding_id == store.id,
            BidProduct.auto_bid_enabled == 1,
            BidProduct.floor_price_zar > 0,
        )
        .order_by(BidProduct.last_checked_at.asc().nullsfirst())
        .limit(BID_CYCLE_PRODUCT_LIMIT)
    )
    products = list(result.scalars().all())

    stats = {
        "checked": 0, "updated": 0, "raised": 0, "lowered": 0,
        "floored": 0, "unchanged": 0, "no_floor": 0, "errors": 0,
        "buybox_refreshed": 0, "buybox_failed": 0,
    }

    if not products:
        return stats

    # ── Step 1: Batch-refresh BuyBox prices ──
    products_with_plid = [
        {"offer_id": p.offer_id, "plid": p.plid or ""}
        for p in products
        if p.plid
    ]

    if products_with_plid:
        logger.info(
            "store=%d: refreshing BuyBox for %d products",
            store.id, len(products_with_plid),
        )
        buybox_results = await batch_refresh_buybox(products_with_plid)

        # Build lookup: offer_id → buybox result
        buybox_lookup = {}
        for br in buybox_results:
            oid = br.get("offer_id", "")
            if oid:
                buybox_lookup[oid] = br

        # Apply refreshed BuyBox prices to product objects
        for product in products:
            br = buybox_lookup.get(product.offer_id)
            if not br:
                continue
            if br.get("ok") and br.get("buybox_price") is not None:
                product.buybox_price_zar = br["buybox_price"]
                if br.get("brand"):
                    product.brand = br["brand"]
                if br.get("buybox_seller"):
                    product.buybox_store = br["buybox_seller"]
                refreshed_url = _normalize_trustworthy_url(br.get("takealot_url"))
                current_url = _normalize_trustworthy_url(product.takealot_url)
                if refreshed_url and (not current_url or "/x/PLID" in current_url):
                    product.takealot_url = refreshed_url
                stats["buybox_refreshed"] += 1
            else:
                stats["buybox_failed"] += 1

        await db.flush()

    # ── Step 2: Bid decisions ──
    for product in products:
        stats["checked"] += 1

        if not product.floor_price_zar or product.floor_price_zar <= 0:
            stats["no_floor"] += 1
            continue

        buybox = product.buybox_price_zar
        current = product.current_price_zar
        floor = product.floor_price_zar

        # 跳过无效数据
        if not buybox or buybox <= 0 or not current or current <= 0:
            stats["unchanged"] += 1
            product.last_checked_at = datetime.utcnow()
            continue

        action = "unchanged"
        new_price = current
        br = buybox_lookup.get(product.offer_id) if products_with_plid else None
        own_store_id = str(store.takealot_store_id or "").strip()
        winner_seller_id = str((br or {}).get("buybox_seller_id") or "").strip()
        winner_offer_id = str((br or {}).get("buybox_offer_id") or "").strip()
        winner_name = str((br or {}).get("buybox_seller") or "").strip().lower()
        own_store_name = str(store.store_name or store.store_alias or "").strip().lower()
        owns_buybox = (
            (own_store_id and winner_seller_id and own_store_id == winner_seller_id)
            or (winner_offer_id and winner_offer_id == str(product.offer_id))
            or (own_store_name and winner_name and own_store_name == winner_name)
        )
        next_offer_price = None
        try:
            if br and br.get("next_offer_price") is not None:
                next_offer_price = float(br["next_offer_price"])
        except (ValueError, TypeError):
            next_offer_price = None

        normalized_buybox = resolve_buybox_display_price(
            current,
            buybox,
            store=store,
            buybox_store=br.get("buybox_seller") if br else product.buybox_store,
        )
        if normalized_buybox is not None and normalized_buybox != buybox:
            buybox = normalized_buybox
            product.buybox_price_zar = normalized_buybox

        if owns_buybox:
            if next_offer_price and next_offer_price > current:
                candidate = int(next_offer_price) - 1
                target_price = product.target_price_zar
                if target_price and target_price > 0:
                    candidate = min(candidate, int(target_price))

                price_ceiling = int(current * MAX_RAISE_RATIO)
                if candidate >= price_ceiling:
                    logger.warning(
                        "bid skip anomaly: offer=%s next_offer=%s current=%s ceiling=%s",
                        product.offer_id, next_offer_price, current, price_ceiling,
                    )
                    product.last_action = "skipped_anomaly"
                    product.last_checked_at = datetime.utcnow()
                    stats["unchanged"] += 1
                    continue

                if candidate > current:
                    new_price = candidate
                    action = "raised"

        elif buybox < current:
            # ── 对手更便宜：降价跟进 ──
            # 策略：buybox - 1，但不低于底价
            candidate = int(buybox) - 1
            if candidate <= 0:
                # BuyBox 太低（可能是异常数据），不跟
                product.last_action = "skipped"
                product.last_checked_at = datetime.utcnow()
                stats["unchanged"] += 1
                continue
            if candidate < floor:
                new_price = int(floor)
                action = "floor"
            else:
                new_price = candidate
                action = "lowered"

        elif buybox == current:
            # ── 价格相同：还没赢 BuyBox ──
            # 在底价以上 → 降1块钱抢 BuyBox
            # 已经到底价或低于底价 → 不动
            candidate = int(current) - 1
            if candidate >= floor and candidate > 0:
                new_price = candidate
                action = "lowered"

        elif buybox > current:
            # ── 对手更贵：涨价赚更多 ──
            candidate = int(buybox) - 1
            target_price = product.target_price_zar
            if target_price and target_price > 0:
                candidate = min(candidate, int(target_price))

            # 防钓鱼：单轮涨幅不超过当前价的 MAX_RAISE_RATIO 倍
            # 如果对手突然从 R300 抬到 R50000，这是异常，不跟
            price_ceiling = int(current * MAX_RAISE_RATIO)
            if candidate >= price_ceiling:
                logger.warning(
                    "bid skip anomaly: offer=%s buybox=%s current=%s ceiling=%s",
                    product.offer_id, buybox, current, price_ceiling,
                )
                product.last_action = "skipped_anomaly"
                product.last_checked_at = datetime.utcnow()
                stats["unchanged"] += 1
                continue

            if candidate > current:
                new_price = candidate
                action = "raised"

        if action == "unchanged":
            stats["unchanged"] += 1
            product.last_action = "unchanged"
            product.last_checked_at = datetime.utcnow()
            continue

        # 已经在底价了，不需要调 API
        if action == "floor" and abs(current - new_price) < 0.01:
            stats["floored"] += 1
            product.last_action = "floor"
            product.last_checked_at = datetime.utcnow()
            continue

        # 最终价格安全校验：必须 > 0 且 >= floor
        if new_price <= 0 or new_price < floor:
            product.last_action = "skipped"
            product.last_checked_at = datetime.utcnow()
            stats["unchanged"] += 1
            continue

        # ── Step 3: Execute price update via Seller API ──
        success, resp = await api.update_offer_price(product.offer_id, new_price)
        if success:
            old_price = current
            product.current_price_zar = new_price
            product.last_action = action
            product.last_updated_at = datetime.utcnow()
            product.last_checked_at = datetime.utcnow()
            product.last_price_change = new_price - old_price

            log = BidLog(
                store_binding_id=store.id,
                offer_id=product.offer_id,
                sku=product.sku,
                old_price=old_price,
                new_price=new_price,
                buybox_price=buybox,
                action=action,
                reason=(
                    f"buybox={buybox}, floor={floor}, old={old_price}, "
                    f"own_buybox={owns_buybox}, next_offer={next_offer_price}"
                ),
            )
            db.add(log)

            stats["updated"] += 1
            # Map action names to stats keys
            action_stats_map = {"raised": "raised", "lowered": "lowered", "floor": "floored"}
            stats_key = action_stats_map.get(action, action)
            if stats_key in stats:
                stats[stats_key] += 1
        else:
            product.last_action = "api_error"
            product.api_status = f"fail:{resp}"
            product.last_checked_at = datetime.utcnow()
            db.add(BidLog(
                store_binding_id=store.id,
                offer_id=product.offer_id,
                sku=product.sku,
                old_price=current,
                new_price=new_price,
                buybox_price=buybox,
                action="api_error",
                reason=str(resp),
            ))
            stats["errors"] += 1

    await db.flush()
    return stats
