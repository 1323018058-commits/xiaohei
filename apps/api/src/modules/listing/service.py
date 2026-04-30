from __future__ import annotations

import re
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, Callable
from uuid import uuid4

from fastapi import HTTPException, status

from src.modules.admin.service import get_request_id
from src.modules.common.dev_state import app_state
from src.modules.common.tenant_scope import require_tenant_access
from src.modules.store.adapters import AdapterCredentials, AdapterError, BaseAdapter, TakealotAdapter
from src.platform.settings.base import settings

from .ai_service import ListingAiService
from .category_matcher import CategoryMatcher
from .image_service import ListingImageService
from .loadsheet_service import ListingLoadsheetService, ListingLoadsheetStatusError, ListingLoadsheetSubmitError
from .repository import (
    CATALOG_IMPORT_REQUIRED_MESSAGE,
    ListingCatalogRepository,
    ListingCatalogUnavailable,
)
from .schemas import (
    CategoryMatchRequest,
    CategoryMatchResponse,
    ListingAiAutopilotRequest,
    ListingAiAutopilotResponse,
    ListingImageRequirementCheckRequest,
    ListingImageRequirementCheckResponse,
    ListingImageUploadResponse,
    ListingImageUrlValidateRequest,
    ListingImageUrlValidateResponse,
    ListingJobListResponse,
    ListingJobResponse,
    ListingLoadsheetPreviewRequest,
    ListingLoadsheetPreviewResponse,
    ListingFinalizeOfferResponse,
    ListingSubmissionCreateRequest,
    ListingSubmissionCreateResponse,
    ListingSubmissionDetailResponse,
    ListingSubmissionItem,
    ListingSubmissionListResponse,
    ListingSubmissionStatusItem,
    ListingSubmissionSyncResponse,
    TakealotBrandSearchResponse,
    TakealotCategoryRequirementsResponse,
    TakealotCategorySearchResponse,
)


PROCESS_LISTING_JOB_TASK_TYPE = "PROCESS_LISTING_JOB"
SUBMIT_LISTING_LOADSHEET_TASK_TYPE = "SUBMIT_LISTING_LOADSHEET"
SYNC_LISTING_SUBMISSION_STATUS_TASK_TYPE = "SYNC_LISTING_SUBMISSION_STATUS"
FINALIZE_LISTING_OFFER_TASK_TYPE = "FINALIZE_LISTING_OFFER"
LISTING_WORKER_SOURCE_ID = "listing-worker"
LISTING_LOADSHEET_SUBMIT_CLAIM_SECONDS = 1200
LISTING_OFFER_FINALIZE_CLAIM_SECONDS = 900
LISTING_WORKER_TASK_TYPES = {
    PROCESS_LISTING_JOB_TASK_TYPE,
    SUBMIT_LISTING_LOADSHEET_TASK_TYPE,
    SYNC_LISTING_SUBMISSION_STATUS_TASK_TYPE,
    FINALIZE_LISTING_OFFER_TASK_TYPE,
}
ListingAdapterFactory = Callable[[dict[str, Any], AdapterCredentials], BaseAdapter]


