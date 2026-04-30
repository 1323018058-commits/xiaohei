from __future__ import annotations

import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta
from math import ceil
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status

from src.modules.admin.service import get_request_id
from src.modules.auth.repo import auth_repository
from src.modules.bidding.service import BiddingService
from src.modules.common.dev_state import app_state
from src.modules.common.tenant_scope import require_tenant_access
from src.modules.subscription.service import subscription_service
from src.platform.settings.base import settings
from .takealot_catalog import catalog_client
from .success_fee_data import SUCCESS_FEE_RULES

from .schemas import (
    ExtensionAuthResponse,
    ExtensionListNowResponse,
    ExtensionListNowTaskStatusResponse,
    ExtensionLoginResponse,
    ExtensionProfileResponse,
    ExtensionProfileUser,
    ExtensionStoreSummary,
    ProfitPreviewGuardrail,
    ProfitPreviewPricing,
    ProfitPreviewProduct,
    ProfitPreviewRequest,
    ProfitPreviewResponse,
    ExtensionListNowRequest,
    ProtectedFloorRequest,
    ProtectedFloorResponse,
)

from src.modules.listing.service import ListingService, PROCESS_LISTING_JOB_TASK_TYPE

SUCCESS_FEE_VAT_RATE = 0.15
DEFAULT_SUCCESS_FEE_RATE = 0.15

FULFILLMENT_CATEGORY_GROUPS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("non-perishable", "household cleaning", "liquor"), "low_standard"),
    (("stationery", "pets", "pet", "baby", "consumer beauty", "health", "fmcg", "bathroom"), "mid_standard"),
    (
        (
            "mobile",
            "laptops",
            "small household appliances",
            "small kitchen appliances",
            "smart home",
            "appliances",
            "tv",
            "audio",
            "video",
            "smart audio",
            "technology",
            "smart energy",
            "certified pre-owned",
        ),
        "electronics_standard",
    ),
)

FULFILLMENT_FEE_TABLE: dict[str, dict[str, float]] = {
    "low_standard": {"light": 22.0, "heavy": 52.0, "heavy_plus": 107.0, "very_heavy": 107.0},
    "mid_standard": {"light": 33.0, "heavy": 52.0, "heavy_plus": 107.0, "very_heavy": 107.0},
    "other_standard": {"light": 45.0, "heavy": 52.0, "heavy_plus": 107.0, "very_heavy": 107.0},
    "electronics_standard": {"light": 60.0, "heavy": 60.0, "heavy_plus": 107.0, "very_heavy": 107.0},
    "large": {"light": 60.0, "heavy": 65.0, "heavy_plus": 107.0, "very_heavy": 118.0},
    "oversize": {"light": 107.0, "heavy": 130.0, "heavy_plus": 160.0, "very_heavy": 160.0},
    "bulky": {"light": 107.0, "heavy": 145.0, "heavy_plus": 160.0, "very_heavy": 172.0},
    "extra_bulky": {"light": 270.0, "heavy": 270.0, "heavy_plus": 320.0, "very_heavy": 390.0},
}

