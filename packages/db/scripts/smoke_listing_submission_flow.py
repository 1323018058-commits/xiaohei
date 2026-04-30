from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

from src.modules.common.dev_state import app_state  # noqa: E402
from src.modules.listing.loadsheet_service import (  # noqa: E402
    ListingLoadsheetService,
    ListingLoadsheetSubmitError,
)
from src.modules.listing.repository import ListingCatalogRepository, ListingCatalogUnavailable  # noqa: E402
from src.modules.listing.schemas import ListingLoadsheetPreviewRequest, ListingSubmissionCreateRequest  # noqa: E402
from src.modules.listing.service import ListingService  # noqa: E402
from src.platform.db.session import get_db_session  # noqa: E402


class MockSubmissionClaimStore:
    def __init__(self) -> None:
        self.row = {
            "id": "submission-1",
            "status": "content_queued",
            "stage": "queued",
            "review_status": "approved",
            "takealot_submission_id": "",
            "takealot_offer_id": "",
            "finalized_at": None,
            "loadsheet_submit_claim_task_id": None,
            "loadsheet_submit_claim_token": None,
            "offer_finalize_claim_task_id": None,
            "offer_finalize_claim_token": None,
        }

    def claim_loadsheet_submit(self, *, task_id: str, token: str) -> bool:
        if self.row["takealot_submission_id"]:
            return False
        if self.row["status"] not in {"content_queued", "content_submit_failed", "queue_failed", "content_submitting"}:
            return False
        if self.row["stage"] not in {"queued", "failed", "submitting"}:
            return False
        if self.row["loadsheet_submit_claim_token"]:
            return False
        self.row["status"] = "content_submitting"
        self.row["stage"] = "submitting"
        self.row["loadsheet_submit_claim_task_id"] = task_id
        self.row["loadsheet_submit_claim_token"] = token
        return True

    def submit_succeeded(self, *, task_id: str, token: str, takealot_submission_id: str) -> bool:
        if self.row["loadsheet_submit_claim_task_id"] != task_id or self.row["loadsheet_submit_claim_token"] != token:
            return False
        if self.row["takealot_submission_id"]:
            return False
        self.row["takealot_submission_id"] = takealot_submission_id
        self.row["status"] = "content_submitted"
        self.row["loadsheet_submit_claim_token"] = None
        return True

    def submit_failed(self, *, task_id: str, token: str) -> bool:
        if self.row["loadsheet_submit_claim_task_id"] != task_id or self.row["loadsheet_submit_claim_token"] != token:
            return False
        if self.row["takealot_submission_id"]:
            return False
        self.row["status"] = "content_submit_failed"
        self.row["loadsheet_submit_claim_token"] = None
        return True

    def claim_offer_finalize(self, *, task_id: str, token: str) -> bool:
        if self.row["review_status"] != "approved":
            return False
        if self.row["takealot_offer_id"] or self.row["finalized_at"]:
            return False
        if self.row["status"] in {"offer_submitting", "offer_submitted"}:
            return False
        if self.row["offer_finalize_claim_token"]:
            return False
        self.row["status"] = "offer_submitting"
        self.row["stage"] = "offer_submitting"
        self.row["offer_finalize_claim_task_id"] = task_id
        self.row["offer_finalize_claim_token"] = token
        return True

    def offer_finalized(self, *, task_id: str, token: str, offer_id: str) -> bool:
        if self.row["offer_finalize_claim_task_id"] != task_id or self.row["offer_finalize_claim_token"] != token:
            return False
        if self.row["takealot_offer_id"] or self.row["finalized_at"]:
            return False
        self.row["takealot_offer_id"] = offer_id
        self.row["finalized_at"] = "now"
        self.row["status"] = "offer_submitted"
        self.row["offer_finalize_claim_token"] = None
        return True

    def offer_failed(self, *, task_id: str, token: str) -> bool:
        if self.row["offer_finalize_claim_task_id"] != task_id or self.row["offer_finalize_claim_token"] != token:
            return False
        if self.row["takealot_offer_id"] or self.row["finalized_at"]:
            return False
        self.row["status"] = "offer_failed"
        self.row["offer_finalize_claim_token"] = None
        return True


