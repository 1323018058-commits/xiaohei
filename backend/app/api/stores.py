"""Store management API router — CRUD, sync, offers, sales, shipments."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import ActiveUser, DbSession, RedisConn
from app.schemas.common import OkResponse
from app.schemas.store import StoreCreate, StoreInfo, StoreListResponse, StoreUpdate
from app.services import snapshot_service, store_service

router = APIRouter(prefix="/api/stores", tags=["stores"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _store_to_info(store, health: dict | None = None) -> StoreInfo:
    from app.utils.encryption import decrypt

    def _mask_secret(secret: str) -> str:
        value = str(secret or "")
        if not value:
            return ""
        if len(value) <= 8:
            return "*" * len(value)
        return f"{value[:4]}{'*' * max(4, len(value) - 8)}{value[-4:]}"

    try:
        raw_key = decrypt(store.api_key) if store.api_key else ""
    except Exception:
        raw_key = ""
    return StoreInfo(
        id=store.id,
        store_name=store.store_name,
        store_alias=store.store_alias or "",
        is_active=store.is_active,
        offer_count=store.offer_count,
        takealot_store_id=store.takealot_store_id or "",
        api_key_status=store.api_key_status or "",
        api_key_display=_mask_secret(raw_key),
        auto_push_price=store.auto_push_price,
        min_price_90pct=store.min_price_90pct,
        direct_ship=store.direct_ship,
        notes=store.notes or "",
        last_synced_at=store.last_synced_at.strftime("%Y-%m-%d %H:%M:%S") if store.last_synced_at else None,
        created_at=store.created_at.strftime("%Y-%m-%d %H:%M:%S") if store.created_at else None,
    )


async def _require_store(db, store_id: int, user_id: int):
    store = await store_service.get_store(db, store_id, user_id)
    if not store:
        raise HTTPException(status_code=404, detail="店铺不存在")
    return store


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

@router.get("", response_model=StoreListResponse)
async def list_stores(user: ActiveUser, db: DbSession):
    stores = await store_service.list_stores(db, user.id)
    store_ids = [s.id for s in stores]
    error_counts = await store_service.get_store_bid_error_counts(db, store_ids)

    store_infos = []
    total_score = 0
    health_levels = {"healthy": 0, "warning": 0, "critical": 0}

    for s in stores:
        h = store_service.health_score(s, error_counts.get(s.id, 0))
        total_score += h["score"]
        health_levels[h["level"]] += 1
        store_infos.append(_store_to_info(s, h))

    return StoreListResponse(stores=store_infos)


@router.post("", response_model=StoreInfo, status_code=201)
async def bind_store(body: StoreCreate, user: ActiveUser, db: DbSession):
    # Store limit: admin=20, normal user=5
    existing_stores = await store_service.list_stores(db, user.id)
    max_stores = 20 if user.role == "admin" else 5
    if len(existing_stores) >= max_stores:
        raise HTTPException(
            status_code=403,
            detail=f"已达店铺上限（{max_stores}家），{'管理员最多20家' if user.role != 'admin' else '已达最大限制'}",
        )

    from app.services.takealot_api import TakealotSellerAPI

    # Validate API key against Takealot
    api = TakealotSellerAPI(body.api_key, body.api_secret)
    try:
        info = await api.get_store_info()
    except RuntimeError:
        raise HTTPException(status_code=400, detail="API Key 验证失败，请检查密钥是否正确")

    store = await store_service.create_store(
        db,
        user_id=user.id,
        api_key=body.api_key,
        api_secret=body.api_secret,
        store_name=body.store_name or info.get("store_name", ""),
        takealot_store_id=body.takealot_store_id,
    )
    store.offer_count = info.get("offer_count", 0)
    store.api_key_status = "有效"
    await db.flush()

    return _store_to_info(store)


@router.get("/{store_id}", response_model=StoreInfo)
async def get_store(store_id: int, user: ActiveUser, db: DbSession):
    store = await _require_store(db, store_id, user.id)
    return _store_to_info(store)


@router.patch("/{store_id}", response_model=StoreInfo)
async def update_store(store_id: int, body: StoreUpdate, user: ActiveUser, db: DbSession):
    store = await _require_store(db, store_id, user.id)
    fields = body.model_dump(exclude_unset=True)
    await store_service.update_store(db, store, **fields)
    return _store_to_info(store)


@router.delete("/{store_id}", response_model=OkResponse)
async def delete_store(store_id: int, user: ActiveUser, db: DbSession):
    store = await _require_store(db, store_id, user.id)
    await store_service.soft_delete_store(db, store)
    return OkResponse()


@router.post("/{store_id}/sync")
async def sync_store(store_id: int, user: ActiveUser, db: DbSession):
    store = await _require_store(db, store_id, user.id)
    result = await store_service.sync_store(db, store)
    if not result["ok"]:
        raise HTTPException(status_code=502, detail=result.get("error", "同步失败"))
    return result


# ---------------------------------------------------------------------------
# Cached Takealot data endpoints (offers, sales, finance, warehouses)
# ---------------------------------------------------------------------------

_CACHE_CONFIGS = {
    "offers":                 {"ttl": 120,  "usable": 1800},
    "sales_orders":           {"ttl": 300,  "usable": 7200},
    "financial_statements":   {"ttl": 600,  "usable": 86400},
    "financial_balance":      {"ttl": 120,  "usable": 1800},
    "financial_transactions": {"ttl": 300,  "usable": 7200},
    "merchant_warehouses":    {"ttl": 3600, "usable": 86400},
    "shipment_facilities":    {"ttl": 3600, "usable": 86400},
    "leadtime_orders":        {"ttl": 120,  "usable": 1800},
    "shipments":              {"ttl": 120,  "usable": 1800},
}


async def _cached_endpoint(
    store_id: int,
    user: ActiveUser,
    db: DbSession,
    redis: RedisConn,
    kind: str,
    fetch_fn,
    params: dict | None = None,
):
    """Generic cached endpoint handler."""
    store = await _require_store(db, store_id, user.id)
    cfg = _CACHE_CONFIGS.get(kind, {"ttl": 120, "usable": 1800})

    cache_result = await snapshot_service.get_cached_payload(
        redis, kind, store_id, params,
        ttl_seconds=cfg["ttl"],
        usable_seconds=cfg["usable"],
    )

    if cache_result["cached"] and not cache_result["snapshot_stale"]:
        return {
            "ok": True,
            "data": cache_result["payload"],
            "cached": True,
            "snapshot_stale": False,
        }

    if cache_result["cached"] and cache_result["snapshot_stale"]:
        # Return stale data, trigger background refresh via Celery
        if cache_result["needs_refresh"]:
            from app.tasks.store_tasks import refresh_snapshot
            refresh_snapshot.delay(store_id, kind, params)
        return {
            "ok": True,
            "data": cache_result["payload"],
            "cached": True,
            "snapshot_stale": True,
            "refreshing": True,
        }

    # Cold miss — fetch synchronously
    api = store_service.get_takealot_api(store)
    try:
        data = await fetch_fn(api, params)
        await snapshot_service.save_snapshot(redis, kind, store_id, data, params)
        return {"ok": True, "data": data, "cached": False, "snapshot_stale": False}
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/{store_id}/offers")
async def store_offers(
    store_id: int, user: ActiveUser, db: DbSession, redis: RedisConn,
    page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=500),
):
    params = {"page": page, "page_size": page_size}

    async def fetch(api, p):
        return await api.get_offers(page=p["page"], page_size=p["page_size"])

    return await _cached_endpoint(store_id, user, db, redis, "offers", fetch, params)


@router.get("/{store_id}/sales/orders")
async def store_sales_orders(
    store_id: int, user: ActiveUser, db: DbSession, redis: RedisConn,
    start_date: str = "", end_date: str = "",
    page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=500),
):
    params = {"page": page, "page_size": page_size, "start_date": start_date, "end_date": end_date}

    async def fetch(api, p):
        return await api.get_sales_orders(
            start_date=p.get("start_date", ""), end_date=p.get("end_date", ""),
            page=p["page"], page_size=p["page_size"],
        )

    return await _cached_endpoint(store_id, user, db, redis, "sales_orders", fetch, params)


@router.get("/{store_id}/financial/statements")
async def store_financial_statements(
    store_id: int, user: ActiveUser, db: DbSession, redis: RedisConn,
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100),
):
    params = {"page": page, "page_size": page_size}

    async def fetch(api, p):
        return await api.get_financial_statements(page=p["page"], page_size=p["page_size"])

    return await _cached_endpoint(store_id, user, db, redis, "financial_statements", fetch, params)


@router.get("/{store_id}/financial/balance")
async def store_financial_balance(
    store_id: int, user: ActiveUser, db: DbSession, redis: RedisConn,
):
    async def fetch(api, p):
        return await api.get_seller_balances()

    return await _cached_endpoint(store_id, user, db, redis, "financial_balance", fetch)


@router.get("/{store_id}/financial/transactions")
async def store_financial_transactions(
    store_id: int, user: ActiveUser, db: DbSession, redis: RedisConn,
    date_from: str = "", date_to: str = "",
    page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=500),
):
    params = {"page": page, "page_size": page_size, "date_from": date_from, "date_to": date_to}

    async def fetch(api, p):
        return await api.get_seller_transactions(
            date_from=p.get("date_from", ""), date_to=p.get("date_to", ""),
            page=p["page"], page_size=p["page_size"],
        )

    return await _cached_endpoint(store_id, user, db, redis, "financial_transactions", fetch, params)


@router.get("/{store_id}/merchant-warehouses")
async def store_merchant_warehouses(
    store_id: int, user: ActiveUser, db: DbSession, redis: RedisConn,
):
    async def fetch(api, p):
        return await api.get_merchant_warehouses()

    return await _cached_endpoint(store_id, user, db, redis, "merchant_warehouses", fetch)


# ---------------------------------------------------------------------------
# Shipments
# ---------------------------------------------------------------------------

@router.get("/{store_id}/shipment/facilities")
async def store_shipment_facilities(
    store_id: int, user: ActiveUser, db: DbSession, redis: RedisConn,
):
    async def fetch(api, p):
        return await api.get_shipment_facilities()

    return await _cached_endpoint(store_id, user, db, redis, "shipment_facilities", fetch)


@router.get("/{store_id}/shipments")
async def store_shipments(
    store_id: int, user: ActiveUser, db: DbSession, redis: RedisConn,
    shipment_state: str = "",
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
):
    params = {"page": page, "page_size": page_size, "shipment_state": shipment_state}

    async def fetch(api, p):
        return await api.get_shipments(
            shipment_state=p.get("shipment_state", ""),
            page=p["page"], page_size=p["page_size"],
        )

    return await _cached_endpoint(store_id, user, db, redis, "shipments", fetch, params)


@router.get("/{store_id}/shipments/{shipment_id}")
async def store_shipment_detail(
    store_id: int, shipment_id: str, user: ActiveUser, db: DbSession,
):
    store = await _require_store(db, store_id, user.id)
    api = store_service.get_takealot_api(store)
    try:
        return {"ok": True, "data": await api.get_shipment_details(shipment_id)}
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/{store_id}/shipments/{shipment_id}/items")
async def store_shipment_items(
    store_id: int, shipment_id: str, user: ActiveUser, db: DbSession,
    page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=500),
):
    store = await _require_store(db, store_id, user.id)
    api = store_service.get_takealot_api(store)
    try:
        return {"ok": True, "data": await api.get_shipment_items(shipment_id, page=page, page_size=page_size)}
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/{store_id}/shipment/leadtime-orders")
async def store_leadtime_orders(
    store_id: int, user: ActiveUser, db: DbSession, redis: RedisConn,
    page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=500),
):
    params = {"page": page, "page_size": page_size}

    async def fetch(api, p):
        return await api.get_leadtime_order_items(page=p["page"], page_size=p["page_size"])

    return await _cached_endpoint(store_id, user, db, redis, "leadtime_orders", fetch, params)


@router.post("/{store_id}/shipment/leadtime-preview")
async def store_leadtime_preview(
    store_id: int, user: ActiveUser, db: DbSession, body: dict,
):
    store = await _require_store(db, store_id, user.id)
    api = store_service.get_takealot_api(store)
    ids = body.get("leadtime_order_item_id_list", [])
    if not ids:
        raise HTTPException(status_code=400, detail="缺少 leadtime_order_item_id_list")
    try:
        return {"ok": True, "data": await api.preview_leadtime_order_items(ids)}
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/{store_id}/shipment/review")
async def store_shipment_review(
    store_id: int, user: ActiveUser, db: DbSession, body: dict,
):
    store = await _require_store(db, store_id, user.id)
    api = store_service.get_takealot_api(store)
    items = body.get("shipment_items", [])
    if not items:
        raise HTTPException(status_code=400, detail="缺少 shipment_items")
    try:
        return {"ok": True, "data": await api.create_shipments_review(items)}
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/{store_id}/shipments/{shipment_id}/task-request")
async def store_shipment_task_request(
    store_id: int, shipment_id: str, user: ActiveUser, db: DbSession, body: dict,
):
    store = await _require_store(db, store_id, user.id)
    api = store_service.get_takealot_api(store)
    task_type_id = body.get("task_type_id")
    if not task_type_id:
        raise HTTPException(status_code=400, detail="缺少 task_type_id")
    try:
        data = await api.create_shipment_task_request(
            shipment_id, task_type_id, body.get("request_params"),
        )
        return {"ok": True, "data": data}
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/{store_id}/shipments/{shipment_id}/confirm-preview")
async def store_shipment_confirm_preview(
    store_id: int, shipment_id: str, user: ActiveUser, db: DbSession,
):
    store = await _require_store(db, store_id, user.id)
    api = store_service.get_takealot_api(store)
    try:
        return {"ok": True, "data": await api.get_shipment_confirm_preview(shipment_id)}
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/{store_id}/shipment/task/{task_id}/status")
async def store_shipment_task_status(
    store_id: int, task_id: str, user: ActiveUser, db: DbSession,
):
    store = await _require_store(db, store_id, user.id)
    api = store_service.get_takealot_api(store)
    try:
        return {"ok": True, "data": await api.get_shipment_task_status(task_id)}
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/{store_id}/shipment/task/{task_id}/result")
async def store_shipment_task_result(
    store_id: int, task_id: str, user: ActiveUser, db: DbSession,
):
    store = await _require_store(db, store_id, user.id)
    api = store_service.get_takealot_api(store)
    try:
        return {"ok": True, "data": await api.get_shipment_task_result(task_id)}
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.put("/{store_id}/shipments/{shipment_id}/reference")
async def store_shipment_reference(
    store_id: int, shipment_id: str, user: ActiveUser, db: DbSession, body: dict,
):
    store = await _require_store(db, store_id, user.id)
    api = store_service.get_takealot_api(store)
    reference = body.get("seller_reference", "")
    try:
        return {"ok": True, "data": await api.update_shipment_reference(shipment_id, reference)}
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.put("/{store_id}/shipments/{shipment_id}/tracking-info")
async def store_shipment_tracking_info(
    store_id: int, shipment_id: str, user: ActiveUser, db: DbSession, body: dict,
):
    store = await _require_store(db, store_id, user.id)
    api = store_service.get_takealot_api(store)
    try:
        return {"ok": True, "data": await api.update_shipment_tracking_info(shipment_id, body)}
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.put("/{store_id}/shipments/{shipment_id}/shipped")
async def store_mark_shipment_shipped(
    store_id: int, shipment_id: str, user: ActiveUser, db: DbSession, body: dict,
):
    store = await _require_store(db, store_id, user.id)
    api = store_service.get_takealot_api(store)
    shipped = body.get("status", "shipped") == "shipped"
    try:
        return {"ok": True, "data": await api.mark_shipment_shipped(shipment_id, shipped)}
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
