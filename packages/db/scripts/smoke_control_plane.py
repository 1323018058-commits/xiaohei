from __future__ import annotations

import json
import sys
from uuid import uuid4
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "apps" / "api"

sys.path.insert(0, str(API_ROOT))


def require_database_url() -> None:
    from src.platform.settings.base import settings

    if not settings.database_url:
        raise SystemExit("XH_DATABASE_URL must be set before running db smoke")


def prepare_database() -> None:
    from src.platform.db.session import apply_sql_directory

    apply_sql_directory(ROOT / "packages" / "db" / "migrations")
    apply_sql_directory(ROOT / "packages" / "db" / "seeds")


def main() -> None:
    require_database_url()
    prepare_database()

    from fastapi.testclient import TestClient

    from api_main import app
    from src.modules.common.dev_state import app_state
    from src.modules.store.adapters.base import AdapterCredentials, BaseAdapter, ListingSnapshot
    from src.modules.store.service import StoreService

    class SmokeListingAdapter(BaseAdapter):
        def __init__(self, credentials: AdapterCredentials) -> None:
            super().__init__(credentials)

        def fetch_listings(self, heartbeat=None) -> list[ListingSnapshot]:
            if heartbeat is not None:
                heartbeat({"page_number": 1, "page_item_count": 2, "listing_count": 2})
            return [
                ListingSnapshot(
                    external_listing_id="smoke-listing-001",
                    sku="SMOKE-SKU-001",
                    title="Smoke Listing One",
                    platform_price=99.95,
                    stock_quantity=12,
                    currency="ZAR",
                    raw_payload={"source": "db_smoke", "index": 1},
                ),
                ListingSnapshot(
                    external_listing_id="smoke-listing-002",
                    sku="SMOKE-SKU-002",
                    title="Smoke Listing Two",
                    platform_price=129.5,
                    stock_quantity=4,
                    currency="ZAR",
                    raw_payload={"source": "db_smoke", "index": 2},
                ),
            ]

    def smoke_adapter_factory(
        store: dict[str, object],
        credentials: AdapterCredentials,
    ) -> BaseAdapter:
        return SmokeListingAdapter(credentials)

    client = TestClient(app)

    login = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    assert login.status_code == 200, login.text
    cookies = login.cookies

    me = client.get("/api/auth/me", cookies=cookies)
    assert me.status_code == 200, me.text

    health = client.get("/admin/api/system/health", cookies=cookies)
    assert health.status_code == 200, health.text
    health_payload = health.json()
    db_component = next(
        item for item in health_payload["components"] if item["component"] == "db"
    )
    assert getattr(app_state, "backend_name", None) == "postgres", health_payload
    assert db_component["status"] == "ok", health_payload

    users = client.get("/admin/api/users", cookies=cookies)
    assert users.status_code == 200, users.text
    admin_user = next(
        user for user in users.json()["users"] if user["username"] == "admin"
    )
    assert admin_user["active_session_count"] >= 1, users.text

    stores = client.get("/api/stores", cookies=cookies)
    assert stores.status_code == 200, stores.text

    unique_suffix = uuid4().hex[:8]
    create_store = client.post(
        "/api/v1/stores",
        json={
            "name": f"Smoke Takealot {unique_suffix}",
            "platform": "takealot",
            "api_key": f"smoke-key-{unique_suffix}",
            "api_secret": f"smoke-secret-{unique_suffix}",
            "status": "active",
        },
        cookies=cookies,
    )
    assert create_store.status_code == 200, create_store.text
    store_id = create_store.json()["store_id"]

    sync = client.post(
        f"/api/stores/{store_id}/sync/force",
        json={"reason": "db smoke"},
        cookies=cookies,
    )
    assert sync.status_code == 200, sync.text
    task_id = sync.json()["task_id"]

    task = client.get(f"/api/tasks/{task_id}", cookies=cookies)
    assert task.status_code == 200, task.text

    processed_task = StoreService().process_sync_task(
        task_id,
        adapter_factory=smoke_adapter_factory,
    )
    assert processed_task["status"] == "succeeded", processed_task

    events = client.get(f"/api/tasks/{task_id}/events", cookies=cookies)
    assert events.status_code == 200, events.text
    assert len(events.json()["events"]) >= 2, events.text

    listings = client.get(f"/api/v1/stores/{store_id}/listings", cookies=cookies)
    assert listings.status_code == 200, listings.text
    listings_payload = listings.json()["listings"]
    assert len(listings_payload) >= 2, listings.text

    logout = client.post("/api/auth/logout", cookies=cookies)
    assert logout.status_code == 200, logout.text

    me_after_logout = client.get("/api/auth/me", cookies=cookies)
    assert me_after_logout.status_code == 401, me_after_logout.text

    print(
        json.dumps(
            {
                "backend_name": getattr(app_state, "backend_name", "unknown"),
                "db_status": db_component["status"],
                "db_detail": db_component["detail"],
                "store_id": store_id,
                "task_id": task_id,
                "task_status": processed_task["status"],
                "event_count": len(events.json()["events"]),
                "listing_count": len(listings_payload),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