def sync_guardrails_for_listing(
    *,
    listing: dict[str, Any],
    request_id: str,
    actor: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    platform_product_id = str(listing.get("platform_product_id") or "").strip()
    if not platform_product_id:
        return []

    guardrails = app_state.list_guardrails_for_store_platform_product(
        store_id=listing["store_id"],
        platform="takealot",
        external_product_id=platform_product_id,
    )
    if not guardrails:
        return []

    bidding_service = BiddingService()
    sync_actor = actor or {
        "id": None,
        "role": "system_worker",
        "tenant_id": guardrails[0]["tenant_id"],
    }
    synced_rules: list[dict[str, Any]] = []
    for guardrail in guardrails:
        try:
            rule = bidding_service.upsert_rule_from_guardrail(
                store_id=listing["store_id"],
                sku=listing["sku"],
                listing_id=listing["external_listing_id"],
                floor_price=guardrail["protected_floor_price"],
                actor=sync_actor,
                request_id=request_id,
                reason="guardrail linked after listing sync",
            )
        except Exception as exc:
            app_state.update_tenant_product_guardrail(
                guardrail["id"],
                status="sync_failed",
                autobid_sync_status="failed",
                last_error_code="AUTOBID_GUARDRAIL_SYNC_FAILED",
                last_error_message=str(exc),
            )
            continue

        app_state.update_tenant_product_guardrail(
            guardrail["id"],
            status="synced_autobid",
            autobid_sync_status="synced",
            linked_bidding_rule_id=rule["id"],
            linked_listing_id=listing["id"],
            last_synced_at=datetime.now(UTC),
            last_error_code=None,
            last_error_message=None,
        )
        synced_rules.append(rule)
    return synced_rules


class ExtensionService:
    LIST_NOW_TASK_TYPE = "EXTENSION_LIST_NOW"
    EXTENSION_WORKER_SOURCE_ID = "extension-worker"

    def issue_auth_token(
        self,
        *,
        actor: dict[str, Any],
        store_id: str | None,
    ) -> ExtensionAuthResponse:
        subscription_service.ensure_writable_feature_enabled(actor, "extension")
        if store_id is not None:
            self._require_store(store_id, actor)
        plain_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(plain_token.encode("utf-8")).hexdigest()
        expires_at = datetime.now(UTC) + timedelta(seconds=settings.extension_token_ttl_seconds)
        record = app_state.create_extension_auth_token(
            token_hash=token_hash,
            tenant_id=actor["tenant_id"],
            user_id=actor["id"],
            store_id=store_id,
            expires_at=expires_at,
        )
        return ExtensionAuthResponse(
            token=plain_token,
            expires_at=record["expires_at"],
            store_id=record.get("store_id"),
        )

    def login_with_credentials(
        self,
        *,
        username: str,
        password: str,
        store_id: str | None,
    ) -> ExtensionLoginResponse:
        user = auth_repository.authenticate(username, password)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户名或密码错误",
            )
        if user["role"] not in {"super_admin", "tenant_admin", "operator"}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="当前账号无扩展访问权限",
            )
        try:
            subscription_service.ensure_writable_feature_enabled(user, "extension")
        except HTTPException:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="当前套餐未开通插件能力，或订阅已到期",
            )
        auth_payload = self.issue_auth_token(actor=user, store_id=store_id)
        profile = self.profile(user)
        return ExtensionLoginResponse(
            token=auth_payload.token,
            expires_at=auth_payload.expires_at,
            store_id=auth_payload.store_id,
            user=profile.user,
            stores=profile.stores,
        )

    def profile(self, actor: dict[str, Any]) -> ExtensionProfileResponse:
        stores = app_state.list_stores(
            None if actor["role"] == "super_admin" else actor["tenant_id"]
        )
        return ExtensionProfileResponse(
            user=ExtensionProfileUser(
                user_id=actor["id"],
                username=actor["username"],
                role=actor["role"],
                tenant_id=actor["tenant_id"],
            ),
            stores=[
                ExtensionStoreSummary(
                    store_id=store["id"],
                    name=store["name"],
                    platform=store["platform"],
                    bidding_enabled=bool(store["feature_policies"].get("bidding_enabled")),
                    listing_enabled=bool(store["feature_policies"].get("listing_enabled")),
                    sync_enabled=bool(store["feature_policies"].get("sync_enabled")),
                )
                for store in stores
                if store["platform"] == "takealot"
            ],
        )

    @staticmethod
    def _positive_int_or_none(value: Any) -> int | None:
        try:
            number = int(value)
        except (TypeError, ValueError):
            return None
        return number if number > 0 else None

    def profit_preview(
        self,
        *,
        payload: ProfitPreviewRequest,
        actor: dict[str, Any],
    ) -> ProfitPreviewResponse:
        store = self._require_store(payload.store_id, actor)
        product = self._ensure_library_product(
            plid=payload.plid,
            title=payload.title,
            store_id=store["id"],
            force_refresh_facts=payload.force_refresh_facts,
            barcode=payload.barcode or payload.gtin,
        )
        listing = app_state.find_store_listing_by_platform_product_id(
            store_id=store["id"],
            platform_product_id=payload.plid,
        )
        guardrail = app_state.get_tenant_product_guardrail(
            tenant_id=store["tenant_id"],
            store_id=store["id"],
            product_id=product["id"],
        )
        return ProfitPreviewResponse(
            store_id=store["id"],
            product=self._to_preview_product(product, fallback_category_path=payload.category_path),
            guardrail=self._to_preview_guardrail(guardrail),
            pricing=self._build_pricing_preview(payload, guardrail, product, listing),
        )

    def save_protected_floor(
        self,
        *,
        payload: ProtectedFloorRequest,
        actor: dict[str, Any],
        request_headers: dict[str, str],
    ) -> ProtectedFloorResponse:
        subscription_service.ensure_writable_feature_enabled(actor, "extension")
        if payload.protected_floor_price <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="protected_floor_price must be greater than 0",
            )
        store = self._require_store(payload.store_id, actor)
        product = self._ensure_library_product(
            plid=payload.plid,
            title=payload.title,
            store_id=store["id"],
        )
        guardrail = app_state.upsert_tenant_product_guardrail(
            tenant_id=store["tenant_id"],
            store_id=store["id"],
            product_id=product["id"],
            protected_floor_price=payload.protected_floor_price,
            created_by=actor["id"],
            updated_by=actor["id"],
            status="pending_listing_link",
            autobid_sync_status="pending",
            source="extension",
        )

        linked_listing = app_state.find_store_listing_by_platform_product_id(
            store_id=store["id"],
            platform_product_id=payload.plid,
        )
        if linked_listing is not None:
            sync_guardrails_for_listing(
                listing=linked_listing,
                request_id=get_request_id(request_headers),
                actor=actor,
            )
            refreshed_guardrail = app_state.get_tenant_product_guardrail(
                tenant_id=store["tenant_id"],
                store_id=store["id"],
                product_id=product["id"],
            )
            if refreshed_guardrail is not None:
                guardrail = refreshed_guardrail

        app_state.append_audit(
            request_id=get_request_id(request_headers),
            tenant_id=store["tenant_id"],
            store_id=store["id"],
            actor_user_id=actor["id"],
            actor_role=actor["role"],
            action="extension.protected_floor.upsert",
            action_label="Save protected floor price",
            risk_level="high",
            target_type="tenant_product_guardrail",
            target_id=guardrail["id"],
            target_label=payload.plid,
            before=None,
            after={
                "product_id": product["id"],
                "plid": payload.plid,
                "protected_floor_price": guardrail["protected_floor_price"],
                "status": guardrail["status"],
                "autobid_sync_status": guardrail["autobid_sync_status"],
                "linked_bidding_rule_id": guardrail.get("linked_bidding_rule_id"),
            },
            reason="Save protected floor from extension",
            result="success",
            task_id=None,
        )
        return self._to_protected_floor_response(guardrail, payload.plid)

    def create_list_now_task(
        self,
        *,
        payload: ExtensionListNowRequest,
        actor: dict[str, Any],
        request_headers: dict[str, str],
    ) -> ExtensionListNowResponse:
        subscription_service.ensure_writable_feature_enabled(actor, "listing")
        store = self._require_store(payload.store_id, actor)
        product = self._ensure_library_product(
            plid=payload.plid,
            title=payload.title,
            store_id=store["id"],
            barcode=payload.barcode or payload.gtin,
        )
        payload_barcode = self._normalize_barcode(payload.barcode or payload.gtin)
        guardrail = app_state.get_tenant_product_guardrail(
            tenant_id=store["tenant_id"],
            store_id=store["id"],
            product_id=product["id"],
        )
        if guardrail is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="请先设置保护价后再发起一键上架",
            )

        task = app_state.create_task(
            task_type=self.LIST_NOW_TASK_TYPE,
            domain="extension",
            queue_name="extension-listing",
            actor_user_id=actor["id"],
            actor_role=actor["role"],
            tenant_id=store["tenant_id"],
            store_id=store["id"],
            target_type="library_product",
            target_id=product["id"],
            request_id=get_request_id(request_headers),
            label=f"{product['title']} 一键上架",
            next_action="等待 Listing Worker 接入正式上架流程",
        )
        task = app_state.update_task(
            task["id"],
            ui_meta={
                **(task.get("ui_meta") or {}),
                "plid": payload.plid,
                "sale_price_zar": payload.sale_price_zar,
                "quantity": payload.quantity,
                "barcode": payload_barcode,
            },
        )
        app_state.append_audit(
            request_id=task["request_id"],
            tenant_id=store["tenant_id"],
            store_id=store["id"],
            actor_user_id=actor["id"],
            actor_role=actor["role"],
            action="extension.list_now.create_task",
            action_label="Create list-now task",
            risk_level="high",
            target_type="extension_list_now_task",
            target_id=task["id"],
            target_label=payload.plid,
            before=None,
            after={
                "task_id": task["id"],
                "plid": payload.plid,
                "product_id": product["id"],
                "guardrail_id": guardrail["id"],
                "protected_floor_price": guardrail["protected_floor_price"],
                "quantity": payload.quantity,
                "barcode": payload_barcode,
            },
            reason="Create extension list-now task shell",
            result="success",
            task_id=task["id"],
        )
        return ExtensionListNowResponse(
            task_id=task["id"],
            status=task["status"],
            stage=task["stage"],
            store_id=store["id"],
            plid=payload.plid,
        )

    def get_list_now_status(
        self,
        *,
        task_id: str,
        actor: dict[str, Any],
    ) -> ExtensionListNowTaskStatusResponse:
        task = self._require_extension_task(task_id, actor)
        store_credentials = (
            app_state.get_store_credentials(task["store_id"])
            if task.get("store_id")
            else None
        ) or {}
        leadtime_merchant_warehouse_id = store_credentials.get("leadtime_merchant_warehouse_id")
        try:
            leadtime_merchant_warehouse_id = (
                int(leadtime_merchant_warehouse_id)
                if leadtime_merchant_warehouse_id is not None
                else None
            )
        except (TypeError, ValueError):
            leadtime_merchant_warehouse_id = None

        task_error_details = task.get("error_details")
        task_error_details = task_error_details if isinstance(task_error_details, dict) else {}
        task_ui_meta = task.get("ui_meta") if isinstance(task.get("ui_meta"), dict) else {}
        task_quantity = self._positive_int_or_none(task_ui_meta.get("quantity"))
        listing_job_id = task_error_details.get("listing_job_id")
        listing_job = app_state.get_listing_job(listing_job_id) if listing_job_id else None
        if listing_job is not None:
            require_tenant_access(actor, listing_job["tenant_id"], detail="Task not found")

        product = None
        if listing_job is not None and listing_job.get("product_id"):
            product = app_state.get_library_product_by_id(listing_job["product_id"])
        elif task.get("target_id"):
            product = app_state.get_library_product_by_id(task["target_id"])

        listing_payload = (
            listing_job.get("raw_payload")
            if listing_job is not None and isinstance(listing_job.get("raw_payload"), dict)
            else {}
        )
        offer_payload = (
            listing_payload.get("offer_payload")
            if isinstance(listing_payload.get("offer_payload"), dict)
            else {}
        )
        offer_diagnosis = (
            listing_payload.get("offer_diagnosis")
            if isinstance(listing_payload.get("offer_diagnosis"), dict)
            else {}
        )
        offer_id_raw = offer_payload.get("offer_id") or offer_payload.get("id")
        try:
            offer_id = int(offer_id_raw) if offer_id_raw is not None else None
        except (TypeError, ValueError):
            offer_id = None
        offer_status = (
            offer_diagnosis.get("offer_status")
            or offer_payload.get("status")
            or None
        )
        needs_buyable_patch = bool(
            offer_id is not None and str(offer_status or "").strip().lower() != "buyable"
        )
        note = (
            listing_job.get("note")
            if listing_job is not None
            else task.get("error_msg")
            or (task.get("ui_meta") or {}).get("next_action")
        )

        return ExtensionListNowTaskStatusResponse(
            task_id=task["id"],
            task_status=task["status"],
            task_stage=task["stage"],
            request_id=task["request_id"],
            store_id=task.get("store_id"),
            plid=(
                product["external_product_id"]
                if product is not None
                else listing_payload.get("plid")
            ),
            listing_job_id=listing_job["id"] if listing_job is not None else None,
            listing_status=listing_job["status"] if listing_job is not None else None,
            listing_stage=listing_job["stage"] if listing_job is not None else None,
            note=note,
            offer_id=offer_id,
            offer_status=str(offer_status) if offer_status is not None else None,
            barcode=(
                str(offer_payload.get("barcode"))
                if offer_payload.get("barcode") is not None
                else (
                    str(listing_payload.get("barcode"))
                    if listing_payload.get("barcode") is not None
                    else self._extract_gtin_from_product(product)
                )
            ),
            sku=(
                str(offer_payload.get("sku"))
                if offer_payload.get("sku") is not None
                else (
                    str(listing_payload.get("generated_sku"))
                    if listing_payload.get("generated_sku") is not None
                    else None
                )
            ),
            protected_floor_price=(
                float(listing_payload["protected_floor_price"])
                if listing_payload.get("protected_floor_price") is not None
                else None
            ),
            leadtime_merchant_warehouse_id=leadtime_merchant_warehouse_id,
            default_leadtime_days=int(settings.extension_listing_default_leadtime_days),
            can_auto_make_buyable=bool(
                offer_id is not None and leadtime_merchant_warehouse_id is not None
                and task_quantity is not None
            ),
            needs_buyable_patch=needs_buyable_patch,
        )

    def refresh_list_now_status(
        self,
        *,
        task_id: str,
        actor: dict[str, Any],
    ) -> ExtensionListNowTaskStatusResponse:
        status_snapshot = self.get_list_now_status(task_id=task_id, actor=actor)
        if status_snapshot.listing_job_id:
            ListingService().refresh_job_status(status_snapshot.listing_job_id, actor)
        return self.get_list_now_status(task_id=task_id, actor=actor)

    def process_queued_extension_tasks(self) -> list[dict[str, Any]]:
        claimed_tasks = app_state.claim_queued_tasks(
            {self.LIST_NOW_TASK_TYPE},
            worker_id=self.EXTENSION_WORKER_SOURCE_ID,
        )
        return [
            self.process_list_now_task(task["id"])
            for task in claimed_tasks
        ]

    def process_list_now_task(self, task_id: str) -> dict[str, Any]:
        task = app_state.get_task(task_id)
        if task is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Task not found",
            )
        if task["task_type"] != self.LIST_NOW_TASK_TYPE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Task is not an extension list-now task",
            )

        store = app_state.get_store(task["store_id"])
        if store is None:
            updated = app_state.update_task(
                task_id,
                status="failed",
                stage="failed",
                progress_percent=100,
                finished_at=datetime.now(UTC),
                last_heartbeat_at=datetime.now(UTC),
                lease_owner=None,
                lease_token=None,
                lease_expires_at=None,
                error_code="STORE_NOT_FOUND",
                error_msg="Store not found for list-now task",
                error_details={"store_id": task.get("store_id")},
            )
            return updated

        product = app_state.get_library_product_by_id(task["target_id"]) if task.get("target_id") else None
        if product is None:
            updated = app_state.update_task(
                task_id,
                status="failed",
                stage="failed",
                progress_percent=100,
                finished_at=datetime.now(UTC),
                last_heartbeat_at=datetime.now(UTC),
                lease_owner=None,
                lease_token=None,
                lease_expires_at=None,
                error_code="PRODUCT_NOT_FOUND",
                error_msg="Library product not found for list-now task",
                error_details={"product_id": task.get("target_id")},
            )
            return updated

        guardrail = app_state.get_tenant_product_guardrail(
            tenant_id=store["tenant_id"],
            store_id=store["id"],
            product_id=product["id"],
        )
        linked_listing = app_state.find_store_listing_by_platform_product_id(
            store_id=store["id"],
            platform_product_id=product["external_product_id"],
        )
        linked_listing_payload = (
            linked_listing.get("raw_payload")
            if linked_listing is not None and isinstance(linked_listing.get("raw_payload"), dict)
            else {}
        )
        task_meta = task.get("ui_meta") if isinstance(task.get("ui_meta"), dict) else {}
        listing_job = app_state.create_listing_job(
            tenant_id=store["tenant_id"],
            store_id=store["id"],
            product_id=product["id"],
            guardrail_id=guardrail["id"] if guardrail else None,
            entry_task_id=task_id,
            processing_task_id=None,
            platform="takealot",
            source="extension",
            source_ref=product["external_product_id"],
            title=product["title"],
            status="queued",
            stage="queued",
            note="Created from extension list-now task",
            raw_payload={
                "plid": product["external_product_id"],
                "sale_price_zar": (task.get("ui_meta") or {}).get("sale_price_zar"),
                "quantity": task_meta.get("quantity"),
                "guardrail_id": guardrail["id"] if guardrail else None,
                "protected_floor_price": guardrail["protected_floor_price"] if guardrail else None,
                "barcode": linked_listing_payload.get("barcode") or task_meta.get("barcode") or self._extract_gtin_from_product(product),
                "existing_offer_id": linked_listing_payload.get("offer_id"),
                "existing_listing_id": linked_listing["id"] if linked_listing is not None else None,
            },
        )
        processing_task = app_state.create_task(
            task_type=PROCESS_LISTING_JOB_TASK_TYPE,
            domain="listing",
            queue_name="listing-jobs",
            actor_user_id=task["actor_user_id"],
            actor_role=task["actor_role"],
            tenant_id=store["tenant_id"],
            store_id=store["id"],
            target_type="listing_job",
            target_id=listing_job["id"],
            request_id=task["request_id"],
            label=f"{product['title']} listing job",
            next_action="Listing worker will prepare listing payload",
        )
        app_state.update_listing_job(
            listing_job["id"],
            processing_task_id=processing_task["id"],
        )

        now = datetime.now(UTC)
        updated = app_state.update_task(
            task_id,
            status="succeeded",
            stage="queued_for_listing_worker",
            progress_percent=100,
            finished_at=now,
            last_heartbeat_at=now,
            lease_owner=None,
            lease_token=None,
            lease_expires_at=None,
            error_code=None,
            error_msg=None,
            error_details={
                "listing_job_id": listing_job["id"],
                "processing_task_id": processing_task["id"],
            },
            ui_meta={
                "label": task["ui_meta"].get("label") if task.get("ui_meta") else "一键上架任务",
                "next_action": "Listing job created and queued for listing worker",
            },
        )
        app_state.add_task_event(
            task_id=task_id,
            event_type="task.succeeded",
            from_status=task["status"],
            to_status="succeeded",
            stage="queued_for_listing_worker",
            message="List-now task created a formal listing job",
            details={
                "worker": self.EXTENSION_WORKER_SOURCE_ID,
                "listing_job_id": listing_job["id"],
                "processing_task_id": processing_task["id"],
            },
            source="worker",
            source_id=self.EXTENSION_WORKER_SOURCE_ID,
        )
        return updated

    def _require_extension_task(
        self,
        task_id: str,
        actor: dict[str, Any],
    ) -> dict[str, Any]:
        task = app_state.get_task(task_id)
        if task is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Task not found",
            )
        if task["task_type"] != self.LIST_NOW_TASK_TYPE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Task is not an extension list-now task",
            )
        require_tenant_access(actor, task["tenant_id"], detail="Task not found")
        return task

    @staticmethod
    def _require_store(store_id: str, actor: dict[str, Any]) -> dict[str, Any]:
        store = app_state.get_store(store_id)
        if store is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Store not found",
            )
        require_tenant_access(actor, store["tenant_id"], detail="Store not found")
        return store

    def _ensure_library_product(
        self,
        *,
        plid: str,
        title: str | None,
        store_id: str,
        force_refresh_facts: bool = False,
        barcode: str | None = None,
    ) -> dict[str, Any]:
        existing = app_state.get_library_product(platform="takealot", external_product_id=plid)
        if existing is None:
            normalized_title = title or f"PLID{plid}"
            existing = app_state.upsert_library_product(
                platform="takealot",
                external_product_id=plid,
                title=normalized_title,
                fact_status="pending_enrichment",
                raw_payload={"source": "extension_stub", "plid": plid, "title": normalized_title},
            )
        refreshed = self._refresh_library_product(
            product=existing,
            store_id=store_id,
            fallback_title=title,
            force_refresh_facts=force_refresh_facts,
        )
        product = refreshed or existing
        return self._persist_extension_barcode(product=product, barcode=barcode)

    def _persist_extension_barcode(
        self,
        *,
        product: dict[str, Any],
        barcode: str | None,
    ) -> dict[str, Any]:
        normalized = self._normalize_barcode(barcode)
        if not normalized:
            return product
        if self._extract_gtin_from_product(product):
            return product

        raw_payload = product.get("raw_payload") if isinstance(product.get("raw_payload"), dict) else {}
        merged_payload = {**raw_payload, "barcode": normalized, "gtin": normalized}
        nested_payload = merged_payload.get("payload")
        if isinstance(nested_payload, dict):
            merged_payload["payload"] = {
                **nested_payload,
                "barcode": nested_payload.get("barcode") or normalized,
                "gtin": nested_payload.get("gtin") or normalized,
            }

        return app_state.upsert_library_product(
            platform=product["platform"],
            external_product_id=product["external_product_id"],
            title=product["title"],
            fact_status=product.get("fact_status") or "pending_enrichment",
            raw_payload=merged_payload,
            merchant_packaged_weight_raw=product.get("merchant_packaged_weight_raw"),
            merchant_packaged_dimensions_raw=product.get("merchant_packaged_dimensions_raw"),
            cbs_package_weight_raw=product.get("cbs_package_weight_raw"),
            cbs_package_dimensions_raw=product.get("cbs_package_dimensions_raw"),
            consolidated_packaged_dimensions_raw=product.get("consolidated_packaged_dimensions_raw"),
            last_refreshed_at=product.get("last_refreshed_at"),
        )

    def _refresh_library_product(
        self,
        *,
        product: dict[str, Any],
        store_id: str,
        fallback_title: str | None,
        force_refresh_facts: bool = False,
    ) -> dict[str, Any] | None:
        if self._is_product_facts_complete(product) and not force_refresh_facts:
            return product

        catalog_attempted = False
        if force_refresh_facts and catalog_client.is_configured():
            catalog_attempted = True
            enriched = self._enrich_product_from_catalog(
                product=product,
                fallback_title=fallback_title,
            )
            if enriched is not None:
                product = enriched
                if self._is_product_facts_complete(product):
                    return product

        listing = app_state.find_store_listing_by_platform_product_id(
            store_id=store_id,
            platform_product_id=product["external_product_id"],
        )
        if listing is not None:
            enriched = self._enrich_product_from_listing(
                product=product,
                listing=listing,
            )
            if self._is_product_facts_complete(enriched):
                return enriched
            product = enriched

        if not catalog_attempted and catalog_client.is_configured():
            enriched = self._enrich_product_from_catalog(
                product=product,
                fallback_title=fallback_title,
            )
            if enriched is not None:
                return enriched
        return product

    @staticmethod
    def _is_product_facts_complete(product: dict[str, Any]) -> bool:
        return bool(
            (
                product.get("merchant_packaged_weight_raw")
                or product.get("cbs_package_weight_raw")
            )
            and (
                product.get("merchant_packaged_dimensions_raw")
                or product.get("cbs_package_dimensions_raw")
                or product.get("consolidated_packaged_dimensions_raw")
            )
        )

    @staticmethod
    def _enrich_product_from_listing(
        *,
        product: dict[str, Any],
        listing: dict[str, Any],
    ) -> dict[str, Any]:
        payload = listing.get("raw_payload") or {}
        weight_grams = payload.get("weight_grams")
        length_cm = payload.get("length_cm")
        width_cm = payload.get("width_cm")
        height_cm = payload.get("height_cm")
        weight_raw = None
        dimensions_raw = None
        if weight_grams not in {None, ""}:
            weight_raw = f"{weight_grams} g"
        if all(value not in {None, ""} for value in (length_cm, width_cm, height_cm)):
            dimensions_raw = f"{length_cm} x {width_cm} x {height_cm} cm"
        if not weight_raw and not dimensions_raw:
            return product
        fact_status = "complete" if weight_raw and dimensions_raw else "partial"
        return app_state.upsert_library_product(
            platform=product["platform"],
            external_product_id=product["external_product_id"],
            title=product["title"] or listing["title"],
            fact_status=fact_status,
            raw_payload={
                "source": "takealot_offers",
                "listing_id": listing["external_listing_id"],
                "payload": {
                    "productline_id": listing.get("platform_product_id"),
                    "barcode": payload.get("barcode"),
                    "weight_grams": weight_grams,
                    "length_cm": length_cm,
                    "width_cm": width_cm,
                    "height_cm": height_cm,
                },
            },
            merchant_packaged_weight_raw=weight_raw,
            merchant_packaged_dimensions_raw=dimensions_raw,
            last_refreshed_at=datetime.now(UTC),
        )

    @staticmethod
    def _enrich_product_from_catalog(
        *,
        product: dict[str, Any],
        fallback_title: str | None,
    ) -> dict[str, Any] | None:
        payload = catalog_client.fetch_product_detail(product["external_product_id"])
        if payload is None:
            return None

        variants = payload.get("variants") if isinstance(payload.get("variants"), list) else []
        variant = variants[0] if variants and isinstance(variants[0], dict) else {}
        attributes = variant.get("attributes") if isinstance(variant.get("attributes"), dict) else {}

        def normalize_key(value: Any) -> str:
            return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())

        def scalar_value(value: Any) -> str | None:
            if value in {None, ""}:
                return None
            if isinstance(value, (int, float)):
                return str(value)
            if isinstance(value, str):
                return value.strip() or None
            if isinstance(value, dict):
                unit = scalar_value(
                    value.get("unit")
                    or value.get("units")
                    or value.get("uom")
                    or value.get("unit_of_measure")
                    or value.get("unitOfMeasure")
                )
                for key in ("value", "display_value", "displayValue", "name", "label", "text"):
                    candidate = scalar_value(value.get(key))
                    if candidate:
                        if unit and not re.search(r"[a-zA-Z]", candidate):
                            return f"{candidate} {unit}"
                        return candidate
            return None

        def number_text(value: Any) -> str | None:
            text = scalar_value(value)
            if not text:
                return None
            match = re.search(r"([0-9]+(?:[.,][0-9]+)?)", text)
            return match.group(1).replace(",", ".") if match else None

        def normalize_weight_raw(value: Any, source_key: str = "") -> str | None:
            text = scalar_value(value)
            if not text:
                return None
            lowered = text.lower()
            if re.search(r"\b(kg|g|gram|grams|kilogram|kilograms)\b", lowered):
                return text
            numeric_text = number_text(text)
            if not numeric_text:
                return text
            try:
                numeric = float(numeric_text)
            except ValueError:
                return text
            key = normalize_key(source_key)
            unit = "g" if ("gram" in key or key.endswith("g") or numeric > 40) else "kg"
            return f"{numeric_text} {unit}"

        def dimension_part_cm(value: Any, source_key: str = "") -> str | None:
            numeric_text = number_text(value)
            if not numeric_text:
                return None
            try:
                numeric = float(numeric_text)
            except ValueError:
                return None
            text = str(value or "").lower()
            key = normalize_key(source_key)
            if "mm" in text or key.endswith("mm"):
                numeric = numeric / 10
            return f"{numeric:g}"

        def find_catalog_value(value: Any, keys: set[str], depth: int = 0) -> str | None:
            if value is None or depth > 7:
                return None
            if isinstance(value, dict):
                label = normalize_key(
                    value.get("key")
                    or value.get("name")
                    or value.get("label")
                    or value.get("display_name")
                    or value.get("displayName")
                )
                if label in keys:
                    direct = scalar_value(value.get("value"))
                    if direct:
                        return direct
                for key, nested in value.items():
                    if normalize_key(key) in keys:
                        direct = scalar_value(nested)
                        if direct:
                            return direct
                    found = find_catalog_value(nested, keys, depth + 1)
                    if found:
                        return found
            if isinstance(value, list):
                for nested in value[:80]:
                    found = find_catalog_value(nested, keys, depth + 1)
                    if found:
                        return found
            return None

        def first_catalog_value(*keys: str) -> str | None:
            normalized = {normalize_key(key) for key in keys}
            for source in (attributes, variant, payload):
                found = find_catalog_value(source, normalized)
                if found:
                    return found
            return None

        def first_weight_value(*keys: str) -> str | None:
            for key in keys:
                found = first_catalog_value(key)
                normalized = normalize_weight_raw(found, key)
                if normalized:
                    return normalized
            return None

        def first_dimension_part(*keys: str) -> str | None:
            for key in keys:
                found = first_catalog_value(key)
                normalized = dimension_part_cm(found, key)
                if normalized:
                    return normalized
            return None

        def dimensions_from_parts() -> str | None:
            length = first_dimension_part(
                "length_cm",
                "package_length_cm",
                "packaged_length_cm",
                "merchant_packaged_length_cm",
                "merchant_package_length_cm",
                "length",
                "package_length",
                "packaged_length",
                "merchant_packaged_length",
                "merchant_package_length",
                "length_mm",
                "package_length_mm",
                "merchant_packaged_length_mm",
            )
            width = first_dimension_part(
                "width_cm",
                "package_width_cm",
                "packaged_width_cm",
                "merchant_packaged_width_cm",
                "merchant_package_width_cm",
                "width",
                "package_width",
                "packaged_width",
                "merchant_packaged_width",
                "merchant_package_width",
                "width_mm",
                "package_width_mm",
                "merchant_packaged_width_mm",
            )
            height = first_dimension_part(
                "height_cm",
                "package_height_cm",
                "packaged_height_cm",
                "merchant_packaged_height_cm",
                "merchant_package_height_cm",
                "height",
                "depth",
                "package_height",
                "packaged_height",
                "package_depth",
                "merchant_packaged_height",
                "merchant_package_height",
                "height_mm",
                "package_height_mm",
                "merchant_packaged_height_mm",
            )
            if all(part not in {None, ""} for part in (length, width, height)):
                return f"{length} x {width} x {height} cm"
            return None

        def attr_value(key: str) -> str | None:
            candidate = attributes.get(key)
            value = scalar_value(candidate)
            if value:
                return value
            return first_catalog_value(key)

        title = (
            (variant.get("title") if isinstance(variant, dict) else None)
            or payload.get("title")
            or product.get("title")
            or fallback_title
            or f"PLID{product['external_product_id']}"
        )
        weight_raw = (
            first_weight_value(
                "merchant_packaged_weight",
                "merchant_packaged_weight_grams",
                "merchant_package_weight",
                "merchant_package_weight_grams",
                "packaged_weight",
                "package_weight",
                "packaged_weight_grams",
                "package_weight_grams",
                "weight_grams",
                "weight_in_grams",
                "weightInGrams",
                "package_weight_g",
                "packaged_weight_g",
                "merchant_packaged_weight_g",
                "shipping_weight",
                "shipping_weight_grams",
                "mass",
                "weight",
            )
        )
        dimensions_raw = (
            attr_value("merchant_packaged_dimensions")
            or first_catalog_value(
                "merchant_packaged_dimensions_cm",
                "merchant_package_dimensions",
                "merchant_package_dimensions_cm",
                "packaged_dimensions",
                "package_dimensions",
                "package_dimensions_cm",
                "package_dimensions_mm",
                "packaging_dimensions",
                "shipping_dimensions",
                "shipping_dimensions_cm",
                "dimensions",
                "dimension",
            )
            or dimensions_from_parts()
        )
        cbs_weight_raw = first_weight_value(
            "cbs_package_weight",
            "cbs_package_weight_grams",
            "cbs_weight",
            "cbs_weight_grams",
        )
        cbs_dimensions_raw = (
            attr_value("cbs_package_dimensions")
            or first_catalog_value("cbs_package_dimensions_cm", "cbs_dimensions")
        )
        consolidated_dimensions_raw = (
            attr_value("consolidated_packaged_dimensions")
            or first_catalog_value("consolidated_packaged_dimensions_cm", "consolidated_dimensions")
        )
        fact_status = (
            "complete"
            if (weight_raw or cbs_weight_raw)
            and (dimensions_raw or cbs_dimensions_raw or consolidated_dimensions_raw)
            else "partial"
        )

        return app_state.upsert_library_product(
            platform=product["platform"],
            external_product_id=product["external_product_id"],
            title=str(title),
            fact_status=fact_status,
            raw_payload={
                "source": "takealot_catalog",
                "payload": payload,
            },
            merchant_packaged_weight_raw=weight_raw,
            merchant_packaged_dimensions_raw=dimensions_raw,
            cbs_package_weight_raw=cbs_weight_raw,
            cbs_package_dimensions_raw=cbs_dimensions_raw,
            consolidated_packaged_dimensions_raw=consolidated_dimensions_raw,
            last_refreshed_at=datetime.now(UTC),
        )

    @staticmethod
    def _clean_category_part(value: Any) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        text = re.sub(r"\s+", " ", text)
        if text.lower() in {"takealot", "departments", "all departments"}:
            return None
        return text

    @staticmethod
    def _coerce_category_path(value: Any, depth: int = 0) -> list[str]:
        if value is None or depth > 5:
            return []
        if isinstance(value, str):
            parts = re.split(r"\s*(?:>|/)\s*", value)
            return [
                part
                for part in (ExtensionService._clean_category_part(part) for part in parts)
                if part
            ]
        if isinstance(value, list):
            path: list[str] = []
            for item in value:
                path.extend(ExtensionService._coerce_category_path(item, depth + 1))
            return path
        if isinstance(value, dict):
            for key in (
                "category_path",
                "categoryPath",
                "breadcrumbs",
                "breadCrumbs",
                "categories",
                "category",
                "department",
                "taxonomy",
                "path",
            ):
                if key in value:
                    path = ExtensionService._coerce_category_path(value.get(key), depth + 1)
                    if path:
                        return path
            for key in ("name", "label", "title", "display_name", "displayName", "categoryName"):
                part = ExtensionService._clean_category_part(value.get(key))
                if part:
                    return [part]
        return []

    @staticmethod
    def _extract_category_path(product: dict[str, Any] | None) -> list[str]:
        if product is None:
            return []

        raw_payload = product.get("raw_payload") if isinstance(product.get("raw_payload"), dict) else {}
        payload = raw_payload.get("payload") if isinstance(raw_payload.get("payload"), dict) else None
        for candidate in (product, raw_payload, payload):
            path = ExtensionService._coerce_category_path(candidate)
            if path:
                return path

        def scan(value: Any, depth: int = 0) -> list[str]:
            if value is None or depth > 4:
                return []
            direct = ExtensionService._coerce_category_path(value, depth)
            if direct:
                return direct
            if isinstance(value, dict):
                for nested in value.values():
                    path = scan(nested, depth + 1)
                    if path:
                        return path
            if isinstance(value, list):
                for nested in value[:20]:
                    path = scan(nested, depth + 1)
                    if path:
                        return path
            return []

        return scan(raw_payload)

    @staticmethod
    def _format_category_label(path: list[str] | None) -> str | None:
        cleaned = [part for part in (ExtensionService._clean_category_part(part) for part in (path or [])) if part]
        return " > ".join(cleaned) if cleaned else None

    @staticmethod
    def _normalize_match_text(value: str | None) -> str:
        text = str(value or "").lower().replace("&", " and ")
        return re.sub(r"[^a-z0-9]+", " ", text).strip()

    @staticmethod
    def _phrase_variants(phrase: str) -> set[str]:
        normalized = ExtensionService._normalize_match_text(phrase)
        if not normalized:
            return set()
        variants = {normalized}
        parts = normalized.split()
        if parts:
            last = parts[-1]
            if last.endswith("s") and len(last) > 3:
                variants.add(" ".join([*parts[:-1], last[:-1]]))
            elif len(last) > 2:
                variants.add(" ".join([*parts[:-1], f"{last}s"]))
        return variants

    @staticmethod
    def _contains_phrase(normalized_haystack: str, phrase: str) -> bool:
        wrapped = f" {normalized_haystack} "
        return any(f" {variant} " in wrapped for variant in ExtensionService._phrase_variants(phrase))

    @staticmethod
    def _meaningful_token_overlap(left: str, right: str) -> int:
        stopwords = {"and", "the", "for", "with", "other", "accessories", "accessory"}
        left_tokens = {
            token
            for token in ExtensionService._normalize_match_text(left).split()
            if len(token) > 3 and token not in stopwords
        }
        right_tokens = {
            token
            for token in ExtensionService._normalize_match_text(right).split()
            if len(token) > 3 and token not in stopwords
        }
        return len(left_tokens & right_tokens)

    @staticmethod
    def _split_success_fee_condition(subcategory: str, sale_price_zar: float | None) -> tuple[str, bool]:
        match = re.search(r"\s*\(if price ([^)]+)\)\s*$", subcategory, flags=re.IGNORECASE)
        if not match:
            return subcategory, True
        base_subcategory = subcategory[: match.start()].strip()
        if sale_price_zar is None:
            return base_subcategory, False
        condition = match.group(1).lower().replace(",", "")
        numbers = [float(number) for number in re.findall(r"\d+(?:\.\d+)?", condition)]
        if not numbers:
            return base_subcategory, False
        price = float(sale_price_zar)
        if ">" in condition and "<=" in condition and len(numbers) >= 2:
            return base_subcategory, price > numbers[0] and price <= numbers[1]
        if "<=" in condition:
            return base_subcategory, price <= numbers[-1]
        if ">" in condition:
            return base_subcategory, price > numbers[0]
        return base_subcategory, False

    @staticmethod
    def _is_generic_success_fee_subcategory(subcategory: str) -> bool:
        normalized = ExtensionService._normalize_match_text(subcategory)
        return normalized in {
            "other",
            "accessories",
            "accessory",
            "parts and accessories",
            "equipment and accessories",
            "consumables",
        }

    @staticmethod
    def _select_success_fee(
        *,
        category_path: list[str],
        title: str | None,
        sale_price_zar: float | None,
    ) -> tuple[str | None, float]:
        category_text = " ".join(category_path)
        category_norm = ExtensionService._normalize_match_text(category_text)
        last_category_norm = ExtensionService._normalize_match_text(category_path[-1] if category_path else "")
        title_norm = ExtensionService._normalize_match_text(title)
        best_score = 0.0
        best_label: str | None = None
        best_rate = DEFAULT_SUCCESS_FEE_RATE

        for section, subcategory, rate in SUCCESS_FEE_RULES:
            base_subcategory, condition_matches = ExtensionService._split_success_fee_condition(
                subcategory,
                sale_price_zar,
            )
            if not condition_matches:
                continue

            section_in_category = ExtensionService._contains_phrase(category_norm, section)
            subcategory_in_category = ExtensionService._contains_phrase(category_norm, base_subcategory)
            subcategory_in_last_category = ExtensionService._contains_phrase(last_category_norm, base_subcategory)
            subcategory_in_title = ExtensionService._contains_phrase(title_norm, base_subcategory)
            section_token_overlap = ExtensionService._meaningful_token_overlap(section, category_text)
            generic = ExtensionService._is_generic_success_fee_subcategory(base_subcategory)
            score = 0.0

            if section_in_category and subcategory_in_category:
                score = 620.0
            elif subcategory_in_category and not generic and section_token_overlap > 0:
                score = 520.0
            elif section_in_category and ExtensionService._normalize_match_text(base_subcategory) == "other":
                score = 320.0
            elif subcategory_in_title and not generic:
                score = 360.0 if section_token_overlap > 0 else 260.0
            elif section_in_category and not generic:
                score = 160.0

            if score <= 0:
                continue

            if subcategory_in_last_category:
                score += 90.0
            score += len(ExtensionService._normalize_match_text(base_subcategory)) / 100.0
            if score > best_score:
                best_score = score
                best_label = f"{section} > {base_subcategory}"
                best_rate = float(rate)

        return best_label, best_rate

    @staticmethod
    def _select_fulfillment_fee(
        *,
        category_path: list[str],
        title: str | None,
        actual_weight_kg: float | None,
        length_cm: float | None,
        width_cm: float | None,
        height_cm: float | None,
    ) -> tuple[float | None, float | None, str | None, str | None]:
        if None in (actual_weight_kg, length_cm, width_cm, height_cm):
            return (None, None, None, None)

        volume_cm3 = float(length_cm) * float(width_cm) * float(height_cm)
        volumetric_weight_kg = volume_cm3 / 6000
        chargeable_weight_kg = max(float(actual_weight_kg), volumetric_weight_kg)

        if chargeable_weight_kg <= 7:
            weight_tier = "light"
        elif chargeable_weight_kg <= 25:
            weight_tier = "heavy"
        elif chargeable_weight_kg < 40:
            weight_tier = "heavy_plus"
        else:
            weight_tier = "very_heavy"

        if volume_cm3 > 545_000:
            size_tier = "extra_bulky"
        elif volume_cm3 > 200_000:
            size_tier = "bulky"
        elif volume_cm3 > 130_000:
            size_tier = "oversize"
        elif volume_cm3 > 35_000:
            size_tier = "large"
        else:
            category_text = " ".join(category_path)
            category_norm = ExtensionService._normalize_match_text(category_text)
            size_tier = "other_standard"
            for keywords, candidate_tier in FULFILLMENT_CATEGORY_GROUPS:
                if any(ExtensionService._contains_phrase(category_norm, keyword) for keyword in keywords):
                    size_tier = candidate_tier
                    break

        shipping_fee = FULFILLMENT_FEE_TABLE[size_tier][weight_tier]
        return (shipping_fee, round(shipping_fee * SUCCESS_FEE_VAT_RATE, 4), size_tier, weight_tier)

    @staticmethod
    def _to_preview_product(
        product: dict[str, Any],
        fallback_category_path: list[str] | None = None,
    ) -> ProfitPreviewProduct:
        actual_weight_kg = ExtensionService._parse_weight_kg(
            product.get("merchant_packaged_weight_raw")
            or product.get("cbs_package_weight_raw")
        )
        length_cm, width_cm, height_cm = ExtensionService._parse_dimensions_cm(
            product.get("merchant_packaged_dimensions_raw")
            or product.get("cbs_package_dimensions_raw")
            or product.get("consolidated_packaged_dimensions_raw")
        )
        category_path = fallback_category_path or ExtensionService._extract_category_path(product)
        return ProfitPreviewProduct(
            product_id=product["id"],
            platform=product["platform"],
            plid=product["external_product_id"],
            title=product["title"],
            fact_status=product["fact_status"],
            merchant_packaged_weight_raw=product.get("merchant_packaged_weight_raw"),
            merchant_packaged_dimensions_raw=product.get("merchant_packaged_dimensions_raw"),
            cbs_package_weight_raw=product.get("cbs_package_weight_raw"),
            cbs_package_dimensions_raw=product.get("cbs_package_dimensions_raw"),
            consolidated_packaged_dimensions_raw=product.get("consolidated_packaged_dimensions_raw"),
            actual_weight_kg=actual_weight_kg,
            length_cm=length_cm,
            width_cm=width_cm,
            height_cm=height_cm,
            category_path=category_path,
            category_label=ExtensionService._format_category_label(category_path),
            last_refreshed_at=product.get("last_refreshed_at"),
        )

    @staticmethod
    def _to_preview_guardrail(guardrail: dict[str, Any] | None) -> ProfitPreviewGuardrail:
        if guardrail is None:
            return ProfitPreviewGuardrail(
                guardrail_id=None,
                protected_floor_price=None,
                status="not_set",
                linked_bidding_rule_id=None,
                linked_listing_id=None,
                autobid_sync_status=None,
            )
        return ProfitPreviewGuardrail(
            guardrail_id=guardrail["id"],
            protected_floor_price=guardrail["protected_floor_price"],
            status=guardrail["status"],
            linked_bidding_rule_id=guardrail.get("linked_bidding_rule_id"),
            linked_listing_id=guardrail.get("linked_listing_id"),
            autobid_sync_status=guardrail.get("autobid_sync_status"),
        )

    @staticmethod
    def _number_setting(setting_key: str, default: float) -> float:
        setting = app_state.get_system_setting(setting_key)
        if setting is None or setting.get("value_type") != "number":
            return default
        try:
            return float(setting.get("value"))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _text_setting(setting_key: str, default: str) -> str:
        setting = app_state.get_system_setting(setting_key)
        if setting is None or setting.get("value_type") != "string":
            return default
        value = setting.get("value")
        return str(value) if value is not None else default

    def _build_pricing_preview(
        self,
        payload: ProfitPreviewRequest,
        guardrail: dict[str, Any] | None,
        product: dict[str, Any] | None = None,
        listing: dict[str, Any] | None = None,
    ) -> ProfitPreviewPricing:
        formula_version = self._text_setting(
            "extension_pricing_formula_version",
            "takealot_success_fee_2025_tail_fee_2026_sale_margin_v3",
        )
        cny_to_zar_rate = self._number_setting("extension_pricing_cny_to_zar_rate", 2.49)
        withdraw_fx_rate = self._number_setting("extension_pricing_withdraw_fx_rate", 0.04965)
        purchase_vat_rate = self._number_setting("extension_pricing_purchase_vat_rate", 0.747)
        po_fee_cny = self._number_setting("extension_pricing_po_fee_cny", 25)
        default_air_freight_cny_per_kg = self._number_setting(
            "extension_pricing_default_air_freight_cny_per_kg",
            100,
        )

        actual_weight_kg = payload.actual_weight_kg
        length_cm = payload.length_cm
        width_cm = payload.width_cm
        height_cm = payload.height_cm
        if product is not None:
            if actual_weight_kg is None:
                actual_weight_kg = self._parse_weight_kg(
                    product.get("merchant_packaged_weight_raw")
                    or product.get("cbs_package_weight_raw")
                )
            parsed_length_cm, parsed_width_cm, parsed_height_cm = self._parse_dimensions_cm(
                product.get("merchant_packaged_dimensions_raw")
                or product.get("cbs_package_dimensions_raw")
                or product.get("consolidated_packaged_dimensions_raw")
            )
            length_cm = length_cm if length_cm is not None else parsed_length_cm
            width_cm = width_cm if width_cm is not None else parsed_width_cm
            height_cm = height_cm if height_cm is not None else parsed_height_cm

        air_freight_unit_cny_per_kg = (
            payload.air_freight_unit_cny_per_kg
            if payload.air_freight_unit_cny_per_kg is not None
            else default_air_freight_cny_per_kg
        )
        purchase_price_cny = payload.purchase_price_cny
        sale_price_zar = payload.sale_price_zar
        best_price_zar = self._extract_best_price_zar(product)
        if sale_price_zar is None:
            if best_price_zar is not None:
                sale_price_zar = max(float(best_price_zar) - 1, 0)
            elif listing is not None and listing.get("platform_price") is not None:
                sale_price_zar = max(float(listing["platform_price"]) - 1, 0)

        category_path = payload.category_path or self._extract_category_path(product)
        success_fee_category, success_fee_rate = self._select_success_fee(
            category_path=category_path,
            title=payload.title or (product.get("title") if product else None),
            sale_price_zar=sale_price_zar,
        )
        payout_rate = max(1 - (success_fee_rate * (1 + SUCCESS_FEE_VAT_RATE)), 0)
        (
            tail_shipping_fee_zar,
            tail_vat_fee_zar,
            fulfillment_size_tier,
            fulfillment_weight_tier,
        ) = self._select_fulfillment_fee(
            category_path=category_path,
            title=payload.title or (product.get("title") if product else None),
            actual_weight_kg=actual_weight_kg,
            length_cm=length_cm,
            width_cm=width_cm,
            height_cm=height_cm,
        )

        if None in (purchase_price_cny, sale_price_zar, actual_weight_kg, length_cm, width_cm, height_cm):
            return ProfitPreviewPricing(
                formula_version=formula_version,
                best_price_zar=best_price_zar,
                air_freight_unit_cny_per_kg=air_freight_unit_cny_per_kg,
                purchase_price_cny=purchase_price_cny,
                sale_price_zar=sale_price_zar,
                actual_weight_kg=actual_weight_kg,
                length_cm=length_cm,
                width_cm=width_cm,
                height_cm=height_cm,
                volume_m3=None,
                volumetric_weight_kg=None,
                chargeable_weight_kg=None,
                cny_to_zar_rate=cny_to_zar_rate,
                payout_rate=payout_rate,
                withdraw_fx_rate=withdraw_fx_rate,
                purchase_vat_rate=purchase_vat_rate,
                po_fee_cny=po_fee_cny,
                po_fee_zar=None,
                success_fee_category=success_fee_category,
                success_fee_rate=success_fee_rate,
                success_fee_vat_rate=SUCCESS_FEE_VAT_RATE,
                success_fee_amount_zar=None,
                tail_shipping_fee_zar=tail_shipping_fee_zar,
                tail_vat_fee_zar=tail_vat_fee_zar,
                fulfillment_size_tier=fulfillment_size_tier,
                fulfillment_weight_tier=fulfillment_weight_tier,
                purchase_converted_cost_zar=None,
                payout_amount_zar=None,
                withdraw_fx_loss_zar=None,
                airfreight_cost_zar=None,
                purchase_tax_cost_zar=None,
                total_main_cost_zar=None,
                profit_zar=None,
                profit_cny=None,
                margin_rate=None,
                recommended_price_10_zar=None,
                recommended_price_30_zar=None,
                recommended_protected_floor_price_zar=guardrail["protected_floor_price"] if guardrail else None,
                break_even_price_zar=guardrail["protected_floor_price"] if guardrail else None,
                note="请输入销售价、采购价，且商品需要有长宽高和重量，才能返回空运利润测算。",
            )

        volume_m3 = (float(length_cm) * float(width_cm) * float(height_cm)) / 1_000_000
        volumetric_weight_kg = (float(length_cm) * float(width_cm) * float(height_cm)) / 6000
        chargeable_weight_kg = max(float(actual_weight_kg), volumetric_weight_kg)
        purchase_converted_cost_zar = float(purchase_price_cny) * cny_to_zar_rate
        po_fee_zar = float(po_fee_cny) * cny_to_zar_rate
        success_fee_amount_zar = float(sale_price_zar) * success_fee_rate * (1 + SUCCESS_FEE_VAT_RATE)
        payout_amount_zar = float(sale_price_zar) - success_fee_amount_zar
        withdraw_fx_loss_zar = float(sale_price_zar) * withdraw_fx_rate
        variable_fee_rate = (success_fee_rate * (1 + SUCCESS_FEE_VAT_RATE)) + withdraw_fx_rate
        net_revenue_rate = max(1 - variable_fee_rate, 0)
        net_revenue_zar = float(sale_price_zar) * net_revenue_rate
        airfreight_cost_zar = chargeable_weight_kg * float(air_freight_unit_cny_per_kg) * cny_to_zar_rate
        purchase_tax_cost_zar = float(purchase_price_cny) * purchase_vat_rate
        total_main_cost_zar = (
            purchase_converted_cost_zar
            + purchase_tax_cost_zar
            + po_fee_zar
            + airfreight_cost_zar
            + float(tail_shipping_fee_zar or 0)
            + float(tail_vat_fee_zar or 0)
        )
        profit_zar = net_revenue_zar - total_main_cost_zar
        profit_cny = profit_zar / cny_to_zar_rate if cny_to_zar_rate else None
        margin_rate = profit_zar / float(sale_price_zar) if float(sale_price_zar) > 0 else None
        recommended_price_10_zar = (
            total_main_cost_zar / (net_revenue_rate - 0.10)
            if net_revenue_rate > 0.10
            else None
        )
        recommended_price_30_zar = (
            total_main_cost_zar / (net_revenue_rate - 0.30)
            if net_revenue_rate > 0.30
            else None
        )
        if recommended_price_10_zar is not None:
            recommended_price_10_zar = ceil(float(recommended_price_10_zar))
        if recommended_price_30_zar is not None:
            recommended_price_30_zar = ceil(float(recommended_price_30_zar))
        break_even_price_zar = total_main_cost_zar / net_revenue_rate if net_revenue_rate > 0 else None
        if break_even_price_zar is not None:
            break_even_price_zar = ceil(float(break_even_price_zar))
        if guardrail and guardrail.get("protected_floor_price") is not None and break_even_price_zar is not None:
            break_even_price_zar = max(ceil(float(guardrail["protected_floor_price"])), float(break_even_price_zar))

        return ProfitPreviewPricing(
            formula_version=formula_version,
            best_price_zar=best_price_zar,
            air_freight_unit_cny_per_kg=float(air_freight_unit_cny_per_kg),
            purchase_price_cny=float(purchase_price_cny),
            sale_price_zar=float(sale_price_zar),
            actual_weight_kg=float(actual_weight_kg),
            length_cm=float(length_cm),
            width_cm=float(width_cm),
            height_cm=float(height_cm),
            volume_m3=round(volume_m3, 6),
            volumetric_weight_kg=round(volumetric_weight_kg, 4),
            chargeable_weight_kg=round(chargeable_weight_kg, 4),
            cny_to_zar_rate=cny_to_zar_rate,
            payout_rate=payout_rate,
            withdraw_fx_rate=withdraw_fx_rate,
            purchase_vat_rate=purchase_vat_rate,
            po_fee_cny=round(float(po_fee_cny), 4),
            po_fee_zar=round(po_fee_zar, 4),
            success_fee_category=success_fee_category,
            success_fee_rate=success_fee_rate,
            success_fee_vat_rate=SUCCESS_FEE_VAT_RATE,
            success_fee_amount_zar=round(success_fee_amount_zar, 4),
            tail_shipping_fee_zar=tail_shipping_fee_zar,
            tail_vat_fee_zar=tail_vat_fee_zar,
            fulfillment_size_tier=fulfillment_size_tier,
            fulfillment_weight_tier=fulfillment_weight_tier,
            purchase_converted_cost_zar=round(purchase_converted_cost_zar, 4),
            payout_amount_zar=round(payout_amount_zar, 4),
            withdraw_fx_loss_zar=round(withdraw_fx_loss_zar, 4),
            airfreight_cost_zar=round(airfreight_cost_zar, 4),
            purchase_tax_cost_zar=round(purchase_tax_cost_zar, 4),
            total_main_cost_zar=round(total_main_cost_zar, 4),
            profit_zar=round(profit_zar, 4),
            profit_cny=round(float(profit_cny), 4) if profit_cny is not None else None,
            margin_rate=round(float(margin_rate), 6) if margin_rate is not None else None,
            recommended_price_10_zar=round(float(recommended_price_10_zar), 4) if recommended_price_10_zar is not None else None,
            recommended_price_30_zar=round(float(recommended_price_30_zar), 4) if recommended_price_30_zar is not None else None,
            recommended_protected_floor_price_zar=round(float(recommended_price_10_zar), 4) if recommended_price_10_zar is not None else None,
            break_even_price_zar=round(float(break_even_price_zar), 4) if break_even_price_zar is not None else None,
            note="空运利润口径 v3：利润率按售价计算；佣金按 2025 Success Fee 类目表并计 VAT；尾程按尺寸/重量档自动测算；总成本含固定 PO 费 25 RMB。",
        )

    @staticmethod
    def _extract_best_price_zar(product: dict[str, Any] | None) -> float | None:
        if product is None:
            return None
        raw_payload = product.get("raw_payload") or {}
        payload = raw_payload.get("payload") if isinstance(raw_payload.get("payload"), dict) else raw_payload.get("payload")
        if not isinstance(payload, dict):
            return None
        variants = payload.get("variants") if isinstance(payload.get("variants"), list) else []
        first_variant = variants[0] if variants and isinstance(variants[0], dict) else {}
        best_price = first_variant.get("bestPrice") or payload.get("bestPrice")
        try:
            return float(best_price) if best_price is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_barcode(value: Any) -> str | None:
        if value is None or value == "":
            return None
        text = re.sub(r"\s+", "", str(value).strip())
        text = re.sub(r"[^0-9A-Za-z-]", "", text)
        return text if len(text) >= 6 else None

    @staticmethod
    def _extract_gtin_from_product(product: dict[str, Any] | None) -> str | None:
        if product is None:
            return None

        target_keys = {
            "gtin",
            "gtin13",
            "globaltradeitemnumber",
            "barcode",
            "ean",
            "ean13",
            "upc",
            "isbn",
            "productbarcode",
            "productgtin",
            "productean",
            "variantgtin",
            "variantbarcode",
        }

        def normalize_key(value: Any) -> str:
            return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())

        def scalar(value: Any) -> Any:
            if value is None or value == "":
                return None
            if isinstance(value, (str, int, float)):
                return value
            if isinstance(value, dict):
                for key in ("value", "display_value", "displayValue", "name", "label", "text"):
                    candidate = scalar(value.get(key))
                    if candidate:
                        return candidate
            return None

        def scan(value: Any, depth: int = 0) -> str | None:
            if value is None or depth > 7:
                return None
            if isinstance(value, list):
                for item in value[:80]:
                    found = scan(item, depth + 1)
                    if found:
                        return found
                return None
            if isinstance(value, dict):
                label = normalize_key(
                    value.get("key")
                    or value.get("name")
                    or value.get("label")
                    or value.get("display_name")
                    or value.get("displayName")
                )
                if label in target_keys:
                    normalized = ExtensionService._normalize_barcode(scalar(value.get("value")))
                    if normalized:
                        return normalized
                for key, nested in value.items():
                    if normalize_key(key) in target_keys:
                        normalized = ExtensionService._normalize_barcode(scalar(nested))
                        if normalized:
                            return normalized
                    found = scan(nested, depth + 1)
                    if found:
                        return found
            return None

        raw_payload = product.get("raw_payload") if isinstance(product.get("raw_payload"), dict) else {}
        return scan(product) or scan(raw_payload)

    @staticmethod
    def _parse_weight_kg(raw: str | None) -> float | None:
        if not raw:
            return None
        text = str(raw).strip().lower()
        match = re.search(r"([0-9]+(?:[.,][0-9]+)?)\s*(kg|kgs|kilogram|kilograms|g|gram|grams)\b", text)
        if not match:
            return None
        value = float(match.group(1).replace(",", "."))
        unit = match.group(2)
        return value if unit.startswith("kg") or unit.startswith("kilogram") else value / 1000

    @staticmethod
    def _parse_dimensions_cm(raw: str | None) -> tuple[float | None, float | None, float | None]:
        if not raw:
            return (None, None, None)
        text = str(raw).strip().lower()
        matches = re.findall(r"([0-9]+(?:[.,][0-9]+)?)", text)
        if len(matches) < 3:
            return (None, None, None)
        length_cm = float(matches[0].replace(",", "."))
        width_cm = float(matches[1].replace(",", "."))
        height_cm = float(matches[2].replace(",", "."))
        if "mm" in text:
            return (length_cm / 10, width_cm / 10, height_cm / 10)
        return (length_cm, width_cm, height_cm)

    @staticmethod
    def _to_protected_floor_response(
        guardrail: dict[str, Any],
        plid: str,
    ) -> ProtectedFloorResponse:
        return ProtectedFloorResponse(
            guardrail_id=guardrail["id"],
            store_id=guardrail["store_id"],
            product_id=guardrail["product_id"],
            plid=plid,
            protected_floor_price=guardrail["protected_floor_price"],
            status=guardrail["status"],
            autobid_sync_status=guardrail["autobid_sync_status"],
            linked_bidding_rule_id=guardrail.get("linked_bidding_rule_id"),
            linked_listing_id=guardrail.get("linked_listing_id"),
            updated_at=guardrail["updated_at"],
        )
