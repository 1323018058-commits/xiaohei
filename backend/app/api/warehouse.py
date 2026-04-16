"""Warehouse management API router — shipment fulfillment workflows."""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DbSession, RedisConn
from app.models.store import StoreBinding
from app.models.warehouse import FulfillmentDraft, FulfillmentAuditLog
from app.schemas.warehouse import DraftSave, DraftResponse, DraftItemResponse, CnxSubmitRequest, JobSummary, AuditLogEntry
from app.services import store_service, warehouse_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/warehouse", tags=["warehouse"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_staff(user):
    """Require admin or warehouse role."""
    if user.role not in ("admin", "warehouse"):
        raise HTTPException(status_code=403, detail="仅限仓库人员访问")


async def _require_store_access(db: AsyncSession, store_id: int, user) -> StoreBinding:
    """admin/warehouse can access all stores, regular users only their own."""
    result = await db.execute(
        select(StoreBinding).where(StoreBinding.id == store_id, StoreBinding.is_active == 1)
    )
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(status_code=404, detail="店铺不存在")
    if user.role not in ("admin", "warehouse") and store.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问该店铺")
    return store


def _draft_to_response(draft: FulfillmentDraft) -> dict:
    """Serialize a FulfillmentDraft to a dict matching DraftResponse schema."""
    ready_count, total_items = warehouse_service.compute_ready_summary(draft)
    items = []
    for item in (draft.items or []):
        items.append({
            "id": item.id,
            "shipment_item_id": item.shipment_item_id,
            "line_no": item.line_no,
            "sku": item.sku,
            "title": item.title,
            "takealot_url": item.takealot_url,
            "tsin_id": item.tsin_id,
            "qty_required": item.qty_required,
            "qty_sending": item.qty_sending,
            "arrived_qty": item.arrived_qty,
            "domestic_tracking_no": item.domestic_tracking_no,
            "domestic_carrier": item.domestic_carrier,
            "declared_en_name": item.declared_en_name,
            "declared_cn_name": item.declared_cn_name,
            "hs_code": item.hs_code,
            "origin_country": item.origin_country,
            "unit_price_usd": item.unit_price_usd,
            "unit_weight_kg": item.unit_weight_kg,
            "note": item.note,
        })
    return {
        "id": draft.id,
        "store_binding_id": draft.store_binding_id,
        "user_id": draft.user_id,
        "shipment_id": draft.shipment_id,
        "shipment_name": draft.shipment_name,
        "po_number": draft.po_number,
        "due_date": draft.due_date,
        "facility_code": draft.facility_code,
        "warehouse_name": draft.warehouse_name,
        "package_count": draft.package_count,
        "total_weight_kg": draft.total_weight_kg,
        "decl_currency": draft.decl_currency,
        "sender_country": draft.sender_country,
        "delivery_address": draft.delivery_address,
        "selected_cnx_warehouse_id": draft.selected_cnx_warehouse_id,
        "selected_cnx_line_id": draft.selected_cnx_line_id,
        "cnx_order_no": draft.cnx_order_no,
        "cnx_forecasted_at": str(draft.cnx_forecasted_at) if draft.cnx_forecasted_at else None,
        "workflow_status": draft.workflow_status,
        "warehouse_received_complete": draft.warehouse_received_complete,
        "labels_done": draft.labels_done,
        "labels_done_at": str(draft.labels_done_at) if draft.labels_done_at else None,
        "sent_to_cnx": draft.sent_to_cnx,
        "sent_to_cnx_at": str(draft.sent_to_cnx_at) if draft.sent_to_cnx_at else None,
        "notify_user_cnx_at": str(draft.notify_user_cnx_at) if draft.notify_user_cnx_at else None,
        "warehouse_note": draft.warehouse_note,
        "updated_by_username": draft.updated_by_username,
        "updated_by_role": draft.updated_by_role,
        "version": draft.version,
        "created_at": str(draft.created_at) if draft.created_at else None,
        "updated_at": str(draft.updated_at) if draft.updated_at else None,
        "ready_count": ready_count,
        "total_items": total_items,
        "items": items,
    }


# ---------------------------------------------------------------------------
# GET /api/warehouse/jobs — list all fulfillment jobs (staff)
# ---------------------------------------------------------------------------

