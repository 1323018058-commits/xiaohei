from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status

from src.modules.admin.service import get_request_id
from src.modules.common.dev_state import app_state
from src.modules.common.tenant_scope import require_tenant_access

from .schemas import (
    TaskEventListResponse,
    TaskEventResponse,
    TaskListResponse,
    TaskRunDetail,
    TaskRunSummary,
)


TAKEALOT_WEBHOOK_TASK_TYPE = "TAKEALOT_WEBHOOK_PROCESS"
TASK_RETRYABLE_STATUSES = {
    "waiting_retry",
    "failed",
    "failed_retryable",
    "failed_final",
    "partial",
    "dead_letter",
    "timed_out",
    "manual_intervention",
    "cancelled",
}
TASK_CANCELLABLE_STATUSES = {
    "created",
    "queued",
    "leased",
    "running",
    "waiting_dependency",
    "waiting_retry",
    "failed_retryable",
    "manual_intervention",
}


class TaskService:
    def list_tasks(
        self,
        actor: dict[str, Any],
        *,
        status_filter: str | None = None,
        store_id: str | None = None,
    ) -> TaskListResponse:
        tasks = app_state.list_tasks(
            None if actor["role"] == "super_admin" else actor["tenant_id"]
        )
        if status_filter:
            tasks = [task for task in tasks if task["status"] == status_filter]
        if store_id:
            tasks = [task for task in tasks if task["store_id"] == store_id]
        webhook_task_ids = [
            task["id"]
            for task in tasks
            if task["task_type"] == TAKEALOT_WEBHOOK_TASK_TYPE
        ]
        events_by_task = self._task_events_map(webhook_task_ids)
        return TaskListResponse(
            tasks=[
                self._to_task_summary(
                    task,
                    events=events_by_task.get(task["id"]),
                )
                for task in tasks
            ]
        )

    def get_task(self, task_id: str, actor: dict[str, Any]) -> TaskRunDetail:
        task = self._require_task(task_id, actor)
        recent_events = [
            self._to_task_event(event)
            for event in app_state.list_task_events(task_id)[:5]
        ]
        return self._to_task_detail(task, recent_events)

    def list_events(self, task_id: str, actor: dict[str, Any]) -> TaskEventListResponse:
        self._require_task(task_id, actor)
        return TaskEventListResponse(
            events=[
                self._to_task_event(event)
                for event in app_state.list_task_events(task_id)
            ]
        )

    def retry_now(
        self,
        task_id: str,
        actor: dict[str, Any],
        request_headers: dict[str, str],
        *,
        reason: str | None = None,
    ) -> TaskRunDetail:
        task = self._require_task(task_id, actor)
        if task["status"] not in TASK_RETRYABLE_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Task cannot be retried from status {task['status']}",
            )

        now = self._now()
        next_max_retries = max(
            int(task.get("max_retries") or 0),
            int(task.get("attempt_count") or 0) + 1,
        )
        updated = app_state.update_task(
            task_id,
            status="queued",
            stage="queued",
            progress_percent=0,
            progress_current=0,
            next_retry_at=None,
            lease_owner=None,
            lease_token=None,
            lease_expires_at=None,
            started_at=None,
            finished_at=None,
            last_heartbeat_at=None,
            cancel_requested_at=None,
            cancel_reason=None,
            max_retries=next_max_retries,
            retryable=True,
            error_code=None,
            error_msg=None,
            error_details=None,
        )
        app_state.add_task_event(
            task_id=task_id,
            event_type="task.retry_requested",
            from_status=task["status"],
            to_status="queued",
            stage="queued",
            message="Task retry requested by operator",
            details={
                "operator_id": actor["id"],
                "operator_role": actor["role"],
                "reason": reason or "Manual retry now",
                "requested_at": now.isoformat(),
            },
            source="api",
            source_id=actor["id"],
        )
        self._append_task_operation_audit(
            task=updated,
            actor=actor,
            request_headers=request_headers,
            action="task.retry_now",
            action_label="Retry task now",
            reason=reason or "Manual retry now",
            before={"status": task["status"], "stage": task["stage"]},
            after={"status": updated["status"], "stage": updated["stage"]},
        )
        return self.get_task(task_id, actor)

    def cancel_task(
        self,
        task_id: str,
        actor: dict[str, Any],
        request_headers: dict[str, str],
        *,
        reason: str | None = None,
    ) -> TaskRunDetail:
        task = self._require_task(task_id, actor)
        if task["status"] not in TASK_CANCELLABLE_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Task cannot be cancelled from status {task['status']}",
            )

        now = self._now()
        cancel_reason = reason or "Manual task cancellation"
        updated = app_state.update_task(
            task_id,
            status="cancelled",
            stage="cancelled",
            progress_percent=task["progress_percent"],
            next_retry_at=None,
            lease_owner=None,
            lease_token=None,
            lease_expires_at=None,
            finished_at=now,
            last_heartbeat_at=now,
            cancel_requested_at=now,
            cancel_reason=cancel_reason,
            error_code="TASK_CANCELLED",
            error_msg=cancel_reason,
            error_details={
                "operator_id": actor["id"],
                "operator_role": actor["role"],
                "cancelled_at": now.isoformat(),
            },
        )
        app_state.add_task_event(
            task_id=task_id,
            event_type="task.cancelled",
            from_status=task["status"],
            to_status="cancelled",
            stage="cancelled",
            message="Task cancelled by operator",
            details={
                "operator_id": actor["id"],
                "operator_role": actor["role"],
                "reason": cancel_reason,
                "cancelled_at": now.isoformat(),
            },
            source="api",
            source_id=actor["id"],
        )
        self._append_task_operation_audit(
            task=updated,
            actor=actor,
            request_headers=request_headers,
            action="task.cancel",
            action_label="Cancel task",
            reason=cancel_reason,
            before={"status": task["status"], "stage": task["stage"]},
            after={"status": updated["status"], "stage": updated["stage"]},
        )
        return self.get_task(task_id, actor)

    @staticmethod
    def _require_task(task_id: str, actor: dict[str, Any]) -> dict[str, Any]:
        task = app_state.get_task(task_id)
        if task is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Task not found",
            )
        require_tenant_access(actor, task["tenant_id"], detail="Task not found")
        return task

    @staticmethod
    def _to_task_summary(
        task: dict[str, Any],
        *,
        events: list[dict[str, Any]] | None = None,
    ) -> TaskRunSummary:
        return TaskRunSummary(
            task_id=task["id"],
            task_type=task["task_type"],
            domain=task["domain"],
            status=task["status"],
            stage=task["stage"],
            progress_percent=task["progress_percent"],
            tenant_id=task["tenant_id"],
            store_id=task["store_id"],
            target_type=task["target_type"],
            target_id=task["target_id"],
            request_id=task["request_id"],
            error_code=task["error_code"],
            error_msg=task["error_msg"],
            attempt_count=task["attempt_count"],
            max_retries=task["max_retries"],
            retryable=task["retryable"],
            next_retry_at=task["next_retry_at"],
            ui_meta=TaskService._task_ui_meta(task, events=events),
            created_at=task["created_at"],
            updated_at=task["updated_at"],
        )

    def _to_task_detail(
        self,
        task: dict[str, Any],
        recent_events: list[TaskEventResponse],
    ) -> TaskRunDetail:
        summary = self._to_task_summary(task)
        return TaskRunDetail(
            **summary.model_dump(),
            progress_current=task["progress_current"],
            progress_total=task["progress_total"],
            priority=task["priority"],
            queue_name=task["queue_name"],
            actor_user_id=task["actor_user_id"],
            actor_role=task["actor_role"],
            source_type=task["source_type"],
            lease_owner=task["lease_owner"],
            lease_expires_at=task["lease_expires_at"],
            started_at=task["started_at"],
            finished_at=task["finished_at"],
            last_heartbeat_at=task["last_heartbeat_at"],
            cancel_requested_at=task["cancel_requested_at"],
            cancel_reason=task["cancel_reason"],
            error_details=task["error_details"],
            recent_events=recent_events,
        )

    @staticmethod
    def _to_task_event(event: dict[str, Any]) -> TaskEventResponse:
        return TaskEventResponse(
            event_id=event["id"],
            task_id=event["task_id"],
            event_type=event["event_type"],
            from_status=event["from_status"],
            to_status=event["to_status"],
            stage=event["stage"],
            message=event["message"],
            details=event["details"],
            source=event["source"],
            source_id=event["source_id"],
            created_at=event["created_at"],
        )

    @staticmethod
    def _task_ui_meta(
        task: dict[str, Any],
        *,
        events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        ui_meta = dict(task["ui_meta"] or {})
        if task["task_type"] != TAKEALOT_WEBHOOK_TASK_TYPE:
            return ui_meta or None

        if events is None:
            events = app_state.list_task_events(task["id"])
        received_event = next(
            (event for event in events if event["event_type"] == "webhook.received"),
            None,
        )
        result_event = next(
            (event for event in events if event["event_type"] == "task.succeeded"),
            None,
        )
        received_details = received_event.get("details") if received_event else None
        result_details = result_event.get("details") if result_event else None
        if isinstance(received_details, dict):
            payload = received_details.get("payload")
            ui_meta.update(
                {
                    "webhook_delivery_id": received_details.get("delivery_id"),
                    "webhook_event_type": received_details.get("event_type"),
                    "webhook_payload_summary": TaskService._payload_summary(payload),
                }
            )
        if isinstance(result_details, dict):
            applied = result_details.get("applied")
            ui_meta.update(
                {
                    "webhook_apply_status": (
                        "applied"
                        if applied is True
                        else result_details.get("reason")
                        or result_details.get("stage")
                        or task["stage"]
                    ),
                    "webhook_store_id": result_details.get("store_id"),
                    "webhook_listing_sku": result_details.get("sku"),
                    "webhook_listing_id": result_details.get("listing_id"),
                }
            )
        else:
            ui_meta["webhook_apply_status"] = (
                task["stage"] if task["stage"] != "queued" else "pending"
            )
        return ui_meta or None

    @staticmethod
    def _payload_summary(payload: Any) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return None

        offer = payload.get("offer") if isinstance(payload.get("offer"), dict) else {}
        values_changed = (
            payload.get("values_changed")
            if isinstance(payload.get("values_changed"), dict)
            else {}
        )
        normalized_changes = {
            key: value.get("new", value.get("value", value.get("current")))
            if isinstance(value, dict)
            else value
            for key, value in values_changed.items()
        }
        merged = {**offer, **payload, **normalized_changes}
        summary = {
            "offer_id": TaskService._first_present(merged, "offer_id", "id"),
            "sku": TaskService._first_present(merged, "merchant_sku", "sku"),
            "title": TaskService._first_present(merged, "product_title", "title"),
            "price": TaskService._first_present(
                merged,
                "selling_price",
                "price",
                "total_selling_price",
            ),
            "stock": TaskService._stock_summary(
                TaskService._first_present(
                    merged,
                    "merchant_warehouse_stock",
                    "leadtime_stock",
                    "seller_warehouse_stock",
                )
            ),
            "changed_fields": sorted(values_changed.keys()) if values_changed else None,
        }
        compact = {
            key: value for key, value in summary.items() if value not in (None, "", [])
        }
        if compact:
            return compact
        return {"keys": list(payload.keys())[:8]}

    @staticmethod
    def _first_present(payload: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            if key in payload and payload[key] is not None:
                return payload[key]
        return None

    @staticmethod
    def _stock_summary(value: Any) -> int | None:
        if isinstance(value, list):
            total = 0
            found = False
            for item in value:
                if not isinstance(item, dict):
                    continue
                quantity = item.get("quantity_available")
                if quantity is None:
                    continue
                try:
                    total += max(0, int(float(quantity)))
                    found = True
                except (TypeError, ValueError):
                    continue
            return total if found else None
        if value in (None, ""):
            return None
        try:
            return max(0, int(float(value)))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _task_events_map(task_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        if not task_ids:
            return {}
        if hasattr(app_state, "list_task_events_map"):
            return app_state.list_task_events_map(task_ids)
        return {task_id: app_state.list_task_events(task_id) for task_id in task_ids}

    @staticmethod
    def _append_task_operation_audit(
        *,
        task: dict[str, Any],
        actor: dict[str, Any],
        request_headers: dict[str, str],
        action: str,
        action_label: str,
        reason: str,
        before: dict[str, Any],
        after: dict[str, Any],
    ) -> None:
        app_state.append_audit(
            request_id=get_request_id(request_headers),
            tenant_id=task["tenant_id"],
            store_id=task["store_id"],
            actor_user_id=actor["id"],
            actor_role=actor["role"],
            action=action,
            action_label=action_label,
            risk_level="medium",
            target_type="task",
            target_id=task["id"],
            target_label=task["task_type"],
            before=before,
            after=after,
            reason=reason,
            result="success",
            task_id=task["id"],
            metadata={
                "task_type": task["task_type"],
                "domain": task["domain"],
                "queue_name": task["queue_name"],
            },
        )

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)
