from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from threading import Lock
from time import monotonic
from typing import Any, Callable
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status

from src.modules.admin.service import get_request_id
from src.modules.common.dev_state import (
    BUYABLE_STATUS_RE,
    DISABLED_STATUS_RE,
    PLATFORM_DISABLED_TOKENS,
    SELLER_DISABLED_TOKENS,
    app_state,
)
from src.modules.extension.service import sync_guardrails_for_listing
from src.modules.common.tenant_scope import require_tenant_access
from src.modules.subscription.service import subscription_service
from src.modules.tasking.schemas import TaskRunSummary
from src.modules.tasking.service import TaskService

from .adapters import (
    AdapterAuthError,
    AdapterCredentials,
    AdapterError,
    AdapterTemporaryError,
    BaseAdapter,
    ListingSnapshot,
    TakealotAdapter,
)
from .schemas import (
    StoreCredentialValidationResponse,
    StoreDeleteResponse,
    StoreDetail,
    StoreFeaturePolicies,
    StoreListingListResponse,
    StoreListingMetricListResponse,
    StoreListingMetricResponse,
    StoreListingResponse,
    StoreListResponse,
    StorePlatformProfile,
    StoreSummary,
    StoreSyncTaskListResponse,
    TaskCreatedResponse,
)

LISTING_STATUS_GROUPS = {"buyable", "not_buyable", "platform_disabled", "seller_disabled"}
LISTING_SORT_FIELDS = {
    "createdAt",
    "stockOnHand",
    "availableStock",
    "buyBoxPrice",
    "sellingPrice",
    "sales30d",
    "cvr30d",
    "pageViews30d",
    "wishlist30d",
    "returns30d",
    "listingQuality",
}


SYNC_STORE_LISTINGS_TASK_TYPE = "SYNC_STORE_LISTINGS"
LEGACY_FULL_SYNC_TASK_TYPE = "store.sync.full"
CREDENTIAL_VALIDATION_TASK_TYPE = "store.credentials.validate"
STORE_TASK_TYPES = {
    SYNC_STORE_LISTINGS_TASK_TYPE,
    LEGACY_FULL_SYNC_TASK_TYPE,
    CREDENTIAL_VALIDATION_TASK_TYPE,
}
SYNC_TASK_TYPES = {
    SYNC_STORE_LISTINGS_TASK_TYPE,
    LEGACY_FULL_SYNC_TASK_TYPE,
}
WORKER_SOURCE_ID = "store-worker"
STATUS_COUNT_CACHE_TTL_SECONDS = 60.0
ACTIVE_SYNC_STATUSES = {"queued", "leased", "running"}
SYNC_TASK_FRESH_WINDOW_SECONDS = 15 * 60
QUEUED_SYNC_TASK_TIMEOUT_SECONDS = 2 * 60
SYNC_SCOPE_FULL = "full"
SYNC_SCOPE_BIDDING = "bidding"
STOCK_DETAIL_PAYLOAD_KEYS = {
    "leadtime_days",
    "leadtime_enabled",
    "leadtime_stock",
    "merchant_warehouse_stock",
    "seller_stock_quantity",
    "seller_warehouse_stock",
    "stock_at_takealot_total",
    "takealot_stock_quantity",
    "takealot_warehouse_stock",
    "total_merchant_stock",
    "total_takealot_stock",
}
DAILY_RECONCILE_TIMEZONE = ZoneInfo("Asia/Shanghai")
DAILY_RECONCILE_TARGET_ID = "active_takealot"

AdapterFactory = Callable[[dict[str, Any], AdapterCredentials], BaseAdapter]