class ListingService:
    def __init__(
        self,
        catalog_repository: ListingCatalogRepository | None = None,
        category_matcher: CategoryMatcher | None = None,
        ai_service: ListingAiService | None = None,
        image_service: ListingImageService | None = None,
        loadsheet_service: ListingLoadsheetService | None = None,
    ) -> None:
        self.catalog_repository = catalog_repository or ListingCatalogRepository()
        self.ai_service = ai_service or (category_matcher.ai_service if category_matcher is not None else ListingAiService())
        self.image_service = image_service or ListingImageService()
        self.loadsheet_service = loadsheet_service or ListingLoadsheetService()
        self.category_matcher = category_matcher or CategoryMatcher(
            repository=self.catalog_repository,
            ai_service=self.ai_service,
        )

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

    def search_categories(
        self,
        actor: dict[str, Any],
        *,
        query: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> TakealotCategorySearchResponse:
        self._require_catalog_permission(actor)
        if self._is_memory_backend():
            return TakealotCategorySearchResponse(
                items=[],
                total=0,
                page=page,
                page_size=page_size,
                catalog_ready=False,
                message=CATALOG_IMPORT_REQUIRED_MESSAGE,
            )
        try:
            query_text = (query or "").strip()
            if query_text and self._contains_cjk(query_text):
                # Chinese typeahead uses the same guarded semantic matcher as
                # the explicit match button: AI/vector may translate or rerank,
                # but category_id still comes only from PostgreSQL catalog rows.
                result = self.category_matcher.match(
                    description=query_text,
                    limit=max(20, page * page_size),
                    use_ai=True,
                )
                if result.suggestions or not result.catalog_ready:
                    start = (page - 1) * page_size
                    end = start + page_size
                    items = self._category_search_items_from_suggestions(result.suggestions[start:end])
                    return TakealotCategorySearchResponse(
                        items=items,
                        total=max(result.total_candidates, len(result.suggestions)),
                        page=page,
                        page_size=page_size,
                        catalog_ready=result.catalog_ready,
                        message=result.message if result.catalog_ready else CATALOG_IMPORT_REQUIRED_MESSAGE,
                    )
                if result.message:
                    return TakealotCategorySearchResponse(
                        items=[],
                        total=0,
                        page=page,
                        page_size=page_size,
                        catalog_ready=result.catalog_ready,
                        message=result.message,
                    )

            items, total, catalog_ready = self.catalog_repository.search_categories(
                query=query_text or None,
                page=page,
                page_size=page_size,
            )
        except ListingCatalogUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message) from exc
        return TakealotCategorySearchResponse(
            items=self._with_category_display_paths(items, use_ai_translation=bool(query_text and self._contains_cjk(query_text))),
            total=total,
            page=page,
            page_size=page_size,
            catalog_ready=catalog_ready,
            message=None if catalog_ready else CATALOG_IMPORT_REQUIRED_MESSAGE,
        )

    def match_category(
        self,
        actor: dict[str, Any],
        request: CategoryMatchRequest,
    ) -> CategoryMatchResponse:
        self._require_catalog_permission(actor)
        if self._is_memory_backend():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"PostgreSQL unavailable; {CATALOG_IMPORT_REQUIRED_MESSAGE}",
            )
        try:
            result = self.category_matcher.match(
                description=request.description,
                limit=request.limit,
                use_ai=request.use_ai,
            )
        except ListingCatalogUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message) from exc
        return CategoryMatchResponse(
            suggestions=result.suggestions,
            total_candidates=result.total_candidates,
            catalog_ready=result.catalog_ready,
            ai_used=result.ai_used,
            vector_used=result.vector_used,
            vector_candidates=result.vector_candidates,
            keyword_candidates=result.keyword_candidates,
            fuzzy_candidates=result.fuzzy_candidates,
            embedding_model=result.embedding_model,
            embedding_dimensions=result.embedding_dimensions,
            translation_used=result.translation_used,
            translation_model=result.translation_model,
            match_strategy=result.match_strategy,
            normalized_keywords=result.normalized_keywords,
            message=result.message,
        )

    def get_category_requirements(
        self,
        category_id: int,
        actor: dict[str, Any],
    ) -> TakealotCategoryRequirementsResponse:
        self._require_catalog_permission(actor)
        if self._is_memory_backend():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=CATALOG_IMPORT_REQUIRED_MESSAGE,
            )
        try:
            item, catalog_ready = self.catalog_repository.get_category_requirements(category_id)
        except ListingCatalogUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message) from exc
        if item is None and not catalog_ready:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=CATALOG_IMPORT_REQUIRED_MESSAGE,
            )
        if item is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Takealot category not found")
        item = self._with_category_display_paths([item], use_ai_translation=True)[0]
        return TakealotCategoryRequirementsResponse(
            **item,
            catalog_ready=True,
            message=None,
        )

    def generate_listing_content(
        self,
        actor: dict[str, Any],
        request: ListingAiAutopilotRequest,
    ) -> ListingAiAutopilotResponse:
        self._require_catalog_permission(actor)
        if self._is_memory_backend():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"PostgreSQL unavailable; {CATALOG_IMPORT_REQUIRED_MESSAGE}",
            )
        try:
            category, catalog_ready = self.catalog_repository.get_category_requirements(request.category_id)
        except ListingCatalogUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message) from exc
        if category is None and not catalog_ready:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=CATALOG_IMPORT_REQUIRED_MESSAGE)
        if category is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Takealot category not found")

        category["path_en"] = self._category_path_en(category)
        category["path_zh"] = self.category_matcher.path_zh(category)
        allowed_attributes = self._normalize_attribute_definitions(
            category.get("required_attributes") or [],
            category.get("optional_attributes") or [],
            request.required_attributes,
            request.optional_attributes,
        )

        warnings: list[str] = []
        content: dict[str, Any] | None = None
        ai_used = False
        fallback_used = True
        if request.use_ai and self.ai_service.enabled:
            ai_payload = self.ai_service.generate_listing_content(
                product_description=request.product_description,
                category=category,
                brand_name=request.brand_name,
                allowed_attributes=allowed_attributes,
            )
            content, validation_warnings = self._validate_ai_generated_content(
                ai_payload,
                request=request,
                category=category,
                allowed_attributes=allowed_attributes,
            )
            warnings.extend(validation_warnings)
            if content is not None:
                ai_used = True
                fallback_used = False
            else:
                warnings.append("AI response was unavailable or invalid; local fallback was used.")
        else:
            warnings.append("AI is not configured or disabled; local fallback was used.")

        if content is None:
            content = self._fallback_generated_content(
                request=request,
                category=category,
                allowed_attributes=allowed_attributes,
            )

        return ListingAiAutopilotResponse(
            **content,
            ai_used=ai_used,
            fallback_used=fallback_used,
            warnings=warnings,
        )

    def upload_listing_images(
        self,
        actor: dict[str, Any],
        *,
        store_id: str,
        files: list[Any],
        submission_id: str | None = None,
    ) -> ListingImageUploadResponse:
        self._require_catalog_permission(actor)
        if self._is_memory_backend():
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="PostgreSQL unavailable")
        if not files:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one image file is required")
        try:
            tenant_id = self.catalog_repository.get_store_tenant_id(store_id)
        except ListingCatalogUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message) from exc
        if tenant_id is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store not found")
        require_tenant_access(actor, tenant_id, detail="Store not found")

        items: list[dict[str, Any]] = []
        warnings: list[str] = []
        for sort_order, upload in enumerate(files):
            filename = getattr(upload, "filename", "") or "image"
            content_type = getattr(upload, "content_type", None)
            file_obj = getattr(upload, "file", None)
            if file_obj is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid upload: {filename}")
            file_obj.seek(0)
            data = file_obj.read()
            result = self.image_service.save_image_bytes(
                data,
                original_file_name=filename,
                content_type=content_type,
            )
            if not result.get("valid"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "file_name": filename,
                        "errors": result.get("errors") or [],
                        "warnings": result.get("warnings") or [],
                    },
                )
            asset_payload = result["asset"]
            asset_warnings = result.get("warnings") or []
            if asset_warnings:
                asset_payload.setdefault("raw_payload", {})["warnings"] = asset_warnings
                warnings.extend(asset_warnings)
            try:
                item = self.catalog_repository.insert_listing_asset(
                    tenant_id=tenant_id,
                    store_id=store_id,
                    submission_id=submission_id,
                    asset=asset_payload,
                    sort_order=sort_order,
                )
            except ListingCatalogUnavailable as exc:
                raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message) from exc
            item["warnings"] = asset_warnings
            items.append(item)
        return ListingImageUploadResponse(items=items, warnings=self._dedupe_strings(warnings))

    def validate_listing_image_url(
        self,
        actor: dict[str, Any],
        request: ListingImageUrlValidateRequest,
    ) -> ListingImageUrlValidateResponse:
        self._require_catalog_permission(actor)
        result = self.image_service.validate_image_url(
            request.image_url,
            check_remote=request.check_remote,
        )
        return ListingImageUrlValidateResponse(**result)

    def check_listing_image_requirements(
        self,
        actor: dict[str, Any],
        request: ListingImageRequirementCheckRequest,
    ) -> ListingImageRequirementCheckResponse:
        self._require_catalog_permission(actor)
        if self._is_memory_backend():
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="PostgreSQL unavailable")
        try:
            category, catalog_ready = self.catalog_repository.get_category_requirements(request.category_id)
        except ListingCatalogUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message) from exc
        if category is None and not catalog_ready:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=CATALOG_IMPORT_REQUIRED_MESSAGE)
        if category is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Takealot category not found")

        warnings: list[str] = []
        valid_image_urls: list[str] = []
        for image_url in request.image_urls:
            result = self.image_service.validate_image_url(image_url, check_remote=False)
            if result["valid"]:
                valid_image_urls.append(image_url)
            else:
                warnings.extend(result.get("errors") or [])

        tenant_id = None if actor.get("role") == "super_admin" else actor.get("tenant_id")
        try:
            assets = self.catalog_repository.list_listing_assets_by_ids(
                asset_ids=request.asset_ids,
                tenant_id=tenant_id,
            )
        except ListingCatalogUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message) from exc
        found_asset_ids = {asset["id"] for asset in assets}
        for asset_id in request.asset_ids:
            if asset_id not in found_asset_ids:
                warnings.append(f"Listing asset not found or not accessible: {asset_id}")

        valid_asset_ids: list[str] = []
        for asset in assets:
            public_url = asset.get("public_url") or asset.get("external_url")
            if self.image_service.is_http_url(public_url):
                valid_asset_ids.append(asset["id"])
            else:
                warnings.append(
                    f"Listing asset {asset['id']} does not have a public http/https URL for Takealot loadsheets."
                )

        current_count = len(self._dedupe_strings(valid_image_urls)) + len(self._dedupe_strings(valid_asset_ids))
        required_count = max(0, int(category.get("min_required_images") or 0))
        missing_count = max(0, required_count - current_count)
        if missing_count:
            warnings.append(f"{missing_count} more public image URL(s) required for this category.")
        return ListingImageRequirementCheckResponse(
            passed=missing_count == 0,
            required_count=required_count,
            current_count=current_count,
            missing_count=missing_count,
            warnings=self._dedupe_strings(warnings),
            valid_image_urls=self._dedupe_strings(valid_image_urls),
            valid_asset_ids=self._dedupe_strings(valid_asset_ids),
        )

    def preview_listing_loadsheet(
        self,
        actor: dict[str, Any],
        request: ListingLoadsheetPreviewRequest,
    ) -> ListingLoadsheetPreviewResponse:
        result = self._prepare_loadsheet_preview(actor, request)["preview"]
        return ListingLoadsheetPreviewResponse(**result)

    def create_listing_submission(
        self,
        actor: dict[str, Any],
        *,
        store_id: str,
        request: ListingSubmissionCreateRequest,
        request_headers: dict[str, str] | None = None,
    ) -> ListingSubmissionCreateResponse:
        preview_request = ListingLoadsheetPreviewRequest(
            store_id=store_id,
            **request.model_dump(exclude={"submit_immediately"}),
        )
        prepared = self._prepare_loadsheet_preview(actor, preview_request)
        preview = prepared["preview"]
        if not preview["valid"]:
            return ListingSubmissionCreateResponse(
                submission_id=None,
                task_id=None,
                status="validation_failed",
                stage="validation_failed",
                message="Listing submission was not created because loadsheet pre-validation failed.",
                loadsheet_asset=preview.get("loadsheet_asset"),
                validation_issues=preview.get("issues") or [],
                warnings=preview.get("warnings") or [],
            )

        generated_fields = preview["generated_fields"]
        loadsheet_payload = {
            "loadsheet_asset": preview.get("loadsheet_asset"),
            "validation_issues": preview.get("issues") or [],
            "warnings": preview.get("warnings") or [],
            "missing_required_fields": preview.get("missing_required_fields") or [],
            "generated_fields": generated_fields,
        }
        weight_g = generated_fields.get("weight_g")
        try:
            weight_kg = float(weight_g) / 1000 if weight_g is not None else None
        except (TypeError, ValueError):
            weight_kg = None

        idempotency_key = self._submission_idempotency_key(
            tenant_id=prepared["tenant_id"],
            store_id=store_id,
            generated_fields=generated_fields,
            request_headers=request_headers or {},
        )
        submission: dict[str, Any] | None = None
        try:
            submission = self.catalog_repository.create_listing_submission(
                submission={
                    "tenant_id": prepared["tenant_id"],
                    "store_id": store_id,
                    "idempotency_key": idempotency_key,
                    "sku": generated_fields["sku"],
                    "barcode": generated_fields["barcode"],
                    "title": generated_fields["title"],
                    "subtitle": generated_fields.get("subtitle") or "",
                    "description": generated_fields.get("description") or "",
                    "whats_in_the_box": generated_fields.get("whats_in_the_box") or "",
                    "category_id": generated_fields["category_id"],
                    "takealot_category_row_id": prepared["category"].get("id"),
                    "category_path": generated_fields.get("category_path_en") or "",
                    "brand_id": generated_fields.get("brand_id") or "",
                    "brand_name": generated_fields.get("brand_name") or "",
                    "selling_price": generated_fields.get("selling_price"),
                    "rrp": generated_fields.get("rrp"),
                    "stock_quantity": int(generated_fields.get("stock_quantity") or 0),
                    "minimum_leadtime_days": int(generated_fields.get("minimum_leadtime_days") or 0),
                    "seller_warehouse_id": generated_fields.get("seller_warehouse_id") or None,
                    "length_cm": generated_fields.get("length_cm"),
                    "width_cm": generated_fields.get("width_cm"),
                    "height_cm": generated_fields.get("height_cm"),
                    "weight_kg": weight_kg,
                    "image_urls": generated_fields.get("image_urls") or [],
                    "dynamic_attributes": self._dynamic_attribute_values_to_dict(
                        generated_fields.get("dynamic_attributes") or []
                    ),
                    "content_payload": generated_fields,
                    "loadsheet_payload": loadsheet_payload,
                    "official_response": {},
                    "status": "content_queued",
                    "stage": "queued",
                    "review_status": "not_submitted",
                }
            )
            if submission.get("reused_existing"):
                immediate_task = None
                if request.submit_immediately and submission.get("task_id") and not submission.get("takealot_submission_id"):
                    # Idempotent retries should still give the user an immediate
                    # Takealot answer. Reusing the original task avoids creating
                    # duplicate tasks, while the submission row claim still gates
                    # the external loadsheet POST.
                    immediate_task = self._process_listing_submission_task_inline(str(submission["task_id"]))
                    submission = self._get_submission_or_current(submission)
                return self._to_submission_create_response(
                    submission=submission,
                    task_id=submission.get("task_id"),
                    message=self._submission_create_message(
                        submission=submission,
                        task=immediate_task,
                        fallback="Existing listing submission reused by idempotency key.",
                    ),
                    reused_existing=True,
                    submit_immediately=request.submit_immediately,
                    task=immediate_task,
                )
            generated_asset = self.catalog_repository.insert_listing_asset(
                tenant_id=prepared["tenant_id"],
                store_id=store_id,
                submission_id=submission["id"],
                asset=self.loadsheet_service.asset_payload_for_generated_loadsheet(preview["loadsheet_asset"]),
            )
            loadsheet_payload["loadsheet_asset"] = self._to_loadsheet_asset(generated_asset)
            submission = self.catalog_repository.update_listing_submission_loadsheet_payload(
                submission_id=submission["id"],
                loadsheet_payload=loadsheet_payload,
            )
        except ListingCatalogUnavailable as exc:
            if submission is not None:
                try:
                    self.catalog_repository.update_listing_submission_status(
                        submission_id=submission["id"],
                        status="queue_failed",
                        stage="failed",
                        error_code="LISTING_SUBMISSION_PREQUEUE_FAILED",
                        error_message=exc.message,
                    )
                except ListingCatalogUnavailable:
                    pass
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message) from exc

        try:
            task = app_state.create_task(
                task_type=SUBMIT_LISTING_LOADSHEET_TASK_TYPE,
                domain="listing",
                queue_name="listing-submissions",
                actor_user_id=actor.get("id"),
                actor_role=actor.get("role") or "operator",
                tenant_id=prepared["tenant_id"],
                store_id=store_id,
                target_type="listing_submission",
                target_id=submission["id"],
                request_id=get_request_id(request_headers or {}),
                label=f"Submit Takealot loadsheet for {submission['sku']}",
                next_action="Worker will submit the generated Takealot loadsheet.",
            )
        except Exception as exc:
            try:
                self.catalog_repository.update_listing_submission_status(
                    submission_id=submission["id"],
                    status="queue_failed",
                    stage="failed",
                    error_code="LISTING_SUBMISSION_QUEUE_FAILED",
                    error_message="Failed to create worker task for listing submission.",
                )
            except ListingCatalogUnavailable:
                pass
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Failed to queue listing submission worker task.",
            ) from exc

        try:
            submission = self.catalog_repository.update_listing_submission_task_id(
                submission_id=submission["id"],
                task_id=task["id"],
            )
        except ListingCatalogUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message) from exc

        immediate_task = None
        if request.submit_immediately:
            # The API request now performs the first Takealot side effect inline
            # so the UI can show a real submitted/failed result. The queued task
            # remains the durable audit record and retry handle; row-level claims
            # below prevent duplicate external POSTs if a worker races this call.
            immediate_task = self._process_listing_submission_task_inline(task["id"])
            submission = self._get_submission_or_current(submission)

        return self._to_submission_create_response(
            submission=submission,
            task_id=task["id"],
            message=self._submission_create_message(
                submission=submission,
                task=immediate_task,
                fallback="Listing submission queued for worker loadsheet submit.",
            ),
            submit_immediately=request.submit_immediately,
            task=immediate_task,
        )

    def list_listing_submissions(
        self,
        actor: dict[str, Any],
        *,
        store_id: str,
        status_filter: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> ListingSubmissionListResponse:
        self._require_catalog_permission(actor)
        tenant_id = self._require_store_access(actor, store_id)
        try:
            items, total = self.catalog_repository.list_listing_submissions(
                store_id=store_id,
                tenant_id=None if actor.get("role") == "super_admin" else tenant_id,
                status_filter=status_filter,
                page=page,
                page_size=page_size,
            )
        except ListingCatalogUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message) from exc
        return ListingSubmissionListResponse(
            items=[self._to_submission_item(item) for item in items],
            total=total,
            page=page,
            page_size=page_size,
        )

    def get_listing_submission_detail(
        self,
        actor: dict[str, Any],
        submission_id: str,
    ) -> ListingSubmissionDetailResponse:
        self._require_catalog_permission(actor)
        tenant_id = None if actor.get("role") == "super_admin" else actor.get("tenant_id")
        try:
            item = self.catalog_repository.get_listing_submission(submission_id, tenant_id=tenant_id)
            asset = self.catalog_repository.get_loadsheet_asset_for_submission(submission_id) if item else None
        except ListingCatalogUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message) from exc
        if item is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Listing submission not found")
        return ListingSubmissionDetailResponse(
            **self._to_submission_item(item, loadsheet_asset=asset).model_dump(),
            content_payload=item.get("content_payload") or {},
            loadsheet_payload=item.get("loadsheet_payload") or {},
            official_response=self.loadsheet_service.sanitize_official_response(item.get("official_response") or {}),
        )

    def sync_store_listing_submissions(
        self,
        actor: dict[str, Any],
        *,
        store_id: str,
        request_headers: dict[str, str] | None = None,
    ) -> ListingSubmissionSyncResponse:
        self._require_catalog_permission(actor)
        tenant_id = self._require_store_access(actor, store_id)
        try:
            submissions = self.catalog_repository.list_submissions_due_status_sync(
                store_id=store_id,
                tenant_id=None if actor.get("role") == "super_admin" else tenant_id,
            )
        except ListingCatalogUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message) from exc

        warnings: list[str] = []
        items: list[ListingSubmissionStatusItem] = []
        for submission in submissions:
            try:
                task = self._queue_listing_submission_worker_task(
                    actor,
                    submission=submission,
                    task_type=SYNC_LISTING_SUBMISSION_STATUS_TASK_TYPE,
                    request_headers=request_headers,
                    label=f"Sync Takealot review status for {submission['sku']}",
                    next_action="Worker will query Takealot loadsheet review status.",
                )
                items.append(self._to_submission_status_item(submission, task_id=task["id"], message="Status sync queued."))
            except Exception as exc:
                warnings.append(f"Failed to queue status sync for submission {submission['id']}: {exc}")
        return ListingSubmissionSyncResponse(
            store_id=store_id,
            queued_count=len(items),
            status="queued" if items else "noop",
            message="Queued listing submission status sync tasks." if items else "No listing submissions are due for status sync.",
            items=items,
            warnings=warnings,
        )

    def sync_listing_submission_status(
        self,
        actor: dict[str, Any],
        submission_id: str,
        *,
        request_headers: dict[str, str] | None = None,
    ) -> ListingSubmissionSyncResponse:
        submission = self._require_listing_submission_access(actor, submission_id)
        if not submission.get("takealot_submission_id"):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Listing submission has no Takealot submission id")
        task = self._queue_listing_submission_worker_task(
            actor,
            submission=submission,
            task_type=SYNC_LISTING_SUBMISSION_STATUS_TASK_TYPE,
            request_headers=request_headers,
            label=f"Sync Takealot review status for {submission['sku']}",
            next_action="Worker will query Takealot loadsheet review status.",
        )
        return ListingSubmissionSyncResponse(
            store_id=submission["store_id"],
            submission_id=submission["id"],
            task_id=task["id"],
            queued_count=1,
            status="queued",
            message="Listing submission status sync queued.",
            items=[self._to_submission_status_item(submission, task_id=task["id"], message="Status sync queued.")],
        )

    def finalize_listing_submission_offer(
        self,
        actor: dict[str, Any],
        submission_id: str,
        *,
        request_headers: dict[str, str] | None = None,
    ) -> ListingFinalizeOfferResponse:
        submission = self._require_listing_submission_access(actor, submission_id)
        if submission.get("takealot_offer_id"):
            return ListingFinalizeOfferResponse(
                submission_id=submission["id"],
                task_id=None,
                status=submission["status"],
                stage=submission["stage"],
                review_status=submission["review_status"],
                takealot_offer_id=submission.get("takealot_offer_id") or "",
                listing_id=submission.get("listing_id"),
                platform_product_id=submission.get("platform_product_id"),
                message="Listing submission already has a Takealot offer id; finalize skipped.",
            )
        if not self.loadsheet_service.is_review_approved(submission):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Takealot content review must be approved before creating or associating an Offer.",
            )
        task = self._queue_listing_submission_worker_task(
            actor,
            submission=submission,
            task_type=FINALIZE_LISTING_OFFER_TASK_TYPE,
            request_headers=request_headers,
            label=f"Finalize Takealot offer for {submission['sku']}",
            next_action="Worker will create or associate the Takealot offer after approved review.",
        )
        return ListingFinalizeOfferResponse(
            submission_id=submission["id"],
            task_id=task["id"],
            status=submission["status"],
            stage=submission["stage"],
            review_status=submission["review_status"],
            takealot_offer_id=submission.get("takealot_offer_id") or "",
            listing_id=submission.get("listing_id"),
            platform_product_id=submission.get("platform_product_id"),
            message="Listing submission offer finalization queued.",
        )

    def search_brands(
        self,
        actor: dict[str, Any],
        *,
        query: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> TakealotBrandSearchResponse:
        self._require_catalog_permission(actor)
        if self._is_memory_backend():
            return TakealotBrandSearchResponse(
                items=[],
                total=0,
                page=page,
                page_size=page_size,
                catalog_ready=False,
                message="需要导入 Takealot 品牌库",
            )
        try:
            items, total, catalog_ready = self.catalog_repository.search_brands(
                query=query,
                page=page,
                page_size=page_size,
            )
        except ListingCatalogUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message) from exc
        return TakealotBrandSearchResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            catalog_ready=catalog_ready,
            message=None if catalog_ready else "需要导入 Takealot 品牌库",
        )

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
            LISTING_WORKER_TASK_TYPES,
            worker_id=LISTING_WORKER_SOURCE_ID,
        )
        return [self.process_listing_task(task["id"], adapter_factory=adapter_factory) for task in claimed_tasks]

    def _process_listing_submission_task_inline(self, task_id: str) -> dict[str, Any] | None:
        task = app_state.get_task(task_id)
        if task is None:
            return None
        if task.get("status") == "succeeded":
            return task
        if task.get("status") in {"cancelled", "dead_letter"}:
            return task

        now = datetime.now(UTC)
        lease_token = f"api-inline:{uuid4().hex}"
        leased = app_state.update_task(
            task_id,
            status="leased",
            stage="leased",
            progress_percent=max(int(task.get("progress_percent") or 0), 1),
            started_at=task.get("started_at") or now,
            finished_at=None,
            last_heartbeat_at=now,
            lease_owner="listing-api-inline",
            lease_token=lease_token,
            lease_expires_at=now + timedelta(seconds=LISTING_LOADSHEET_SUBMIT_CLAIM_SECONDS),
            error_code=None,
            error_msg=None,
            error_details=None,
        )
        app_state.add_task_event(
            task_id=task_id,
            event_type="task.inline_submit_started",
            from_status=str(task.get("status") or ""),
            to_status="leased",
            stage="leased",
            message="Listing submission is being submitted to Takealot inline.",
            details={"target_id": task.get("target_id")},
            source="api",
            source_id="listing-api-inline",
        )
        return self.process_listing_submission_task(str(leased["id"]))

    def process_listing_task(
        self,
        task_id: str,
        *,
        adapter_factory: ListingAdapterFactory | None = None,
    ) -> dict[str, Any]:
        task = app_state.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
        if task["task_type"] == SUBMIT_LISTING_LOADSHEET_TASK_TYPE:
            return self.process_listing_submission_task(task_id)
        if task["task_type"] == SYNC_LISTING_SUBMISSION_STATUS_TASK_TYPE:
            return self.process_listing_submission_status_task(task_id)
        if task["task_type"] == FINALIZE_LISTING_OFFER_TASK_TYPE:
            return self.process_listing_finalize_offer_task(task_id, adapter_factory=adapter_factory)
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

    def process_listing_submission_task(self, task_id: str) -> dict[str, Any]:
        task = app_state.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
        if task["task_type"] != SUBMIT_LISTING_LOADSHEET_TASK_TYPE:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Task is not a loadsheet submission task")

        try:
            submission = self.catalog_repository.get_listing_submission(str(task.get("target_id") or ""))
        except ListingCatalogUnavailable as exc:
            return self._fail_submission_task(
                task=task,
                submission=None,
                error_code="LISTING_SUBMISSION_DB_UNAVAILABLE",
                error_msg=exc.message,
            )
        if submission is None:
            return self._fail_submission_task(
                task=task,
                submission=None,
                error_code="LISTING_SUBMISSION_NOT_FOUND",
                error_msg="Listing submission not found",
            )

        existing_submission_id = (
            submission.get("takealot_submission_id")
            or self.loadsheet_service.extract_submission_id(submission.get("official_response") or {})
        )
        if existing_submission_id:
            try:
                self.catalog_repository.update_listing_submission_official_response(
                    submission_id=submission["id"],
                    takealot_submission_id=str(existing_submission_id),
                    official_response=self.loadsheet_service.sanitize_official_response(submission.get("official_response") or {}),
                    official_status=submission.get("official_status") or "submitted",
                )
            except ListingCatalogUnavailable:
                pass
            return self._succeed_submission_task(
                task=task,
                submission=submission,
                message="Listing submission already has a Takealot submission id; skipping duplicate submit.",
                details={"takealot_submission_id": str(existing_submission_id), "idempotent": True},
            )

        claim_token = uuid4().hex
        claim_expires_at = datetime.now(UTC) + timedelta(seconds=LISTING_LOADSHEET_SUBMIT_CLAIM_SECONDS)
        try:
            # Claim before the external POST. If another worker already owns an
            # active claim, this task exits idempotently without calling Takealot.
            claimed_submission = self.catalog_repository.claim_listing_submission_submit(
                submission_id=submission["id"],
                task_id=task["id"],
                claim_token=claim_token,
                claim_expires_at=claim_expires_at,
            )
        except ListingCatalogUnavailable as exc:
            return self._fail_submission_task(
                task=task,
                submission=submission,
                error_code="LISTING_SUBMISSION_DB_UNAVAILABLE",
                error_msg=exc.message,
            )
        if claimed_submission is None:
            try:
                refreshed = self.catalog_repository.get_listing_submission(submission["id"])
            except ListingCatalogUnavailable:
                refreshed = None
            existing_submission_id = (
                (refreshed or {}).get("takealot_submission_id")
                or self.loadsheet_service.extract_submission_id((refreshed or {}).get("official_response") or {})
            )
            return self._succeed_submission_task(
                task=task,
                submission=refreshed or submission,
                message="Listing submission submit was already claimed or completed; skipping duplicate submit.",
                details={"takealot_submission_id": str(existing_submission_id or ""), "idempotent": True},
                stage=str((refreshed or submission).get("stage") or "submitted"),
            )
        submission = claimed_submission
        try:
            loadsheet_asset = self.catalog_repository.get_loadsheet_asset_for_submission(submission["id"])
        except ListingCatalogUnavailable as exc:
            return self._fail_submission_task(
                task=task,
                submission=submission,
                error_code="LISTING_SUBMISSION_DB_UNAVAILABLE",
                error_msg=exc.message,
                claim_token=claim_token,
            )
        if loadsheet_asset is None:
            return self._fail_submission_task(
                task=task,
                submission=submission,
                error_code="LISTING_LOADSHEET_ASSET_MISSING",
                error_msg="Generated loadsheet asset not found for listing submission.",
                claim_token=claim_token,
            )

        store = app_state.get_store(submission["store_id"])
        if store is None:
            return self._fail_submission_task(
                task=task,
                submission=submission,
                error_code="LISTING_STORE_NOT_FOUND",
                error_msg="Store not found for listing submission.",
                claim_token=claim_token,
            )
        credentials_payload = app_state.get_store_credentials(store["id"])
        if not credentials_payload or not credentials_payload.get("api_key"):
            return self._fail_submission_task(
                task=task,
                submission=submission,
                error_code="LISTING_STORE_CREDENTIALS_MISSING",
                error_msg="Store credentials unavailable for Takealot loadsheet submit.",
                claim_token=claim_token,
            )

        secrets = self._credential_secrets(credentials_payload)
        try:
            loadsheet_asset = self._ensure_official_loadsheet_asset(
                submission=submission,
                current_asset=loadsheet_asset,
                api_key=str(credentials_payload.get("api_key") or ""),
            )
        except ListingLoadsheetSubmitError as exc:
            return self._fail_submission_task(
                task=task,
                submission=submission,
                error_code="LISTING_OFFICIAL_LOADSHEET_GENERATION_FAILED",
                error_msg=exc.message,
                official_response=exc.official_response,
                claim_token=claim_token,
                secrets=secrets,
            )
        except ListingCatalogUnavailable as exc:
            return self._fail_submission_task(
                task=task,
                submission=submission,
                error_code="LISTING_OFFICIAL_LOADSHEET_ASSET_FAILED",
                error_msg=exc.message,
                claim_token=claim_token,
                secrets=secrets,
            )
        try:
            submit_result = self.loadsheet_service.submit_loadsheet_to_takealot(
                loadsheet_asset=loadsheet_asset,
                api_key=str(credentials_payload.get("api_key") or ""),
                submission_name=self._loadsheet_submission_file_name(submission),
            )
        except ListingLoadsheetSubmitError as exc:
            return self._fail_submission_task(
                task=task,
                submission=submission,
                error_code="LISTING_LOADSHEET_SUBMIT_FAILED",
                error_msg=exc.message,
                official_response=exc.official_response,
                claim_token=claim_token,
                secrets=secrets,
            )

        takealot_submission_id = str(submit_result.get("takealot_submission_id") or "").strip()
        official_response = submit_result.get("official_response") if isinstance(submit_result.get("official_response"), dict) else {}
        if not takealot_submission_id:
            return self._fail_submission_task(
                task=task,
                submission=submission,
                error_code="LISTING_LOADSHEET_SUBMISSION_ID_MISSING",
                error_msg="Takealot accepted the loadsheet request but did not return a submission id.",
                official_response=official_response,
                claim_token=claim_token,
                secrets=secrets,
            )

        official_status = str(
            official_response.get("submission_status")
            or official_response.get("status")
            or "submitted"
        )
        try:
            updated_submission = self.catalog_repository.mark_listing_submission_submit_succeeded(
                submission_id=submission["id"],
                task_id=task["id"],
                claim_token=claim_token,
                takealot_submission_id=takealot_submission_id,
                official_response=self._merge_official_response(
                    submission,
                    secrets=secrets,
                    loadsheet_response=official_response,
                    loadsheet_asset_id=loadsheet_asset.get("id"),
                ),
                official_status=official_status,
            )
        except ListingCatalogUnavailable as exc:
            return self._fail_submission_task(
                task=task,
                submission=submission,
                error_code="LISTING_SUBMISSION_WRITEBACK_FAILED",
                error_msg=exc.message,
                official_response=official_response,
                claim_token=claim_token,
                secrets=secrets,
            )
        if updated_submission is None:
            try:
                refreshed = self.catalog_repository.get_listing_submission(submission["id"])
            except ListingCatalogUnavailable:
                refreshed = None
            return self._succeed_submission_task(
                task=task,
                submission=refreshed or submission,
                message="Listing submission submit result was already written by another worker; writeback skipped.",
                details={"submission_id": submission["id"], "takealot_submission_id": takealot_submission_id, "idempotent": True},
            )

        return self._succeed_submission_task(
            task=task,
            submission=updated_submission,
            message="Takealot loadsheet submitted.",
            details={
                "submission_id": updated_submission["id"],
                "takealot_submission_id": takealot_submission_id,
            },
        )

    def process_listing_submission_status_task(self, task_id: str) -> dict[str, Any]:
        task = app_state.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
        if task["task_type"] != SYNC_LISTING_SUBMISSION_STATUS_TASK_TYPE:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Task is not a status sync task")

        try:
            submission = self.catalog_repository.get_listing_submission(str(task.get("target_id") or ""))
        except ListingCatalogUnavailable as exc:
            return self._fail_status_sync_task(
                task=task,
                submission=None,
                error_code="LISTING_SUBMISSION_DB_UNAVAILABLE",
                error_msg=exc.message,
            )
        if submission is None:
            return self._fail_status_sync_task(
                task=task,
                submission=None,
                error_code="LISTING_SUBMISSION_NOT_FOUND",
                error_msg="Listing submission not found",
            )

        takealot_submission_id = str(submission.get("takealot_submission_id") or "").strip()
        if not takealot_submission_id:
            return self._fail_status_sync_task(
                task=task,
                submission=submission,
                error_code="LISTING_SUBMISSION_ID_MISSING",
                error_msg="Listing submission has no Takealot submission id to sync.",
                update_submission=True,
            )

        store = app_state.get_store(submission["store_id"])
        credentials_payload = app_state.get_store_credentials(submission["store_id"]) if store is not None else None
        if store is None or not credentials_payload or not credentials_payload.get("api_key"):
            # Missing credentials are an environment/configuration issue. We
            # record the failure timestamp but do not replace any previously
            # approved review state with a failure.
            return self._fail_status_sync_task(
                task=task,
                submission=submission,
                error_code="LISTING_STORE_CREDENTIALS_MISSING",
                error_msg="Store credentials unavailable for Takealot status sync.",
                update_submission=True,
            )

        secrets = self._credential_secrets(credentials_payload)
        try:
            status_payload = self.loadsheet_service.get_submission_status(
                api_key=str(credentials_payload.get("api_key") or ""),
                takealot_submission_id=takealot_submission_id,
            )
        except ListingLoadsheetStatusError as exc:
            return self._fail_status_sync_task(
                task=task,
                submission=submission,
                error_code="LISTING_SUBMISSION_STATUS_SYNC_FAILED",
                error_msg=exc.message,
                official_response=exc.official_response,
                update_submission=True,
                secrets=secrets,
            )

        mapped = self.loadsheet_service.map_submission_status(status_payload)
        official_response = self._merge_official_response(
            submission,
            secrets=secrets,
            status_sync_response=status_payload,
            status_mapping=mapped,
        )
        try:
            # Repository applies the anti-regression policy atomically: finalized
            # offers remain offer_submitted, and approved reviews ignore stale
            # pending/unknown status reads from Takealot.
            updated_submission = self.catalog_repository.update_listing_submission_review_status(
                submission_id=submission["id"],
                status=str(mapped["status"]),
                stage=str(mapped["stage"]),
                review_status=str(mapped["review_status"]),
                official_status=str(mapped["official_status"]),
                official_response=official_response,
            )
        except ListingCatalogUnavailable as exc:
            return self._fail_status_sync_task(
                task=task,
                submission=submission,
                error_code="LISTING_SUBMISSION_STATUS_WRITEBACK_FAILED",
                error_msg=exc.message,
            )

        finalize_task_id: str | None = None
        if self.loadsheet_service.is_review_approved(updated_submission) and not updated_submission.get("takealot_offer_id"):
            try:
                # An approved content review is the only point where we enqueue
                # Offer finalization. This avoids creating offers for loadsheets
                # that are still pending, partial, or rejected.
                finalize_task = self._queue_listing_submission_worker_task_from_task(
                    task,
                    submission=updated_submission,
                    task_type=FINALIZE_LISTING_OFFER_TASK_TYPE,
                    label=f"Finalize Takealot offer for {updated_submission['sku']}",
                    next_action="Worker will create or associate the Takealot offer after approved review.",
                )
                finalize_task_id = finalize_task["id"]
            except Exception as exc:
                try:
                    self.catalog_repository.record_listing_submission_error(
                        submission_id=updated_submission["id"],
                        error_code="LISTING_FINALIZE_QUEUE_FAILED",
                        error_message="Approved review synced, but finalize offer task could not be queued.",
                        offer_error_message=str(exc)[:500],
                    )
                except ListingCatalogUnavailable:
                    pass
                return self._fail_status_sync_task(
                    task=task,
                    submission=updated_submission,
                    error_code="LISTING_FINALIZE_QUEUE_FAILED",
                    error_msg="Approved review synced, but finalize offer task could not be queued.",
                )

        return self._succeed_submission_task(
            task=task,
            submission=updated_submission,
            message=str(mapped.get("message") or "Takealot submission status synced."),
            details={
                "submission_id": updated_submission["id"],
                "takealot_submission_id": takealot_submission_id,
                "review_status": updated_submission.get("review_status"),
                "official_status": updated_submission.get("official_status"),
                "finalize_task_id": finalize_task_id,
            },
            stage=str(mapped.get("stage") or "submitted"),
        )

    def process_listing_finalize_offer_task(
        self,
        task_id: str,
        *,
        adapter_factory: ListingAdapterFactory | None = None,
    ) -> dict[str, Any]:
        task = app_state.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
        if task["task_type"] != FINALIZE_LISTING_OFFER_TASK_TYPE:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Task is not an offer finalize task")

        try:
            submission = self.catalog_repository.get_listing_submission(str(task.get("target_id") or ""))
        except ListingCatalogUnavailable as exc:
            return self._fail_offer_task(
                task=task,
                submission=None,
                error_code="LISTING_SUBMISSION_DB_UNAVAILABLE",
                error_msg=exc.message,
            )
        if submission is None:
            return self._fail_offer_task(
                task=task,
                submission=None,
                error_code="LISTING_SUBMISSION_NOT_FOUND",
                error_msg="Listing submission not found",
            )
        if submission.get("takealot_offer_id"):
            # This is the primary idempotency guard. Once an offer id is stored,
            # retries and duplicate tasks must not call Takealot again.
            return self._succeed_submission_task(
                task=task,
                submission=submission,
                message="Listing submission already has a Takealot offer id; skipping duplicate finalize.",
                details={
                    "submission_id": submission["id"],
                    "takealot_offer_id": submission.get("takealot_offer_id"),
                    "idempotent": True,
                },
                stage="offer_submitted",
            )
        if not self.loadsheet_service.is_review_approved(submission):
            # Offer creation is gated on approved review because Takealot can
            # accept a loadsheet upload long before content is approved.
            return self._fail_offer_task(
                task=task,
                submission=submission,
                error_code="LISTING_SUBMISSION_NOT_APPROVED",
                error_msg="Takealot content review is not approved; offer finalization skipped.",
                update_submission=False,
            )

        claim_token = uuid4().hex
        claim_expires_at = datetime.now(UTC) + timedelta(seconds=LISTING_OFFER_FINALIZE_CLAIM_SECONDS)
        try:
            finalizing_submission = self.catalog_repository.mark_listing_submission_offer_finalizing(
                submission_id=submission["id"],
                task_id=task["id"],
                claim_token=claim_token,
                claim_expires_at=claim_expires_at,
            )
        except ListingCatalogUnavailable as exc:
            return self._fail_offer_task(
                task=task,
                submission=submission,
                error_code="LISTING_SUBMISSION_WRITEBACK_FAILED",
                error_msg=exc.message,
            )
        if finalizing_submission is None:
            try:
                refreshed = self.catalog_repository.get_listing_submission(submission["id"])
            except ListingCatalogUnavailable:
                refreshed = None
            if refreshed and (refreshed.get("takealot_offer_id") or refreshed.get("finalized_at")):
                return self._succeed_submission_task(
                    task=task,
                    submission=refreshed,
                    message="Listing submission was finalized by another worker; skipping duplicate finalize.",
                    details={
                        "submission_id": refreshed["id"],
                        "takealot_offer_id": refreshed.get("takealot_offer_id"),
                        "idempotent": True,
                    },
                    stage="offer_submitted",
                )
            return self._succeed_submission_task(
                task=task,
                submission=submission,
                message="Listing submission offer finalization is already claimed or no longer eligible; skipping duplicate finalize.",
                details={"submission_id": submission["id"], "idempotent": True},
                stage=str((refreshed or submission).get("stage") or "offer_submitting"),
            )
        submission = finalizing_submission

        store = app_state.get_store(submission["store_id"])
        credentials_payload = app_state.get_store_credentials(submission["store_id"]) if store is not None else None
        if store is None or not credentials_payload or not credentials_payload.get("api_key"):
            return self._fail_offer_task(
                task=task,
                submission=submission,
                error_code="LISTING_STORE_CREDENTIALS_MISSING",
                error_msg="Store credentials unavailable for Takealot offer finalization.",
                update_submission=True,
                claim_token=claim_token,
            )

        secrets = self._credential_secrets(credentials_payload)
        credentials = AdapterCredentials(
            platform=store["platform"],
            api_key=str(credentials_payload.get("api_key") or ""),
            api_secret=str(credentials_payload.get("api_secret") or ""),
        )
        adapter = self._build_adapter(store=store, credentials=credentials, adapter_factory=adapter_factory)
        try:
            # Reuse the existing Takealot adapter so Offer writes follow the
            # same Marketplace API behavior as the rest of the ERP. The adapter
            # itself handles create-vs-update by barcode.
            offer_payload = adapter.create_or_update_offer(
                barcode=submission["barcode"],
                sku=submission["sku"],
                selling_price=float(submission.get("selling_price") or 0),
                rrp=submission.get("rrp"),
                quantity=int(submission.get("stock_quantity") or 0),
                minimum_leadtime_days=int(submission.get("minimum_leadtime_days") or 0),
                leadtime_merchant_warehouse_id=self._optional_int(
                    submission.get("seller_warehouse_id")
                    or credentials_payload.get("leadtime_merchant_warehouse_id")
                    or settings.takealot_leadtime_merchant_warehouse_id
                ),
            )
        except AdapterError as exc:
            return self._fail_offer_task(
                task=task,
                submission=submission,
                error_code="LISTING_OFFER_FINALIZE_FAILED",
                error_msg=str(exc),
                update_submission=True,
                claim_token=claim_token,
                secrets=secrets,
            )

        offer_payload = self.loadsheet_service.sanitize_official_response(offer_payload, secrets=secrets)
        takealot_offer_id = self._extract_offer_id(offer_payload)
        if not takealot_offer_id:
            return self._fail_offer_task(
                task=task,
                submission=submission,
                error_code="LISTING_OFFER_ID_MISSING",
                error_msg="Takealot offer response did not include an offer id.",
                official_response=self._merge_official_response(submission, secrets=secrets, offer_response=offer_payload),
                update_submission=True,
                claim_token=claim_token,
                secrets=secrets,
            )

        platform_product_id = self._extract_platform_product_id(offer_payload) or submission.get("platform_product_id")
        try:
            listing = app_state.upsert_store_listing(
                store_id=store["id"],
                external_listing_id=takealot_offer_id,
                platform_product_id=platform_product_id or submission.get("barcode"),
                sku=str(offer_payload.get("sku") or submission["sku"]),
                title=str(offer_payload.get("title") or submission["title"]),
                platform_price=float(offer_payload.get("selling_price") or submission.get("selling_price") or 0),
                stock_quantity=int(submission.get("stock_quantity") or 0),
                currency="ZAR",
                sync_status="synced",
                raw_payload={
                    **offer_payload,
                    "listing_submission_id": submission["id"],
                    "source": "listing_submission_finalize",
                },
            )
        except Exception as exc:
            return self._fail_offer_task(
                task=task,
                submission=submission,
                error_code="LISTING_STORE_LISTING_UPSERT_FAILED",
                error_msg=str(exc),
                official_response=self._merge_official_response(submission, secrets=secrets, offer_response=offer_payload),
                update_submission=True,
                claim_token=claim_token,
                secrets=secrets,
            )

        official_response = self._merge_official_response(
            submission,
            secrets=secrets,
            offer_response=offer_payload,
            linked_listing_id=listing["id"],
        )
        try:
            updated_submission = self.catalog_repository.mark_listing_submission_offer_finalized(
                submission_id=submission["id"],
                task_id=task["id"],
                claim_token=claim_token,
                takealot_offer_id=takealot_offer_id,
                listing_id=listing["id"],
                platform_product_id=platform_product_id or submission.get("barcode"),
                official_response=official_response,
            )
        except ListingCatalogUnavailable as exc:
            return self._fail_offer_task(
                task=task,
                submission=submission,
                error_code="LISTING_OFFER_WRITEBACK_FAILED",
                error_msg=exc.message,
                official_response=official_response,
                update_submission=True,
                claim_token=claim_token,
                secrets=secrets,
            )
        if updated_submission is None:
            try:
                refreshed = self.catalog_repository.get_listing_submission(submission["id"])
            except ListingCatalogUnavailable:
                refreshed = None
            return self._succeed_submission_task(
                task=task,
                submission=refreshed or submission,
                message="Listing submission offer was already finalized; writeback skipped.",
                details={"submission_id": submission["id"], "takealot_offer_id": takealot_offer_id, "idempotent": True},
                stage="offer_submitted",
            )

        return self._succeed_submission_task(
            task=task,
            submission=updated_submission,
            message="Takealot offer finalized and linked to local listing.",
            details={
                "submission_id": updated_submission["id"],
                "takealot_offer_id": takealot_offer_id,
                "listing_id": listing["id"],
            },
            stage="offer_submitted",
        )

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

    def _prepare_loadsheet_preview(
        self,
        actor: dict[str, Any],
        request: ListingLoadsheetPreviewRequest,
    ) -> dict[str, Any]:
        self._require_catalog_permission(actor)
        if self._is_memory_backend():
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="PostgreSQL unavailable")
        tenant_id = self._require_store_access(actor, request.store_id)

        try:
            category, catalog_ready = self.catalog_repository.get_category_requirements(request.category_id)
        except ListingCatalogUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message) from exc
        if category is None and not catalog_ready:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=CATALOG_IMPORT_REQUIRED_MESSAGE)
        if category is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Takealot category not found")

        category["path_en"] = self._category_path_en(category)
        category["path_zh"] = self.category_matcher.path_zh(category)
        allowed_attributes = self._normalize_attribute_definitions(
            category.get("required_attributes") or [],
            category.get("optional_attributes") or [],
            [],
            [],
        )

        try:
            assets = self.catalog_repository.list_listing_assets_by_ids(
                asset_ids=request.asset_ids,
                tenant_id=tenant_id,
            )
            brand = None
            brand_catalog_ready = True
            if (request.brand_id or "").strip() or request.brand_name.strip():
                brand, brand_catalog_ready = self.catalog_repository.find_brand(
                    brand_id=request.brand_id,
                    brand_name=request.brand_name,
                )
        except ListingCatalogUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message) from exc

        preview = self.loadsheet_service.build_preview(
            request=request,
            category=category,
            allowed_attributes=allowed_attributes,
            assets=assets,
            brand=brand,
            brand_catalog_ready=brand_catalog_ready,
        )
        return {
            "tenant_id": tenant_id,
            "category": category,
            "allowed_attributes": allowed_attributes,
            "assets": assets,
            "brand": brand,
            "preview": preview,
        }

    def _require_store_access(self, actor: dict[str, Any], store_id: str) -> str:
        if self._is_memory_backend():
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="PostgreSQL unavailable")
        try:
            tenant_id = self.catalog_repository.get_store_tenant_id(store_id)
        except ListingCatalogUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message) from exc
        if tenant_id is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store not found")
        require_tenant_access(actor, tenant_id, detail="Store not found")
        return tenant_id

    def _require_listing_submission_access(self, actor: dict[str, Any], submission_id: str) -> dict[str, Any]:
        self._require_catalog_permission(actor)
        if self._is_memory_backend():
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="PostgreSQL unavailable")
        tenant_id = None if actor.get("role") == "super_admin" else actor.get("tenant_id")
        try:
            submission = self.catalog_repository.get_listing_submission(submission_id, tenant_id=tenant_id)
        except ListingCatalogUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message) from exc
        if submission is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Listing submission not found")
        return submission

    def _queue_listing_submission_worker_task(
        self,
        actor: dict[str, Any],
        *,
        submission: dict[str, Any],
        task_type: str,
        request_headers: dict[str, str] | None,
        label: str,
        next_action: str,
    ) -> dict[str, Any]:
        return app_state.create_task(
            task_type=task_type,
            domain="listing",
            queue_name="listing-submissions",
            actor_user_id=actor.get("id"),
            actor_role=actor.get("role") or "operator",
            tenant_id=submission["tenant_id"],
            store_id=submission["store_id"],
            target_type="listing_submission",
            target_id=submission["id"],
            request_id=get_request_id(request_headers or {}),
            label=label,
            next_action=next_action,
        )

    def _queue_listing_submission_worker_task_from_task(
        self,
        task: dict[str, Any],
        *,
        submission: dict[str, Any],
        task_type: str,
        label: str,
        next_action: str,
    ) -> dict[str, Any]:
        return app_state.create_task(
            task_type=task_type,
            domain="listing",
            queue_name="listing-submissions",
            actor_user_id=task.get("actor_user_id"),
            actor_role=task.get("actor_role") or "operator",
            tenant_id=submission["tenant_id"],
            store_id=submission["store_id"],
            target_type="listing_submission",
            target_id=submission["id"],
            request_id=str(task.get("request_id") or ""),
            label=label,
            next_action=next_action,
        )

    def _to_submission_item(
        self,
        submission: dict[str, Any],
        *,
        loadsheet_asset: dict[str, Any] | None = None,
    ) -> ListingSubmissionItem:
        loadsheet_payload = submission.get("loadsheet_payload") or {}
        asset_payload = loadsheet_asset or loadsheet_payload.get("loadsheet_asset")
        return ListingSubmissionItem(
            submission_id=submission["id"],
            tenant_id=submission["tenant_id"],
            store_id=submission["store_id"],
            listing_id=submission.get("listing_id"),
            task_id=submission.get("task_id"),
            status=submission["status"],
            stage=submission["stage"],
            review_status=submission["review_status"],
            sku=submission["sku"],
            barcode=submission["barcode"],
            title=submission["title"],
            category_id=submission["category_id"],
            category_path=submission.get("category_path") or "",
            brand_id=submission.get("brand_id") or "",
            brand_name=submission.get("brand_name") or "",
            selling_price=submission.get("selling_price"),
            rrp=submission.get("rrp"),
            stock_quantity=int(submission.get("stock_quantity") or 0),
            minimum_leadtime_days=int(submission.get("minimum_leadtime_days") or 0),
            takealot_submission_id=submission.get("takealot_submission_id") or "",
            takealot_offer_id=submission.get("takealot_offer_id") or "",
            platform_product_id=submission.get("platform_product_id"),
            official_status=submission.get("official_status") or "",
            error_code=submission.get("error_code"),
            error_message=submission.get("error_message"),
            offer_error_message=submission.get("offer_error_message"),
            loadsheet_asset=self._to_loadsheet_asset(asset_payload) if asset_payload else None,
            validation_issues=loadsheet_payload.get("validation_issues") or [],
            warnings=loadsheet_payload.get("warnings") or [],
            created_at=submission["created_at"],
            updated_at=submission["updated_at"],
            submitted_at=submission.get("submitted_at"),
            last_checked_at=submission.get("last_checked_at"),
            last_status_sync_at=submission.get("last_status_sync_at"),
            finalized_at=submission.get("finalized_at"),
        )

    def _to_submission_create_response(
        self,
        *,
        submission: dict[str, Any],
        task_id: str | None,
        message: str,
        reused_existing: bool = False,
        submit_immediately: bool = False,
        task: dict[str, Any] | None = None,
    ) -> ListingSubmissionCreateResponse:
        loadsheet_payload = submission.get("loadsheet_payload") or {}
        asset_payload = loadsheet_payload.get("loadsheet_asset")
        takealot_submission_id = str(submission.get("takealot_submission_id") or "")
        task_status = str((task or {}).get("status") or "")
        submit_succeeded: bool | None = None
        if submit_immediately:
            if takealot_submission_id:
                submit_succeeded = True
            elif task_status == "failed":
                submit_succeeded = False

        return ListingSubmissionCreateResponse(
            submission_id=submission["id"],
            task_id=task_id,
            status=submission["status"],
            stage=submission["stage"],
            message=message,
            reused_existing=reused_existing,
            submit_immediately=submit_immediately,
            submit_succeeded=submit_succeeded,
            takealot_submission_id=takealot_submission_id,
            official_status=str(submission.get("official_status") or ""),
            error_code=submission.get("error_code") or (task or {}).get("error_code"),
            error_message=submission.get("error_message") or (task or {}).get("error_msg"),
            loadsheet_asset=self._to_loadsheet_asset(asset_payload) if asset_payload else None,
            validation_issues=loadsheet_payload.get("validation_issues") or [],
            warnings=loadsheet_payload.get("warnings") or [],
        )

    def _submission_create_message(
        self,
        *,
        submission: dict[str, Any],
        task: dict[str, Any] | None,
        fallback: str,
    ) -> str:
        takealot_submission_id = str(submission.get("takealot_submission_id") or "")
        if takealot_submission_id:
            return "Takealot loadsheet submitted successfully."
        if task and task.get("status") == "failed":
            return str(task.get("error_msg") or submission.get("error_message") or "Takealot loadsheet submit failed.")
        return fallback

    def _get_submission_or_current(self, submission: dict[str, Any]) -> dict[str, Any]:
        try:
            return self.catalog_repository.get_listing_submission(submission["id"]) or submission
        except ListingCatalogUnavailable:
            return submission

    @staticmethod
    def _to_submission_status_item(
        submission: dict[str, Any],
        *,
        task_id: str | None = None,
        message: str | None = None,
        warnings: list[str] | None = None,
    ) -> ListingSubmissionStatusItem:
        return ListingSubmissionStatusItem(
            submission_id=submission["id"],
            store_id=submission["store_id"],
            task_id=task_id or submission.get("task_id"),
            status=submission["status"],
            stage=submission["stage"],
            review_status=submission["review_status"],
            official_status=submission.get("official_status") or "",
            takealot_submission_id=submission.get("takealot_submission_id") or "",
            takealot_offer_id=submission.get("takealot_offer_id") or "",
            listing_id=submission.get("listing_id"),
            platform_product_id=submission.get("platform_product_id"),
            last_checked_at=submission.get("last_checked_at"),
            last_status_sync_at=submission.get("last_status_sync_at"),
            finalized_at=submission.get("finalized_at"),
            message=message,
            warnings=warnings or [],
        )

    @staticmethod
    def _to_loadsheet_asset(asset: dict[str, Any]) -> dict[str, Any]:
        return {
            "asset_id": asset.get("asset_id") or asset.get("id"),
            "storage_path": asset.get("storage_path"),
            "public_url": asset.get("public_url"),
            "content_type": asset.get("content_type") or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "size_bytes": int(asset.get("size_bytes") or 0),
            "checksum_sha256": asset.get("checksum_sha256") or "",
        }

    @staticmethod
    def _dynamic_attribute_values_to_dict(values: Any) -> dict[str, Any]:
        if isinstance(values, dict):
            return dict(values)
        result: dict[str, Any] = {}
        if not isinstance(values, list):
            return result
        for item in values:
            if hasattr(item, "model_dump"):
                item = item.model_dump()
            if not isinstance(item, dict):
                continue
            key = item.get("key")
            if key not in (None, ""):
                result[str(key)] = item.get("value")
        return result

    @staticmethod
    def _loadsheet_submission_file_name(submission: dict[str, Any]) -> str:
        safe_sku = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(submission.get("sku") or "")).strip("-") or "listing"
        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        return f"{safe_sku}_{timestamp}.xlsm"

    @staticmethod
    def _submission_idempotency_key(
        *,
        tenant_id: str,
        store_id: str,
        generated_fields: dict[str, Any],
        request_headers: dict[str, str],
    ) -> str:
        headers_by_name = {str(key).lower(): str(value).strip() for key, value in request_headers.items()}
        client_key = headers_by_name.get("idempotency-key") or headers_by_name.get("x-idempotency-key")
        if client_key:
            digest = hashlib.sha256(f"{tenant_id}:{store_id}:{client_key}".encode("utf-8")).hexdigest()
            return f"client:{digest}"
        payload = {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "sku": generated_fields.get("sku"),
            "barcode": generated_fields.get("barcode"),
            "category_id": generated_fields.get("category_id"),
            "brand_id": generated_fields.get("brand_id"),
            "brand_name": generated_fields.get("brand_name"),
            "title": generated_fields.get("title"),
            "subtitle": generated_fields.get("subtitle"),
            "description": generated_fields.get("description"),
            "whats_in_the_box": generated_fields.get("whats_in_the_box"),
            "selling_price": generated_fields.get("selling_price"),
            "rrp": generated_fields.get("rrp"),
            "stock_quantity": generated_fields.get("stock_quantity"),
            "minimum_leadtime_days": generated_fields.get("minimum_leadtime_days"),
            "seller_warehouse_id": generated_fields.get("seller_warehouse_id"),
            "length_cm": generated_fields.get("length_cm"),
            "width_cm": generated_fields.get("width_cm"),
            "height_cm": generated_fields.get("height_cm"),
            "weight_g": generated_fields.get("weight_g"),
            "image_urls": generated_fields.get("image_urls") or [],
            "dynamic_attributes": generated_fields.get("dynamic_attributes") or [],
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        return f"listing:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"

    @staticmethod
    def _credential_secrets(credentials_payload: dict[str, Any] | None) -> list[str]:
        if not credentials_payload:
            return []
        return [
            str(value).strip()
            for value in (
                credentials_payload.get("api_key"),
                credentials_payload.get("api_secret"),
                credentials_payload.get("access_token"),
                credentials_payload.get("token"),
            )
            if str(value or "").strip()
        ]

    @staticmethod
    def _merge_official_response(
        submission: dict[str, Any],
        *,
        secrets: list[str] | None = None,
        **entries: Any,
    ) -> dict[str, Any]:
        official_response = dict(submission.get("official_response") or {})
        for key, value in entries.items():
            if value is not None:
                official_response[key] = ListingLoadsheetService.sanitize_official_response(value, secrets=secrets)
        return ListingLoadsheetService.sanitize_official_response(official_response, secrets=secrets)

    def _ensure_official_loadsheet_asset(
        self,
        *,
        submission: dict[str, Any],
        current_asset: dict[str, Any] | None,
        api_key: str,
    ) -> dict[str, Any]:
        if self.loadsheet_service.is_official_template_asset(current_asset):
            return current_asset or {}

        category, catalog_ready = self.catalog_repository.get_category_requirements(int(submission["category_id"]))
        if category is None and not catalog_ready:
            raise ListingLoadsheetSubmitError(CATALOG_IMPORT_REQUIRED_MESSAGE)
        if category is None:
            raise ListingLoadsheetSubmitError("Takealot category not found for official loadsheet generation.")

        category["path_en"] = self._category_path_en(category)
        category["path_zh"] = self.category_matcher.path_zh(category)
        content_payload = submission.get("content_payload") if isinstance(submission.get("content_payload"), dict) else {}
        weight_g = content_payload.get("weight_g")
        if weight_g in (None, "") and submission.get("weight_kg") is not None:
            try:
                weight_g = float(submission["weight_kg"]) * 1000
            except (TypeError, ValueError):
                weight_g = None

        request = ListingLoadsheetPreviewRequest(
            store_id=str(submission["store_id"]),
            category_id=int(submission["category_id"]),
            brand_id=str(submission.get("brand_id") or content_payload.get("brand_id") or ""),
            brand_name=str(submission.get("brand_name") or content_payload.get("brand_name") or ""),
            sku=str(submission.get("sku") or content_payload.get("sku") or ""),
            barcode=str(submission.get("barcode") or content_payload.get("barcode") or ""),
            title=str(submission.get("title") or content_payload.get("title") or ""),
            subtitle=str(submission.get("subtitle") or content_payload.get("subtitle") or ""),
            description=str(submission.get("description") or content_payload.get("description") or ""),
            whats_in_the_box=str(submission.get("whats_in_the_box") or content_payload.get("whats_in_the_box") or ""),
            selling_price=submission.get("selling_price") or content_payload.get("selling_price"),
            rrp=submission.get("rrp") or content_payload.get("rrp"),
            stock_quantity=int(submission.get("stock_quantity") or content_payload.get("stock_quantity") or 0),
            minimum_leadtime_days=int(
                submission.get("minimum_leadtime_days") or content_payload.get("minimum_leadtime_days") or 0
            ),
            seller_warehouse_id=str(
                submission.get("seller_warehouse_id") or content_payload.get("seller_warehouse_id") or ""
            ),
            length_cm=submission.get("length_cm") or content_payload.get("length_cm"),
            width_cm=submission.get("width_cm") or content_payload.get("width_cm"),
            height_cm=submission.get("height_cm") or content_payload.get("height_cm"),
            weight_g=weight_g,
            image_urls=submission.get("image_urls") or content_payload.get("image_urls") or [],
            dynamic_attributes=submission.get("dynamic_attributes") or content_payload.get("dynamic_attributes") or {},
        )
        allowed_attributes = self._normalize_attribute_definitions(
            category.get("required_attributes") or [],
            category.get("optional_attributes") or [],
            [],
            [],
        )
        brand = None
        if request.brand_id or request.brand_name:
            brand = {"brand_id": request.brand_id or None, "brand_name": request.brand_name}

        preview = self.loadsheet_service.build_preview(
            request=request,
            category=category,
            allowed_attributes=allowed_attributes,
            assets=[],
            brand=brand,
            brand_catalog_ready=True,
            api_key=api_key,
        )
        if not preview.get("valid"):
            issue_messages = [
                str(issue.get("message") or issue)
                for issue in preview.get("issues") or []
                if isinstance(issue, dict)
            ]
            raise ListingLoadsheetSubmitError(
                "Official Takealot loadsheet generation failed: " + "; ".join(issue_messages[:3])
            )

        generated_asset = self.catalog_repository.insert_listing_asset(
            tenant_id=str(submission["tenant_id"]),
            store_id=str(submission["store_id"]),
            submission_id=str(submission["id"]),
            asset=self.loadsheet_service.asset_payload_for_generated_loadsheet(preview["loadsheet_asset"] or {}),
        )
        loadsheet_payload = dict(submission.get("loadsheet_payload") or {})
        loadsheet_payload.update(
            {
                "loadsheet_asset": self._to_loadsheet_asset(generated_asset),
                "validation_issues": preview.get("issues") or [],
                "warnings": preview.get("warnings") or [],
                "missing_required_fields": preview.get("missing_required_fields") or [],
                "generated_fields": preview.get("generated_fields") or loadsheet_payload.get("generated_fields") or {},
            }
        )
        self.catalog_repository.update_listing_submission_loadsheet_payload(
            submission_id=str(submission["id"]),
            loadsheet_payload=loadsheet_payload,
        )
        return generated_asset

    @staticmethod
    def _extract_offer_id(payload: dict[str, Any]) -> str:
        for key in ("offer_id", "offerId", "id", "takealot_offer_id", "takealotOfferId"):
            value = payload.get(key)
            if value not in (None, ""):
                return str(value).strip()
        nested = payload.get("offer")
        if isinstance(nested, dict):
            return ListingService._extract_offer_id(nested)
        return ""

    @staticmethod
    def _extract_platform_product_id(payload: dict[str, Any]) -> str | None:
        for key in ("productline_id", "productlineId", "product_line_id", "tsin_id", "tsinId"):
            value = payload.get(key)
            if value not in (None, ""):
                return str(value).strip()
        nested = payload.get("offer")
        if isinstance(nested, dict):
            return ListingService._extract_platform_product_id(nested)
        return None

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _succeed_submission_task(
        self,
        *,
        task: dict[str, Any],
        submission: dict[str, Any],
        message: str,
        details: dict[str, Any],
        stage: str = "submitted",
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        updated = app_state.update_task(
            task["id"],
            status="succeeded",
            stage=stage,
            progress_percent=100,
            finished_at=now,
            last_heartbeat_at=now,
            lease_owner=None,
            lease_token=None,
            lease_expires_at=None,
            error_code=None,
            error_msg=None,
            error_details=details,
        )
        app_state.add_task_event(
            task_id=task["id"],
            event_type="task.succeeded",
            from_status=task["status"],
            to_status="succeeded",
            stage=stage,
            message=message,
            details={"submission_id": submission["id"], **details},
            source="worker",
            source_id=LISTING_WORKER_SOURCE_ID,
        )
        return updated

    def _fail_submission_task(
        self,
        *,
        task: dict[str, Any],
        submission: dict[str, Any] | None,
        error_code: str,
        error_msg: str,
        official_response: dict[str, Any] | None = None,
        claim_token: str | None = None,
        secrets: list[str] | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        safe_error_msg = self.loadsheet_service.sanitize_text(error_msg, secrets=secrets)
        safe_official_response = (
            self.loadsheet_service.sanitize_official_response(official_response, secrets=secrets)
            if official_response is not None
            else None
        )
        if submission is not None:
            try:
                if claim_token:
                    self.catalog_repository.mark_listing_submission_submit_failed(
                        submission_id=submission["id"],
                        task_id=task["id"],
                        claim_token=claim_token,
                        error_code=error_code,
                        error_message=safe_error_msg,
                        official_response=safe_official_response,
                    )
                # Without a row claim, this worker has no authority to write a
                # submit failure. A duplicate or stale task could otherwise
                # overwrite another worker's successful Takealot submission id.
            except ListingCatalogUnavailable:
                pass
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
            error_msg=safe_error_msg,
            error_details={
                "submission_id": submission["id"] if submission is not None else task.get("target_id"),
                "official_response": safe_official_response,
            },
        )
        app_state.add_task_event(
            task_id=task["id"],
            event_type="task.failed",
            from_status=task["status"],
            to_status="failed",
            stage="failed",
            message=safe_error_msg,
            details={"submission_id": submission["id"] if submission is not None else task.get("target_id"), "reason": error_code},
            source="worker",
            source_id=LISTING_WORKER_SOURCE_ID,
        )
        return updated

    def _fail_status_sync_task(
        self,
        *,
        task: dict[str, Any],
        submission: dict[str, Any] | None,
        error_code: str,
        error_msg: str,
        official_response: dict[str, Any] | None = None,
        update_submission: bool = False,
        secrets: list[str] | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        safe_error_msg = self.loadsheet_service.sanitize_text(error_msg, secrets=secrets)
        safe_official_response = (
            self.loadsheet_service.sanitize_official_response(official_response, secrets=secrets)
            if official_response is not None
            else None
        )
        if update_submission and submission is not None:
            try:
                # Sync failures are recorded without changing status/stage.
                # This preserves a previous approved/rejected outcome if a
                # later poll fails because PostgreSQL, credentials, or Takealot
                # are temporarily unavailable.
                self.catalog_repository.record_listing_submission_error(
                    submission_id=submission["id"],
                    error_code=error_code,
                    error_message=safe_error_msg,
                    official_response=(
                        self._merge_official_response(submission, secrets=secrets, status_sync_error=safe_official_response)
                        if safe_official_response
                        else None
                    ),
                    last_status_sync_at=True,
                )
            except ListingCatalogUnavailable:
                pass
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
            error_msg=safe_error_msg,
            error_details={
                "submission_id": submission["id"] if submission is not None else task.get("target_id"),
                "official_response": safe_official_response,
            },
        )
        app_state.add_task_event(
            task_id=task["id"],
            event_type="task.failed",
            from_status=task["status"],
            to_status="failed",
            stage="failed",
            message=safe_error_msg,
            details={"submission_id": submission["id"] if submission is not None else task.get("target_id"), "reason": error_code},
            source="worker",
            source_id=LISTING_WORKER_SOURCE_ID,
        )
        return updated

    def _fail_offer_task(
        self,
        *,
        task: dict[str, Any],
        submission: dict[str, Any] | None,
        error_code: str,
        error_msg: str,
        official_response: dict[str, Any] | None = None,
        update_submission: bool = False,
        claim_token: str | None = None,
        secrets: list[str] | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        safe_error_msg = self.loadsheet_service.sanitize_text(error_msg, secrets=secrets)
        safe_official_response = (
            self.loadsheet_service.sanitize_official_response(official_response, secrets=secrets)
            if official_response is not None
            else None
        )
        if update_submission and submission is not None:
            try:
                # Offer failures keep review_status intact. An approved review
                # remains approved even when the later Offer API call fails.
                # The claim token prevents a late failure from overwriting a
                # different worker's successful offer finalization.
                if claim_token:
                    self.catalog_repository.mark_listing_submission_offer_failed(
                        submission_id=submission["id"],
                        task_id=task["id"],
                        claim_token=claim_token,
                        error_code=error_code,
                        error_message=safe_error_msg,
                        official_response=safe_official_response,
                    )
            except ListingCatalogUnavailable:
                pass
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
            error_msg=safe_error_msg,
            error_details={
                "submission_id": submission["id"] if submission is not None else task.get("target_id"),
                "official_response": safe_official_response,
            },
        )
        app_state.add_task_event(
            task_id=task["id"],
            event_type="task.failed",
            from_status=task["status"],
            to_status="failed",
            stage="failed",
            message=safe_error_msg,
            details={"submission_id": submission["id"] if submission is not None else task.get("target_id"), "reason": error_code},
            source="worker",
            source_id=LISTING_WORKER_SOURCE_ID,
        )
        return updated

    def _validate_ai_generated_content(
        self,
        payload: dict[str, Any],
        *,
        request: ListingAiAutopilotRequest,
        category: dict[str, Any],
        allowed_attributes: list[dict[str, Any]],
    ) -> tuple[dict[str, Any] | None, list[str]]:
        warnings: list[str] = []
        if not isinstance(payload, dict):
            return None, ["AI did not return a JSON object."]
        try:
            category_id = int(payload.get("category_id"))
        except (TypeError, ValueError):
            return None, ["AI response did not include a valid category_id."]
        if category_id != request.category_id:
            return None, ["AI attempted to change category_id."]

        required_text_fields = ("title", "subtitle", "description", "whats_in_the_box")
        text_values: dict[str, str] = {}
        for field in required_text_fields:
            value = payload.get(field)
            if not isinstance(value, str) or not value.strip():
                return None, [f"AI response missing required field: {field}."]
            cleaned = self._box_text(value) if field == "whats_in_the_box" else self._plain_text(value)
            if field == "description" and self._contains_html(cleaned):
                return None, ["AI response description contained HTML."]
            if not self._looks_english(cleaned):
                return None, [f"AI response field is not English enough: {field}."]
            text_values[field] = cleaned
        if not self._valid_whats_in_the_box(text_values["whats_in_the_box"]):
            return None, ["AI response whats_in_the_box did not use '<quantity> x <Product Name>' lines."]

        dimensions = self._extract_positive_dimensions(payload)
        if dimensions is None:
            return None, ["AI response dimensions or weight were missing or non-positive."]

        dynamic_attributes, attr_warnings, attributes_valid = self._normalize_dynamic_attribute_values(
            payload.get("dynamic_attributes"),
            allowed_attributes,
            source="ai",
            strict=True,
        )
        warnings.extend(attr_warnings)
        if not attributes_valid:
            return None, warnings or ["AI response dynamic_attributes were not allowed by category requirements."]

        return {
            "category_id": request.category_id,
            "category_path_en": category["path_en"],
            "category_path_zh": category["path_zh"],
            "title": self._bounded_text(text_values["title"], 150),
            "subtitle": self._bounded_text(text_values["subtitle"], 150),
            "description": text_values["description"],
            "whats_in_the_box": text_values["whats_in_the_box"],
            "length_cm": dimensions["length_cm"],
            "width_cm": dimensions["width_cm"],
            "height_cm": dimensions["height_cm"],
            "weight_g": dimensions["weight_g"],
            "dynamic_attributes": dynamic_attributes,
        }, warnings

    def _fallback_generated_content(
        self,
        *,
        request: ListingAiAutopilotRequest,
        category: dict[str, Any],
        allowed_attributes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        product_name = self._fallback_product_name(request, category)
        dimensions = self._fallback_dimensions(product_name, category)
        dynamic_attributes, _, _ = self._normalize_dynamic_attribute_values(
            None,
            allowed_attributes,
            source="fallback",
            strict=False,
        )
        return {
            "category_id": request.category_id,
            "category_path_en": category["path_en"],
            "category_path_zh": category["path_zh"],
            "title": self._bounded_text(product_name, 150),
            "subtitle": self._bounded_text(f"Practical {self._category_leaf_name(category)} for everyday use", 150),
            "description": (
                f"This {product_name} is a practical choice for everyday use. "
                "It is intended for customers looking for a simple product in this category. "
                "Please review the product images, specifications, and package contents before purchase."
            ),
            "whats_in_the_box": f"1 x {product_name}",
            "length_cm": dimensions["length_cm"],
            "width_cm": dimensions["width_cm"],
            "height_cm": dimensions["height_cm"],
            "weight_g": dimensions["weight_g"],
            "dynamic_attributes": dynamic_attributes,
        }

    def _normalize_attribute_definitions(
        self,
        db_required: list[Any],
        db_optional: list[Any],
        request_required: list[Any],
        request_optional: list[Any],
    ) -> list[dict[str, Any]]:
        definitions: dict[str, dict[str, Any]] = {}
        for required, values in (
            (True, db_required),
            (False, db_optional),
            (True, request_required),
            (False, request_optional),
        ):
            for item in values:
                definition = self._normalize_attribute_definition(item, required=required)
                if definition is None:
                    continue
                key = definition["key"]
                existing = definitions.get(key)
                if existing is None:
                    definitions[key] = definition
                else:
                    existing["required"] = bool(existing.get("required")) or required
                    if not existing.get("options") and definition.get("options"):
                        existing["options"] = definition["options"]
                    if existing.get("value_type") in ("text", "") and definition.get("value_type"):
                        existing["value_type"] = definition["value_type"]
        return list(definitions.values())

    @staticmethod
    def _normalize_attribute_definition(item: Any, *, required: bool) -> dict[str, Any] | None:
        if isinstance(item, str):
            key = item.strip()
            if not key:
                return None
            return {
                "key": key,
                "label": key,
                "value_type": "text",
                "options": [],
                "required": required,
            }
        if not isinstance(item, dict):
            return None
        key = (
            item.get("key")
            or item.get("name")
            or item.get("attribute_key")
            or item.get("attribute_name")
            or item.get("field_name")
            or item.get("display_name")
            or item.get("id")
        )
        key = str(key or "").strip()
        if not key:
            return None
        raw_type = str(
            item.get("value_type")
            or item.get("type")
            or item.get("data_type")
            or item.get("input_type")
            or "text"
        ).strip().lower()
        if raw_type in {"bool", "boolean", "checkbox"}:
            value_type = "boolean"
        elif raw_type in {"int", "integer", "number", "numeric", "decimal", "float"}:
            value_type = "number"
        elif raw_type in {"select", "enum", "dropdown", "option"}:
            value_type = "select"
        else:
            value_type = "text"
        options = ListingService._normalize_attribute_options(
            item.get("options")
            or item.get("values")
            or item.get("allowed_values")
            or item.get("enum")
            or []
        )
        if options and value_type == "text":
            value_type = "select"
        return {
            "key": key,
            "label": str(item.get("label") or item.get("display_name") or key),
            "value_type": value_type,
            "options": options,
            "required": bool(item.get("required", required)),
        }

    @staticmethod
    def _normalize_attribute_options(values: Any) -> list[Any]:
        if isinstance(values, str):
            values = [part.strip() for part in re.split(r"[\n;,|]+", values) if part.strip()]
        if not isinstance(values, list):
            return []
        options: list[Any] = []
        for value in values:
            if isinstance(value, dict):
                option = value.get("value") or value.get("name") or value.get("label") or value.get("id")
            else:
                option = value
            if option not in (None, "") and option not in options:
                options.append(option)
        return options

    def _normalize_dynamic_attribute_values(
        self,
        raw_values: Any,
        allowed_attributes: list[dict[str, Any]],
        *,
        source: str,
        strict: bool,
    ) -> tuple[list[dict[str, Any]], list[str], bool]:
        warnings: list[str] = []
        allowed_by_key = {definition["key"]: definition for definition in allowed_attributes}
        provided = self._dynamic_attribute_payload_to_dict(raw_values)
        if strict and raw_values is not None and provided is None:
            return [], ["AI dynamic_attributes must be an object or a list of key/value objects."], False
        provided = provided or {}
        result: list[dict[str, Any]] = []
        valid = True

        for key in provided:
            if key not in allowed_by_key:
                valid = False
                warnings.append(f"AI returned disallowed dynamic attribute: {key}.")
        for definition in allowed_attributes:
            key = definition["key"]
            has_value = key in provided
            if has_value:
                value = provided[key]
                value, value_valid = self._coerce_attribute_value(value, definition)
                if not value_valid:
                    valid = False
                    warnings.append(f"AI returned invalid value for dynamic attribute: {key}.")
            elif strict and definition.get("required"):
                valid = False
                warnings.append(f"AI omitted required dynamic attribute: {key}.")
                value = None
            else:
                value = self._fallback_attribute_value(definition)
            if has_value or not strict:
                result.append(
                    {
                        "key": key,
                        "value": value,
                        "value_type": definition.get("value_type"),
                        "source": source,
                        "warning": None if has_value else "fallback default",
                    }
                )
        return result, warnings, valid

    @staticmethod
    def _dynamic_attribute_payload_to_dict(raw_values: Any) -> dict[str, Any] | None:
        if raw_values in (None, ""):
            return {}
        if isinstance(raw_values, dict):
            return {str(key): value for key, value in raw_values.items()}
        if isinstance(raw_values, list):
            result: dict[str, Any] = {}
            for item in raw_values:
                if not isinstance(item, dict):
                    return None
                key = item.get("key") or item.get("name") or item.get("attribute_key")
                if key in (None, ""):
                    return None
                result[str(key)] = item.get("value")
            return result
        return None

    @staticmethod
    def _coerce_attribute_value(value: Any, definition: dict[str, Any]) -> tuple[Any, bool]:
        options = definition.get("options") or []
        value_type = definition.get("value_type") or "text"
        if options:
            for option in options:
                if str(value).strip().lower() == str(option).strip().lower():
                    return option, True
            return None, False
        if value_type == "boolean":
            if isinstance(value, bool):
                return "Yes" if value else "No", True
            normalized = str(value).strip().lower()
            if normalized in {"yes", "true", "1"}:
                return "Yes", True
            if normalized in {"no", "false", "0"}:
                return "No", True
            return None, False
        if value_type == "number":
            if value in (None, ""):
                return None, True
            try:
                return float(value), True
            except (TypeError, ValueError):
                return None, False
        return "" if value is None else str(value).strip(), True

    @staticmethod
    def _fallback_attribute_value(definition: dict[str, Any]) -> Any:
        options = definition.get("options") or []
        value_type = definition.get("value_type") or "text"
        if options:
            return options[0]
        if value_type == "boolean":
            return "No"
        if value_type == "number":
            return None
        return ""

    @staticmethod
    def _extract_positive_dimensions(payload: dict[str, Any]) -> dict[str, Any] | None:
        try:
            length_cm = float(payload.get("length_cm"))
            width_cm = float(payload.get("width_cm"))
            height_cm = float(payload.get("height_cm"))
            weight_g = int(round(float(payload.get("weight_g"))))
        except (TypeError, ValueError):
            return None
        if min(length_cm, width_cm, height_cm, weight_g) <= 0:
            return None
        return {
            "length_cm": round(length_cm, 2),
            "width_cm": round(width_cm, 2),
            "height_cm": round(height_cm, 2),
            "weight_g": weight_g,
        }

    @staticmethod
    def _fallback_dimensions(product_name: str, category: dict[str, Any]) -> dict[str, Any]:
        text = f"{product_name} {category.get('path_en') or ''} {category.get('lowest_category_name') or ''}".lower()
        if "phone case" in text:
            return {"length_cm": 18.0, "width_cm": 10.0, "height_cm": 2.0, "weight_g": 100}
        if "fishing rod" in text:
            return {"length_cm": 120.0, "width_cm": 8.0, "height_cm": 8.0, "weight_g": 500}
        if "hammock" in text:
            return {"length_cm": 35.0, "width_cm": 25.0, "height_cm": 10.0, "weight_g": 900}
        if "lantern" in text:
            return {"length_cm": 18.0, "width_cm": 12.0, "height_cm": 12.0, "weight_g": 450}
        if "toothbrush" in text:
            return {"length_cm": 25.0, "width_cm": 8.0, "height_cm": 8.0, "weight_g": 350}
        return {"length_cm": 20.0, "width_cm": 15.0, "height_cm": 10.0, "weight_g": 500}

    @staticmethod
    def _fallback_product_name(
        request: ListingAiAutopilotRequest,
        category: dict[str, Any],
    ) -> str:
        description = request.product_description.strip()
        ascii_words = re.findall(r"[A-Za-z0-9][A-Za-z0-9&+,' -]{1,80}", description)
        base = ascii_words[0].strip(" -,.") if ascii_words else ListingService._category_leaf_name(category)
        if not base:
            base = "Product"
        brand = request.brand_name.strip()
        if brand and brand.lower() not in base.lower():
            base = f"{brand} {base}"
        return ListingService._bounded_text(base.title(), 150)

    @staticmethod
    def _category_leaf_name(category: dict[str, Any]) -> str:
        return (
            str(category.get("lowest_category_name") or "").strip()
            or str(category.get("main_category_name") or "").strip()
            or "Product"
        )

    @staticmethod
    def _category_path_en(category: dict[str, Any]) -> str:
        existing = str(category.get("path_en") or "").strip()
        if existing:
            return existing
        return " > ".join(
            part
            for part in [
                str(category.get("division") or "").strip(),
                str(category.get("department") or "").strip(),
                str(category.get("main_category_name") or "").strip(),
                str(category.get("lowest_category_name") or "").strip(),
            ]
            if part
        )

    def _with_category_display_paths(
        self,
        items: list[dict[str, Any]],
        *,
        use_ai_translation: bool = False,
    ) -> list[dict[str, Any]]:
        display_items: list[dict[str, Any]] = []
        for item in items:
            row = dict(item)
            translation_source = str(row.get("translation_source") or "").strip()
            row["path_en"] = self._category_path_en(row)
            row["path_zh"] = self.category_matcher.path_zh(row)
            row["translation_source"] = translation_source or "rules"
            display_items.append(row)
        if use_ai_translation and self.ai_service.enabled and display_items:
            paths = [
                row["path_en"]
                for row in display_items
                if row.get("path_en") and row.get("translation_source") != "catalog"
            ]
            translations = self.ai_service.translate_category_paths(paths)
            for row in display_items:
                translated = translations.get(row.get("path_en") or "")
                if not translated:
                    continue
                # AI improves Chinese display text only. The official English
                # path and category_id remain the database source of truth.
                row["path_zh"] = translated
                row["translation_source"] = "ai"
        return display_items

    def _category_search_items_from_suggestions(self, suggestions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for suggestion in suggestions:
            row = {
                "id": str(suggestion.get("id") or suggestion.get("category_id") or ""),
                "category_id": int(suggestion.get("category_id") or 0),
                "division": suggestion.get("division") or "",
                "department": suggestion.get("department") or "",
                "main_category_id": int(suggestion.get("main_category_id") or 0),
                "main_category_name": suggestion.get("main_category_name") or "",
                "lowest_category_name": suggestion.get("lowest_category_name") or "",
                "lowest_category_raw": suggestion.get("lowest_category_raw") or "",
                "path_en": suggestion.get("path_en") or "",
                "path_zh": suggestion.get("path_zh") or "",
                "min_required_images": int(suggestion.get("min_required_images") or 0),
                "compliance_certificates": suggestion.get("compliance_certificates") or [],
                "image_requirement_texts": suggestion.get("image_requirement_texts") or [],
                "required_attributes": suggestion.get("required_attributes") or [],
                "optional_attributes": suggestion.get("optional_attributes") or [],
                "loadsheet_template_id": suggestion.get("loadsheet_template_id"),
                "loadsheet_template_name": suggestion.get("loadsheet_template_name") or "",
                "attributes_ready": bool(suggestion.get("attributes_ready")),
                "attribute_source": suggestion.get("attribute_source") or "missing",
                "attribute_message": suggestion.get("attribute_message"),
                "translation_source": suggestion.get("translation_source") or "rules",
                "match_score": suggestion.get("confidence"),
                "source": suggestion.get("source") or "match",
            }
            items.append(self._with_category_display_paths([row])[0])
        return items

    @staticmethod
    def _contains_cjk(value: str) -> bool:
        return bool(re.search(r"[\u4e00-\u9fff]", value or ""))

    @staticmethod
    def _plain_text(value: str) -> str:
        return re.sub(r"\s+", " ", value.replace("\r", "\n")).strip()

    @staticmethod
    def _box_text(value: str) -> str:
        return "\n".join(
            re.sub(r"\s+", " ", line).strip()
            for line in value.replace("\r", "\n").split("\n")
            if line.strip()
        )

    @staticmethod
    def _contains_html(value: str) -> bool:
        return bool(re.search(r"<\s*/?\s*[a-zA-Z][^>]*>", value))

    @staticmethod
    def _valid_whats_in_the_box(value: str) -> bool:
        lines = [line.strip() for line in value.replace("\r", "\n").split("\n") if line.strip()]
        if not lines:
            lines = [value.strip()]
        return all(re.match(r"^[1-9][0-9]*\s+x\s+.{2,}$", line) for line in lines)

    @staticmethod
    def _looks_english(value: str) -> bool:
        letters = re.findall(r"[A-Za-z]", value)
        non_ascii = [char for char in value if ord(char) > 127]
        return bool(letters) and len(non_ascii) <= max(3, len(value) // 5)

    @staticmethod
    def _bounded_text(value: str, limit: int) -> str:
        cleaned = re.sub(r"\s+", " ", value).strip()
        return cleaned if len(cleaned) <= limit else cleaned[: limit - 1].rstrip() + "."

    @staticmethod
    def _dedupe_strings(values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            normalized = str(value or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
        return result

    @staticmethod
    def _require_job(job_id: str, actor: dict[str, Any]) -> dict[str, Any]:
        job = app_state.get_listing_job(job_id)
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Listing job not found")
        require_tenant_access(actor, job["tenant_id"], detail="Listing job not found")
        return job

    @staticmethod
    def _require_catalog_permission(actor: dict[str, Any]) -> None:
        if actor.get("role") not in {"super_admin", "tenant_admin", "operator"}:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    @staticmethod
    def _is_memory_backend() -> bool:
        return getattr(app_state, "backend_name", "memory") != "postgres"

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
        raw_payload = product.get("raw_payload") or {}
        if raw_payload.get("source") == "takealot_catalog":
            payload = raw_payload.get("payload") or {}
            variants = payload.get("variants") if isinstance(payload.get("variants"), list) else []
            first_variant = variants[0] if variants and isinstance(variants[0], dict) else {}
            for candidate in (
                first_variant.get("gtin"),
                first_variant.get("barcode"),
                payload.get("gtin"),
            ):
                if candidate:
                    return str(candidate)
        return (job.get("raw_payload") or {}).get("barcode")

    @staticmethod
    def _extract_selling_price(job: dict[str, Any]) -> float | None:
        raw_payload = job.get("raw_payload") or {}
        value = raw_payload.get("sale_price_zar")
        try:
            return float(max(0, int(round(float(value))))) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _extract_quantity(job: dict[str, Any]) -> int:
        raw_payload = job.get("raw_payload") or {}
        value = raw_payload.get("quantity")
        try:
            if value is not None:
                return max(1, int(value))
        except (TypeError, ValueError):
            pass
        return max(1, int(settings.extension_listing_default_quantity))

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