def run_pure_checks() -> dict[str, Any]:
    storage_root = Path(tempfile.gettempdir()) / "xiaohei-listing-submission-smoke"
    loadsheet_service = ListingLoadsheetService(storage_root=storage_root)
    category = {
        "id": "00000000-0000-0000-0000-000000000001",
        "category_id": 123,
        "path_en": "Electronics > Accessories > Mobile Phone Cases",
        "path_zh": "电子产品 > 配件 > 手机壳",
        "min_required_images": 1,
        "loadsheet_template_id": "smoke-template",
        "loadsheet_template_name": "Smoke Template",
        "compliance_certificates": [],
    }
    preview_request = ListingLoadsheetPreviewRequest(
        store_id="00000000-0000-0000-0000-000000000000",
        category_id=123,
        sku="SMOKE-SUBMISSION",
        barcode="1234567890123",
        title="Smoke Submission Product",
        subtitle="Smoke subtitle",
        description="A conservative smoke product description.",
        whats_in_the_box="1 x Smoke Submission Product",
        selling_price=100,
        rrp=120,
        stock_quantity=5,
        minimum_leadtime_days=2,
        seller_warehouse_id="WH1",
        length_cm=10,
        width_cm=8,
        height_cm=4,
        weight_g=250,
        image_urls=["https://example.com/smoke.jpg"],
        dynamic_attributes={},
    )
    preview = loadsheet_service.build_preview(
        request=preview_request,
        category=category,
        allowed_attributes=[],
        assets=[],
        brand=None,
        brand_catalog_ready=True,
    )
    preview_asset = preview["loadsheet_asset"] or {}
    generated_file = Path(preview_asset.get("storage_path") or "")
    missing_key_short_circuited = False
    try:
        loadsheet_service.submit_loadsheet_to_takealot(
            loadsheet_asset=preview_asset,
            api_key="",
        )
    except ListingLoadsheetSubmitError as exc:
        missing_key_short_circuited = exc.message == "Store credentials unavailable"
    loadsheet_claims = MockSubmissionClaimStore()
    first_loadsheet_claimed = loadsheet_claims.claim_loadsheet_submit(task_id="task-a", token="token-a")
    duplicate_loadsheet_claimed = loadsheet_claims.claim_loadsheet_submit(task_id="task-b", token="token-b")
    submit_success = loadsheet_claims.submit_succeeded(
        task_id="task-a",
        token="token-a",
        takealot_submission_id="TAKEALOT-SUB-1",
    )
    late_submit_failure = loadsheet_claims.submit_failed(task_id="task-a", token="token-a")

    offer_claims = MockSubmissionClaimStore()
    offer_claims.row["status"] = "content_reviewed"
    offer_claims.row["stage"] = "reviewed"
    first_offer_claimed = offer_claims.claim_offer_finalize(task_id="offer-task-a", token="offer-token-a")
    duplicate_offer_claimed = offer_claims.claim_offer_finalize(task_id="offer-task-b", token="offer-token-b")
    offer_success = offer_claims.offer_finalized(task_id="offer-task-a", token="offer-token-a", offer_id="OFFER-1")
    late_offer_failure = offer_claims.offer_failed(task_id="offer-task-a", token="offer-token-a")
    return {
        "xlsx_generated": generated_file.exists() and int(preview_asset.get("size_bytes") or 0) > 0,
        "submission_id_extracted": loadsheet_service.extract_submission_id({"data": {"submission_id": "smoke-123"}})
        == "smoke-123",
        "nested_submission_id_extracted": loadsheet_service.extract_submission_id(
            {"loadsheet_response": {"submissionId": "smoke-nested-123"}}
        )
        == "smoke-nested-123",
        "missing_api_key_short_circuited": missing_key_short_circuited,
        "duplicate_loadsheet_task_claims_once": first_loadsheet_claimed is True
        and duplicate_loadsheet_claimed is False
        and submit_success is True,
        "late_loadsheet_failure_does_not_overwrite_success": late_submit_failure is False
        and loadsheet_claims.row["takealot_submission_id"] == "TAKEALOT-SUB-1",
        "duplicate_offer_finalize_claims_once": first_offer_claimed is True
        and duplicate_offer_claimed is False
        and offer_success is True,
        "late_offer_failure_does_not_overwrite_success": late_offer_failure is False
        and offer_claims.row["takealot_offer_id"] == "OFFER-1",
    }


def normalize_attribute_definitions(category: dict[str, Any]) -> list[dict[str, Any]]:
    definitions: dict[str, dict[str, Any]] = {}
    for required, values in (
        (True, category.get("required_attributes") or []),
        (False, category.get("optional_attributes") or []),
    ):
        for item in values:
            definition = normalize_attribute_definition(item, required=required)
            if definition is not None:
                definitions[definition["key"]] = definition
    return list(definitions.values())