@router.get("/jobs")
async def warehouse_jobs(user: CurrentUser, db: DbSession, redis: RedisConn):
    """List all shipments across active stores — merges Takealot API + saved drafts."""
    _require_staff(user)

    # Check Redis cache
    cache_key = "warehouse:jobs:list"
    cached = await redis.get(cache_key)
    if cached:
        try:
            return json.loads(cached)
        except (json.JSONDecodeError, TypeError):
            pass

    # 1. Load all active stores
    result = await db.execute(
        select(StoreBinding).where(StoreBinding.is_active == 1)
    )
    stores = list(result.scalars().all())
    if not stores:
        return {"ok": True, "items": []}

    # 2. Load existing drafts from DB
    drafts = await warehouse_service.list_drafts_for_warehouse(db)
    existing_keys: set[tuple[int, int]] = set()
    items: list[dict] = []

    stores_map: dict[int, StoreBinding] = {s.id: s for s in stores}

    for draft in drafts:
        store = stores_map.get(draft.store_binding_id)
        store_alias = ""
        if store:
            store_alias = store.store_alias or store.store_name or f"Store #{store.id}"

        ready_count, total_items = warehouse_service.compute_ready_summary(draft)
        existing_keys.add((draft.store_binding_id, draft.shipment_id))
        items.append({
            "store_id": draft.store_binding_id,
            "store_alias": store_alias,
            "shipment_id": draft.shipment_id,
            "shipment_name": draft.shipment_name,
            "po_number": draft.po_number,
            "due_date": draft.due_date,
            "workflow_status": draft.workflow_status,
            "ready_count": ready_count,
            "total_items": total_items,
            "updated_at": str(draft.updated_at) if draft.updated_at else None,
            "updated_by_username": draft.updated_by_username,
        })

    # 3. Fetch new shipments from Takealot API for each store (best-effort)
    refreshing_count = 0
    for store in stores:
        try:
            api = store_service.get_takealot_api(store)
            data = await api.get_shipments(page=1, page_size=50)
            shipments_list = data.get("shipments") or data.get("results") or []

            for s in shipments_list:
                sid = int(s.get("shipment_id") or 0)
                if sid <= 0:
                    continue
                key = (store.id, sid)
                if key in existing_keys:
                    continue
                existing_keys.add(key)

                # Parse shipment info
                ref = s.get("reference") or ""
                instruction = s.get("instruction_id") or ""
                due_obj = s.get("due_date") or {}
                due_date = str(due_obj.get("date") or "") if isinstance(due_obj, dict) else str(due_obj or "")
                state = s.get("shipment_state") or ""
                total_qty = int(s.get("total_quantity") or 0)

                store_alias = store.store_alias or store.store_name or f"Store #{store.id}"
                items.append({
                    "store_id": store.id,
                    "store_alias": store_alias,
                    "shipment_id": sid,
                    "shipment_name": ref or f"Shipment {sid}",
                    "po_number": str(instruction),
                    "due_date": due_date,
                    "workflow_status": "待用户预报快递",
                    "ready_count": 0,
                    "total_items": total_qty,
                    "updated_at": None,
                    "updated_by_username": "",
                })
        except Exception as exc:
            logger.warning("Failed to fetch shipments for store %d: %s", store.id, exc)
            refreshing_count += 1

    # Sort by updated_at (saved drafts first) then by due_date
    items.sort(key=lambda x: x.get("updated_at") or "", reverse=True)

    response = {"ok": True, "items": items, "refreshing_store_count": refreshing_count}

    # Cache for 30 seconds
    try:
        await redis.setex(cache_key, 30, json.dumps(response, ensure_ascii=False, default=str))
    except Exception:
        logger.warning("Failed to set Redis cache for warehouse jobs list")

    return response


# ---------------------------------------------------------------------------
# GET /api/warehouse/jobs/{store_id}/{shipment_id} — job detail
# ---------------------------------------------------------------------------

