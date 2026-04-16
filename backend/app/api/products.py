"""Product management API router."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import ActiveUser, DbSession, RedisConn
from app.services import bid_service, product_sync_progress_service, store_service

router = APIRouter(prefix="/api/products/{store_id}", tags=["products"])
logger = logging.getLogger(__name__)

_SYNC_STATUS_CACHE_TTL_SECONDS = 3
_MANUAL_OFFER_STATUSES = {
    "Buyable",
    "Not Buyable",
    "Disabled by Seller",
}
_READ_ONLY_OFFER_STATUSES = {
    "Disabled by Takealot",
}
_ALLOWED_LEADTIME_DAYS = {
    14,
}


def _sync_status_cache_key(store_id: int) -> str:
    return f"cache:catalog_product_sync_status:{store_id}"


async def _get_cached_json(redis, key: str) -> dict | None:
    raw = await redis.get(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
        await redis.delete(key)
        return None


async def _set_cached_json(redis, key: str, payload: dict, ttl_seconds: int) -> None:
    await redis.setex(key, ttl_seconds, json.dumps(payload, default=str))


async def _delete_cache_key(redis, key: str) -> None:
    try:
        await redis.delete(key)
    except Exception:
        logger.warning("failed to delete cache key %s", key, exc_info=True)


def _float_or_none(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _resolve_display_offer_status(raw_offer_status: object, dropship_stock: object) -> str:
    offer_status = str(raw_offer_status or "").strip()
    if offer_status == "Buyable" and int(dropship_stock or 0) <= 0:
        return "Not Buyable"
    return offer_status


def _apply_status_fields(payload: dict, offer_status: object, api_status: object) -> None:
    status_group = bid_service.resolve_product_status_group(offer_status, api_status)
    payload["status"] = status_group
    payload["status_group"] = status_group
    payload["status_label"] = bid_service.resolve_product_status_label(status_group)


def _serialize_product_list_item(product, store) -> dict:
    dropship_stock = int(product.dropship_stock or 0)
    display_offer_status = _resolve_display_offer_status(product.offer_status, dropship_stock)
    payload = {
        "id": product.id,
        "offer_id": product.offer_id,
        "sku": product.sku,
        "plid": product.plid,
        "title": product.title,
        "selling_price": product.current_price_zar,
        "rrp": product.rrp_zar,
        "stock_on_hand": dropship_stock,
        "current_price_zar": product.current_price_zar,
        "buybox_price_zar": bid_service.resolve_buybox_display_price(
            product.current_price_zar,
            product.buybox_price_zar,
            store=store,
            buybox_store=product.buybox_store,
        ),
        "brand": product.brand,
        "image_url": product.image_url,
        "takealot_url": bid_service.resolve_takealot_url(product.takealot_url, product.plid),
        "api_status": product.api_status,
        "offer_status": display_offer_status,
        "floor_price_zar": product.floor_price_zar,
        "auto_bid_enabled": product.auto_bid_enabled,
        "procurement_price_cny": product.procurement_price_cny,
        "procurement_url": product.procurement_url,
        "dropship_stock": dropship_stock,
        "last_checked_at": str(product.last_checked_at) if product.last_checked_at else None,
    }
    _apply_status_fields(payload, display_offer_status, product.api_status)
    return payload


def _serialize_product_detail_item(product, store) -> dict:
    dropship_stock = int(product.dropship_stock or 0)
    display_offer_status = _resolve_display_offer_status(product.offer_status, dropship_stock)
    payload = {
        "id": product.id,
        "offer_id": product.offer_id,
        "sku": product.sku,
        "plid": product.plid,
        "title": product.title,
        "brand": product.brand,
        "current_price_zar": product.current_price_zar,
        "rrp_zar": product.rrp_zar,
        "buybox_price_zar": bid_service.resolve_buybox_display_price(
            product.current_price_zar,
            product.buybox_price_zar,
            store=store,
            buybox_store=product.buybox_store,
        ),
        "floor_price_zar": product.floor_price_zar,
        "target_price_zar": product.target_price_zar,
        "image_url": product.image_url,
        "takealot_url": bid_service.resolve_takealot_url(product.takealot_url, product.plid),
        "api_status": product.api_status,
        "offer_status": display_offer_status,
        "procurement_price_cny": product.procurement_price_cny,
        "procurement_url": product.procurement_url,
        "product_weight_g": product.product_weight_g,
        "dropship_stock": dropship_stock,
        "leadtime_days": None,
    }
    _apply_status_fields(payload, display_offer_status, product.api_status)
    return payload


def _parse_positive_price(value, field_label: str) -> float:
    try:
        parsed = float(value)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"{field_label}格式不正确") from exc
    if parsed <= 0:
        raise HTTPException(status_code=400, detail=f"{field_label}必须大于 0")
    return parsed


def _parse_non_negative_int(value, field_label: str) -> int:
    try:
        parsed = int(value)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"{field_label}格式不正确") from exc
    if parsed < 0:
        raise HTTPException(status_code=400, detail=f"{field_label}不能小于 0")
    return parsed


def _parse_offer_status(value) -> str:
    status = str(value or "").strip()
    if not status:
        raise HTTPException(status_code=400, detail="状态不能为空")
    if status in _READ_ONLY_OFFER_STATUSES:
        raise HTTPException(status_code=400, detail="Disabled by Takealot 不能手动设置")
    if status not in _MANUAL_OFFER_STATUSES:
        allowed = "、".join(sorted(_MANUAL_OFFER_STATUSES))
        raise HTTPException(status_code=400, detail=f"状态仅支持：{allowed}")
    return status


def _parse_leadtime_days(value) -> int | None:
    if value in (None, "", "None", "none"):
        return None
    try:
        parsed = int(value)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Leadtime 格式不正确") from exc
    if parsed not in _ALLOWED_LEADTIME_DAYS:
        raise HTTPException(status_code=400, detail="Leadtime 目前仅支持 None 或 14 days")
    return parsed


async def _resolve_merchant_warehouse_id(api, requested_warehouse_id: int | None = None) -> int:
    if requested_warehouse_id and requested_warehouse_id > 0:
        return requested_warehouse_id

    payload = await api.get_merchant_warehouses(validated=True)
    candidates = payload.get("merchant_warehouses") or payload.get("warehouses") or []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        for key in ("merchant_warehouse_id", "warehouse_id", "id"):
            value = candidate.get(key)
            if isinstance(value, int) and value > 0:
                return value
        nested = candidate.get("warehouse")
        if isinstance(nested, dict):
            value = nested.get("warehouse_id") or nested.get("id")
            if isinstance(value, int) and value > 0:
                return value

    raise HTTPException(status_code=409, detail="未找到可用的 Takealot 商家仓库，暂时无法同步库存")


async def _resolve_leadtime_stock_warehouse_id(
    api,
    offer_id: str,
    requested_warehouse_id: int | None = None,
) -> int:
    if requested_warehouse_id and requested_warehouse_id > 0:
        return requested_warehouse_id

    try:
        remote_offer = await api.get_offer_detail(offer_id)
    except Exception:
        remote_offer = None

    for item in (remote_offer or {}).get("leadtime_stock") or []:
        if not isinstance(item, dict):
            continue
        merchant_warehouse = item.get("merchant_warehouse") or {}
        if not isinstance(merchant_warehouse, dict):
            continue
        warehouse_id = merchant_warehouse.get("warehouse_id") or merchant_warehouse.get("merchant_warehouse_id")
        if isinstance(warehouse_id, int) and warehouse_id > 0:
            return warehouse_id

    return await _resolve_merchant_warehouse_id(api)


async def _require_store(db, store_id: int, user_id: int):
    store = await store_service.get_store(db, store_id, user_id)
    if not store:
        raise HTTPException(status_code=404, detail="店铺不存在")
    return store


@router.get("")
async def list_products(
    store_id: int, user: ActiveUser, db: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=200),
    q: str = "",
    status: str = "",
    sort: str = "updated",
    dir: str = "desc",
):
    store = await _require_store(db, store_id, user.id)
    counts = await bid_service.count_store_products_by_status(
        db,
        store_id,
        sku=q,
    )
    products, total = await bid_service.list_store_products(
        db, store_id, page=page, page_size=page_size, sku=q, status=status,
    )
    items = [_serialize_product_list_item(product, store) for product in products]
    return {
        "ok": True,
        "total": total,
        "page": page,
        "page_size": page_size,
        "counts": counts,
        "products": items,
    }


@router.get("/{offer_id}")
async def product_detail(store_id: int, offer_id: str, user: ActiveUser, db: DbSession):
    store = await _require_store(db, store_id, user.id)
    product = await bid_service.get_bid_product(db, store_id, offer_id)
    if not product:
        raise HTTPException(status_code=404, detail="商品不存在")

    history = await bid_service.list_bid_log_for_offer(db, store_id, offer_id, limit=5)
    offer_history = [
        {
            "old_price": log.old_price, "new_price": log.new_price,
            "buybox_price": log.buybox_price, "action": log.action,
            "created_at": str(log.created_at) if log.created_at else None,
        }
        for log in history
    ]
    payload = _serialize_product_detail_item(product, store)
    api = store_service.get_takealot_api(store)
    try:
        remote_offer = await api.get_offer_detail(offer_id)
    except RuntimeError:
        remote_offer = None
    if remote_offer:
        remote_leadtime_days = remote_offer.get("leadtime_days")
        remote_stock = bid_service.extract_leadtime_stock_quantity(remote_offer)
        remote_offer_status = bid_service.resolve_effective_offer_status(
            remote_offer.get("status") or payload["offer_status"],
            remote_leadtime_days,
            remote_stock,
        )
        payload["leadtime_days"] = remote_leadtime_days
        payload["offer_status"] = remote_offer_status
        payload["dropship_stock"] = remote_stock
        _apply_status_fields(payload, remote_offer_status, product.api_status)

        dirty = False
        if product.dropship_stock != remote_stock:
            product.dropship_stock = remote_stock
            dirty = True
        if remote_offer_status and product.offer_status != remote_offer_status:
            product.offer_status = remote_offer_status
            dirty = True

        remote_price = _float_or_none(remote_offer.get("selling_price"))
        if remote_price is not None and product.current_price_zar != remote_price:
            product.current_price_zar = remote_price
            payload["current_price_zar"] = remote_price
            dirty = True

        remote_rrp = _float_or_none(remote_offer.get("rrp"))
        if remote_rrp is not None and product.rrp_zar != remote_rrp:
            product.rrp_zar = remote_rrp
            payload["rrp_zar"] = remote_rrp
            dirty = True

        if dirty:
            await db.flush()

    return {
        "ok": True,
        "product": payload,
        "history": offer_history,
    }


@router.post("/{offer_id}/save-sync")
async def product_save_sync(
    store_id: int, offer_id: str, user: ActiveUser, db: DbSession, body: dict,
):
    store = await _require_store(db, store_id, user.id)
    product = await bid_service.get_bid_product(db, store_id, offer_id)
    if not product:
        raise HTTPException(status_code=404, detail="商品不存在")

    result = {"ok": True}
    fields_to_save = {}
    sync_fields = {}
    synced_field_names: list[str] = []
    expected_remote_stock: int | None = None

    api = store_service.get_takealot_api(store)
    requested_offer_status = None
    if "offer_status" in body or "status" in body:
        requested_offer_status = _parse_offer_status(body.get("offer_status", body.get("status")))

    requested_leadtime_days = None
    if "leadtime_days" in body:
        requested_leadtime_days = _parse_leadtime_days(body.get("leadtime_days"))

    if "selling_price_zar" in body:
        price = _parse_positive_price(body["selling_price_zar"], "售价")
        sync_fields["selling_price"] = int(price)
        fields_to_save["current_price_zar"] = price
        synced_field_names.append("selling_price_zar")

    if "rrp_zar" in body:
        rrp = _parse_positive_price(body["rrp_zar"], "RRP")
        sync_fields["rrp"] = int(rrp)
        fields_to_save["rrp_zar"] = rrp
        synced_field_names.append("rrp_zar")

    requested_stock = None
    if "dropship_stock" in body:
        requested_stock = _parse_non_negative_int(body["dropship_stock"], "库存")
        fields_to_save["dropship_stock"] = requested_stock
        synced_field_names.append("dropship_stock")

    requested_warehouse_id = None
    if "warehouse_id" in body:
        requested_warehouse_id = _parse_non_negative_int(body["warehouse_id"], "仓库")
        if requested_warehouse_id == 0:
            requested_warehouse_id = None

    desired_leadtime_days = requested_leadtime_days
    if requested_offer_status == "Buyable":
        desired_leadtime_days = 14
    elif requested_offer_status == "Not Buyable":
        desired_leadtime_days = None

    if requested_offer_status == "Disabled by Seller":
        sync_fields["status"] = requested_offer_status
        fields_to_save["offer_status"] = requested_offer_status
        synced_field_names.append("offer_status")
    elif desired_leadtime_days == 14:
        target_stock = requested_stock if requested_stock is not None else int(product.dropship_stock or 0)
        if target_stock <= 0:
            raise HTTPException(status_code=400, detail="要变成在售，库存必须大于 0，并且 Leadtime 设为 14 days")
        warehouse_id = await _resolve_leadtime_stock_warehouse_id(api, offer_id, requested_warehouse_id)
        sync_fields["leadtime_days"] = 14
        sync_fields["leadtime_stock"] = [
            {"merchant_warehouse_id": warehouse_id, "quantity": target_stock},
        ]
        fields_to_save["offer_status"] = "Buyable"
        expected_remote_stock = target_stock
        synced_field_names.append("leadtime_days")
    elif "leadtime_days" in body or requested_offer_status == "Not Buyable":
        sync_fields["leadtime_days"] = -1
        fields_to_save["offer_status"] = "Not Buyable"
        synced_field_names.append("leadtime_days")
        if requested_offer_status == "Not Buyable":
            fields_to_save["dropship_stock"] = 0

    if requested_stock is not None and desired_leadtime_days != 14:
        warehouse_id = await _resolve_leadtime_stock_warehouse_id(api, offer_id, requested_warehouse_id)
        sync_fields["leadtime_stock"] = [
            {"merchant_warehouse_id": warehouse_id, "quantity": requested_stock},
        ]
        expected_remote_stock = requested_stock

    if sync_fields:
        success, resp = await api.update_offer_fields(offer_id, sync_fields)
        if not success:
            raise HTTPException(status_code=502, detail=f"Takealot 同步失败: {resp}")
        remote_offer = resp.get("offer") or {}
        if expected_remote_stock is not None:
            response_stock = (
                bid_service.extract_leadtime_stock_quantity(remote_offer)
                if isinstance(remote_offer.get("leadtime_stock"), list)
                else None
            )
            if response_stock != expected_remote_stock:
                try:
                    confirmed_offer = await api.get_offer_detail(offer_id)
                except RuntimeError:
                    confirmed_offer = None
                confirmed_stock = bid_service.extract_leadtime_stock_quantity(confirmed_offer)
                if confirmed_stock != expected_remote_stock:
                    actual_label = confirmed_stock if confirmed_offer else response_stock
                    raise HTTPException(
                        status_code=502,
                        detail=f"Takealot 库存同步未生效：目标库存 {expected_remote_stock}，远端仍是 {actual_label}",
                    )
                remote_offer = confirmed_offer or remote_offer
        if "selling_price" in remote_offer:
            fields_to_save["current_price_zar"] = float(remote_offer["selling_price"])
        if "rrp" in remote_offer and remote_offer.get("rrp") is not None:
            fields_to_save["rrp_zar"] = float(remote_offer["rrp"])
        resolved_remote_stock = (
            bid_service.extract_leadtime_stock_quantity(remote_offer)
            if isinstance(remote_offer.get("leadtime_stock"), list)
            else int(fields_to_save.get("dropship_stock", product.dropship_stock or 0) or 0)
        )
        resolved_remote_leadtime = remote_offer.get("leadtime_days", desired_leadtime_days)
        remote_status = bid_service.resolve_effective_offer_status(
            remote_offer.get("status") or fields_to_save.get("offer_status") or product.offer_status,
            resolved_remote_leadtime,
            resolved_remote_stock,
        )
        if "leadtime_stock" in remote_offer:
            fields_to_save["dropship_stock"] = resolved_remote_stock
        if remote_status:
            fields_to_save["offer_status"] = remote_status
        result["sync_result"] = "ok"
        result["synced_fields"] = synced_field_names

    # Procurement fields
    for field in ("procurement_price_cny", "procurement_url",
                  "procurement_length_cm", "procurement_width_cm",
                  "procurement_height_cm", "procurement_weight_g"):
        if field in body:
            fields_to_save[field] = body[field]

    if not fields_to_save:
        raise HTTPException(status_code=400, detail="没有可保存的内容")

    # Save to DB
    for k, v in fields_to_save.items():
        if hasattr(product, k):
            setattr(product, k, v)
    await db.flush()

    if not sync_fields:
        result["sync_result"] = "local_only"
    result["saved_fields"] = sorted(fields_to_save.keys())
    result["product"] = _serialize_product_detail_item(product, store)
    if sync_fields:
        remote_offer = (resp or {}).get("offer") or {}
        result["product"]["leadtime_days"] = remote_offer.get("leadtime_days", desired_leadtime_days)
        result["product"]["offer_status"] = fields_to_save.get("offer_status", result["product"]["offer_status"])
        result["product"]["dropship_stock"] = int(fields_to_save.get("dropship_stock", result["product"]["dropship_stock"]) or 0)
        _apply_status_fields(result["product"], result["product"]["offer_status"], product.api_status)
    return result


@router.post("/sync")
async def products_sync(store_id: int, user: ActiveUser, db: DbSession, redis: RedisConn):
    await _require_store(db, store_id, user.id)
    def _load_task():
        from app.tasks.product_sync_tasks import run_catalog_product_sync
        return run_catalog_product_sync

    try:
        response = await product_sync_progress_service.enqueue_sync(
            redis,
            store_id,
            task_importer=_load_task,
            progress_scope="products",
            lock_scope=product_sync_progress_service.DEFAULT_LOCK_SCOPE,
            queued_message="商品管理同步任务已提交，等待开始...",
            conflict_message="自动出价商品同步正在运行，请稍后再试",
        )
        await _delete_cache_key(redis, _sync_status_cache_key(store_id))
        return response
    except product_sync_progress_service.SyncTaskMissing:
        raise HTTPException(status_code=503, detail="同步任务未就绪")


@router.get("/sync/status")
async def products_sync_status(store_id: int, user: ActiveUser, db: DbSession, redis: RedisConn):
    await _require_store(db, store_id, user.id)
    cache_key = _sync_status_cache_key(store_id)
    cached = await _get_cached_json(redis, cache_key)
    if cached is not None:
        return cached

    progress = await product_sync_progress_service.get_progress(
        redis,
        store_id,
        scope="products",
    )
    payload = {"ok": True, **progress}
    await _set_cached_json(redis, cache_key, payload, _SYNC_STATUS_CACHE_TTL_SECONDS)
    return payload
