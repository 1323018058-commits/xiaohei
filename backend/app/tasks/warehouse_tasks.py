"""Warehouse Celery tasks — stale draft detection, CNX forecast submission.

Follows the same async-in-sync pattern as scrape_tasks.py.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


def _run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Periodic: stale draft check (every hour)
# ---------------------------------------------------------------------------

@celery_app.task(name="app.tasks.warehouse_tasks.check_stale_fulfillment_drafts")
def check_stale_fulfillment_drafts():
    """Check for fulfillment drafts that have exceeded their status timeout.

    Generates SiteNotifications for stale drafts so staff can take action.
    """
    async def _check():
        from app.database import task_db_session
        from app.models.notification import SiteNotification
        from app.services import warehouse_service
        from sqlalchemy import select

        async with task_db_session() as db:
            stale_list = await warehouse_service.check_stale_drafts(db)

            if not stale_list:
                logger.info("No stale fulfillment drafts found")
                return {"ok": True, "stale_count": 0}

            logger.warning("Found %d stale fulfillment drafts", len(stale_list))

            for item in stale_list:
                # Create or update a stale notification
                notif_key = f"warehouse_stale:{item['store_binding_id']}:{item['shipment_id']}"
                result = await db.execute(
                    select(SiteNotification).where(SiteNotification.notif_key == notif_key)
                )
                existing = result.scalar_one_or_none()

                title = f"履约单超时提醒 — {item['workflow_status']}"
                body = (
                    f"Shipment #{item['shipment_id']} 在 [{item['workflow_status']}] "
                    f"状态已停留 {item['hours_stale']}h（阈值 {item['threshold_hours']}h）"
                )

                if existing:
                    existing.title = title
                    existing.body = body
                    existing.level = "warning"
                    existing.is_read = 0
                else:
                    # Get the draft owner user_id
                    draft = await warehouse_service.get_draft(
                        db, item["store_binding_id"], item["shipment_id"]
                    )
                    user_id = draft.user_id if draft else 1  # fallback to admin

                    notif = SiteNotification(
                        user_id=user_id,
                        store_binding_id=item["store_binding_id"],
                        notif_key=notif_key,
                        module="warehouse",
                        level="warning",
                        title=title,
                        body=body,
                        entity_type="fulfillment_draft",
                        entity_id=str(item["shipment_id"]),
                        link_url=f"/warehouse/jobs/{item['store_binding_id']}/{item['shipment_id']}",
                        is_read=0,
                    )
                    db.add(notif)

            await db.commit()
            return {"ok": True, "stale_count": len(stale_list)}

    return _run_async(_check())


# ---------------------------------------------------------------------------
# On-demand: submit CNX forecast
# ---------------------------------------------------------------------------

@celery_app.task(bind=True, max_retries=2, default_retry_delay=30, name="app.tasks.warehouse_tasks.submit_cnx_forecast")
def submit_cnx_forecast(self, draft_id: int, user_id: int):
    """Submit a CNX (嘉鸿) forecast for a fulfillment draft.

    This task is dispatched from the API when a user clicks 'submit CNX'.
    On success it updates the draft with cnx_order_no and workflow status.
    """
    async def _submit():
        from app.database import task_db_session
        from app.models.warehouse import FulfillmentDraft
        from app.models.store import StoreBinding
        from app.models.user import User
        from app.services import warehouse_service, store_service
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        async with task_db_session() as db:
            # Load draft
            result = await db.execute(
                select(FulfillmentDraft)
                .where(FulfillmentDraft.id == draft_id)
                .options(selectinload(FulfillmentDraft.items))
            )
            draft = result.scalar_one_or_none()
            if not draft:
                logger.error("CNX submit: draft %d not found", draft_id)
                return {"ok": False, "error": "Draft not found"}

            if draft.cnx_order_no:
                logger.info("CNX submit: draft %d already has cnx_order_no", draft_id)
                return {"ok": True, "already_submitted": True}

            # Load store
            result = await db.execute(
                select(StoreBinding).where(StoreBinding.id == draft.store_binding_id)
            )
            store = result.scalar_one_or_none()
            if not store:
                logger.error("CNX submit: store %d not found", draft.store_binding_id)
                return {"ok": False, "error": "Store not found"}

            # Load user for audit
            result = await db.execute(
                select(User).where(User.id == user_id)
            )
            user = result.scalar_one_or_none()

            # TODO: Call actual CNX API here when integrated
            # For now, record the submission attempt
            old_status = draft.workflow_status

            # Mark as forecasted
            cnx_order_no = f"CNX-{draft.shipment_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
            draft.cnx_order_no = cnx_order_no
            draft.cnx_forecasted_at = datetime.now(timezone.utc)
            draft.workflow_status = warehouse_service.compute_workflow_status(draft)
            new_status = draft.workflow_status

            # Audit log
            await warehouse_service.write_audit_log(
                db, draft, user, "cnx_submit",
                old_status, new_status,
                changes_json=json.dumps({
                    "cnx_order_no": cnx_order_no,
                    "selected_cnx_warehouse_id": draft.selected_cnx_warehouse_id,
                    "selected_cnx_line_id": draft.selected_cnx_line_id,
                }, ensure_ascii=False),
            )

            # Sync notification
            await warehouse_service.sync_workflow_notification(db, draft, store)

            await db.commit()

            logger.info(
                "CNX submit success: draft=%d shipment=%d cnx_order_no=%s",
                draft_id, draft.shipment_id, cnx_order_no,
            )
            return {"ok": True, "cnx_order_no": cnx_order_no}

    try:
        return _run_async(_submit())
    except Exception as exc:
        logger.error("CNX submit task failed for draft %d: %s", draft_id, exc, exc_info=True)
        raise self.retry(exc=exc)
