"""Warehouse fulfillment service — draft CRUD, workflow status, audit."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.warehouse import FulfillmentDraft, FulfillmentDraftItem, FulfillmentAuditLog
from app.models.notification import SiteNotification
from app.models.store import StoreBinding

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Permission whitelists
# ---------------------------------------------------------------------------

USER_EDITABLE_ITEM_FIELDS = {
    "domestic_tracking_no", "domestic_carrier",
    "declared_en_name", "declared_cn_name",
    "hs_code", "origin_country",
    "unit_price_usd", "unit_weight_kg", "note",
}

STAFF_ONLY_DRAFT_FIELDS = {
    "warehouse_received_complete", "labels_done",
    "sent_to_cnx", "warehouse_note",
}

STAFF_ONLY_ITEM_FIELDS = {"arrived_qty"}

# All item fields that can appear in an update payload
ALL_ITEM_FIELDS = USER_EDITABLE_ITEM_FIELDS | STAFF_ONLY_ITEM_FIELDS | {
    "shipment_item_id", "line_no", "sku", "title", "takealot_url",
    "tsin_id", "qty_required", "qty_sending",
}


# ---------------------------------------------------------------------------
# Workflow status machine
# ---------------------------------------------------------------------------

def compute_workflow_status(draft: FulfillmentDraft) -> str:
    """Determine the current workflow status based on draft state (priority order)."""
    if draft.cnx_order_no:
        return "嘉鸿已预报"
    if draft.sent_to_cnx == 1:
        return "待用户预报嘉鸿"
    if draft.labels_done == 1:
        return "待送嘉鸿"
    if draft.warehouse_received_complete == 1:
        return "待贴三标"

    # Check if all items have domestic tracking numbers
    items = draft.items or []
    if items and all(
        (item.domestic_tracking_no or "").strip() for item in items
    ):
        return "待到仓"

    return "待用户预报快递"


def compute_ready_summary(draft: FulfillmentDraft) -> tuple[int, int]:
    """Return (ready_count, total_items).

    An item is 'ready' when arrived_qty >= qty_sending AND has a domestic tracking number.
    """
    items = draft.items or []
    total = len(items)
    ready = sum(
        1 for item in items
        if item.arrived_qty >= item.qty_sending
        and (item.domestic_tracking_no or "").strip()
    )
    return ready, total


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

async def get_draft(
    db: AsyncSession,
    store_binding_id: int,
    shipment_id: int,
) -> FulfillmentDraft | None:
    """Fetch a single draft with items eagerly loaded (avoids N+1)."""
    result = await db.execute(
        select(FulfillmentDraft)
        .where(
            FulfillmentDraft.store_binding_id == store_binding_id,
            FulfillmentDraft.shipment_id == shipment_id,
        )
        .options(selectinload(FulfillmentDraft.items))
    )
    return result.scalar_one_or_none()


async def list_drafts_for_warehouse(db: AsyncSession) -> list[FulfillmentDraft]:
    """List all drafts for active stores, ordered by updated_at DESC."""
    result = await db.execute(
        select(FulfillmentDraft)
        .join(StoreBinding, FulfillmentDraft.store_binding_id == StoreBinding.id)
        .where(StoreBinding.is_active == 1)
        .options(selectinload(FulfillmentDraft.items))
        .order_by(FulfillmentDraft.updated_at.desc())
    )
    return list(result.scalars().all())


async def create_draft_from_api(
    db: AsyncSession,
    user_id: int,
    store_binding_id: int,
    shipment_id: int,
    shipment_payload: dict,
    items_payload: dict,
) -> FulfillmentDraft:
    """Create a FulfillmentDraft from Takealot API response data.

    Mirrors the old _default_shipment_cnx_draft logic.
    """
    draft = FulfillmentDraft(
        store_binding_id=store_binding_id,
        user_id=user_id,
        shipment_id=shipment_id,
        shipment_name=shipment_payload.get("shipment_name", ""),
        po_number=shipment_payload.get("po_number", ""),
        due_date=shipment_payload.get("due_date", ""),
        facility_code=shipment_payload.get("facility_code", ""),
        facility_id=shipment_payload.get("facility_id"),
        warehouse_name=shipment_payload.get("warehouse_name", ""),
        delivery_address=shipment_payload.get("delivery_address", ""),
        workflow_status="待用户预报快递",
        version=1,
    )
    db.add(draft)
    await db.flush()

    # Parse items from API response
    raw_items = items_payload.get("shipment_items", [])
    if not raw_items:
        raw_items = items_payload.get("items", [])
    if not raw_items and isinstance(items_payload, list):
        raw_items = items_payload

    for idx, raw in enumerate(raw_items):
        item = FulfillmentDraftItem(
            draft_id=draft.id,
            shipment_item_id=str(raw.get("shipment_item_id", "")),
            line_no=idx + 1,
            sku=raw.get("sku", raw.get("offer_sku", "")),
            title=raw.get("product_title", raw.get("title", "")),
            takealot_url=raw.get("takealot_url", ""),
            tsin_id=str(raw.get("tsin_id", "")),
            qty_required=raw.get("quantity_required", raw.get("qty_required", 0)),
            qty_sending=raw.get("quantity_sending", raw.get("qty_sending", 1)),
            arrived_qty=0,
            domestic_tracking_no="",
            domestic_carrier="",
            declared_en_name=raw.get("product_title", raw.get("title", ""))[:255],
            declared_cn_name="",
            hs_code="",
            origin_country="CN-China/中国",
            unit_price_usd=0.1,
            unit_weight_kg=0.5,
            note="",
        )
        db.add(item)

    await db.flush()

    # Reload with items
    result = await db.execute(
        select(FulfillmentDraft)
        .where(FulfillmentDraft.id == draft.id)
        .options(selectinload(FulfillmentDraft.items))
    )
    draft = result.scalar_one()

    # Set initial workflow status
    draft.workflow_status = compute_workflow_status(draft)
    await db.flush()

    # Write creation audit log
    await write_audit_log(db, draft, None, "create", "", draft.workflow_status)

    return draft


async def update_draft(
    db: AsyncSession,
    draft: FulfillmentDraft,
    data: dict,
    user,
    is_staff: bool,
) -> FulfillmentDraft:
    """Core update logic with optimistic locking and field-level permissions.

    Args:
        db: Async database session.
        draft: The draft to update (must have items loaded).
        data: Dict of fields to update (from DraftSave schema).
        user: The current user performing the update.
        is_staff: Whether the user has staff (admin/warehouse) role.

    Raises:
        ValueError: On version conflict.
    """
    # Optimistic lock check
    if data.get("version") != draft.version:
        raise ValueError("版本冲突")

    old_status = draft.workflow_status
    changes: dict = {}

    # --- Update draft-level fields ---
    draft_updatable = {
        "shipment_name", "po_number", "due_date", "facility_code",
        "facility_id", "warehouse_name", "package_count", "total_weight_kg",
        "length_cm", "width_cm", "height_cm", "decl_currency",
        "sender_country", "bill_files", "delivery_address",
        "selected_cnx_warehouse_id", "selected_cnx_line_id",
    }
    if is_staff:
        draft_updatable |= STAFF_ONLY_DRAFT_FIELDS

    for field in draft_updatable:
        if field in data:
            new_val = data[field]
            old_val = getattr(draft, field, None)
            # Normalize bool -> int for integer fields
            if isinstance(new_val, bool):
                new_val = int(new_val)
            if old_val != new_val:
                changes[field] = {"old": old_val, "new": new_val}
                setattr(draft, field, new_val)

    # Timestamp helpers for staff state changes
    now = datetime.now(timezone.utc)
    if "labels_done" in changes and draft.labels_done == 1:
        draft.labels_done_at = now
    if "sent_to_cnx" in changes and draft.sent_to_cnx == 1:
        draft.sent_to_cnx_at = now

    # --- Update items ---
    items_data = data.get("items", [])
    if items_data:
        # Build a lookup by line_no for existing items
        existing_items = {item.line_no: item for item in (draft.items or [])}

        allowed_item_fields = set(USER_EDITABLE_ITEM_FIELDS)
        if is_staff:
            allowed_item_fields |= STAFF_ONLY_ITEM_FIELDS

        for idx, item_data in enumerate(items_data):
            item_dict = item_data if isinstance(item_data, dict) else item_data.model_dump()
            line_no = item_dict.get("line_no", idx + 1)
            existing_item = existing_items.get(line_no)

            if not existing_item and draft.items and idx < len(draft.items):
                existing_item = draft.items[idx]

            if not existing_item:
                continue

            for field in allowed_item_fields:
                if field in item_dict:
                    new_val = item_dict[field]
                    old_val = getattr(existing_item, field, None)
                    if old_val != new_val:
                        item_key = f"items[{line_no}].{field}"
                        changes[item_key] = {"old": old_val, "new": new_val}
                        setattr(existing_item, field, new_val)

    # --- Recompute workflow status ---
    draft.workflow_status = compute_workflow_status(draft)
    new_status = draft.workflow_status

    if old_status != new_status:
        changes["workflow_status"] = {"old": old_status, "new": new_status}

    # --- Update audit fields ---
    draft.updated_by_user_id = user.id
    draft.updated_by_username = user.username
    draft.updated_by_role = user.role
    draft.version += 1

    await db.flush()

    # --- Audit log ---
    await write_audit_log(
        db, draft, user, "update", old_status, new_status,
        changes_json=json.dumps(changes, ensure_ascii=False, default=str) if changes else "",
    )

    return draft


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

_STATUS_NOTIF_MAP = {
    "待用户预报快递": {"level": "info", "title": "履约单等待快递预报"},
    "待到仓": {"level": "info", "title": "快递已发出，等待到仓"},
    "待贴三标": {"level": "warning", "title": "货物已到仓，等待贴三标"},
    "待送嘉鸿": {"level": "warning", "title": "三标已完成，等待送嘉鸿"},
    "待用户预报嘉鸿": {"level": "warning", "title": "已送嘉鸿，等待用户预报"},
    "嘉鸿已预报": {"level": "success", "title": "嘉鸿已预报完成"},
}


async def sync_workflow_notification(
    db: AsyncSession,
    draft: FulfillmentDraft,
    store_binding: StoreBinding,
) -> None:
    """Upsert a SiteNotification for the current workflow status."""
    status = draft.workflow_status
    notif_info = _STATUS_NOTIF_MAP.get(status)
    if not notif_info:
        return

    notif_key = f"warehouse_flow:{store_binding.id}:{draft.shipment_id}"
    store_alias = store_binding.store_alias or store_binding.store_name or f"Store #{store_binding.id}"
    body = f"[{store_alias}] Shipment #{draft.shipment_id} — {status}"

    # Upsert: check existing
    result = await db.execute(
        select(SiteNotification).where(SiteNotification.notif_key == notif_key)
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.level = notif_info["level"]
        existing.title = notif_info["title"]
        existing.body = body
        existing.is_read = 0
    else:
        notif = SiteNotification(
            user_id=draft.user_id,
            store_binding_id=store_binding.id,
            notif_key=notif_key,
            module="warehouse",
            level=notif_info["level"],
            title=notif_info["title"],
            body=body,
            entity_type="fulfillment_draft",
            entity_id=str(draft.shipment_id),
            link_url=f"/warehouse/jobs/{store_binding.id}/{draft.shipment_id}",
            is_read=0,
        )
        db.add(notif)

    await db.flush()


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

async def write_audit_log(
    db: AsyncSession,
    draft: FulfillmentDraft,
    user,
    action: str,
    old_status: str,
    new_status: str,
    changes_json: str = "",
) -> None:
    """Write an audit log entry for a draft change."""
    log = FulfillmentAuditLog(
        draft_id=draft.id,
        user_id=user.id if user else None,
        username=user.username if user else "system",
        role=user.role if user else "system",
        action=action,
        old_status=old_status,
        new_status=new_status,
        changes_json=changes_json,
    )
    db.add(log)
    await db.flush()


# ---------------------------------------------------------------------------
# Stale draft detection
# ---------------------------------------------------------------------------

# Thresholds in hours per status
_STALE_THRESHOLDS: dict[str, int] = {
    "待到仓": 168,           # 7 days
    "待贴三标": 72,          # 3 days
    "待送嘉鸿": 48,          # 2 days
    "待用户预报嘉鸿": 72,    # 3 days
}


async def check_stale_drafts(db: AsyncSession) -> list[dict]:
    """Return drafts that have exceeded their status timeout threshold."""
    now = datetime.now(timezone.utc)
    stale: list[dict] = []

    for status, hours in _STALE_THRESHOLDS.items():
        result = await db.execute(
            select(FulfillmentDraft)
            .where(
                FulfillmentDraft.workflow_status == status,
            )
            .options(selectinload(FulfillmentDraft.items))
        )
        drafts = result.scalars().all()

        for draft in drafts:
            updated = draft.updated_at
            if updated and updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            if updated and (now - updated).total_seconds() > hours * 3600:
                stale.append({
                    "draft_id": draft.id,
                    "store_binding_id": draft.store_binding_id,
                    "shipment_id": draft.shipment_id,
                    "workflow_status": status,
                    "hours_stale": round((now - updated).total_seconds() / 3600, 1),
                    "threshold_hours": hours,
                })

    return stale
