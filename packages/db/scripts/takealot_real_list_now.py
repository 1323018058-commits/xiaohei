from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "apps" / "api"

sys.path.insert(0, str(API_ROOT))

from src.modules.common.dev_state import ADMIN_USER_ID, DEMO_TENANT_ID, app_state  # noqa: E402
from src.modules.extension.schemas import ExtensionListNowRequest, ProtectedFloorRequest  # noqa: E402
from src.modules.extension.service import ExtensionService  # noqa: E402
from src.modules.listing.service import ListingService  # noqa: E402
from src.modules.store.service import StoreService  # noqa: E402
from src.platform.db.session import get_db_session  # noqa: E402


DEFAULT_STORE_NAME = "Takealot Pilot Store"


def require_database_url() -> None:
    from src.platform.settings.base import settings

    if not settings.database_url:
        raise SystemExit("XH_DATABASE_URL must be set before running real list-now execute mode")


def _credentials() -> tuple[str, str]:
    api_key = os.environ.get("XH_TAKEALOT_API_KEY", "").strip()
    api_secret = os.environ.get("XH_TAKEALOT_API_SECRET", "").strip() or "takealot-api-secret-placeholder"
    if not api_key:
        raise SystemExit("Missing XH_TAKEALOT_API_KEY")
    return api_key, api_secret


def _actor() -> dict[str, str]:
    return {
        "id": ADMIN_USER_ID,
        "role": "super_admin",
        "tenant_id": DEMO_TENANT_ID,
    }


def _request_headers(label: str) -> dict[str, str]:
    return {"x-request-id": f"takealot-real-list-now-{label}"}


def _find_store_id(name: str) -> str | None:
    for store in app_state.list_stores():
        if store["name"] == name:
            return store["id"]
    return None


def _prepare_store(
    service: StoreService,
    *,
    store_name: str,
    api_key: str,
    api_secret: str,
) -> str:
    store_id = _find_store_id(store_name)
    if store_id is None:
        detail = service.create_store(
            {
                "name": store_name,
                "platform": "takealot",
                "api_key": api_key,
                "api_secret": api_secret,
                "status": "active",
            },
            _actor(),
            _request_headers("create"),
        )
        store_id = detail.store_id

    validation_task = service.update_credentials(
        store_id,
        api_key,
        api_secret,
        "Real Takealot credential validation before list-now",
        _actor(),
        _request_headers("validate"),
    )
    validation_result = service.process_store_task(validation_task.task_id)
    if validation_result["status"] != "succeeded":
        raise SystemExit(
            json.dumps(
                {
                    "store_id": store_id,
                    "validation_task_id": validation_task.task_id,
                    "validation_status": validation_result["status"],
                    "error_code": validation_result.get("error_code"),
                    "error_msg": validation_result.get("error_msg"),
                },
                ensure_ascii=False,
            )
        )
    return store_id


def _enable_listing_jobs() -> None:
    with get_db_session() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                update system_settings
                set value_json = 'true'::jsonb,
                    updated_at = now()
                where setting_key = 'listing_jobs_enabled'
                """
            )
        connection.commit()
    if hasattr(app_state, "_system_settings_cache"):
        app_state._system_settings_cache = (0.0, [])


def main() -> None:
    parser = argparse.ArgumentParser(description="Guarded real end-to-end list-now execution")
    parser.add_argument("--plid", required=True)
    parser.add_argument("--title", default=None)
    parser.add_argument("--sale-price-zar", required=True, type=float)
    parser.add_argument("--protected-floor-price", required=True, type=float)
    parser.add_argument("--barcode", default=None, help="GTIN/barcode from Takealot catalogue")
    parser.add_argument("--store-name", default=os.environ.get("XH_TAKEALOT_REAL_STORE_NAME", DEFAULT_STORE_NAME))
    parser.add_argument("--poll-seconds", type=int, default=5)
    parser.add_argument("--max-polls", type=int, default=12)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually execute the end-to-end store validation + list-now + listing worker flow",
    )
    args = parser.parse_args()

    if not args.execute:
        print(
            json.dumps(
                {
                    "mode": "dry-run",
                    "message": "Add --execute to run end-to-end list-now against the live Takealot API.",
                    "payload": {
                        "plid": args.plid,
                        "title": args.title or f"PLID{args.plid}",
                        "sale_price_zar": args.sale_price_zar,
                        "protected_floor_price": args.protected_floor_price,
                        "barcode": args.barcode,
                        "store_name": args.store_name,
                    },
                    "requirements": [
                        "XH_DATABASE_URL",
                        "XH_TAKEALOT_API_KEY",
                        "Optional --barcode or seller-api enrichment path",
                    ],
                },
                ensure_ascii=False,
            )
        )
        return

    require_database_url()
    api_key, api_secret = _credentials()
    store_service = StoreService()
    extension_service = ExtensionService()
    listing_service = ListingService()
    store_id = _prepare_store(
        store_service,
        store_name=args.store_name.strip() or DEFAULT_STORE_NAME,
        api_key=api_key,
        api_secret=api_secret,
    )

    if args.barcode:
        app_state.upsert_library_product(
            platform="takealot",
            external_product_id=args.plid,
            title=args.title or f"PLID{args.plid}",
            fact_status="complete",
            raw_payload={
                "source": "takealot_catalog",
                "payload": {
                    "variants": [
                        {
                            "gtin": args.barcode,
                        }
                    ]
                },
            },
        )

    protected_floor = extension_service.save_protected_floor(
        payload=ProtectedFloorRequest(
            store_id=store_id,
            plid=args.plid,
            title=args.title,
            protected_floor_price=args.protected_floor_price,
        ),
        actor=_actor(),
        request_headers=_request_headers("guardrail"),
    )

    task = extension_service.create_list_now_task(
        payload=ExtensionListNowRequest(
            store_id=store_id,
            plid=args.plid,
            title=args.title,
            sale_price_zar=args.sale_price_zar,
        ),
        actor=_actor(),
        request_headers=_request_headers("list-now"),
    )

    processed_extension_tasks = extension_service.process_queued_extension_tasks()
    _enable_listing_jobs()
    processing_task_id = None
    for processed_task in processed_extension_tasks:
        if processed_task.get("id") == task.task_id:
            error_details = processed_task.get("error_details") or {}
            processing_task_id = error_details.get("processing_task_id")
            break
    processed_listing_tasks: list[dict[str, object]] = []
    latest_job = None
    for _ in range(max(1, args.max_polls)):
        if processing_task_id:
            current = listing_service.process_listing_task(processing_task_id)
            processed_listing_tasks.append(current)
            if current.get("status") == "waiting_retry":
                app_state.update_task(current["id"], next_retry_at=None)
        listing_jobs = listing_service.list_jobs(_actor(), store_id=store_id).jobs
        latest_job = listing_jobs[0] if listing_jobs else None
        if latest_job and latest_job.status in {"ready_to_submit", "manual_intervention", "failed"}:
            break
        time.sleep(max(1, args.poll_seconds))

    result = {
        "mode": "execute",
        "store_id": store_id,
        "plid": args.plid,
        "protected_floor_price": protected_floor.protected_floor_price,
        "extension_task_id": task.task_id,
        "processed_extension_task_count": len(processed_extension_tasks),
        "processed_listing_task_count": len(processed_listing_tasks),
        "processing_task_id": processing_task_id,
        "listing_job": latest_job.model_dump(mode="json") if latest_job else None,
    }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