@router.get("/jobs/{store_id}/{shipment_id}")
async def warehouse_job_detail(
    store_id: int, shipment_id: str, user: CurrentUser, db: DbSession,
):
    """Get or create a fulfillment draft for a specific shipment."""
    store = await _require_store_access(db, store_id, user)

    # Validate shipment_id is numeric
    if not shipment_id.isdigit():
        raise HTTPException(status_code=400, detail="shipment_id 必须为数字")

    sid = int(shipment_id)
    api = store_service.get_takealot_api(store)

    # Fetch Takealot data and draft concurrently
    async def _fetch_shipment():
        try:
            return await api.get_shipment_details(shipment_id)
        except RuntimeError as exc:
            logger.warning("Failed to fetch shipment details: %s", exc)
            return {}

    async def _fetch_items():
        try:
            return await api.get_shipment_items(shipment_id, page=1, page_size=200)
        except RuntimeError as exc:
            logger.warning("Failed to fetch shipment items: %s", exc)
            return {}

    shipment_data, items_data = await asyncio.gather(
        _fetch_shipment(), _fetch_items()
    )

    # Get or create draft
    draft = await warehouse_service.get_draft(db, store_id, sid)

    if not draft:
        draft = await warehouse_service.create_draft_from_api(
            db,
            user_id=store.user_id or user.id,
            store_binding_id=store_id,
            shipment_id=sid,
            shipment_payload=shipment_data,
            items_payload=items_data,
        )

    return {
        "ok": True,
        "draft": _draft_to_response(draft),
        "shipment": shipment_data,
        "items": items_data,
    }


# ---------------------------------------------------------------------------
# POST /api/warehouse/jobs/{store_id}/{shipment_id} — save draft
# ---------------------------------------------------------------------------

@router.post("/jobs/{store_id}/{shipment_id}")
async def warehouse_job_save(
    store_id: int,
    shipment_id: str,
    body: DraftSave,
    user: CurrentUser,
    db: DbSession,
    redis: RedisConn,
):
    """Save (update) a fulfillment draft with optimistic locking."""
    store = await _require_store_access(db, store_id, user)

    if not shipment_id.isdigit():
        raise HTTPException(status_code=400, detail="shipment_id 必须为数字")

    sid = int(shipment_id)
    draft = await warehouse_service.get_draft(db, store_id, sid)
    if not draft:
        raise HTTPException(status_code=404, detail="履约草稿不存在，请先访问详情页创建")

    is_staff = user.role in ("admin", "warehouse")

    # Convert Pydantic model to dict
    data = body.model_dump()

    try:
        draft = await warehouse_service.update_draft(db, draft, data, user, is_staff)
    except ValueError as exc:
        if "版本冲突" in str(exc):
            raise HTTPException(status_code=409, detail="版本冲突，请刷新页面后重试")
        raise HTTPException(status_code=400, detail=str(exc))

    # Sync notification
    try:
        await warehouse_service.sync_workflow_notification(db, draft, store)
    except Exception:
        logger.warning("Failed to sync workflow notification for draft %d", draft.id)

    # Clear Redis cache
    try:
        await redis.delete("warehouse:jobs:list")
    except Exception:
        pass

    return {
        "ok": True,
        "draft_id": draft.id,
        "version": draft.version,
        "workflow_status": draft.workflow_status,
    }


# ---------------------------------------------------------------------------
# GET /api/warehouse/print/{store_id}/{shipment_id} — print data (staff)
# ---------------------------------------------------------------------------

@router.get("/print/{store_id}/{shipment_id}")
async def warehouse_print_data(
    store_id: int, shipment_id: str, user: CurrentUser, db: DbSession,
):
    """Return label printing data for a shipment (staff only)."""
    _require_staff(user)
    store = await _require_store_access(db, store_id, user)

    if not shipment_id.isdigit():
        raise HTTPException(status_code=400, detail="shipment_id 必须为数字")

    sid = int(shipment_id)
    draft = await warehouse_service.get_draft(db, store_id, sid)
    if not draft:
        raise HTTPException(status_code=404, detail="履约草稿不存在")

    store_alias = store.store_alias or store.store_name or f"Store #{store.id}"

    items = []
    for item in (draft.items or []):
        items.append({
            "line_no": item.line_no,
            "sku": item.sku,
            "title": item.title,
            "tsin_id": item.tsin_id,
            "qty_sending": item.qty_sending,
            "arrived_qty": item.arrived_qty,
            "declared_en_name": item.declared_en_name,
            "declared_cn_name": item.declared_cn_name,
            "hs_code": item.hs_code,
            "origin_country": item.origin_country,
            "unit_price_usd": item.unit_price_usd,
            "unit_weight_kg": item.unit_weight_kg,
            "domestic_tracking_no": item.domestic_tracking_no,
            "domestic_carrier": item.domestic_carrier,
        })

    return {
        "ok": True,
        "store_alias": store_alias,
        "shipment_id": draft.shipment_id,
        "shipment_name": draft.shipment_name,
        "po_number": draft.po_number,
        "due_date": draft.due_date,
        "facility_code": draft.facility_code,
        "warehouse_name": draft.warehouse_name,
        "package_count": draft.package_count,
        "total_weight_kg": draft.total_weight_kg,
        "decl_currency": draft.decl_currency,
        "sender_country": draft.sender_country,
        "delivery_address": draft.delivery_address,
        "items": items,
    }


