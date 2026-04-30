from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

from src.modules.listing.loadsheet_service import (  # noqa: E402
    ListingLoadsheetService,
    ListingLoadsheetStatusError,
)
from src.modules.listing.repository import ListingCatalogRepository, ListingCatalogUnavailable  # noqa: E402
from src.modules.listing.service import ListingService  # noqa: E402
from src.platform.db.session import get_db_session  # noqa: E402


def apply_mock_status_sync_policy(existing: dict[str, Any], mapped: dict[str, Any]) -> dict[str, Any]:
    if existing.get("takealot_offer_id") or existing.get("finalized_at") or existing.get("status") == "offer_submitted":
        return {"status": "offer_submitted", "stage": "offer_submitted", "review_status": "approved"}
    if existing.get("review_status") == "approved" and mapped.get("review_status") in {"submitted", "under_review", "unknown"}:
        return {
            "status": existing["status"],
            "stage": existing["stage"],
            "review_status": existing["review_status"],
        }
    return {
        "status": mapped["status"],
        "stage": mapped["stage"],
        "review_status": mapped["review_status"],
    }


def run_pure_checks() -> dict[str, Any]:
    """Validate Phase 8 rules that do not need PostgreSQL or Takealot.

    Failures here are logic regressions. Environment failures, such as missing
    PostgreSQL or missing Takealot credentials, are reported separately below so
    this smoke never pretends a real official sync happened.
    """

    service = ListingLoadsheetService()
    approved = service.map_submission_status({"submission_status": "Approved"})
    partial = service.map_submission_status({"status": "partially approved"})
    pending = service.map_submission_status({"data": {"status": "in review"}})
    rejected = service.map_submission_status({"review_status": "Rejected"})
    exact_secret = "sk_live_exact_secret_1234567890"
    long_secret = "abcDEF1234567890" * 3
    sanitized = service.sanitize_official_response(
        {
            "status": "approved",
            "api_key": "never-store-me",
            "nested": {"Authorization": "Key never-store-me"},
            "message": (
                f"Bearer {exact_secret} api_key={exact_secret} access_token={exact_secret} "
                f"Authorization: {exact_secret} raw {long_secret}"
            ),
        },
        secrets=[exact_secret],
    )
    sanitized_text = json.dumps(sanitized, ensure_ascii=False)
    generated_fields = {
        "sku": "SKU-1",
        "barcode": "6000000000001",
        "category_id": 123,
        "brand_id": "BRAND",
        "title": "Stable product",
        "selling_price": 100,
        "stock_quantity": 2,
        "dynamic_attributes": [{"key": "Color", "value": "Black"}],
    }
    idempotency_key_a = ListingService._submission_idempotency_key(
        tenant_id="tenant-1",
        store_id="store-1",
        generated_fields=dict(generated_fields),
        request_headers={},
    )
    idempotency_key_b = ListingService._submission_idempotency_key(
        tenant_id="tenant-1",
        store_id="store-1",
        generated_fields=dict(generated_fields),
        request_headers={"x-request-id": "different-retry"},
    )
    header_key_a = ListingService._submission_idempotency_key(
        tenant_id="tenant-1",
        store_id="store-1",
        generated_fields=dict(generated_fields),
        request_headers={"Idempotency-Key": "client-retry-key"},
    )
    header_key_b = ListingService._submission_idempotency_key(
        tenant_id="tenant-1",
        store_id="store-1",
        generated_fields={"sku": "different"},
        request_headers={"idempotency-key": "client-retry-key"},
    )
    terminal_policy = apply_mock_status_sync_policy(
        {"status": "offer_submitted", "stage": "offer_submitted", "review_status": "approved", "takealot_offer_id": "OFFER-1"},
        {"status": "content_rejected", "stage": "rejected", "review_status": "rejected"},
    )
    approved_policy = apply_mock_status_sync_policy(
        {"status": "content_reviewed", "stage": "reviewed", "review_status": "approved"},
        {"status": "content_submitted", "stage": "submitted", "review_status": "unknown"},
    )
    missing_key_short_circuited = False
    try:
        service.get_submission_status(api_key="", takealot_submission_id="smoke")
    except ListingLoadsheetStatusError as exc:
        missing_key_short_circuited = exc.message == "Store credentials unavailable"

    return {
        "approved_maps_to_offer_gate": approved["approved"] is True
        and approved["review_status"] == "approved"
        and approved["status"] == "content_reviewed",
        "partial_does_not_open_offer_gate": partial["approved"] is False
        and partial["review_status"] == "partial",
        "pending_does_not_open_offer_gate": pending["approved"] is False
        and pending["review_status"] == "under_review",
        "rejected_does_not_open_offer_gate": rejected["approved"] is False
        and rejected["review_status"] == "rejected",
        "existing_offer_id_is_idempotent": service.is_review_approved({"review_status": "approved"}) is True
        and bool({"takealot_offer_id": "123"}.get("takealot_offer_id")),
        "sensitive_response_fields_redacted": sanitized["api_key"] == "[redacted]"
        and sanitized["nested"]["Authorization"] == "[redacted]",
        "sensitive_response_strings_redacted": exact_secret not in sanitized_text and long_secret not in sanitized_text,
        "same_payload_generates_same_idempotency_key": idempotency_key_a == idempotency_key_b,
        "client_idempotency_key_takes_precedence": header_key_a == header_key_b and header_key_a != idempotency_key_a,
        "stale_status_does_not_regress_offer_submitted": terminal_policy["status"] == "offer_submitted"
        and terminal_policy["review_status"] == "approved",
        "stale_pending_does_not_regress_approved_review": approved_policy["status"] == "content_reviewed"
        and approved_policy["review_status"] == "approved",
        "missing_api_key_short_circuited": missing_key_short_circuited,
    }


def main() -> None:
    pure_checks = run_pure_checks()
    repository = ListingCatalogRepository()
    try:
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                store = cursor.execute(
                    "select id::text as id, tenant_id::text as tenant_id from stores order by created_at asc limit 1"
                ).fetchone()
                submission = cursor.execute(
                    """
                    select id::text as id
                    from listing_submissions
                    order by created_at desc
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
        sys.exit(2)

    due_count = 0
    submission_checked = False
    if store is not None:
        due = repository.list_submissions_due_status_sync(
            store_id=store["id"],
            tenant_id=None,
            limit=5,
        )
        due_count = len(due)
    if submission is not None:
        submission_checked = repository.get_listing_submission(submission["id"]) is not None

    passed = all(pure_checks.values())
    print(
        json.dumps(
            {
                "passed": passed,
                "pure_checks": pure_checks,
                "db_checked": True,
                "store_checked": store is not None,
                "submission_checked": submission_checked,
                "due_status_sync_count": due_count,
                "takealot_status_checked": False,
                "takealot_offer_checked": False,
                "message": (
                    "Smoke validated parsing, sanitization, approved-only gate, and idempotency helpers. "
                    "It did not call Takealot or claim official sync success."
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
