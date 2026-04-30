from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, status

from src.modules.admin.service import get_request_id
from src.modules.common.dev_state import app_state
from src.modules.common.tenant_scope import require_tenant_access
from src.modules.store.adapters import (
    AdapterAuthError,
    AdapterCredentials,
    AdapterError,
    AdapterTemporaryError,
    BaseAdapter,
    OrderSnapshot,
    TakealotAdapter,
)
from src.modules.store.schemas import TaskCreatedResponse
from src.modules.subscription.service import subscription_service
from src.platform.settings.base import settings

from .schemas import (
    OrderDetail,
    OrderEventResponse,
    OrderItemResponse,
    OrderListResponse,
    OrderSummary,
)
from .status import normalize_takealot_order_status


SYNC_TAKEALOT_ORDERS_TASK_TYPE = "SYNC_TAKEALOT_ORDERS"
ORDER_TASK_TYPES = {SYNC_TAKEALOT_ORDERS_TASK_TYPE}
ORDER_WORKER_SOURCE_ID = "order-worker"
ORDER_AUTO_SYNC_ACTOR_ID: str | None = None

OrderAdapterFactory = Callable[[dict[str, Any], AdapterCredentials], BaseAdapter]


class OrderService:
    def list_orders(
        self,
        actor: dict[str, Any],
        *,
        store_id: str | None = None,
        status_filter: str | None = None,
        query: str | None = None,
    ) -> OrderListResponse:
        if store_id is not None:
            self._require_store(store_id, actor)
        tenant_id = None if actor["role"] == "super_admin" else actor["tenant_id"]
        return OrderListResponse(
            orders=[
                self._to_order_summary(order)
                for order in app_state.list_orders(
                    tenant_id=tenant_id,
                    store_id=store_id,
                    status_filter=status_filter,
                    query=query,
                )
            ]
        )

    def get_order(self, order_id: str, actor: dict[str, Any]) -> OrderDetail:
        order = self._require_order(order_id, actor)
        return self._to_order_detail(order)

    def sync_store_orders(
        self,
        store_id: str,
        actor: dict[str, Any],
        request_headers: dict[str, str],
        *,
        reason: str | None = None,
        force: bool = False,
    ) -> TaskCreatedResponse:
        if not app_state.is_setting_enabled("store_sync_enabled", True):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Store sync is disabled by release switch",
            )
        store = self._require_store(store_id, actor)
        if store["platform"] != "takealot":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only Takealot order sync is supported",
            )
        if not store["feature_policies"].get("sync_enabled", False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Store sync policy is disabled for this store",
            )
        subscription_service.ensure_can_enqueue_sync(actor)

        if not force:
            for task in app_state.list_tasks():
                if (
                    task["store_id"] == store_id
                    and task["task_type"] == SYNC_TAKEALOT_ORDERS_TASK_TYPE
                    and task["status"] in {"queued", "leased", "running", "waiting_retry"}
                ):
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="This store already has an active order sync task",
                    )

        task = app_state.create_task(
            task_type=SYNC_TAKEALOT_ORDERS_TASK_TYPE,
            domain="orders",
            queue_name="order-sync",
            actor_user_id=actor["id"],
            actor_role=actor["role"],
            tenant_id=store["tenant_id"],
            store_id=store["id"],
            target_type="store",
            target_id=store["id"],
            request_id=get_request_id(request_headers),
            label=f"{store['name']} orders sync",
            next_action="Worker will sync Takealot /sales into orders",
        )
        app_state.append_audit(
            request_id=task["request_id"],
            tenant_id=store["tenant_id"],
            store_id=store["id"],
            actor_user_id=actor["id"],
            actor_role=actor["role"],
            action="orders.sync.force" if force else "orders.sync.start",
            action_label="Force Takealot order sync" if force else "Start Takealot order sync",
            risk_level="high" if force else "medium",
            target_type="store",
            target_id=store["id"],
            target_label=store["name"],
            before=None,
            after={"task_id": task["id"], "status": task["status"], "task_type": task["task_type"]},
            reason=reason or ("Force Takealot order sync" if force else "Start Takealot order sync"),
            result="success",
            task_id=task["id"],
        )
        return self._to_task_created(task)

    def process_queued_order_tasks(
        self,
        *,
        adapter_factory: OrderAdapterFactory | None = None,
    ) -> list[dict[str, Any]]:
        claimed_tasks = app_state.claim_queued_tasks(
            ORDER_TASK_TYPES,
            worker_id=ORDER_WORKER_SOURCE_ID,
        )
        return [
            self.process_order_sync_task(task["id"], adapter_factory=adapter_factory)
            for task in claimed_tasks
        ]

    def enqueue_due_order_sync_tasks(self) -> list[dict[str, Any]]:
        if not app_state.is_setting_enabled("store_sync_enabled", True):
            return []

        now = self._now()
        interval = timedelta(
            minutes=max(1, int(settings.takealot_order_auto_sync_interval_minutes)),
        )
        batch_size = max(1, int(settings.takealot_order_auto_sync_batch_size))
        active_statuses = {"queued", "leased", "running", "waiting_retry"}
        order_tasks = [
            task
            for task in app_state.list_tasks()
            if task["task_type"] == SYNC_TAKEALOT_ORDERS_TASK_TYPE
        ]
        active_store_ids = {
            task["store_id"]
            for task in order_tasks
            if task.get("store_id") and task["status"] in active_statuses
        }
        latest_task_by_store: dict[str, dict[str, Any]] = {}
        for task in order_tasks:
            store_id = task.get("store_id")
            if not store_id:
                continue
            current = latest_task_by_store.get(store_id)
            if current is None or _task_reference_time(task) > _task_reference_time(current):
                latest_task_by_store[store_id] = task

        created: list[dict[str, Any]] = []
        for store in app_state.list_stores():
            if len(created) >= batch_size:
                break
            if not self._store_can_auto_sync_orders(store):
                continue
            if store["id"] in active_store_ids:
                continue
            last_attempt_at = (
                _task_reference_time(latest_task_by_store[store["id"]])
                if store["id"] in latest_task_by_store
                else None
            )
            last_success_or_attempt = max(
                (
                    value
                    for value in [store.get("last_synced_at"), last_attempt_at]
                    if value is not None
                ),
                default=None,
            )
            if (
                last_success_or_attempt is not None
                and now - _as_utc(last_success_or_attempt) < interval
            ):
                continue

            task = app_state.create_task(
                task_type=SYNC_TAKEALOT_ORDERS_TASK_TYPE,
                domain="orders",
                queue_name="order-sync",
                actor_user_id=ORDER_AUTO_SYNC_ACTOR_ID,
                actor_role="system",
                tenant_id=store["tenant_id"],
                store_id=store["id"],
                target_type="store",
                target_id=store["id"],
                request_id=f"auto-order-sync-{store['id']}-{int(now.timestamp())}",
                label=f"{store['name']} orders auto sync",
                next_action="Worker will sync Takealot sales in the background",
            )
            created.append(task)
        return created

    def process_order_sync_task(
        self,
        task_id: str,
        *,
        adapter_factory: OrderAdapterFactory | None = None,
    ) -> dict[str, Any]:
        task = self._require_order_task(task_id)
        if self._task_cancel_requested(task_id):
            return self._mark_task_cancelled(task_id)
        store = self._require_store(task["store_id"])
        started_at = self._now()
        self._update_task_progress(
            task_id,
            status="running",
            stage="syncing_orders",
            progress_current=0,
            progress_total=1,
            progress_percent=0,
            started_at=started_at,
            last_heartbeat_at=started_at,
            error_code=None,
            error_msg=None,
            error_details=None,
        )
        app_state.add_task_event(
            task_id=task_id,
            event_type="task.started",
            from_status=task["status"],
            to_status="running",
            stage="syncing_orders",
            message="Worker started syncing Takealot orders",
            details={"store_id": store["id"], "platform": store["platform"]},
            source="worker",
            source_id=ORDER_WORKER_SOURCE_ID,
        )

        try:
            credentials_payload = app_state.get_store_credentials(store["id"])
            if not credentials_payload:
                raise AdapterAuthError("Store credentials unavailable")
            credentials = AdapterCredentials(
                platform=store["platform"],
                api_key=credentials_payload.get("api_key", ""),
                api_secret=credentials_payload.get("api_secret", ""),
            )
            if not credentials.api_key:
                raise AdapterAuthError("Store credentials unavailable")
            adapter = self._build_adapter(
                store=store,
                credentials=credentials,
                adapter_factory=adapter_factory,
            )
            sync_start_date, sync_end_date = self._order_sync_window()
            snapshots = self._fetch_order_snapshots(
                adapter=adapter,
                task_id=task_id,
                start_date=sync_start_date,
                end_date=sync_end_date,
            )
            order_count = 0
            item_count = 0
            for snapshot in snapshots:
                if self._task_cancel_requested(task_id):
                    return self._mark_task_cancelled(task_id)
                if not snapshot.external_order_id:
                    continue
                self._upsert_order(store, snapshot)
                order_count += 1
                item_count += len(snapshot.items)
                if order_count % 25 == 0:
                    self._update_task_progress(task_id, last_heartbeat_at=self._now())

            completed_at = self._now()
            updated_store = app_state.update_store(
                store["id"],
                last_synced_at=completed_at,
                api_key_status="valid",
                credential_status="valid",
            )
            updated_task = self._update_task_progress(
                task_id,
                status="succeeded",
                stage="completed",
                progress_current=1,
                progress_total=1,
                progress_percent=100,
                finished_at=completed_at,
                last_heartbeat_at=completed_at,
                next_retry_at=None,
                lease_owner=None,
                lease_token=None,
                lease_expires_at=None,
                error_code=None,
                error_msg=None,
                error_details=None,
            )
            app_state.add_task_event(
                task_id=task_id,
                event_type="task.succeeded",
                from_status="running",
                to_status="succeeded",
                stage="completed",
                message=f"Synced {order_count} Takealot orders for {store['name']}",
                details={
                    "store_id": store["id"],
                    "order_count": order_count,
                    "item_count": item_count,
                    "sync_start_date": sync_start_date.isoformat(),
                    "sync_end_date": sync_end_date.isoformat(),
                    "last_synced_at": updated_store["last_synced_at"].isoformat()
                    if updated_store["last_synced_at"] is not None
                    else None,
                },
                source="worker",
                source_id=ORDER_WORKER_SOURCE_ID,
            )
            self._append_order_task_audit(
                task=task,
                store=store,
                result="success",
                reason=f"Synced {order_count} Takealot orders",
                metadata={
                    "order_count": order_count,
                    "item_count": item_count,
                    "sync_start_date": sync_start_date.isoformat(),
                    "sync_end_date": sync_end_date.isoformat(),
                },
            )
            return updated_task
        except Exception as exc:
            return self._handle_order_sync_failure(task=task, store=store, exc=exc)

    def _handle_order_sync_failure(
        self,
        *,
        task: dict[str, Any],
        store: dict[str, Any],
        exc: Exception,
    ) -> dict[str, Any]:
        current_task = app_state.get_task(task["id"])
        if current_task is not None and current_task.get("status") == "succeeded":
            return current_task

        retryable = False
        if isinstance(exc, AdapterAuthError):
            app_state.update_store(
                store["id"],
                api_key_status="stale",
                credential_status="expired",
            )
            error_code = "ORDER_SYNC_AUTH_FAILED"
        elif isinstance(exc, AdapterTemporaryError):
            retryable = True
            error_code = "ORDER_PLATFORM_UNAVAILABLE"
        elif isinstance(exc, AdapterError):
            error_code = "ORDER_ADAPTER_FAILED"
        else:
            error_code = "ORDER_SYNC_EXCEPTION"

        now = self._now()
        sync_start_date, sync_end_date = self._order_sync_window()
        can_retry = retryable and int(task.get("attempt_count", 0)) < int(task.get("max_retries", 0))
        if can_retry:
            retry_at = self._next_retry_at(task)
            updated = self._update_task_progress(
                task["id"],
                status="waiting_retry",
                stage="waiting_retry",
                progress_current=0,
                progress_total=1,
                progress_percent=0,
                finished_at=None,
                last_heartbeat_at=now,
                next_retry_at=retry_at,
                lease_owner=None,
                lease_token=None,
                lease_expires_at=None,
                error_code=error_code,
                error_msg=str(exc),
                error_details={
                    "store_id": store["id"],
                    "platform": store["platform"],
                    "retry_at": retry_at.isoformat(),
                    "retryable": True,
                    "sync_start_date": sync_start_date.isoformat(),
                    "sync_end_date": sync_end_date.isoformat(),
                },
            )
            app_state.add_task_event(
                task_id=task["id"],
                event_type="task.retry_scheduled",
                from_status="running",
                to_status="waiting_retry",
                stage="waiting_retry",
                message="Temporary Takealot order sync failure; retry scheduled",
                details={"error": str(exc), "error_code": error_code, "retry_at": retry_at.isoformat()},
                source="worker",
                source_id=ORDER_WORKER_SOURCE_ID,
            )
            audit_result = "partial"
        else:
            updated = self._update_task_progress(
                task["id"],
                status="failed",
                stage="failed",
                progress_current=0,
                progress_total=1,
                progress_percent=100,
                finished_at=now,
                last_heartbeat_at=now,
                next_retry_at=None,
                lease_owner=None,
                lease_token=None,
                lease_expires_at=None,
                error_code=error_code,
                error_msg=str(exc),
                error_details={
                    "store_id": store["id"],
                    "platform": store["platform"],
                    "retryable": retryable,
                    "sync_start_date": sync_start_date.isoformat(),
                    "sync_end_date": sync_end_date.isoformat(),
                },
            )
            app_state.add_task_event(
                task_id=task["id"],
                event_type="task.failed",
                from_status="running",
                to_status="failed",
                stage="failed",
                message="Takealot order sync failed",
                details={"error": str(exc), "error_code": error_code, "retryable": retryable},
                source="worker",
                source_id=ORDER_WORKER_SOURCE_ID,
            )
            audit_result = "failed"
        self._append_order_task_audit(
            task=task,
            store=store,
            result=audit_result,
            reason=str(exc),
            metadata={
                "error_code": error_code,
                "retryable": retryable,
                "sync_start_date": sync_start_date.isoformat(),
                "sync_end_date": sync_end_date.isoformat(),
            },
            error_code=error_code,
        )
        return updated

    def _upsert_order(self, store: dict[str, Any], snapshot: OrderSnapshot) -> dict[str, Any]:
        raw_order_status = snapshot.fulfillment_status or snapshot.status
        return app_state.upsert_order(
            tenant_id=store["tenant_id"],
            store_id=store["id"],
            external_order_id=snapshot.external_order_id,
            order_number=snapshot.order_number,
            status=normalize_takealot_order_status(snapshot.status),
            fulfillment_status=raw_order_status,
            total_amount=snapshot.total_amount,
            currency=snapshot.currency,
            placed_at=snapshot.placed_at,
            raw_payload=snapshot.raw_payload,
            items=[
                {
                    "external_order_item_id": item.external_order_item_id,
                    "sku": item.sku,
                    "title": item.title,
                    "quantity": item.quantity,
                    "unit_price": item.unit_price,
                    "status": normalize_takealot_order_status(item.status),
                    "raw_payload": item.raw_payload,
                }
                for item in snapshot.items
            ],
        )

    def _append_order_task_audit(
        self,
        *,
        task: dict[str, Any],
        store: dict[str, Any],
        result: str,
        reason: str,
        metadata: dict[str, Any],
        error_code: str | None = None,
    ) -> None:
        app_state.append_audit(
            request_id=task["request_id"],
            tenant_id=store["tenant_id"],
            store_id=store["id"],
            actor_user_id=task["actor_user_id"],
            actor_role=task["actor_role"],
            action="orders.sync.worker",
            action_label="Sync Takealot orders",
            risk_level="medium" if result == "success" else "high",
            target_type="store",
            target_id=store["id"],
            target_label=store["name"],
            before=None,
            after={"task_id": task["id"], "result": result},
            reason=reason,
            result=result,
            task_id=task["id"],
            error_code=error_code,
            metadata=metadata,
        )

    def _build_adapter(
        self,
        *,
        store: dict[str, Any],
        credentials: AdapterCredentials,
        adapter_factory: OrderAdapterFactory | None,
    ) -> BaseAdapter:
        if adapter_factory is not None:
            return adapter_factory(store, credentials)
        if store["platform"] == "takealot":
            return TakealotAdapter(
                credentials,
                page_limit=settings.takealot_order_page_limit,
                max_pages=settings.takealot_order_max_pages,
            )
        raise AdapterError(f"Unsupported store platform: {store['platform']}")

    def _fetch_order_snapshots(
        self,
        *,
        adapter: BaseAdapter,
        task_id: str,
        start_date: date,
        end_date: date,
    ) -> list[OrderSnapshot]:
        heartbeat = lambda _: self._update_task_progress(
            task_id,
            last_heartbeat_at=self._now(),
        )
        try:
            return adapter.fetch_orders(
                start_date=start_date,
                end_date=end_date,
                heartbeat=heartbeat,
            )
        except AdapterTemporaryError:
            fallback_chunk_days = max(0, int(settings.takealot_order_sync_fallback_chunk_days))
            if fallback_chunk_days <= 0 or (end_date - start_date).days + 1 <= fallback_chunk_days:
                raise

        self._update_task_progress(
            task_id,
            stage="syncing_orders_chunked",
            last_heartbeat_at=self._now(),
        )
        app_state.add_task_event(
            task_id=task_id,
            event_type="task.fallback",
            from_status="running",
            to_status="running",
            stage="syncing_orders_chunked",
            message="Takealot order sync switched to smaller date windows",
            details={
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "chunk_days": fallback_chunk_days,
            },
            source="worker",
            source_id=ORDER_WORKER_SOURCE_ID,
        )

        snapshots: list[OrderSnapshot] = []
        seen_external_order_ids: set[str] = set()
        for chunk_start, chunk_end in _date_chunks(start_date, end_date, fallback_chunk_days):
            chunk_snapshots = adapter.fetch_orders(
                start_date=chunk_start,
                end_date=chunk_end,
                heartbeat=heartbeat,
            )
            for snapshot in chunk_snapshots:
                if snapshot.external_order_id in seen_external_order_ids:
                    continue
                seen_external_order_ids.add(snapshot.external_order_id)
                snapshots.append(snapshot)
        return snapshots

    @staticmethod
    def _store_can_auto_sync_orders(store: dict[str, Any]) -> bool:
        if store.get("platform") != "takealot":
            return False
        if store.get("status") not in {"active", "connected", "healthy"}:
            return False
        if not store.get("feature_policies", {}).get("sync_enabled", False):
            return False
        if store.get("credential_status") in {"expired", "invalid", "revoked"}:
            return False
        return True

    def _require_order(self, order_id: str, actor: dict[str, Any]) -> dict[str, Any]:
        order = app_state.get_order(order_id)
        if order is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found",
            )
        require_tenant_access(actor, order["tenant_id"], detail="Order not found")
        return order

    @staticmethod
    def _require_store(
        store_id: str,
        actor: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        store = app_state.get_store(store_id)
        if store is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Store not found",
            )
        if actor is not None:
            require_tenant_access(actor, store["tenant_id"], detail="Store not found")
        return store

    @staticmethod
    def _require_order_task(task_id: str) -> dict[str, Any]:
        task = app_state.get_task(task_id)
        if task is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Task not found",
            )
        if task["task_type"] not in ORDER_TASK_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Task is not an order sync task",
            )
        return task

    def _to_order_detail(self, order: dict[str, Any]) -> OrderDetail:
        return OrderDetail(
            **self._to_order_summary(order).model_dump(),
            raw_payload=order["raw_payload"],
            items=[
                self._to_order_item(item)
                for item in app_state.list_order_items(order["id"])
            ],
            events=[
                self._to_order_event(event)
                for event in app_state.list_order_events(order["id"])
            ],
        )

    @staticmethod
    def _to_order_summary(order: dict[str, Any]) -> OrderSummary:
        return OrderSummary(
            order_id=order["id"],
            tenant_id=order["tenant_id"],
            store_id=order["store_id"],
            external_order_id=order["external_order_id"],
            order_number=order["order_number"],
            status=order["status"],
            fulfillment_status=order["fulfillment_status"],
            total_amount=order["total_amount"],
            currency=order["currency"],
            item_count=order.get("item_count", 0),
            placed_at=order["placed_at"],
            last_synced_at=order["last_synced_at"],
            created_at=order["created_at"],
            updated_at=order["updated_at"],
        )

    @staticmethod
    def _to_order_item(item: dict[str, Any]) -> OrderItemResponse:
        return OrderItemResponse(
            item_id=item["id"],
            order_id=item["order_id"],
            external_order_item_id=item["external_order_item_id"],
            sku=item["sku"],
            title=item["title"],
            quantity=item["quantity"],
            unit_price=item["unit_price"],
            status=item["status"],
            raw_payload=item["raw_payload"],
            created_at=item["created_at"],
            updated_at=item["updated_at"],
        )

    @staticmethod
    def _to_order_event(event: dict[str, Any]) -> OrderEventResponse:
        return OrderEventResponse(
            event_id=event["id"],
            order_id=event["order_id"],
            event_type=event["event_type"],
            status=event["status"],
            message=event["message"],
            payload=event["payload"],
            occurred_at=event["occurred_at"],
            created_at=event["created_at"],
        )

    @staticmethod
    def _to_task_created(task: dict[str, Any]) -> TaskCreatedResponse:
        return TaskCreatedResponse(
            task_id=task["id"],
            status=task["status"],
            stage=task["stage"],
        )

    @staticmethod
    def _update_task_progress(task_id: str, **changes: Any) -> dict[str, Any]:
        return app_state.update_task(task_id, **changes)

    def _next_retry_at(self, task: dict[str, Any]) -> datetime:
        attempt_count = max(0, int(task.get("attempt_count", 0)))
        delay_seconds = min(300, 30 * (2 ** attempt_count))
        return self._now() + timedelta(seconds=delay_seconds)

    @staticmethod
    def _order_sync_window() -> tuple[date, date]:
        try:
            business_zone = ZoneInfo(settings.dashboard_business_timezone)
        except ZoneInfoNotFoundError:
            business_zone = ZoneInfo("Africa/Johannesburg")
        today = datetime.now(UTC).astimezone(business_zone).date()
        # Takealot /sales can return 500 for the in-progress business day.
        # Sync completed SAST days here; current-day updates should come from webhooks.
        end_date = today - timedelta(days=1)
        lookback_days = max(1, int(settings.takealot_order_sync_lookback_days))
        return end_date - timedelta(days=lookback_days - 1), end_date

    @staticmethod
    def _task_cancel_requested(task_id: str) -> bool:
        task = app_state.get_task(task_id)
        return bool(task and (task["status"] == "cancelled" or task["cancel_requested_at"]))

    @staticmethod
    def _mark_task_cancelled(task_id: str) -> dict[str, Any]:
        task = app_state.get_task(task_id)
        if task is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Task not found",
            )
        if task["status"] == "cancelled":
            return task
        cancelled_at = datetime.now(UTC)
        return app_state.update_task(
            task_id,
            status="cancelled",
            stage="cancelled",
            finished_at=cancelled_at,
            last_heartbeat_at=cancelled_at,
            next_retry_at=None,
            lease_owner=None,
            lease_token=None,
            lease_expires_at=None,
            error_code="TASK_CANCELLED",
            error_msg=task["cancel_reason"] or "Task cancelled",
        )

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)


def _date_chunks(start_date: date, end_date: date, chunk_days: int) -> list[tuple[date, date]]:
    chunks: list[tuple[date, date]] = []
    current = start_date
    step = timedelta(days=max(1, chunk_days) - 1)
    while current <= end_date:
        chunk_end = min(end_date, current + step)
        chunks.append((current, chunk_end))
        current = chunk_end + timedelta(days=1)
    return chunks


def _task_reference_time(task: dict[str, Any]) -> datetime:
    value = task.get("finished_at") or task.get("updated_at") or task.get("created_at")
    if isinstance(value, datetime):
        return _as_utc(value)
    return datetime.min.replace(tzinfo=UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