# ---------------------------------------------------------------------------
# POST /api/warehouse/jobs/{store_id}/{shipment_id}/cnx-submit — submit CNX
# ---------------------------------------------------------------------------

@router.post("/jobs/{store_id}/{shipment_id}/cnx-submit")
async def warehouse_cnx_submit(
    store_id: int,
    shipment_id: str,
    body: CnxSubmitRequest,
    user: CurrentUser,
    db: DbSession,
    redis: RedisConn,
):
    """Submit a CNX (嘉鸿) forecast for a shipment. Dispatches as Celery task."""
    store = await _require_store_access(db, store_id, user)

    if not shipment_id.isdigit():
        raise HTTPException(status_code=400, detail="shipment_id 必须为数字")

    sid = int(shipment_id)
    draft = await warehouse_service.get_draft(db, store_id, sid)
    if not draft:
        raise HTTPException(status_code=404, detail="履约草稿不存在")

    if draft.cnx_order_no:
        raise HTTPException(status_code=400, detail="该 shipment 已完成嘉鸿预报")

    # Update CNX config on draft
    draft.selected_cnx_warehouse_id = body.selected_cnx_warehouse_id
    draft.selected_cnx_line_id = body.selected_cnx_line_id
    draft.package_count = body.package_count
    draft.total_weight_kg = body.total_weight_kg
    draft.length_cm = body.length_cm
    draft.width_cm = body.width_cm
    draft.height_cm = body.height_cm
    await db.flush()

    # Dispatch Celery task
    try:
        from app.tasks.warehouse_tasks import submit_cnx_forecast
        task = submit_cnx_forecast.delay(draft.id, user.id)
        task_id = task.id
    except Exception as exc:
        logger.error("Failed to dispatch CNX submit task: %s", exc)
        raise HTTPException(status_code=500, detail="提交嘉鸿预报任务失败，请稍后重试")

    # Clear cache
    try:
        await redis.delete("warehouse:jobs:list")
    except Exception:
        pass

    return {
        "ok": True,
        "message": "嘉鸿预报任务已提交",
        "task_id": task_id,
    }


# ---------------------------------------------------------------------------
# GET /api/warehouse/audit/{store_id}/{shipment_id} — audit log (staff)
# ---------------------------------------------------------------------------

@router.get("/audit/{store_id}/{shipment_id}")
async def warehouse_audit_log(
    store_id: int,
    shipment_id: str,
    user: CurrentUser,
    db: DbSession,
    limit: int = Query(50, ge=1, le=200),
):
    """Return audit log entries for a specific shipment draft (staff only)."""
    _require_staff(user)
    await _require_store_access(db, store_id, user)

    if not shipment_id.isdigit():
        raise HTTPException(status_code=400, detail="shipment_id 必须为数字")

    sid = int(shipment_id)
    draft = await warehouse_service.get_draft(db, store_id, sid)
    if not draft:
        raise HTTPException(status_code=404, detail="履约草稿不存在")

    result = await db.execute(
        select(FulfillmentAuditLog)
        .where(FulfillmentAuditLog.draft_id == draft.id)
        .order_by(FulfillmentAuditLog.created_at.desc())
        .limit(limit)
    )
    logs = list(result.scalars().all())

    items = []
    for log in logs:
        items.append({
            "id": log.id,
            "action": log.action,
            "old_status": log.old_status,
            "new_status": log.new_status,
            "changes_json": log.changes_json,
            "username": log.username,
            "role": log.role,
            "created_at": str(log.created_at) if log.created_at else None,
        })

    return {"ok": True, "items": items}