class StoreService:
    def __init__(self) -> None:
        self._task_service = TaskService()
        self._listing_status_count_cache: dict[tuple[str, str, str], tuple[float, dict[str, int]]] = {}
        self._listing_status_count_cache_lock = Lock()

    def list_stores(self, actor: dict[str, Any]) -> StoreListResponse:
        return StoreListResponse(
            stores=[
                self._to_store_summary(store)
                for store in app_state.list_stores(
                    None if actor["role"] == "super_admin" else actor["tenant_id"]
                )
            ]
        )

    def get_store(self, store_id: str, actor: dict[str, Any]) -> StoreDetail:
        store = self._require_store(store_id, actor)
        return StoreDetail(
            **self._to_store_summary(store).model_dump(),
            masked_api_key=store["masked_api_key"],
            platform_profile=self._store_platform_profile(store),
            sync_tasks=self._store_tasks(store_id),
        )

    def list_store_listings(
        self,
        store_id: str,
        actor: dict[str, Any],
        sku_query: str | None = None,
        query: str | None = None,
        status_group: str | None = None,
        bidding_filter: str | None = None,
        sort_by: str | None = None,
        sort_dir: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> StoreListingListResponse:
        self._require_store(store_id, actor)
        normalized_limit = max(1, min(limit, 200))
        normalized_offset = max(0, offset)
        normalized_sku_query = (query or sku_query or "").strip() or None
        normalized_status_group = (
            status_group.strip()
            if status_group and status_group.strip() in LISTING_STATUS_GROUPS
            else None
        )
        normalized_bidding_filter = (bidding_filter or "").strip()
        bidding_sku_filter = self._bidding_sku_filter(store_id, normalized_bidding_filter)
        normalized_sort_by = sort_by.strip() if sort_by and sort_by.strip() in LISTING_SORT_FIELDS else "createdAt"
        normalized_sort_dir = "asc" if sort_dir == "asc" else "desc"
        if bidding_sku_filter is None:
            listings = app_state.list_store_listings(
                store_id=store_id,
                sku_query=normalized_sku_query,
                status_group=normalized_status_group,
                sort_by=normalized_sort_by,
                sort_dir=normalized_sort_dir,
                limit=normalized_limit,
                offset=normalized_offset,
            )
        else:
            filtered_listings = [
                listing
                for listing in app_state.list_store_listings(
                    store_id=store_id,
                    sku_query=normalized_sku_query,
                    status_group=normalized_status_group,
                    sort_by=normalized_sort_by,
                    sort_dir=normalized_sort_dir,
                    limit=None,
                    offset=0,
                )
                if listing["sku"] in bidding_sku_filter
            ]
            listings = filtered_listings[normalized_offset:normalized_offset + normalized_limit]
        status_counts = self._listing_status_counts(
            store_id,
            normalized_sku_query,
            sku_filter=bidding_sku_filter,
        )
        total = status_counts[normalized_status_group or "all"]
        return StoreListingListResponse(
            listings=[self._to_listing_response(listing) for listing in listings],
            total=total,
            limit=normalized_limit,
            offset=normalized_offset,
            status_counts=status_counts,
        )

    def list_store_listing_metrics(
        self,
        store_id: str,
        actor: dict[str, Any],
        sku_filter: list[str] | None = None,
    ) -> StoreListingMetricListResponse:
        self._require_store(store_id, actor)
        normalized_skus = {
            sku.strip()
            for sku in (sku_filter or [])
            if sku and sku.strip()
        }
        return StoreListingMetricListResponse(
            metrics=[
                StoreListingMetricResponse(**metric)
                for metric in app_state.list_store_listing_metrics(
                    store_id=store_id,
                    days=30,
                    sku_filter=normalized_skus or None,
                )
            ]
        )

    def update_store_listing(
        self,
        store_id: str,
        listing_id: str,
        payload: dict[str, Any],
        actor: dict[str, Any],
        request_headers: dict[str, str],
    ) -> StoreListingResponse:
        store = self._require_store(store_id, actor)
        listing = self._require_store_listing(store_id, listing_id)
        requested_price = payload.get("selling_price")
        requested_stock = payload.get("seller_stock")
        requested_stock_enabled = payload.get("seller_stock_enabled")
        if (
            requested_price is None
            and requested_stock is None
            and requested_stock_enabled is None
        ):
            return self._to_listing_response(listing)

        next_price = float(requested_price) if requested_price is not None else None
        next_stock = int(requested_stock) if requested_stock is not None else None
        if requested_stock_enabled is False:
            next_stock = 0
        current_stock = self._seller_stock_quantity(listing.get("raw_payload"))
        current_stock_enabled = self._seller_stock_enabled(listing.get("raw_payload"))
        price_changed = (
            next_price is not None
            and not self._same_money(listing.get("platform_price"), next_price)
        )
        stock_changed = next_stock is not None and next_stock != current_stock
        stock_enabled_changed = (
            requested_stock_enabled is not None
            and bool(requested_stock_enabled) != current_stock_enabled
        )
        if not price_changed and not stock_changed and not stock_enabled_changed:
            return self._to_listing_response(listing)

        credentials_payload = app_state.get_store_credentials(store_id)
        if not credentials_payload:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Store credentials unavailable",
            )
        credentials = AdapterCredentials(
            platform=store["platform"],
            api_key=credentials_payload.get("api_key", ""),
            api_secret=credentials_payload.get("api_secret", ""),
        )
        if not credentials.api_key or not credentials.api_secret:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Store credentials unavailable",
            )

        adapter = self._build_adapter(
            store=store,
            credentials=credentials,
            adapter_factory=None,
        )
        seller_warehouse_id = self._seller_warehouse_id(listing.get("raw_payload"))
        leadtime_merchant_warehouse_id = (
            self._leadtime_merchant_warehouse_id(listing.get("raw_payload"))
            or credentials_payload.get("leadtime_merchant_warehouse_id")
        )
        barcode = self._listing_barcode(listing)
        before = self._listing_audit_snapshot(listing)
        try:
            platform_payload = adapter.update_offer(
                offer_id=listing["external_listing_id"],
                sku=listing["sku"],
                barcode=barcode,
                selling_price=next_price if price_changed else None,
                seller_stock=next_stock if (stock_changed or requested_stock_enabled is not None) else None,
                seller_stock_enabled=bool(requested_stock_enabled)
                if requested_stock_enabled is not None
                else None,
                seller_warehouse_id=seller_warehouse_id,
                leadtime_merchant_warehouse_id=leadtime_merchant_warehouse_id,
            )
        except AdapterAuthError as exc:
            app_state.update_store(
                store_id,
                api_key_status="stale",
                credential_status="expired",
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(exc),
            ) from exc
        except AdapterTemporaryError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc
        except AdapterError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc),
            ) from exc

        next_raw_payload = self._listing_payload_with_updates(
            listing.get("raw_payload"),
            platform_payload=platform_payload,
            selling_price=next_price if price_changed else None,
            seller_stock=next_stock if (stock_changed or requested_stock_enabled is not None) else None,
            seller_stock_enabled=bool(requested_stock_enabled)
            if requested_stock_enabled is not None
            else None,
            seller_warehouse_id=seller_warehouse_id,
            leadtime_merchant_warehouse_id=leadtime_merchant_warehouse_id,
        )
        updated = app_state.update_store_listing(
            store_id=store_id,
            listing_id=listing_id,
            platform_price=next_price if price_changed else None,
            raw_payload=next_raw_payload,
        )
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Listing not found",
            )
        self._clear_listing_status_count_cache(store_id)
        sync_guardrails_for_listing(
            listing=updated,
            request_id=get_request_id(request_headers),
            actor=actor,
        )
        app_state.append_audit(
            request_id=get_request_id(request_headers),
            tenant_id=store["tenant_id"],
            store_id=store_id,
            actor_user_id=actor["id"],
            actor_role=actor["role"],
            action="store.listing.update",
            action_label="Update store listing",
            risk_level="high",
            target_type="listing",
            target_id=listing_id,
            target_label=listing["sku"],
            before=before,
            after=self._listing_audit_snapshot(updated),
            reason="Inline product management edit",
            result="success",
            task_id=None,
            metadata={
                "changed_fields": [
                    key
                    for key, changed in {
                        "selling_price": price_changed,
                        "seller_stock": stock_changed,
                        "seller_stock_enabled": stock_enabled_changed,
                    }.items()
                    if changed
                ],
                "platform_response": platform_payload,
            },
        )
        return self._to_listing_response(updated)

    def list_sync_tasks(
        self,
        store_id: str,
        actor: dict[str, Any],
    ) -> StoreSyncTaskListResponse:
        self._require_store(store_id, actor)
        self._release_orphaned_sync_tasks(store_id)
        return StoreSyncTaskListResponse(tasks=self._store_tasks(store_id))

    def create_store(
        self,
        payload: dict[str, Any],
        actor: dict[str, Any],
        request_headers: dict[str, str],
    ) -> StoreDetail:
        self._ensure_admin_enabled()
        subscription_service.ensure_can_create_store(actor)
        validated_at = self._now()
        platform_profile = self._validate_platform_credentials(
            store={"id": None, "platform": payload["platform"]},
            credentials=AdapterCredentials(
                platform=payload["platform"],
                api_key=payload["api_key"],
                api_secret=payload["api_secret"],
            ),
            validated_at=validated_at,
        )
        prepared_payload = {
            **payload,
            "tenant_id": actor["tenant_id"],
            "masked_api_key": self._mask_credential(payload["api_key"]),
            "api_key_status": "valid",
            "credential_status": "valid",
            "last_validated_at": validated_at,
            "platform_profile": platform_profile.model_dump(mode="json"),
            "feature_policies": {
                "bidding_enabled": False,
                "listing_enabled": False,
                "sync_enabled": True,
            },
        }
        store = app_state.create_store(prepared_payload)
        app_state.append_audit(
            request_id=get_request_id(request_headers),
            tenant_id=store["tenant_id"],
            store_id=store["id"],
            actor_user_id=actor["id"],
            actor_role=actor["role"],
            action="store.create",
            action_label="Create store",
            risk_level="medium",
            target_type="store",
            target_id=store["id"],
            target_label=store["name"],
            before=None,
            after=self._store_audit_snapshot(store),
            reason="Create store with encrypted credentials",
            result="success",
            task_id=None,
        )
        return self.get_store(store["id"], actor)

    def validate_credentials(
        self,
        store_id: str,
        actor: dict[str, Any],
        request_headers: dict[str, str],
    ) -> StoreCredentialValidationResponse:
        self._ensure_admin_enabled()
        store = self._require_store(store_id, actor)
        before = self._store_audit_snapshot(store)
        credentials = self._credentials_for_store(store)
        validated_at = self._now()
        platform_profile = self._validate_platform_credentials(
            store=store,
            credentials=credentials,
            validated_at=validated_at,
        )
        updated = app_state.update_store(
            store_id,
            api_key_status="valid",
            credential_status="valid",
            last_validated_at=validated_at,
            platform_profile=platform_profile.model_dump(mode="json"),
        )
        app_state.append_audit(
            request_id=get_request_id(request_headers),
            tenant_id=store["tenant_id"],
            store_id=store_id,
            actor_user_id=actor["id"],
            actor_role=actor["role"],
            action="store.credentials.validate",
            action_label="Validate store credentials",
            risk_level="critical",
            target_type="store",
            target_id=store_id,
            target_label=store["name"],
            before=before,
            after=self._store_audit_snapshot(updated),
            reason="Manual API Key validation from store detail",
            result="success",
            task_id=None,
            metadata={"platform_profile": platform_profile.model_dump(mode="json")},
        )
        return StoreCredentialValidationResponse(
            store_id=store_id,
            status="valid",
            message="Takealot 已返回店铺资料",
            platform_profile=platform_profile,
            store=self.get_store(store_id, actor),
        )

    def delete_store(
        self,
        store_id: str,
        actor: dict[str, Any],
        request_headers: dict[str, str],
    ) -> StoreDeleteResponse:
        self._ensure_admin_enabled()
        store = self._require_store(store_id, actor)
        deleted = app_state.delete_store(store_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Store not found",
            )
        app_state.append_audit(
            request_id=get_request_id(request_headers),
            tenant_id=store["tenant_id"],
            store_id=store_id,
            actor_user_id=actor["id"],
            actor_role=actor["role"],
            action="store.delete",
            action_label="Delete store",
            risk_level="critical",
            target_type="store",
            target_id=store_id,
            target_label=store["name"],
            before=self._store_audit_snapshot(store),
            after={"deleted": True},
            reason="Remove store from store detail",
            result="success",
            task_id=None,
        )
        return StoreDeleteResponse(store_id=store_id, deleted=True)

    def update_store(
        self,
        store_id: str,
        payload: dict[str, Any],
        actor: dict[str, Any],
        request_headers: dict[str, str],
    ) -> StoreDetail:
        self._ensure_admin_enabled()
        store = self._require_store(store_id, actor)
        before = self._store_audit_snapshot(store)
        feature_policies = dict(store["feature_policies"])
        for key in ("bidding_enabled", "listing_enabled", "sync_enabled"):
            if payload.get(key) is not None:
                feature_policies[key] = payload[key]

        changes: dict[str, Any] = {"feature_policies": feature_policies}
        if payload.get("name") is not None:
            changes["name"] = payload["name"]
        if payload.get("status") is not None:
            changes["status"] = payload["status"]

        updated = app_state.update_store(store_id, **changes)
        app_state.append_audit(
            request_id=get_request_id(request_headers),
            tenant_id=store["tenant_id"],
            store_id=store_id,
            actor_user_id=actor["id"],
            actor_role=actor["role"],
            action="store.update",
            action_label="Update store",
            risk_level="medium",
            target_type="store",
            target_id=store_id,
            target_label=updated["name"],
            before=before,
            after=self._store_audit_snapshot(updated),
            reason="Update store configuration",
            result="success",
            task_id=None,
        )
        return self.get_store(store_id, actor)

    def update_credentials(
        self,
        store_id: str,
        api_key: str,
        api_secret: str,
        reason: str,
        actor: dict[str, Any],
        request_headers: dict[str, str],
    ) -> TaskCreatedResponse:
        self._ensure_admin_enabled()
        store = self._require_store(store_id, actor)
        updated = app_state.update_store(
            store_id,
            api_key=api_key,
            api_secret=api_secret,
            credential_platform=store["platform"],
            api_key_status="validating",
            credential_status="validating",
            masked_api_key=self._mask_credential(api_key),
        )
        task = self._create_store_task(
            store=updated,
            actor=actor,
            request_headers=request_headers,
            task_type=CREDENTIAL_VALIDATION_TASK_TYPE,
            label=f"{store['name']} credential validation",
            next_action="Waiting for worker credential validation",
        )
        app_state.append_audit(
            request_id=task["request_id"],
            tenant_id=store["tenant_id"],
            store_id=store_id,
            actor_user_id=actor["id"],
            actor_role=actor["role"],
            action="store.credentials.update",
            action_label="Update store credentials",
            risk_level="critical",
            target_type="store",
            target_id=store_id,
            target_label=store["name"],
            before={"credential_status": store["credential_status"]},
            after={"credential_status": updated["credential_status"], "task_id": task["id"]},
            reason=reason,
            result="success",
            task_id=task["id"],
        )
        return self._to_task_created(task)

    def sync_store(
        self,
        store_id: str,
        actor: dict[str, Any],
        request_headers: dict[str, str],
        reason: str | None = None,
        sync_scope: str = SYNC_SCOPE_FULL,
        force: bool = False,
    ) -> TaskCreatedResponse:
        if not app_state.is_setting_enabled("store_sync_enabled", True):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Store sync is disabled by release switch",
            )

        store = self._require_store(store_id, actor)
        self._clear_listing_status_count_cache(store_id)
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
                    and self._is_fresh_active_sync_task(task)
                ):
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="This store already has an active sync task",
                    )

        normalized_scope = SYNC_SCOPE_BIDDING if sync_scope == SYNC_SCOPE_BIDDING else SYNC_SCOPE_FULL
        next_action = (
            "Fast sync for auto bidding listings"
            if normalized_scope == SYNC_SCOPE_BIDDING
            else "Waiting for worker to sync platform listings"
        )
        task = self._create_store_task(
            store=store,
            actor=actor,
            request_headers=request_headers,
            task_type=SYNC_STORE_LISTINGS_TASK_TYPE,
            label=f"{store['name']} listings sync",
            next_action=next_action,
        )
        task = app_state.update_task(
            task["id"],
            ui_meta={
                **(task.get("ui_meta") or {}),
                "sync_scope": normalized_scope,
            },
        )
        app_state.append_audit(
            request_id=task["request_id"],
            tenant_id=store["tenant_id"],
            store_id=store_id,
            actor_user_id=actor["id"],
            actor_role=actor["role"],
            action="store.sync.force" if force else "store.sync.start",
            action_label="Force store sync" if force else "Start store sync",
            risk_level="high" if force else "medium",
            target_type="store",
            target_id=store_id,
            target_label=store["name"],
            before=None,
            after={
                "task_id": task["id"],
                "status": task["status"],
                "task_type": task["task_type"],
                "sync_scope": normalized_scope,
            },
            reason=reason or ("Force listings sync" if force else "Start listings sync"),
            result="success",
            task_id=task["id"],
        )
        return self._to_task_created(task)

    def reconcile_active_stores(
        self,
        actor: dict[str, Any],
        request_headers: dict[str, str],
        reason: str | None = None,
    ) -> TaskCreatedResponse:
        if not app_state.is_setting_enabled("store_sync_enabled", True):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Store sync is disabled by release switch",
            )

        stores = [
            store
            for store in app_state.list_stores(
                None if actor["role"] == "super_admin" else actor["tenant_id"]
            )
            if store["status"] == "active"
            and store["platform"] == "takealot"
            and store["feature_policies"].get("sync_enabled", False)
        ]
        if not stores:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No active Takealot stores are eligible for reconciliation",
            )
        subscription_service.ensure_can_enqueue_sync(actor)

        for task in app_state.list_tasks():
            if (
                task["store_id"] is None
                and self._is_fresh_active_sync_task(task)
                and (
                    actor["role"] == "super_admin"
                    or task["tenant_id"] == actor["tenant_id"]
                )
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A global store reconciliation task is already active",
                )

        task = app_state.create_task(
            task_type=SYNC_STORE_LISTINGS_TASK_TYPE,
            domain="store",
            queue_name="store-sync",
            actor_user_id=actor["id"],
            actor_role=actor["role"],
            tenant_id=actor["tenant_id"],
            store_id=None,
            target_type="store_collection",
            target_id="active_takealot",
            request_id=get_request_id(request_headers),
            label="Takealot listings reconciliation",
            next_action="Worker will reconcile all active Takealot stores from /offers",
        )
        app_state.append_audit(
            request_id=task["request_id"],
            tenant_id=actor["tenant_id"],
            store_id=None,
            actor_user_id=actor["id"],
            actor_role=actor["role"],
            action="store.sync.reconcile",
            action_label="Reconcile all active Takealot stores",
            risk_level="medium",
            target_type="store_collection",
            target_id="active_takealot",
            target_label="Active Takealot stores",
            before=None,
            after={
                "task_id": task["id"],
                "status": task["status"],
                "task_type": task["task_type"],
                "store_count": len(stores),
            },
            reason=reason or "Scheduled source-of-truth listings reconciliation",
            result="success",
            task_id=task["id"],
            metadata={"store_ids": [store["id"] for store in stores]},
        )
        return self._to_task_created(task)

    def enqueue_due_daily_reconciliation(
        self,
        *,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        current = now or self._now()
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        local_now = current.astimezone(DAILY_RECONCILE_TIMEZONE)
        if local_now.hour != 0:
            return []
        if not app_state.is_setting_enabled("store_sync_enabled", True):
            return []

        actor = self._system_super_admin_actor()
        if actor is None:
            return []

        stores = [
            store
            for store in app_state.list_stores()
            if store["status"] == "active"
            and store["platform"] == "takealot"
            and store["feature_policies"].get("sync_enabled", False)
        ]
        if not stores:
            return []

        local_date = local_now.date()
        for task in app_state.list_tasks():
            if (
                task["task_type"] in SYNC_TASK_TYPES
                and task.get("target_id") == DAILY_RECONCILE_TARGET_ID
                and self._task_local_date(task) == local_date
            ):
                return []

        try:
            subscription_service.ensure_can_enqueue_sync(actor)
        except HTTPException:
            return []

        task = app_state.create_task(
            task_type=SYNC_STORE_LISTINGS_TASK_TYPE,
            domain="store",
            queue_name="store-sync",
            actor_user_id=actor["id"],
            actor_role=actor["role"],
            tenant_id=actor["tenant_id"],
            store_id=None,
            target_type="store_collection",
            target_id=DAILY_RECONCILE_TARGET_ID,
            request_id=f"scheduled-store-reconcile-{local_date.isoformat()}",
            label="Takealot listings daily reconciliation",
            next_action="Worker will reconcile all active Takealot stores from /offers",
        )
        app_state.append_audit(
            request_id=task["request_id"],
            tenant_id=actor["tenant_id"],
            store_id=None,
            actor_user_id=actor["id"],
            actor_role=actor["role"],
            action="store.sync.reconcile.daily",
            action_label="Daily Takealot listings reconciliation",
            risk_level="medium",
            target_type="store_collection",
            target_id=DAILY_RECONCILE_TARGET_ID,
            target_label="Active Takealot stores",
            before=None,
            after={
                "task_id": task["id"],
                "status": task["status"],
                "task_type": task["task_type"],
                "store_count": len(stores),
                "scheduled_for": local_date.isoformat(),
            },
            reason="每日凌晨自动全量校准",
            result="success",
            task_id=task["id"],
            metadata={"store_ids": [store["id"] for store in stores]},
        )
        return [task]

    def process_queued_store_tasks(
        self,
        *,
        adapter_factory: AdapterFactory | None = None,
    ) -> list[dict[str, Any]]:
        claimed_tasks = app_state.claim_queued_tasks(
            STORE_TASK_TYPES,
            worker_id=WORKER_SOURCE_ID,
        )
        return [
            self.process_store_task(task["id"], adapter_factory=adapter_factory)
            for task in claimed_tasks
        ]

    def process_queued_sync_tasks(
        self,
        *,
        adapter_factory: AdapterFactory | None = None,
    ) -> list[dict[str, Any]]:
        claimed_tasks = app_state.claim_queued_tasks(
            SYNC_TASK_TYPES,
            worker_id=WORKER_SOURCE_ID,
        )
        return [
            self.process_sync_task(task["id"], adapter_factory=adapter_factory)
            for task in claimed_tasks
        ]

    def process_store_task(
        self,
        task_id: str,
        *,
        adapter_factory: AdapterFactory | None = None,
    ) -> dict[str, Any]:
        task = self._require_store_task(task_id)
        if task["task_type"] == CREDENTIAL_VALIDATION_TASK_TYPE:
            return self.process_credential_validation_task(
                task_id,
                adapter_factory=adapter_factory,
            )
        return self.process_sync_task(task_id, adapter_factory=adapter_factory)

    def process_sync_task(
        self,
        task_id: str,
        *,
        adapter_factory: AdapterFactory | None = None,
    ) -> dict[str, Any]:
        task = self._require_sync_task(task_id)
        if self._task_cancel_requested(task_id):
            return self._mark_task_cancelled(task_id)
        stores = self._stores_for_task(task)
        started_at = self._now()
        self._update_task_progress(
            task_id,
            status="running",
            stage="syncing",
            progress_current=0,
            progress_total=len(stores),
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
            stage="syncing",
            message="Worker started syncing store listings",
            details={"store_count": len(stores)},
            source="worker",
            source_id=WORKER_SOURCE_ID,
        )

        failures: list[dict[str, Any]] = []
        total_synced = 0
        for index, store in enumerate(stores, start=1):
            if self._task_cancel_requested(task_id):
                return self._mark_task_cancelled(task_id)
            try:
                synced_count = self._sync_single_store(
                    task=task,
                    store=store,
                    adapter_factory=adapter_factory,
                )
                total_synced += synced_count
            except Exception as exc:
                failure = self._handle_store_sync_failure(task=task, store=store, exc=exc)
                failures.append(failure)
            finally:
                percent = round((index / max(len(stores), 1)) * 100, 2)
                self._update_task_progress(
                    task_id,
                    progress_current=index,
                    progress_total=len(stores),
                    progress_percent=percent,
                    last_heartbeat_at=self._now(),
                )

        final_status = "succeeded"
        final_stage = "completed"
        error_code = None
        error_msg = None
        should_retry = self._should_retry_sync_task(task, failures, total_synced)
        if should_retry:
            retry_at = self._next_retry_at(task)
            updated_task = self._update_task_progress(
                task_id,
                status="waiting_retry",
                stage="waiting_retry",
                progress_current=len(stores),
                progress_total=len(stores),
                progress_percent=100,
                finished_at=None,
                last_heartbeat_at=self._now(),
                next_retry_at=retry_at,
                lease_owner=None,
                lease_token=None,
                lease_expires_at=None,
                error_code="STORE_PLATFORM_UNAVAILABLE",
                error_msg="Store sync temporarily failed; retry scheduled",
                error_details={
                    "failures": failures,
                    "listing_count": total_synced,
                    "store_count": len(stores),
                    "retry_at": retry_at.isoformat(),
                },
            )
            app_state.add_task_event(
                task_id=task_id,
                event_type="task.retry_scheduled",
                from_status="running",
                to_status="waiting_retry",
                stage="waiting_retry",
                message="Temporary store sync failure; retry scheduled",
                details={
                    "retry_at": retry_at.isoformat(),
                    "attempt_count": task.get("attempt_count", 0),
                    "max_retries": task.get("max_retries", 0),
                    "failed_store_count": len(failures),
                },
                source="worker",
                source_id=WORKER_SOURCE_ID,
            )
            return updated_task

        if failures and total_synced == 0:
            final_status = "failed_final" if task.get("attempt_count", 0) >= task.get("max_retries", 0) else "failed"
            final_stage = "failed"
            error_code = "STORE_SYNC_FAILED"
            error_msg = "All store sync attempts failed"
        elif failures:
            final_status = "partial"
            final_stage = "completed_with_errors"
            error_code = "STORE_SYNC_PARTIAL"
            error_msg = f"{len(failures)} store sync failures"

        completed_at = self._now()
        updated_task = self._update_task_progress(
            task_id,
            status=final_status,
            stage=final_stage,
            progress_current=len(stores),
            progress_total=len(stores),
            progress_percent=100,
            finished_at=completed_at,
            last_heartbeat_at=completed_at,
            next_retry_at=None,
            lease_owner=None,
            lease_token=None,
            lease_expires_at=None,
            error_code=error_code,
            error_msg=error_msg,
            error_details={
                "failures": failures,
                "listing_count": total_synced,
                "store_count": len(stores),
            }
            if failures
            else None,
        )
        app_state.add_task_event(
            task_id=task_id,
            event_type=f"task.{final_status}",
            from_status="running",
            to_status=final_status,
            stage=final_stage,
            message=f"Store sync finished with status {final_status}",
            details={
                "listing_count": total_synced,
                "failed_store_count": len(failures),
            },
            source="worker",
            source_id=WORKER_SOURCE_ID,
        )
        return updated_task

    def process_credential_validation_task(
        self,
        task_id: str,
        *,
        adapter_factory: AdapterFactory | None = None,
    ) -> dict[str, Any]:
        task = self._require_credential_task(task_id)
        if self._task_cancel_requested(task_id):
            return self._mark_task_cancelled(task_id)
        store = self._require_store(task["store_id"])
        started_at = self._now()
        self._update_task_progress(
            task_id,
            status="running",
            stage="validating",
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
            stage="validating",
            message="Worker started validating store credentials",
            details={"store_id": store["id"], "platform": store["platform"]},
            source="worker",
            source_id=WORKER_SOURCE_ID,
        )

        try:
            credentials_payload = app_state.get_store_credentials(store["id"])
            if self._task_cancel_requested(task_id):
                return self._mark_task_cancelled(task_id)
            if not credentials_payload:
                raise AdapterAuthError("Store credentials unavailable")
            credentials = AdapterCredentials(
                platform=store["platform"],
                api_key=credentials_payload.get("api_key", ""),
                api_secret=credentials_payload.get("api_secret", ""),
            )
            if not credentials.api_key or not credentials.api_secret:
                raise AdapterAuthError("Store credentials unavailable")

            adapter = self._build_adapter(
                store=store,
                credentials=credentials,
                adapter_factory=adapter_factory,
            )
            validation_meta = adapter.get_seller_profile()
            validated_at = self._now()
            platform_profile = self._map_platform_profile(validation_meta, validated_at)
            app_state.update_store(
                store["id"],
                api_key_status="valid",
                credential_status="valid",
                last_validated_at=validated_at,
                platform_profile=platform_profile.model_dump(mode="json"),
            )
            updated_task = self._update_task_progress(
                task_id,
                status="succeeded",
                stage="completed",
                progress_current=1,
                progress_total=1,
                progress_percent=100,
                finished_at=validated_at,
                last_heartbeat_at=validated_at,
            )
            app_state.add_task_event(
                task_id=task_id,
                event_type="task.succeeded",
                from_status="running",
                to_status="succeeded",
                stage="completed",
                message=f"{store['name']} credentials validated",
                details=validation_meta,
                source="worker",
                source_id=WORKER_SOURCE_ID,
            )
            self._append_store_task_audit(
                task=task,
                store=store,
                action="store.credentials.validate",
                action_label="Validate store credentials",
                result="success",
                reason="Platform credential validation succeeded",
                metadata=validation_meta,
            )
            return updated_task
        except Exception as exc:
            error_code, store_changes = self._credential_validation_failure_state(exc)
            app_state.update_store(
                store["id"],
                **store_changes,
            )
            failed_at = self._now()
            updated_task = self._update_task_progress(
                task_id,
                status="failed",
                stage="failed",
                progress_current=1,
                progress_total=1,
                progress_percent=100,
                finished_at=failed_at,
                last_heartbeat_at=failed_at,
                error_code=error_code,
                error_msg=str(exc),
                error_details={
                    "store_id": store["id"],
                    "platform": store["platform"],
                    "error": str(exc),
                },
            )
            app_state.add_task_event(
                task_id=task_id,
                event_type="task.failed",
                from_status="running",
                to_status="failed",
                stage="failed",
                message=f"{store['name']} credential validation failed",
                details={
                    "error": str(exc),
                    "error_code": error_code,
                    **store_changes,
                },
                source="worker",
                source_id=WORKER_SOURCE_ID,
            )
            self._append_store_task_audit(
                task=task,
                store=store,
                action="store.credentials.validate",
                action_label="Validate store credentials",
                result="failed",
                reason=str(exc),
                metadata=store_changes,
                error_code=error_code,
            )
            return updated_task

    def _sync_single_store(
        self,
        *,
        task: dict[str, Any],
        store: dict[str, Any],
        adapter_factory: AdapterFactory | None,
    ) -> int:
        credentials_payload = app_state.get_store_credentials(store["id"])
        if not credentials_payload:
            raise AdapterAuthError("Store credentials unavailable")

        credentials = AdapterCredentials(
            platform=store["platform"],
            api_key=credentials_payload.get("api_key", ""),
            api_secret=credentials_payload.get("api_secret", ""),
        )
        if not credentials.api_key or not credentials.api_secret:
            raise AdapterAuthError("Store credentials unavailable")

        adapter = self._build_adapter(
            store=store,
            credentials=credentials,
            adapter_factory=adapter_factory,
        )
        snapshots = adapter.fetch_listings(
            heartbeat=lambda _: self._update_task_progress(
                task["id"],
                last_heartbeat_at=self._now(),
            ),
            include_stock_details=self._sync_scope(task) != SYNC_SCOPE_BIDDING,
        )
        synced_count = self._bulk_upsert_listings(
            store["id"],
            snapshots,
            preserve_stock_details=self._sync_scope(task) == SYNC_SCOPE_BIDDING,
        )
        self._mark_stale_listings(store["id"], snapshots)
        self._clear_listing_status_count_cache(store["id"])
        self._update_task_progress(
            task["id"],
            last_heartbeat_at=self._now(),
        )

        updated_store = app_state.update_store(
            store["id"],
            last_synced_at=self._now(),
            api_key_status="valid",
            credential_status="valid",
        )
        app_state.add_task_event(
            task_id=task["id"],
            event_type="task.progress",
            from_status="running",
            to_status="running",
            stage="syncing",
            message=f"Synced {synced_count} listings for {store['name']}",
            details={
                "store_id": store["id"],
                "listing_count": synced_count,
                "last_synced_at": updated_store["last_synced_at"].isoformat()
                if updated_store["last_synced_at"] is not None
                else None,
            },
            source="worker",
            source_id=WORKER_SOURCE_ID,
        )
        self._append_store_sync_audit(
            task=task,
            store=store,
            result="success",
            reason=f"Synced {synced_count} platform listings",
            metadata={"listing_count": synced_count},
        )
        return synced_count

    def _bulk_upsert_listings(
        self,
        store_id: str,
        snapshots: list[ListingSnapshot],
        *,
        preserve_stock_details: bool = False,
    ) -> int:
        prepared_snapshots = (
            self._snapshots_preserving_stock_details(store_id, snapshots)
            if preserve_stock_details
            else snapshots
        )
        bulk_upsert = getattr(app_state, "upsert_store_listings_bulk", None)
        if bulk_upsert is not None:
            return int(
                bulk_upsert(
                    [
                        {
                            "store_id": store_id,
                            "external_listing_id": snapshot.external_listing_id,
                            "platform_product_id": snapshot.platform_product_id,
                            "sku": snapshot.sku,
                            "title": snapshot.title,
                            "platform_price": snapshot.platform_price,
                            "stock_quantity": snapshot.stock_quantity,
                            "currency": snapshot.currency,
                            "sync_status": snapshot.sync_status,
                            "raw_payload": snapshot.raw_payload,
                        }
                        for snapshot in prepared_snapshots
                    ]
                )
            )

        synced_count = 0
        for snapshot in prepared_snapshots:
            self._upsert_listing(store_id, snapshot)
            synced_count += 1
        return synced_count

    @staticmethod
    def _sync_scope(task: dict[str, Any]) -> str:
        ui_meta = task.get("ui_meta")
        if isinstance(ui_meta, dict) and ui_meta.get("sync_scope") == SYNC_SCOPE_BIDDING:
            return SYNC_SCOPE_BIDDING
        return SYNC_SCOPE_FULL

    @staticmethod
    def _snapshots_preserving_stock_details(
        store_id: str,
        snapshots: list[ListingSnapshot],
    ) -> list[ListingSnapshot]:
        if not snapshots:
            return []

        existing_by_external_id: dict[str, dict[str, Any]] = {}
        existing_by_sku: dict[str, dict[str, Any]] = {}
        for listing in app_state.list_store_listings(store_id=store_id, limit=None, offset=0):
            if listing.get("external_listing_id"):
                existing_by_external_id[str(listing["external_listing_id"])] = listing
            if listing.get("sku"):
                existing_by_sku[str(listing["sku"])] = listing

        prepared: list[ListingSnapshot] = []
        for snapshot in snapshots:
            existing = (
                existing_by_external_id.get(str(snapshot.external_listing_id))
                or existing_by_sku.get(str(snapshot.sku))
            )
            raw_payload = dict(snapshot.raw_payload or {})
            existing_payload = existing.get("raw_payload") if isinstance(existing, dict) else None
            if isinstance(existing_payload, dict):
                for key in STOCK_DETAIL_PAYLOAD_KEYS:
                    if key not in raw_payload and key in existing_payload:
                        raw_payload[key] = existing_payload[key]
            prepared.append(
                ListingSnapshot(
                    external_listing_id=snapshot.external_listing_id,
                    sku=snapshot.sku,
                    title=snapshot.title,
                    platform_product_id=snapshot.platform_product_id,
                    platform_price=snapshot.platform_price,
                    stock_quantity=(
                        snapshot.stock_quantity
                        if snapshot.stock_quantity is not None
                        else existing.get("stock_quantity")
                        if isinstance(existing, dict)
                        else None
                    ),
                    currency=snapshot.currency,
                    sync_status=snapshot.sync_status,
                    raw_payload=raw_payload,
                )
            )
        return prepared

    def _mark_stale_listings(
        self,
        store_id: str,
        snapshots: list[ListingSnapshot],
    ) -> int:
        mark_stale = getattr(app_state, "mark_store_listings_stale_except", None)
        if mark_stale is None:
            return 0
        return int(
            mark_stale(
                store_id=store_id,
                external_listing_ids=[
                    snapshot.external_listing_id
                    for snapshot in snapshots
                ],
            )
        )

    def _handle_store_sync_failure(
        self,
        *,
        task: dict[str, Any],
        store: dict[str, Any],
        exc: Exception,
    ) -> dict[str, Any]:
        if isinstance(exc, AdapterAuthError):
            app_state.update_store(
                store["id"],
                api_key_status="stale",
                credential_status="expired",
            )
            error_code = "STORE_AUTH_FAILED"
            retryable = False
        elif isinstance(exc, AdapterTemporaryError):
            error_code = "STORE_PLATFORM_UNAVAILABLE"
            retryable = True
        elif isinstance(exc, AdapterError):
            error_code = "STORE_ADAPTER_FAILED"
            retryable = False
        else:
            error_code = "STORE_SYNC_EXCEPTION"
            retryable = False

        details = {
            "store_id": store["id"],
            "store_name": store["name"],
            "platform": store["platform"],
            "error": str(exc),
            "error_code": error_code,
            "retryable": retryable,
        }
        app_state.add_task_event(
            task_id=task["id"],
            event_type="task.store_failed",
            from_status="running",
            to_status="running",
            stage="syncing",
            message=f"{store['name']} sync failed",
            details=details,
            source="worker",
            source_id=WORKER_SOURCE_ID,
        )
        self._append_store_sync_audit(
            task=task,
            store=store,
            result="failed",
            reason=str(exc),
            metadata=details,
            error_code=error_code,
        )
        return details

    @staticmethod
    def _should_retry_sync_task(
        task: dict[str, Any],
        failures: list[dict[str, Any]],
        total_synced: int,
    ) -> bool:
        if not failures or total_synced > 0:
            return False
        if not task.get("retryable", True):
            return False
        if task.get("attempt_count", 0) >= task.get("max_retries", 0):
            return False
        return all(bool(failure.get("retryable")) for failure in failures)

    def _next_retry_at(self, task: dict[str, Any]) -> datetime:
        attempt_count = max(0, int(task.get("attempt_count", 0)))
        delay_seconds = min(300, 30 * (2 ** attempt_count))
        return self._now() + timedelta(seconds=delay_seconds)

    def _append_store_sync_audit(
        self,
        *,
        task: dict[str, Any],
        store: dict[str, Any],
        result: str,
        reason: str,
        metadata: dict[str, Any],
        error_code: str | None = None,
    ) -> None:
        self._append_store_task_audit(
            task=task,
            store=store,
            action="store.sync.worker",
            action_label="Sync store listings",
            result=result,
            reason=reason,
            metadata=metadata,
            error_code=error_code,
        )

    def _append_store_task_audit(
        self,
        *,
        task: dict[str, Any],
        store: dict[str, Any],
        action: str,
        action_label: str,
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
            action=action,
            action_label=action_label,
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

    def _credentials_for_store(self, store: dict[str, Any]) -> AdapterCredentials:
        credentials_payload = app_state.get_store_credentials(store["id"])
        if not credentials_payload:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="店铺凭证不可用",
            )
        credentials = AdapterCredentials(
            platform=store["platform"],
            api_key=credentials_payload.get("api_key", ""),
            api_secret=credentials_payload.get("api_secret", ""),
        )
        if not credentials.api_key or not credentials.api_secret:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="店铺凭证不可用",
            )
        return credentials

    def _validate_platform_credentials(
        self,
        *,
        store: dict[str, Any],
        credentials: AdapterCredentials,
        validated_at: datetime,
    ) -> StorePlatformProfile:
        adapter = self._build_adapter(
            store=store,
            credentials=credentials,
            adapter_factory=None,
        )
        try:
            return self._map_platform_profile(adapter.get_seller_profile(), validated_at)
        except AdapterAuthError as exc:
            if store.get("id"):
                app_state.update_store(
                    store["id"],
                    api_key_status="stale",
                    credential_status="expired",
                )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API Key 校验失败，请确认 Takealot API Key 是否正确。",
            ) from exc
        except AdapterTemporaryError as exc:
            if store.get("id"):
                app_state.update_store(
                    store["id"],
                    api_key_status="configured",
                    credential_status="configured",
                )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Takealot 暂时无法完成 API Key 校验，请稍后再试。",
            ) from exc
        except AdapterError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Takealot API Key 校验失败：{exc}",
            ) from exc

    def _store_platform_profile(self, store: dict[str, Any]) -> StorePlatformProfile | None:
        raw_profile = store.get("platform_profile")
        if raw_profile is None:
            credentials_payload = app_state.get_store_credentials(store["id"])
            if credentials_payload:
                raw_profile = credentials_payload.get("platform_profile")
        if isinstance(raw_profile, StorePlatformProfile):
            return raw_profile
        if not isinstance(raw_profile, dict):
            return None
        try:
            return StorePlatformProfile(**raw_profile)
        except ValueError:
            return None

    @staticmethod
    def _map_platform_profile(
        payload: dict[str, Any],
        validated_at: datetime,
    ) -> StorePlatformProfile:
        return StorePlatformProfile(
            seller_id=StoreService._first_text(
                payload,
                "seller_id",
                "sellerId",
                "sellerID",
                "id",
            ),
            display_name=StoreService._first_text(
                payload,
                "display_name",
                "displayName",
                "seller_name",
                "name",
            ),
            business_status=StoreService._business_status_label(payload),
            on_vacation=StoreService._bool_value(payload.get("on_vacation")),
            leadtime_label=StoreService._leadtime_label(payload),
            tenure_label=StoreService._tenure_label(payload),
            validated_at=validated_at,
        )

    @staticmethod
    def _business_status_label(payload: dict[str, Any]) -> str | None:
        on_vacation = StoreService._bool_value(payload.get("on_vacation"))
        if on_vacation is True:
            return "休假中"
        if on_vacation is False:
            return "营业中"
        if StoreService._bool_value(payload.get("disable_listing_enabled")) is True:
            return "停用"
        if StoreService._bool_value(payload.get("registration_complete")) is False:
            return "待完成注册"
        if StoreService._bool_value(payload.get("account_verified")) is False:
            return "待验证"
        return None

    @staticmethod
    def _leadtime_label(payload: dict[str, Any]) -> str | None:
        details = payload.get("leadtime_details")
        min_days: list[int] = []
        max_days: list[int] = []
        single_days: list[int] = []
        if isinstance(details, list):
            for item in details:
                if not isinstance(item, dict):
                    continue
                minimum = StoreService._int_value(
                    item.get("min_days")
                    or item.get("minimum_days")
                    or item.get("minimum_leadtime_days")
                )
                maximum = StoreService._int_value(
                    item.get("max_days")
                    or item.get("maximum_days")
                    or item.get("maximum_leadtime_days")
                )
                single = StoreService._int_value(
                    item.get("days")
                    or item.get("leadtime_days")
                    or item.get("minimum_leadtime")
                )
                if minimum is not None:
                    min_days.append(minimum)
                if maximum is not None:
                    max_days.append(maximum)
                if single is not None:
                    single_days.append(single)

        direct = StoreService._int_value(
            payload.get("leadtime_days")
            or payload.get("minimum_leadtime_days")
            or payload.get("minimum_leadtime")
        )
        if direct is not None:
            single_days.append(direct)

        if min_days and max_days:
            minimum = min(min_days)
            maximum = max(max_days)
            if minimum != maximum:
                return f"{minimum}-{maximum} 天"
            return f"{minimum} 天"
        if single_days:
            return f"{min(single_days)} 天"
        if StoreService._bool_value(payload.get("leadtime_enabled")) is False:
            return "未启用"
        return None

    @staticmethod
    def _tenure_label(payload: dict[str, Any]) -> str | None:
        for key in (
            "date_added",
            "created_at",
            "registered_at",
            "registration_date",
            "joined_at",
            "seller_since",
        ):
            parsed = StoreService._datetime_value(payload.get(key))
            if parsed is None:
                continue
            delta = datetime.now(UTC) - parsed
            return f"{max(1, delta.days)} 天"
        return None

    @staticmethod
    def _first_text(payload: dict[str, Any], *keys: str) -> str | None:
        for key in keys:
            value = payload.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return None

    @staticmethod
    def _bool_value(value: Any) -> bool | None:
        if isinstance(value, bool):
            return value
        if isinstance(value, int | float) and value in {0, 1}:
            return bool(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "y"}:
                return True
            if normalized in {"false", "0", "no", "n"}:
                return False
        return None

    @staticmethod
    def _int_value(value: Any) -> int | None:
        if isinstance(value, bool) or value in (None, ""):
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _datetime_value(value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, date):
            parsed = datetime.combine(value, datetime.min.time())
        elif isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                return None
        else:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    def _build_adapter(
        self,
        *,
        store: dict[str, Any],
        credentials: AdapterCredentials,
        adapter_factory: AdapterFactory | None,
    ) -> BaseAdapter:
        if adapter_factory is not None:
            return adapter_factory(store, credentials)
        if store["platform"] == "takealot":
            return TakealotAdapter(credentials)
        raise AdapterError(f"Unsupported store platform: {store['platform']}")

    def _upsert_listing(self, store_id: str, snapshot: ListingSnapshot) -> dict[str, Any]:
        listing = app_state.upsert_store_listing(
            store_id=store_id,
            external_listing_id=snapshot.external_listing_id,
            platform_product_id=snapshot.platform_product_id,
            sku=snapshot.sku,
            title=snapshot.title,
            platform_price=snapshot.platform_price,
            stock_quantity=snapshot.stock_quantity,
            currency=snapshot.currency,
            sync_status=snapshot.sync_status,
            raw_payload=snapshot.raw_payload,
        )
        sync_guardrails_for_listing(
            listing=listing,
            request_id=f"listing-sync-{store_id}",
            actor=None,
        )
        return listing

    def _is_fresh_active_sync_task(self, task: dict[str, Any]) -> bool:
        if task["task_type"] not in SYNC_TASK_TYPES or task["status"] not in ACTIVE_SYNC_STATUSES:
            return False
        if task["status"] == "queued":
            marker = task.get("updated_at") or task.get("created_at")
            timeout_seconds = QUEUED_SYNC_TASK_TIMEOUT_SECONDS
        else:
            marker = (
                task.get("last_heartbeat_at")
                or task.get("started_at")
                or task.get("updated_at")
                or task.get("created_at")
            )
            timeout_seconds = SYNC_TASK_FRESH_WINDOW_SECONDS
        if marker is None:
            return False
        if marker.tzinfo is None:
            marker = marker.replace(tzinfo=UTC)
        return self._now() - marker <= timedelta(seconds=timeout_seconds)

    def _release_orphaned_sync_tasks(self, store_id: str) -> list[dict[str, Any]]:
        released: list[dict[str, Any]] = []
        now = self._now()
        for task in app_state.list_tasks():
            if (
                task.get("store_id") != store_id
                or task.get("task_type") not in SYNC_TASK_TYPES
                or task.get("status") not in ACTIVE_SYNC_STATUSES
            ):
                continue
            if task["status"] == "queued":
                marker = task.get("updated_at") or task.get("created_at")
                timeout_seconds = QUEUED_SYNC_TASK_TIMEOUT_SECONDS
                error_code = "STORE_SYNC_WORKER_TIMEOUT"
                error_msg = "Store sync was queued but no worker picked it up in time"
                event_message = "Queued store sync released because no worker picked it up"
            else:
                marker = (
                    task.get("last_heartbeat_at")
                    or task.get("started_at")
                    or task.get("updated_at")
                    or task.get("created_at")
                )
                timeout_seconds = SYNC_TASK_FRESH_WINDOW_SECONDS
                error_code = "STORE_SYNC_HEARTBEAT_TIMEOUT"
                error_msg = "Store sync stopped sending progress heartbeats"
                event_message = "Store sync released because its heartbeat became stale"
            if marker is None:
                continue
            if marker.tzinfo is None:
                marker = marker.replace(tzinfo=UTC)
            if now - marker <= timedelta(seconds=timeout_seconds):
                continue
            updated = app_state.update_task(
                task["id"],
                status="timed_out",
                stage="failed",
                finished_at=now,
                next_retry_at=None,
                lease_owner=None,
                lease_token=None,
                lease_expires_at=None,
                error_code=error_code,
                error_msg=error_msg,
                error_details={
                    "previous_status": task["status"],
                    "last_seen_at": marker.isoformat(),
                    "timeout_seconds": timeout_seconds,
                },
            )
            app_state.add_task_event(
                task_id=task["id"],
                event_type="task.timed_out",
                from_status=task["status"],
                to_status="timed_out",
                stage="failed",
                message=event_message,
                details={
                    "last_seen_at": marker.isoformat(),
                    "timeout_seconds": timeout_seconds,
                },
                source="api",
                source_id="store-sync-watchdog",
            )
            released.append(updated)
        return released

    def process_store_task_safely(self, task_id: str) -> dict[str, Any] | None:
        try:
            task = app_state.get_task(task_id)
            if task is None or task.get("status") not in {"queued", "leased", "waiting_retry"}:
                return task
            return self.process_store_task(task_id)
        except Exception as exc:
            now = self._now()
            try:
                updated = app_state.update_task(
                    task_id,
                    status="failed",
                    stage="failed",
                    finished_at=now,
                    lease_owner=None,
                    lease_token=None,
                    lease_expires_at=None,
                    error_code="STORE_SYNC_BACKGROUND_FAILED",
                    error_msg=str(exc),
                )
                app_state.add_task_event(
                    task_id=task_id,
                    event_type="task.failed",
                    from_status=None,
                    to_status="failed",
                    stage="failed",
                    message="API background store sync failed",
                    details={"error": str(exc)},
                    source="api",
                    source_id="store-sync-background",
                )
                return updated
            except Exception:
                return None

    @staticmethod
    def _task_marker_age_seconds(task: dict[str, Any]) -> float | None:
        marker = (
            task.get("last_heartbeat_at")
            or task.get("started_at")
            or task.get("updated_at")
            or task.get("created_at")
        )
        if marker is None:
            return None
        if marker.tzinfo is None:
            marker = marker.replace(tzinfo=UTC)
        return (datetime.now(UTC) - marker).total_seconds()

    @staticmethod
    def _task_local_date(task: dict[str, Any]) -> date | None:
        marker = task.get("created_at") or task.get("updated_at")
        if marker is None:
            return None
        if marker.tzinfo is None:
            marker = marker.replace(tzinfo=UTC)
        return marker.astimezone(DAILY_RECONCILE_TIMEZONE).date()

    @staticmethod
    def _system_super_admin_actor() -> dict[str, Any] | None:
        return next(
            (
                user
                for user in app_state.list_users()
                if user.get("role") == "super_admin" and user.get("status") == "active"
            ),
            None,
        )

    def _stores_for_task(self, task: dict[str, Any]) -> list[dict[str, Any]]:
        if task["store_id"]:
            return [self._require_store(task["store_id"])]
        return [
            store
            for store in app_state.list_stores()
            if store["status"] == "active"
            and (
                task["actor_role"] == "super_admin"
                or store["tenant_id"] == task["tenant_id"]
            )
            and store["feature_policies"].get("sync_enabled", False)
        ]

    def _require_sync_task(self, task_id: str) -> dict[str, Any]:
        task = app_state.get_task(task_id)
        if task is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Task not found",
            )
        if task["task_type"] not in SYNC_TASK_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Task is not a store sync task",
            )
        return task

    def _require_credential_task(self, task_id: str) -> dict[str, Any]:
        task = self._require_store_task(task_id)
        if task["task_type"] != CREDENTIAL_VALIDATION_TASK_TYPE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Task is not a credential validation task",
            )
        return task

    def _require_store_task(self, task_id: str) -> dict[str, Any]:
        task = app_state.get_task(task_id)
        if task is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Task not found",
            )
        if task["task_type"] not in STORE_TASK_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Task is not a store task",
            )
        return task

    def _create_store_task(
        self,
        *,
        store: dict[str, Any],
        actor: dict[str, Any],
        request_headers: dict[str, str],
        task_type: str,
        label: str,
        next_action: str,
    ) -> dict[str, Any]:
        return app_state.create_task(
            task_type=task_type,
            domain="store",
            queue_name="store-sync",
            actor_user_id=actor["id"],
            actor_role=actor["role"],
            tenant_id=store["tenant_id"],
            store_id=store["id"],
            target_type="store",
            target_id=store["id"],
            request_id=get_request_id(request_headers),
            label=label,
            next_action=next_action,
        )

    def _store_tasks(self, store_id: str) -> list[TaskRunSummary]:
        tasks = [
            task
            for task in app_state.list_tasks()
            if task["store_id"] == store_id
            and (task["domain"] == "store" or task["task_type"] in STORE_TASK_TYPES)
        ]
        return [self._task_service._to_task_summary(task) for task in tasks]

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
    def _require_store_listing(store_id: str, listing_id: str) -> dict[str, Any]:
        get_listing = getattr(app_state, "get_store_listing", None)
        listing = (
            get_listing(store_id=store_id, listing_id=listing_id)
            if callable(get_listing)
            else None
        )
        if listing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Listing not found",
            )
        return listing

    @staticmethod
    def _ensure_admin_enabled() -> None:
        if not app_state.is_setting_enabled("admin_enabled", True):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin control plane is disabled",
            )

    @staticmethod
    def _mask_credential(value: str) -> str:
        if len(value) <= 8:
            return "********"
        return f"{value[:4]}********{value[-4:]}"

    @staticmethod
    def _same_money(current: Any, requested: float) -> bool:
        try:
            return abs(float(current) - float(requested)) < 0.005
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _offer_payload(payload: Any) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return None
        offer = payload.get("offer")
        return offer if isinstance(offer, dict) else payload

    @staticmethod
    def _seller_stock_quantity(payload: Any) -> int | None:
        source = StoreService._offer_payload(payload)
        if source is None:
            return None
        if not StoreService._seller_stock_enabled(payload):
            return 0
        leadtime_stock = StoreService._sum_stock_array(
            source.get("leadtime_stock") or source.get("merchant_warehouse_stock")
        )
        if leadtime_stock is not None:
            return leadtime_stock
        direct = StoreService._numeric_value(source.get("total_merchant_stock"))
        if direct is None:
            direct = StoreService._numeric_value(source.get("seller_stock_quantity"))
        if direct is not None:
            return int(direct)
        return StoreService._sum_stock_array(source.get("seller_warehouse_stock")) or 0

    @staticmethod
    def _seller_stock_enabled(payload: Any) -> bool:
        source = StoreService._offer_payload(payload)
        if source is None:
            return False
        explicit_enabled = (
            StoreService._bool_value(source.get("leadtime_enabled"))
            if "leadtime_enabled" in source
            else StoreService._bool_value(source.get("leadtimeEnabled"))
        )
        if explicit_enabled is False:
            return False
        leadtime_days = (
            StoreService._numeric_value(source.get("leadtime_days"))
            or StoreService._numeric_value(source.get("minimum_leadtime_days"))
            or StoreService._numeric_value(source.get("minimum_leadtime"))
        )
        if leadtime_days is not None:
            return leadtime_days > 0
        if explicit_enabled is True:
            return True
        seller_stock = StoreService._sum_stock_array(source.get("seller_warehouse_stock"))
        return (
            seller_stock is not None
            and seller_stock > 0
            and StoreService._payload_is_buyable(payload)
        )

    @staticmethod
    def _payload_status_text(payload: Any) -> str:
        values: list[Any] = []

        def append_payload_status(source: Any) -> None:
            if not isinstance(source, dict):
                return
            for key in ("status", "offer_status", "availability", "state"):
                values.append(source.get(key))

        append_payload_status(payload)
        if isinstance(payload, dict):
            append_payload_status(payload.get("payload"))
            append_payload_status(payload.get("offer"))
        return " ".join(
            str(value).lower()
            for value in values
            if value not in (None, "")
        )

    @staticmethod
    def _payload_is_buyable(payload: Any) -> bool:
        status_text = StoreService._payload_status_text(payload)
        is_platform_disabled = any(token in status_text for token in PLATFORM_DISABLED_TOKENS)
        is_seller_disabled = any(token in status_text for token in SELLER_DISABLED_TOKENS)
        return (
            bool(BUYABLE_STATUS_RE.search(status_text))
            and not bool(DISABLED_STATUS_RE.search(status_text))
            and not is_platform_disabled
            and not is_seller_disabled
        )

    @staticmethod
    def _sum_stock_array(value: Any) -> int | None:
        if not isinstance(value, list):
            return None
        total = 0
        has_value = False
        for item in value:
            if not isinstance(item, dict):
                continue
            quantity = StoreService._numeric_value(item.get("quantity_available"))
            if quantity is None:
                quantity = StoreService._numeric_value(item.get("quantityAvailable"))
            if quantity is None:
                quantity = StoreService._numeric_value(item.get("quantity"))
            if quantity is None:
                continue
            total += int(quantity)
            has_value = True
        return total if has_value else None

    @staticmethod
    def _seller_warehouse_id(payload: Any) -> int | None:
        source = StoreService._offer_payload(payload)
        if source is None:
            return None
        for key in ("seller_warehouse_id", "merchant_warehouse_id"):
            value = StoreService._numeric_value(source.get(key))
            if value is not None:
                return int(value)
        warehouse_stock = source.get("seller_warehouse_stock")
        if not isinstance(warehouse_stock, list):
            return None
        for item in warehouse_stock:
            if not isinstance(item, dict):
                continue
            for key in ("seller_warehouse_id", "merchant_warehouse_id"):
                value = StoreService._numeric_value(item.get(key))
                if value is not None:
                    return int(value)
        return None

    @staticmethod
    def _leadtime_merchant_warehouse_id(payload: Any) -> int | None:
        source = StoreService._offer_payload(payload)
        if source is None:
            return None
        for key in ("leadtime_merchant_warehouse_id", "merchant_warehouse_id", "seller_warehouse_id"):
            value = StoreService._numeric_value(source.get(key))
            if value is not None:
                return int(value)
        for key in ("leadtime_stock", "merchant_warehouse_stock", "seller_warehouse_stock"):
            stock = source.get(key)
            if not isinstance(stock, list):
                continue
            for item in stock:
                if not isinstance(item, dict):
                    continue
                for item_key in ("merchant_warehouse_id", "seller_warehouse_id", "warehouse_id"):
                    value = StoreService._numeric_value(item.get(item_key))
                    if value is not None:
                        return int(value)
                warehouse = item.get("merchant_warehouse") or item.get("warehouse")
                if isinstance(warehouse, dict):
                    value = StoreService._numeric_value(
                        warehouse.get("warehouse_id") or warehouse.get("id")
                    )
                    if value is not None:
                        return int(value)
        return None

    @staticmethod
    def _listing_barcode(listing: dict[str, Any]) -> str | None:
        payload = listing.get("raw_payload")
        if not isinstance(payload, dict):
            return None
        barcode = payload.get("barcode")
        if isinstance(barcode, str) and barcode.strip():
            return barcode.strip()
        if isinstance(barcode, int | float):
            return str(barcode)
        return None

    @staticmethod
    def _listing_payload_with_updates(
        raw_payload: Any,
        *,
        platform_payload: dict[str, Any] | None,
        selling_price: float | None,
        seller_stock: int | None,
        seller_stock_enabled: bool | None,
        seller_warehouse_id: int | None,
        leadtime_merchant_warehouse_id: int | None,
    ) -> dict[str, Any]:
        next_payload = dict(raw_payload) if isinstance(raw_payload, dict) else {}
        if isinstance(platform_payload, dict):
            next_payload.update(platform_payload)
        if selling_price is not None:
            next_payload["selling_price"] = selling_price
        if seller_stock_enabled is False:
            next_payload["leadtime_days"] = None
        elif seller_stock_enabled is True and StoreService._numeric_value(next_payload.get("leadtime_days")) is None:
            next_payload["leadtime_days"] = settings.extension_listing_default_leadtime_days
        if seller_stock is not None:
            next_payload["total_merchant_stock"] = seller_stock
            next_payload["seller_stock_quantity"] = seller_stock
            leadtime_stock = next_payload.get("leadtime_stock")
            if isinstance(leadtime_stock, list) and leadtime_stock:
                updated_leadtime_stock: list[Any] = []
                for index, item in enumerate(leadtime_stock):
                    if not isinstance(item, dict):
                        updated_leadtime_stock.append(item)
                        continue
                    next_item = dict(item)
                    if index == 0:
                        next_item["quantity_available"] = int(seller_stock)
                        next_item["quantity"] = int(seller_stock)
                    updated_leadtime_stock.append(next_item)
                next_payload["leadtime_stock"] = updated_leadtime_stock
            elif leadtime_merchant_warehouse_id is not None:
                next_payload["leadtime_stock"] = [
                    {
                        "merchant_warehouse_id": leadtime_merchant_warehouse_id,
                        "quantity_available": int(seller_stock),
                    }
                ]
            warehouse_stock = next_payload.get("seller_warehouse_stock")
            if isinstance(warehouse_stock, list) and warehouse_stock:
                updated_stock: list[Any] = []
                remaining = int(seller_stock)
                for index, item in enumerate(warehouse_stock):
                    if not isinstance(item, dict):
                        updated_stock.append(item)
                        continue
                    next_item = dict(item)
                    if index == 0:
                        next_item["quantity_available"] = remaining
                    updated_stock.append(next_item)
                next_payload["seller_warehouse_stock"] = updated_stock
            elif seller_warehouse_id is not None:
                next_payload["seller_warehouse_stock"] = [
                    {
                        "seller_warehouse_id": seller_warehouse_id,
                        "quantity_available": int(seller_stock),
                    }
                ]
        return next_payload

    @staticmethod
    def _numeric_value(value: Any) -> float | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int | float):
            return float(value)
        if isinstance(value, str) and value.strip():
            try:
                return float(value.strip())
            except ValueError:
                return None
        return None

    @staticmethod
    def _listing_audit_snapshot(listing: dict[str, Any]) -> dict[str, Any]:
        return {
            "listing_id": listing["id"],
            "store_id": listing["store_id"],
            "external_listing_id": listing["external_listing_id"],
            "sku": listing["sku"],
            "selling_price": listing.get("platform_price"),
            "seller_stock": StoreService._seller_stock_quantity(listing.get("raw_payload")),
        }

    @staticmethod
    def _to_task_created(task: dict[str, Any]) -> TaskCreatedResponse:
        return TaskCreatedResponse(
            task_id=task["id"],
            status=task["status"],
            stage=task["stage"],
        )

    @staticmethod
    def _to_store_summary(store: dict[str, Any]) -> StoreSummary:
        return StoreSummary(
            store_id=store["id"],
            tenant_id=store["tenant_id"],
            name=store["name"],
            platform=store["platform"],
            status=store["status"],
            api_key_status=store["api_key_status"],
            credential_status=store["credential_status"],
            last_synced_at=store["last_synced_at"],
            feature_policies=StoreFeaturePolicies(**store["feature_policies"]),
            created_at=store["created_at"],
            updated_at=store["updated_at"],
            version=store["version"],
        )

    @staticmethod
    def _to_listing_response(listing: dict[str, Any]) -> StoreListingResponse:
        return StoreListingResponse(
            listing_id=listing["id"],
            store_id=listing["store_id"],
            external_listing_id=listing["external_listing_id"],
            platform_product_id=listing.get("platform_product_id"),
            sku=listing["sku"],
            title=listing["title"],
            platform_price=listing["platform_price"],
            buybox_price=listing.get("buybox_price"),
            stock_quantity=listing["stock_quantity"],
            currency=listing["currency"],
            sync_status=listing["sync_status"],
            raw_payload=listing["raw_payload"],
            last_synced_at=listing["last_synced_at"],
            created_at=listing["created_at"],
            updated_at=listing["updated_at"],
        )

    def _listing_status_counts(
        self,
        store_id: str,
        sku_query: str | None,
        *,
        sku_filter: set[str] | None = None,
    ) -> dict[str, int]:
        sku_filter_key = "*" if sku_filter is None else ",".join(sorted(sku_filter))
        cache_key = (store_id, (sku_query or "").strip().lower(), sku_filter_key)
        now = monotonic()
        with self._listing_status_count_cache_lock:
            cached = self._listing_status_count_cache.get(cache_key)
            if cached and now - cached[0] <= STATUS_COUNT_CACHE_TTL_SECONDS:
                return dict(cached[1])

        if sku_filter is not None:
            counts = {
                "all": self._count_store_listings_for_skus(
                    store_id=store_id,
                    sku_query=sku_query,
                    sku_filter=sku_filter,
                ),
            }
            for status_group in LISTING_STATUS_GROUPS:
                counts[status_group] = self._count_store_listings_for_skus(
                    store_id=store_id,
                    sku_query=sku_query,
                    sku_filter=sku_filter,
                    status_group=status_group,
                )
        else:
            count_groups = getattr(app_state, "count_store_listing_status_groups", None)
            if callable(count_groups):
                counts = count_groups(store_id=store_id, sku_query=sku_query)
            else:
                counts = {
                    "all": app_state.count_store_listings(store_id=store_id, sku_query=sku_query),
                }
                for status_group in LISTING_STATUS_GROUPS:
                    counts[status_group] = app_state.count_store_listings(
                        store_id=store_id,
                        sku_query=sku_query,
                        status_group=status_group,
                    )

        normalized_counts = {
            "all": int(counts.get("all", 0) or 0),
            "buyable": int(counts.get("buyable", 0) or 0),
            "not_buyable": int(counts.get("not_buyable", 0) or 0),
            "platform_disabled": int(counts.get("platform_disabled", 0) or 0),
            "seller_disabled": int(counts.get("seller_disabled", 0) or 0),
        }
        with self._listing_status_count_cache_lock:
            self._listing_status_count_cache[cache_key] = (now, normalized_counts)
        return dict(normalized_counts)

    @staticmethod
    def _floor_price_sku_filter(store_id: str) -> set[str]:
        return {
            rule["sku"]
            for rule in app_state.list_bidding_rules(store_id=store_id)
            if rule.get("floor_price") is not None
        }

    @staticmethod
    def _bidding_sku_filter(store_id: str, bidding_filter: str) -> set[str] | None:
        if bidding_filter == "with_floor":
            return StoreService._floor_price_sku_filter(store_id)
        if bidding_filter not in {"active", "won", "lost", "alerts", "blocked", "paused"}:
            return None
        return {
            rule["sku"]
            for rule in app_state.list_bidding_rules(store_id=store_id)
            if StoreService._bidding_rule_matches_filter(rule, bidding_filter)
        }

    @staticmethod
    def _bidding_rule_matches_filter(rule: dict[str, Any], bidding_filter: str) -> bool:
        if bidding_filter == "active":
            return bool(rule.get("is_active"))
        if bidding_filter == "won":
            return bool(rule.get("is_active")) and StoreService._bidding_rule_owns_lowest(rule)
        if bidding_filter == "lost":
            return (
                bool(rule.get("is_active"))
                and rule.get("last_buybox_price") is not None
                and not StoreService._bidding_rule_owns_lowest(rule)
            )
        if bidding_filter == "alerts":
            return StoreService._bidding_rule_has_alert(rule)
        if bidding_filter == "blocked":
            return rule.get("buybox_status") == "blocked"
        if bidding_filter == "paused":
            return not bool(rule.get("is_active")) and (
                rule.get("floor_price") is not None
                or bool(rule.get("last_action"))
                or bool(rule.get("last_cycle_error"))
                or bool(rule.get("repricing_blocked_reason"))
            )
        return False

    @staticmethod
    def _bidding_rule_owns_lowest(rule: dict[str, Any]) -> bool:
        decision = rule.get("last_decision")
        return isinstance(decision, dict) and decision.get("owns_buybox") is True

    @staticmethod
    def _bidding_rule_has_alert(rule: dict[str, Any]) -> bool:
        if not rule.get("is_active"):
            return False
        if rule.get("floor_price") is None:
            return True
        if rule.get("buybox_status") in {"blocked", "retrying"}:
            return True
        if rule.get("last_cycle_error") or rule.get("repricing_blocked_reason"):
            return True
        if rule.get("last_action") == "floor":
            return True
        floor_price = StoreService._numeric_value(rule.get("floor_price"))
        lowest_price = StoreService._numeric_value(rule.get("last_buybox_price"))
        return bool(
            floor_price is not None
            and lowest_price is not None
            and lowest_price < floor_price
            and not StoreService._bidding_rule_owns_lowest(rule)
        )

    @staticmethod
    def _count_store_listings_for_skus(
        *,
        store_id: str,
        sku_query: str | None,
        sku_filter: set[str],
        status_group: str | None = None,
    ) -> int:
        return sum(
            1
            for listing in app_state.list_store_listings(
                store_id=store_id,
                sku_query=sku_query,
                status_group=status_group,
                limit=None,
                offset=0,
            )
            if listing["sku"] in sku_filter
        )

    def _clear_listing_status_count_cache(self, store_id: str | None = None) -> None:
        with self._listing_status_count_cache_lock:
            if store_id is None:
                self._listing_status_count_cache.clear()
                return
            for key in list(self._listing_status_count_cache):
                if key[0] == store_id:
                    self._listing_status_count_cache.pop(key, None)

    @staticmethod
    def _store_audit_snapshot(store: dict[str, Any]) -> dict[str, Any]:
        return {
            "store_id": store["id"],
            "name": store["name"],
            "platform": store["platform"],
            "status": store["status"],
            "api_key_status": store["api_key_status"],
            "credential_status": store["credential_status"],
            "masked_api_key": store["masked_api_key"],
            "feature_policies": store["feature_policies"],
        }

    @staticmethod
    def _update_task_progress(task_id: str, **changes: Any) -> dict[str, Any]:
        return app_state.update_task(task_id, **changes)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    @staticmethod
    def _credential_validation_failure_state(exc: Exception) -> tuple[str, dict[str, Any]]:
        if isinstance(exc, AdapterAuthError):
            return "STORE_AUTH_FAILED", {
                "api_key_status": "stale",
                "credential_status": "expired",
            }
        if isinstance(exc, AdapterTemporaryError):
            return "STORE_PLATFORM_UNAVAILABLE", {
                "api_key_status": "configured",
                "credential_status": "configured",
            }
        if isinstance(exc, AdapterError):
            return "STORE_ADAPTER_FAILED", {
                "api_key_status": "configured",
                "credential_status": "configured",
            }
        return "STORE_CREDENTIAL_VALIDATION_EXCEPTION", {
            "api_key_status": "configured",
            "credential_status": "configured",
        }

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
