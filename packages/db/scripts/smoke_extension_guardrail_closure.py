from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "apps" / "api"

sys.path.insert(0, str(API_ROOT))


def require_database_url() -> None:
    from src.platform.settings.base import settings

    if not settings.database_url:
        raise SystemExit("XH_DATABASE_URL must be set before running extension guardrail smoke")


def prepare_database() -> None:
    from src.platform.db.session import apply_sql_directory

    apply_sql_directory(ROOT / "packages" / "db" / "migrations")
    apply_sql_directory(ROOT / "packages" / "db" / "seeds")


def main() -> None:
    require_database_url()
    prepare_database()

    from fastapi.testclient import TestClient

    from api_main import app
    from src.modules.extension.service import ExtensionService
    from src.modules.listing.service import ListingService
    from src.platform.db.session import get_db_session
    from src.modules.store.adapters.base import AdapterCredentials, BaseAdapter, ListingSnapshot
    from src.modules.store.service import StoreService

    class GuardrailAdapter(BaseAdapter):
        batch_status_calls = 0

        def __init__(self, credentials: AdapterCredentials) -> None:
            super().__init__(credentials)

        def fetch_listings(self, heartbeat=None) -> list[ListingSnapshot]:
            plid = "92833194"
            if heartbeat is not None:
                heartbeat({"page_number": 1, "page_item_count": 1, "listing_count": 1})
            return [
                ListingSnapshot(
                    external_listing_id="guardrail-listing-001",
                    platform_product_id=plid,
                    sku="GUARDRAIL-SKU-001",
                    title="Guardrail Listing",
                    platform_price=199.99,
                    stock_quantity=3,
                    currency="ZAR",
                    raw_payload={
                        "source": "guardrail_smoke",
                        "productline_id": plid,
                        "weight_grams": 300,
                        "length_cm": 16.5,
                        "width_cm": 8.5,
                        "height_cm": 8.5,
                    },
                )
            ]

        def create_or_update_offer(
            self,
            *,
            barcode: str,
            sku: str,
            selling_price: float,
            rrp: float | None = None,
            quantity: int,
            minimum_leadtime_days: int,
            leadtime_merchant_warehouse_id: int | None = None,
        ) -> dict:
            return {
                "batch_id": 445566,
                "batch_status": "processing",
                "sku": sku,
                "barcode": barcode,
                "title": "Guardrail Listing",
                "selling_price": selling_price,
                "rrp": rrp,
                "quantity": quantity,
                "minimum_leadtime_days": minimum_leadtime_days,
                "leadtime_merchant_warehouse_id": leadtime_merchant_warehouse_id,
            }

        def get_offer_batch_status(self, batch_id: int) -> dict:
            GuardrailAdapter.batch_status_calls += 1
            return {
                "batch_id": batch_id,
                "status": "success" if GuardrailAdapter.batch_status_calls >= 2 else "processing",
            }

        def get_offer_by_barcode(self, barcode: str) -> dict | None:
            if GuardrailAdapter.batch_status_calls < 2:
                return None
            return {
                "offer_id": 99887766,
                "sku": "XH-LISTING-MOCK-001",
                "barcode": barcode,
                "title": "Guardrail Listing",
                "selling_price": 299,
                "minimum_leadtime_days": 14,
            }

    def adapter_factory(store: dict[str, object], credentials: AdapterCredentials) -> BaseAdapter:
        return GuardrailAdapter(credentials)

    client = TestClient(app)

    login = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    assert login.status_code == 200, login.text
    cookies = login.cookies

    unique_suffix = uuid4().hex[:8]
    create_store = client.post(
        "/api/v1/stores",
        json={
            "name": f"Extension Guardrail {unique_suffix}",
            "platform": "takealot",
            "api_key": f"guardrail-key-{unique_suffix}",
            "api_secret": f"guardrail-secret-{unique_suffix}",
            "status": "active",
        },
        cookies=cookies,
    )
    assert create_store.status_code == 200, create_store.text
    store_id = create_store.json()["store_id"]

    extension_auth = client.post(
        "/api/extension/login",
        json={
            "username": "admin",
            "password": "admin123",
            "store_id": store_id,
        },
    )
    assert extension_auth.status_code == 200, extension_auth.text
    extension_token = extension_auth.json()["token"]
    extension_headers = {"Authorization": f"Bearer {extension_token}"}

    protected_floor = client.post(
        "/api/extension/protected-floor",
        json={
            "store_id": store_id,
            "plid": "92833194",
            "title": "Guardrail Listing",
            "protected_floor_price": 123.45,
        },
        headers=extension_headers,
    )
    assert protected_floor.status_code == 200, protected_floor.text
    protected_floor_payload = protected_floor.json()
    assert protected_floor_payload["status"] == "pending_listing_link", protected_floor.text

    sync = client.post(
        f"/api/stores/{store_id}/sync/force",
        json={"reason": "extension guardrail smoke"},
        cookies=cookies,
    )
    assert sync.status_code == 200, sync.text
    task_id = sync.json()["task_id"]

    processed_task = StoreService().process_sync_task(
        task_id,
        adapter_factory=adapter_factory,
    )
    assert processed_task["status"] == "succeeded", processed_task

    preview = client.post(
        "/api/extension/profit-preview",
        json={
            "store_id": store_id,
            "plid": "92833194",
            "title": "Guardrail Listing",
            "purchase_price_cny": 50,
        },
        headers=extension_headers,
    )
    assert preview.status_code == 200, preview.text
    preview_payload = preview.json()
    assert preview_payload["product"]["merchant_packaged_weight_raw"] == "300 g", preview.text
    assert preview_payload["product"]["merchant_packaged_dimensions_raw"] == "16.5 x 8.5 x 8.5 cm", preview.text
    assert preview_payload["pricing"]["recommended_price_10_zar"] is not None, preview.text
    assert (
        preview_payload["pricing"]["recommended_protected_floor_price_zar"]
        == preview_payload["pricing"]["recommended_price_10_zar"]
    ), preview.text
    assert preview_payload["pricing"]["profit_zar"] is not None, preview.text
    assert preview_payload["guardrail"]["status"] == "synced_autobid", preview.text
    assert preview_payload["guardrail"]["autobid_sync_status"] == "synced", preview.text

    from src.modules.common.dev_state import app_state
    product = app_state.get_library_product(platform="takealot", external_product_id="92833194")
    assert product is not None
    app_state.upsert_library_product(
        platform="takealot",
        external_product_id="92833194",
        title=product["title"],
        fact_status=product["fact_status"],
        raw_payload={
            "source": "takealot_catalog",
            "payload": {
                "variants": [
                    {
                        "gtin": "6001234567890",
                    }
                ]
            },
        },
    )

    rules = client.get(
        f"/api/v1/bidding/rules?store_id={store_id}",
        cookies=cookies,
    )
    assert rules.status_code == 200, rules.text
    rules_payload = rules.json()["rules"]
    assert len(rules_payload) == 1, rules.text
    assert rules_payload[0]["sku"] == "GUARDRAIL-SKU-001", rules.text
    assert abs(rules_payload[0]["floor_price"] - 123.45) < 0.0001, rules.text

    list_now = client.post(
        "/api/extension/list-now",
        json={
            "store_id": store_id,
            "plid": "92833194",
            "title": "Guardrail Listing",
            "sale_price_zar": 299,
        },
        headers=extension_headers,
    )
    assert list_now.status_code == 200, list_now.text
    list_now_payload = list_now.json()
    assert list_now_payload["status"] == "queued", list_now.text
    processed_extension_tasks = ExtensionService().process_queued_extension_tasks()
    assert processed_extension_tasks, "extension worker should process list-now task"
    processed_extension_task = next(
        task for task in processed_extension_tasks if task["id"] == list_now_payload["task_id"]
    )
    assert processed_extension_task["status"] == "succeeded", processed_extension_tasks

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

    listing_jobs = client.get(
        f"/api/listing/jobs?store_id={store_id}",
        cookies=cookies,
    )
    assert listing_jobs.status_code == 200, listing_jobs.text
    listing_job_id = processed_extension_task["error_details"]["listing_job_id"]
    processing_task_id = processed_extension_task["error_details"]["processing_task_id"]

    listing_service = ListingService()
    listing_task = listing_service.process_listing_task(
        processing_task_id,
        adapter_factory=adapter_factory,
    )
    assert listing_task["status"] == "waiting_retry", listing_task
    app_state.update_task(
        listing_task["id"],
        next_retry_at=None,
    )

    listing_task = listing_service.process_listing_task(
        processing_task_id,
        adapter_factory=adapter_factory,
    )
    assert listing_task["status"] == "waiting_retry", listing_task
    app_state.update_task(
        listing_task["id"],
        next_retry_at=None,
    )

    listing_task = listing_service.process_listing_task(
        processing_task_id,
        adapter_factory=adapter_factory,
    )
    listing_job_detail = client.get(
        f"/api/listing/jobs/{listing_job_id}",
        cookies=cookies,
    )
    assert listing_job_detail.status_code == 200, listing_job_detail.text
    listing_job_payload = listing_job_detail.json()
    assert listing_job_payload["status"] == "ready_to_submit", listing_job_detail.text

    print(
        json.dumps(
            {
                "store_id": store_id,
                "task_id": task_id,
                "guardrail_status": preview_payload["guardrail"]["status"],
                "autobid_sync_status": preview_payload["guardrail"]["autobid_sync_status"],
                "weight": preview_payload["product"]["merchant_packaged_weight_raw"],
                "dimensions": preview_payload["product"]["merchant_packaged_dimensions_raw"],
                "recommended_price_10_zar": preview_payload["pricing"]["recommended_price_10_zar"],
                "bidding_rule_id": preview_payload["guardrail"]["linked_bidding_rule_id"],
                "rule_count": len(rules_payload),
                "list_now_task_id": list_now_payload["task_id"],
                "list_now_task_status": processed_extension_task["status"],
                "listing_job_id": listing_job_id,
                "listing_job_status": listing_job_payload["status"],
                "listing_task_status": listing_task["status"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