def normalize_attribute_definition(item: Any, *, required: bool) -> dict[str, Any] | None:
    if isinstance(item, str):
        key = item.strip()
        if not key:
            return None
        return {"key": key, "label": key, "value_type": "text", "options": [], "required": required}
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
        item.get("value_type") or item.get("type") or item.get("data_type") or item.get("input_type") or "text"
    ).strip().lower()
    if raw_type in {"bool", "boolean", "checkbox"}:
        value_type = "boolean"
    elif raw_type in {"int", "integer", "number", "numeric", "decimal", "float"}:
        value_type = "number"
    elif raw_type in {"select", "enum", "dropdown", "option"}:
        value_type = "select"
    else:
        value_type = "text"
    options = normalize_attribute_options(
        item.get("options") or item.get("values") or item.get("allowed_values") or item.get("enum") or []
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


def normalize_attribute_options(values: Any) -> list[Any]:
    if isinstance(values, str):
        values = [part.strip() for part in values.replace("|", ",").replace(";", ",").split(",") if part.strip()]
    if not isinstance(values, list):
        return []
    options: list[Any] = []
    for value in values:
        option = value.get("value") or value.get("name") or value.get("label") if isinstance(value, dict) else value
        if option not in (None, "") and option not in options:
            options.append(option)
    return options


def sample_dynamic_attributes(allowed_attributes: list[dict[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for attribute in allowed_attributes:
        if not attribute.get("required"):
            continue
        key = attribute["key"]
        options = attribute.get("options") or []
        value_type = attribute.get("value_type") or "text"
        if options:
            payload[key] = options[0]
        elif value_type == "boolean":
            payload[key] = "No"
        elif value_type == "number":
            payload[key] = 1
        else:
            payload[key] = "Smoke value"
    return payload


def main() -> None:
    pure_checks = run_pure_checks()
    repository = ListingCatalogRepository()
    try:
        categories, _, catalog_ready = repository.search_categories(query=None, page=1, page_size=1)
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                store = cursor.execute(
                    "select id::text as id, tenant_id::text as tenant_id from stores order by created_at asc limit 1"
                ).fetchone()
                actor = cursor.execute(
                    """
                    select id::text as id, role, tenant_id::text as tenant_id
                    from users
                    where role = 'super_admin'
                    order by created_at asc
                    limit 1
                    """
                ).fetchone()
    except Exception as exc:
        detail = exc.message if isinstance(exc, ListingCatalogUnavailable) else str(exc)
        print(
            json.dumps(
                {
                    "passed": False,
                    "message": "PostgreSQL unavailable",
                    "detail": detail,
                    "pure_checks": pure_checks,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        raise SystemExit(2) from exc

    if not catalog_ready or not categories:
        print(
            json.dumps(
                {
                    "passed": False,
                    "message": "Takealot category catalog import required",
                    "pure_checks": pure_checks,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        raise SystemExit(1)
    if store is None:
        print(
            json.dumps(
                {
                    "passed": False,
                    "message": "No store found for listing submission smoke.",
                    "pure_checks": pure_checks,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        raise SystemExit(1)
    if actor is None:
        print(
            json.dumps(
                {
                    "passed": False,
                    "message": "No super_admin user found for listing submission smoke.",
                    "pure_checks": pure_checks,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        raise SystemExit(1)

    category = categories[0]
    required_images = max(1, int(category.get("min_required_images") or 0))
    allowed_attributes = normalize_attribute_definitions(category)
    service = ListingService(
        loadsheet_service=ListingLoadsheetService(
            storage_root=Path(tempfile.gettempdir()) / "xiaohei-listing-submission-smoke"
        )
    )
    unique_suffix = uuid4().hex[:8]
    unique_barcode = f"1234567{uuid4().int % 1000000:06d}"
    response = service.create_listing_submission(
        {
            "id": actor["id"],
            "role": actor["role"],
            "tenant_id": actor.get("tenant_id") or store["tenant_id"],
        },
        store_id=store["id"],
        request=ListingSubmissionCreateRequest(
            category_id=int(category["category_id"]),
            sku=f"SMOKE-SUBMISSION-{unique_suffix}",
            barcode=unique_barcode,
            title="Smoke Submission Product",
            subtitle="Smoke subtitle",
            description="A conservative smoke product description for Takealot review.",
            whats_in_the_box="1 x Smoke Submission Product",
            selling_price=100,
            rrp=120,
            stock_quantity=5,
            minimum_leadtime_days=2,
            seller_warehouse_id="WH1",
            length_cm=10,
            width_cm=8,
            height_cm=4,
            weight_g=250,
            image_urls=[f"https://example.com/smoke-{index}.jpg" for index in range(required_images)],
            dynamic_attributes=sample_dynamic_attributes(allowed_attributes),
        ),
        request_headers={"x-request-id": f"smoke-listing-submission-flow-{unique_suffix}"},
    )
    task = app_state.get_task(response.task_id) if response.task_id else None
    submission = repository.get_listing_submission(response.submission_id) if response.submission_id else None
    passed = (
        all(pure_checks.values())
        and response.submission_id is not None
        and response.task_id is not None
        and task is not None
        and submission is not None
        and submission["status"] == "content_queued"
    )
    print(
        json.dumps(
            {
                "passed": passed,
                "pure_checks": pure_checks,
                "db_submission_checked": submission is not None,
                "task_checked": task is not None,
                "submission_id": response.submission_id,
                "task_id": response.task_id,
                "status": response.status,
                "stage": response.stage,
                "takealot_submit_checked": False,
                "message": "Smoke queued a worker task but did not call Takealot.",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
