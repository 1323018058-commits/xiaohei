from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Callable
from uuid import uuid4

from fastapi import HTTPException, status

from src.modules.common.dev_state import app_state
from src.modules.common.tenant_scope import require_tenant_access
from src.modules.store.adapters import AdapterCredentials, BaseAdapter, TakealotAdapter
from src.platform.settings.base import settings

from .schemas import ListingJobListResponse, ListingJobResponse


PROCESS_LISTING_JOB_TASK_TYPE = "PROCESS_LISTING_JOB"
LISTING_WORKER_SOURCE_ID = "listing-worker"
ListingAdapterFactory = Callable[[dict[str, Any], AdapterCredentials], BaseAdapter]


class ListingService:
    def list_jobs(
        self,
        actor: dict[str, Any],
        *,
        store_id: str | None = None,
        status_filter: str | None = None,
    ) -> ListingJobListResponse:
        jobs = app_state.list_listing_jobs(
            None if actor["role"] == "super_admin" else actor["tenant_id"],
            store_id=store_id,
            status_filter=status_filter,
        )
        return ListingJobListResponse(jobs=[self._to_job_response(job) for job in jobs])

    def get_job(self, job_id: str, actor: dict[str, Any]) -> ListingJobResponse:
        job = self._require_job(job_id, actor)
        return self._to_job_response(job)

    def refresh_job_status(
        self,
        job_id: str,
        actor: dict[str, Any],
        *,
        adapter_factory: ListingAdapterFactory | None = None,
    ) -> ListingJobResponse:
        job = self._require_job(job_id, actor)
        store = app_state.get_store(job["store_id"])
        if store is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store not found")
        product = app_state.get_library_product_by_id(job["product_id"]) if job.get("product_id") else None
        if product is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Library product not found")
        credentials_payload = app_state.get_store_credentials(store["id"])
        if not credentials_payload:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Store credentials unavailable")
        credentials = AdapterCredentials(
            platform=store["platform"],
            api_key=credentials_payload.get("api_key", ""),
            api_secret=credentials_payload.get("api_secret", ""),
        )
        adapter = self._build_adapter(store=store, credentials=credentials, adapter_factory=adapter_factory)
        barcode = self._extract_barcode(job, product)
        if not barcode:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Listing job has no barcode/GTIN")
        task = app_state.get_task(job["processing_task_id"]) if job.get("processing_task_id") else None
        batch_status_payload = None
        raw_payload = job.get("raw_payload") or {}
        batch_id = (
            raw_payload.get("batch_id")
            or (raw_payload.get("offer_payload") or {}).get("batch_id")
            or (raw_payload.get("batch_status_payload") or {}).get("batch_id")
        )
        if batch_id:
            batch_status_payload = adapter.get_offer_batch_status(int(batch_id))

        offer_payload = adapter.get_offer_by_barcode(barcode)
        if offer_payload is None:
            if batch_status_payload is not None:
                app_state.update_listing_job(
                    job["id"],
                    status="processing",
                    stage="processing",
                    note=f"Batch {batch_id} status {batch_status_payload.get('status')}; waiting for offer visibility",
                    raw_payload={**raw_payload, "batch_status_payload": batch_status_payload},
                )
            return self._to_job_response(app_state.get_listing_job(job["id"]) or job)

        listing = app_state.upsert_store_listing(
            store_id=store["id"],
            external_listing_id=str(offer_payload.get("offer_id") or offer_payload.get("id") or product["external_product_id"]),
            platform_product_id=product["external_product_id"],
            sku=str(offer_payload.get("sku") or self._build_offer_sku(store, product)),
            title=str(offer_payload.get("title") or product["title"]),
            platform_price=float(offer_payload.get("selling_price") or 0),
            stock_quantity=self._extract_quantity(job),
            currency="ZAR",
            sync_status="synced",
            raw_payload=offer_payload,
        )
        diagnosis = self._diagnose_offer_payload(offer_payload)
        updated_job = app_state.update_listing_job(
            job["id"],
            status="manual_intervention" if diagnosis["action_required"] else "ready_to_submit",
            stage="waiting_manual" if diagnosis["action_required"] else "prepared",
            note=diagnosis["summary"],
            raw_payload={
                **raw_payload,
                "offer_payload": offer_payload,
                "batch_status_payload": batch_status_payload,
                "listing_id": listing["id"],
                "offer_diagnosis": diagnosis,
            },
        )
        if task is not None:
            app_state.update_task(
                task["id"],
                status="manual_intervention" if diagnosis["action_required"] else "succeeded",
                stage="waiting_manual" if diagnosis["action_required"] else "prepared",
                progress_percent=100,
                finished_at=datetime.now(UTC),
                last_heartbeat_at=datetime.now(UTC),
                lease_owner=None,
                lease_token=None,
                lease_expires_at=None,
                error_code=diagnosis["primary_code"] if diagnosis["action_required"] else None,
                error_msg=diagnosis["summary"] if diagnosis["action_required"] else None,
                error_details={
                    "job_id": job["id"],
                    "listing_id": listing["id"],
                    "offer_status": diagnosis["offer_status"],
                    "codes": diagnosis["codes"],
                },
            )
            app_state.add_task_event(
                task_id=task["id"],
                event_type="task.status_refreshed",
                from_status=task["status"],
                to_status="manual_intervention" if diagnosis["action_required"] else "succeeded",
                stage="waiting_manual" if diagnosis["action_required"] else "prepared",
                message="Operator refreshed official offer status",
                details={
                    "job_id": job["id"],
                    "listing_id": listing["id"],
                    "offer_status": diagnosis["offer_status"],
                    "batch_status": batch_status_payload.get("status") if isinstance(batch_status_payload, dict) else None,
                },
                source="api",
                source_id=actor["id"],
            )
        return self._to_job_response(updated_job or job)

    def process_queued_listing_tasks(
        self,
        *,
        adapter_factory: ListingAdapterFactory | None = None,
    ) -> list[dict[str, Any]]:
        claimed_tasks = app_state.claim_queued_tasks(
            {PROCESS_LISTING_JOB_TASK_TYPE},
            worker_id=LISTING_WORKER_SOURCE_ID,
        )
        return [self.process_listing_task(task["id"], adapter_factory=adapter_factory) for task in claimed_tasks]

    def process_listing_task(
        self,
        task_id: str,
        *,
        adapter_factory: ListingAdapterFactory | None = None,
    ) -> dict[str, Any]:
        task = app_state.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
        if task["task_type"] != PROCESS_LISTING_JOB_TASK_TYPE:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Task is not a listing task")

        job = app_state.get_listing_job(task["target_id"])
        if job is None:
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
                error_code="LISTING_JOB_NOT_FOUND",
                error_msg="Listing job not found",
                error_details={"job_id": task["target_id"]},
            )
            app_state.add_task_event(
                task_id=task_id,
                event_type="task.failed",
                from_status=task["status"],
                to_status="failed",
                stage="failed",
                message="Listing job missing during worker execution",
                details={"job_id": task["target_id"]},
                source="worker",
                source_id=LISTING_WORKER_SOURCE_ID,
            )
            return updated

        now = datetime.now(UTC)
        if not app_state.is_setting_enabled("listing_jobs_enabled", False):
            app_state.update_listing_job(
                job["id"],
                status="manual_intervention",
                stage="waiting_manual",
                note="Listing worker is not enabled yet; job parked for manual follow-up",
            )
            updated = app_state.update_task(
                task_id,
                status="manual_intervention",
                stage="waiting_listing_worker",
                progress_percent=100,
                finished_at=now,
                last_heartbeat_at=now,
                lease_owner=None,
                lease_token=None,
                lease_expires_at=None,
                error_code="LISTING_WORKER_DISABLED",
                error_msg="Listing worker is disabled by release switch",
                error_details={"job_id": job["id"]},
            )
            app_state.add_task_event(
                task_id=task_id,
                event_type="task.manual_intervention",
                from_status=task["status"],
                to_status="manual_intervention",
                stage="waiting_listing_worker",
                message="Listing job parked until release switch is enabled",
                details={"job_id": job["id"]},
                source="worker",
                source_id=LISTING_WORKER_SOURCE_ID,
            )
            return updated

        store = app_state.get_store(job["store_id"])
        if store is None:
            return self._fail_task(
                task=task,
                job=job,
                error_code="LISTING_STORE_NOT_FOUND",
                error_msg="Store not found for listing worker",
            )

        product = app_state.get_library_product_by_id(job["product_id"]) if job.get("product_id") else None
        if product is None:
            return self._fail_task(
                task=task,
                job=job,
                error_code="LISTING_PRODUCT_NOT_FOUND",
                error_msg="Library product not found for listing worker",
            )

        credentials_payload = app_state.get_store_credentials(store["id"])
        if not credentials_payload:
            return self._fail_task(
                task=task,
                job=job,
                error_code="LISTING_STORE_CREDENTIALS_MISSING",
                error_msg="Store credentials unavailable for listing worker",
            )
        credentials = AdapterCredentials(
            platform=store["platform"],
            api_key=credentials_payload.get("api_key", ""),
            api_secret=credentials_payload.get("api_secret", ""),
        )
        adapter = self._build_adapter(store=store, credentials=credentials, adapter_factory=adapter_factory)
        barcode = self._extract_barcode(job, product)
        if not barcode:
            return self._manual_job(
                task=task,
                job=job,
                note="Missing barcode/GTIN; cannot call official POST /offers",
                error_code="LISTING_BARCODE_MISSING",
            )

        selling_price = self._extract_selling_price(job)
        if selling_price is None:
            return self._manual_job(
                task=task,
                job=job,
                note="Missing selling price; cannot call official POST /offers",
                error_code="LISTING_SELLING_PRICE_MISSING",
            )

        quantity = self._extract_quantity(job)
        minimum_leadtime_days = settings.extension_listing_default_leadtime_days
        leadtime_merchant_warehouse_id = credentials_payload.get("leadtime_merchant_warehouse_id")
        pending_task_update, resolved_offer_payload = self._poll_existing_batch_if_needed(
            task=task,
            job=job,
            adapter=adapter,
            barcode=barcode,
        )
        if pending_task_update is not None:
            return pending_task_update
        if resolved_offer_payload is None:
            offer_payload = adapter.create_or_update_offer(
                barcode=barcode,
                sku=self._extract_or_create_offer_sku(job),
                selling_price=selling_price,
                rrp=selling_price * 2,
                quantity=quantity,
                minimum_leadtime_days=minimum_leadtime_days,
                leadtime_merchant_warehouse_id=leadtime_merchant_warehouse_id,
            )
            batch_pending_result = self._handle_batch_pending(
                task=task,
                job=job,
                offer_payload=offer_payload,
                barcode=barcode,
            )
            if batch_pending_result is not None:
                return batch_pending_result
        else:
            offer_payload = resolved_offer_payload
        listing = app_state.upsert_store_listing(
            store_id=store["id"],
            external_listing_id=str(offer_payload.get("offer_id") or offer_payload.get("id") or product["external_product_id"]),
            platform_product_id=product["external_product_id"],
            sku=str(offer_payload.get("sku") or self._extract_or_create_offer_sku(job)),
            title=str(offer_payload.get("title") or product["title"]),
            platform_price=float(offer_payload.get("selling_price") or selling_price),
            stock_quantity=quantity,
            currency="ZAR",
            sync_status="synced",
            raw_payload=offer_payload,
        )
        diagnosis = self._diagnose_offer_payload(offer_payload)
        app_state.update_listing_job(
            job["id"],
            status="manual_intervention" if diagnosis["action_required"] else "ready_to_submit",
            stage="waiting_manual" if diagnosis["action_required"] else "prepared",
            note=diagnosis["summary"],
            raw_payload={
                **(job.get("raw_payload") or {}),
                "offer_payload": offer_payload,
                "listing_id": listing["id"],
                "offer_diagnosis": diagnosis,
            },
        )
        if diagnosis["action_required"]:
            updated = app_state.update_task(
                task_id,
                status="manual_intervention",
                stage="waiting_manual",
                progress_percent=100,
                finished_at=now,
                last_heartbeat_at=now,
                lease_owner=None,
                lease_token=None,
                lease_expires_at=None,
                error_code=diagnosis["primary_code"],
                error_msg=diagnosis["summary"],
                error_details={
                    "job_id": job["id"],
                    "listing_id": listing["id"],
                    "offer_status": diagnosis["offer_status"],
                    "codes": diagnosis["codes"],
                },
            )
            app_state.add_task_event(
                task_id=task_id,
                event_type="task.manual_intervention",
                from_status=task["status"],
                to_status="manual_intervention",
                stage="waiting_manual",
                message=diagnosis["summary"],
                details={
                    "job_id": job["id"],
                    "listing_id": listing["id"],
                    "barcode": barcode,
                    "diagnosis": diagnosis,
                },
                source="worker",
                source_id=LISTING_WORKER_SOURCE_ID,
            )
            return updated
        updated = app_state.update_task(
            task_id,
            status="succeeded",
            stage="prepared",
            progress_percent=100,
            finished_at=now,
            last_heartbeat_at=now,
            lease_owner=None,
            lease_token=None,
            lease_expires_at=None,
            error_code=None,
            error_msg=None,
            error_details={"job_id": job["id"], "listing_id": listing["id"]},
        )
        app_state.add_task_event(
            task_id=task_id,
            event_type="task.succeeded",
            from_status=task["status"],
            to_status="succeeded",
            stage="prepared",
            message="Listing job created/updated official Takealot offer",
            details={"job_id": job["id"], "listing_id": listing["id"], "barcode": barcode},
            source="worker",
            source_id=LISTING_WORKER_SOURCE_ID,
        )
        return updated

    def _poll_existing_batch_if_needed(
        self,
        *,
        task: dict[str, Any],
        job: dict[str, Any],
        adapter: BaseAdapter,
        barcode: str,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        raw_payload = job.get("raw_payload") or {}
        batch_id = (
            raw_payload.get("batch_id")
            or (raw_payload.get("offer_payload") or {}).get("batch_id")
            or (raw_payload.get("batch_status_payload") or {}).get("batch_id")
        )
        if not batch_id:
            return None, None
        try:
            batch_status = adapter.get_offer_batch_status(int(batch_id))
        except Exception as exc:
            return self._fail_task(
                task=task,
                job=job,
                error_code="LISTING_BATCH_STATUS_FAILED",
                error_msg=str(exc),
            ), None

        status_value = str(batch_status.get("status") or "").lower()
        if status_value in {"pending", "processing"}:
            return self._park_waiting_retry(
                task=task,
                job=job,
                note=f"Takealot batch {batch_id} still {status_value}",
                batch_payload=batch_status,
            ), None
        if status_value == "failed":
            return self._manual_job(
                task=task,
                job=job,
                note=f"Takealot batch {batch_id} failed: {batch_status}",
                error_code="LISTING_BATCH_FAILED",
            ), None
        refreshed_offer = adapter.get_offer_by_barcode(barcode)
        if refreshed_offer is None:
            return self._manual_job(
                task=task,
                job=job,
                note=f"Takealot batch {batch_id} succeeded but offer lookup by barcode returned nothing",
                error_code="LISTING_BATCH_SUCCESS_OFFER_MISSING",
            ), None
        app_state.update_listing_job(
            job["id"],
            raw_payload={**raw_payload, "batch_status_payload": batch_status, "offer_payload": refreshed_offer},
        )
        return None, refreshed_offer

    def _handle_batch_pending(
        self,
        *,
        task: dict[str, Any],
        job: dict[str, Any],
        offer_payload: dict[str, Any],
        barcode: str,
    ) -> dict[str, Any] | None:
        batch_id = offer_payload.get("batch_id")
        batch_status = str(offer_payload.get("batch_status") or "").lower()
        if not batch_id or batch_status not in {"pending", "processing"}:
            return None
        raw_payload = {
            **(job.get("raw_payload") or {}),
            "barcode": barcode,
            "batch_id": batch_id,
            "batch_status": batch_status,
            "offer_payload": offer_payload,
        }
        app_state.update_listing_job(
            job["id"],
            status="processing",
            stage="processing",
            note=f"Takealot batch {batch_id} is {batch_status}; waiting for final status",
            raw_payload=raw_payload,
        )
        return self._park_waiting_retry(
            task=task,
            job=job,
            note=f"Takealot batch {batch_id} is {batch_status}",
            batch_payload=offer_payload,
        )

    @staticmethod
    def _park_waiting_retry(
        *,
        task: dict[str, Any],
        job: dict[str, Any],
        note: str,
        batch_payload: dict[str, Any],
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        retry_at = now + timedelta(seconds=5)
        app_state.update_listing_job(
            job["id"],
            status="processing",
            stage="processing",
            note=note,
            raw_payload={**(job.get("raw_payload") or {}), "batch_status_payload": batch_payload},
        )
        updated = app_state.update_task(
            task["id"],
            status="waiting_retry",
            stage="waiting_retry",
            progress_percent=50,
            finished_at=None,
            last_heartbeat_at=now,
            next_retry_at=retry_at,
            lease_owner=None,
            lease_token=None,
            lease_expires_at=None,
            error_code="LISTING_BATCH_PENDING",
            error_msg=note,
            error_details={"job_id": job["id"], "retry_at": retry_at.isoformat()},
        )
        app_state.add_task_event(
            task_id=task["id"],
            event_type="task.retry_scheduled",
            from_status=task["status"],
            to_status="waiting_retry",
            stage="waiting_retry",
            message=note,
            details={"job_id": job["id"], "retry_at": retry_at.isoformat()},
            source="worker",
            source_id=LISTING_WORKER_SOURCE_ID,
        )
        return updated

    @staticmethod
    def _require_job(job_id: str, actor: dict[str, Any]) -> dict[str, Any]:
        job = app_state.get_listing_job(job_id)
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Listing job not found")
        require_tenant_access(actor, job["tenant_id"], detail="Listing job not found")
        return job

    @staticmethod
    def _to_job_response(job: dict[str, Any]) -> ListingJobResponse:
        return ListingJobResponse(
            job_id=job["id"],
            tenant_id=job["tenant_id"],
            store_id=job["store_id"],
            product_id=job.get("product_id"),
            guardrail_id=job.get("guardrail_id"),
            entry_task_id=job.get("entry_task_id"),
            processing_task_id=job.get("processing_task_id"),
            platform=job["platform"],
            source=job["source"],
            source_ref=job.get("source_ref"),
            title=job["title"],
            status=job["status"],
            stage=job["stage"],
            note=job.get("note"),
            raw_payload=job.get("raw_payload"),
            created_at=job["created_at"],
            updated_at=job["updated_at"],
        )

    def _build_adapter(
        self,
        *,
        store: dict[str, Any],
        credentials: AdapterCredentials,
        adapter_factory: ListingAdapterFactory | None,
    ) -> BaseAdapter:
        if adapter_factory is not None:
            return adapter_factory(store, credentials)
        if store["platform"] == "takealot":
            return TakealotAdapter(credentials)
        raise HTTPException(status_code=400, detail=f"Unsupported store platform: {store['platform']}")

    @staticmethod
    def _extract_barcode(job: dict[str, Any], product: dict[str, Any]) -> str | None:
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
            return "".join(ch for ch in str(value or "").lower() if ch.isalnum())

        def normalize_barcode(value: Any) -> str | None:
            if value is None or value == "":
                return None
            if isinstance(value, dict):
                for key in ("value", "display_value", "displayValue", "name", "label", "text"):
                    normalized = normalize_barcode(value.get(key))
                    if normalized:
                        return normalized
                return None
            text = "".join(ch for ch in str(value).strip() if ch.isalnum() or ch == "-")
            return text if len(text) >= 6 else None

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
                    normalized = normalize_barcode(value.get("value"))
                    if normalized:
                        return normalized
                for key, nested in value.items():
                    if normalize_key(key) in target_keys:
                        normalized = normalize_barcode(nested)
                        if normalized:
                            return normalized
                    found = scan(nested, depth + 1)
                    if found:
                        return found
            return None

        job_payload = job.get("raw_payload") if isinstance(job.get("raw_payload"), dict) else {}
        product_payload = product.get("raw_payload") if isinstance(product.get("raw_payload"), dict) else {}
        return scan(job_payload) or scan(product_payload)

    @staticmethod
    def _extract_selling_price(job: dict[str, Any]) -> float | None:
        raw_payload = job.get("raw_payload") or {}
        value = raw_payload.get("sale_price_zar")
        try:
            return float(max(0, int(round(float(value))))) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _extract_quantity(job: dict[str, Any]) -> int | None:
        raw_payload = job.get("raw_payload") or {}
        value = raw_payload.get("quantity")
        try:
            if value is not None:
                return max(1, int(value))
        except (TypeError, ValueError):
            pass
        return None

    @staticmethod
    def _extract_or_create_offer_sku(job: dict[str, Any]) -> str:
        raw_payload = job.get("raw_payload") or {}
        existing = raw_payload.get("generated_sku")
        if existing:
            return str(existing)
        generated = f"XH{str(uuid4().int)[:10]}"
        raw_payload["generated_sku"] = generated
        app_state.update_listing_job(
            job["id"],
            raw_payload=raw_payload,
        )
        return generated

    @staticmethod
    def _diagnose_offer_payload(offer_payload: dict[str, Any]) -> dict[str, Any]:
        status_value = str(offer_payload.get("status") or "").lower()
        codes: list[str] = []
        hints: list[str] = []
        if status_value and status_value != "buyable":
            codes.append(f"STATUS_{status_value.upper()}")
        if bool(offer_payload.get("disabled_by_takealot")):
            codes.append("DISABLED_BY_TAKEALOT")
            hints.append("平台侧已禁用该报价。")
        if bool(offer_payload.get("disabled_by_seller")):
            codes.append("DISABLED_BY_SELLER")
            hints.append("卖家侧当前禁用了该报价。")
        if bool(offer_payload.get("affected_by_vacation")):
            codes.append("AFFECTED_BY_VACATION")
            hints.append("店铺休假状态影响了该报价。")
        if status_value == "not_buyable" and not codes:
            codes.append("NOT_BUYABLE_UNSPECIFIED")
            hints.append("报价已创建，但当前不可售；请复核 leadtime、库存或平台规则。")

        action_required = status_value not in {"", "buyable"}
        summary = (
            "Offer created and currently buyable."
            if not action_required
            else "Offer created but not buyable yet. " + " ".join(hints)
        )
        return {
            "offer_status": status_value or None,
            "codes": codes,
            "primary_code": codes[0] if codes else None,
            "hints": hints,
            "action_required": action_required,
            "summary": summary,
        }

    @staticmethod
    def _manual_job(
        *,
        task: dict[str, Any],
        job: dict[str, Any],
        note: str,
        error_code: str,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        app_state.update_listing_job(
            job["id"],
            status="manual_intervention",
            stage="waiting_manual",
            note=note,
        )
        updated = app_state.update_task(
            task["id"],
            status="manual_intervention",
            stage="waiting_manual",
            progress_percent=100,
            finished_at=now,
            last_heartbeat_at=now,
            lease_owner=None,
            lease_token=None,
            lease_expires_at=None,
            error_code=error_code,
            error_msg=note,
            error_details={"job_id": job["id"]},
        )
        app_state.add_task_event(
            task_id=task["id"],
            event_type="task.manual_intervention",
            from_status=task["status"],
            to_status="manual_intervention",
            stage="waiting_manual",
            message=note,
            details={"job_id": job["id"], "reason": error_code},
            source="worker",
            source_id=LISTING_WORKER_SOURCE_ID,
        )
        return updated

    @staticmethod
    def _fail_task(
        *,
        task: dict[str, Any],
        job: dict[str, Any],
        error_code: str,
        error_msg: str,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        app_state.update_listing_job(
            job["id"],
            status="failed",
            stage="failed",
            note=error_msg,
        )
        updated = app_state.update_task(
            task["id"],
            status="failed",
            stage="failed",
            progress_percent=100,
            finished_at=now,
            last_heartbeat_at=now,
            lease_owner=None,
            lease_token=None,
            lease_expires_at=None,
            error_code=error_code,
            error_msg=error_msg,
            error_details={"job_id": job["id"]},
        )
        app_state.add_task_event(
            task_id=task["id"],
            event_type="task.failed",
            from_status=task["status"],
            to_status="failed",
            stage="failed",
            message=error_msg,
            details={"job_id": job["id"], "reason": error_code},
            source="worker",
            source_id=LISTING_WORKER_SOURCE_ID,
        )
        return updated
