from __future__ import annotations

import json
import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

os.environ["XH_DATABASE_URL"] = ""

ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "apps" / "api"

sys.path.insert(0, str(API_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from api_main import app  # noqa: E402
from src.modules.common.dev_state import ADMIN_USER_ID, DEMO_TENANT_ID, app_state  # noqa: E402
from src.modules.orders.service import OrderService, SYNC_TAKEALOT_ORDERS_TASK_TYPE  # noqa: E402
from src.modules.store.adapters.base import (  # noqa: E402
    AdapterAuthError,
    AdapterCredentials,
    AdapterTemporaryError,
    BaseAdapter,
    ListingSnapshot,
    OrderItemSnapshot,
    OrderSnapshot,
)
from src.modules.store.adapters.takealot import TakealotAdapter  # noqa: E402


class SuccessOrderAdapter(BaseAdapter):
    def fetch_listings(self, heartbeat=None) -> list[ListingSnapshot]:
        return []

    def fetch_orders(
        self,
        heartbeat=None,
        *,
        start_date: date | datetime | None = None,
        end_date: date | datetime | None = None,
    ) -> list[OrderSnapshot]:
        if heartbeat is not None:
            heartbeat({"page_number": 1, "page_item_count": 2, "sale_count": 2})
        return [
            OrderSnapshot(
                external_order_id="900001",
                order_number="900001",
                status="Preparing for Customer",
                fulfillment_status="Preparing for Customer",
                total_amount=319.8,
                currency="ZAR",
                placed_at=datetime(2026, 4, 23, 9, 30, tzinfo=UTC),
                raw_payload={"source": "smoke", "order_id": 900001},
                items=[
                    OrderItemSnapshot(
                        external_order_item_id="900001-1",
                        sku="ORDER-SMOKE-001",
                        title="Smoke Order Item One",
                        quantity=2,
                        unit_price=99.9,
                        status="Preparing for Customer",
                        raw_payload={"order_item_id": "900001-1"},
                    ),
                    OrderItemSnapshot(
                        external_order_item_id="900001-2",
                        sku="ORDER-SMOKE-002",
                        title="Smoke Order Item Two",
                        quantity=1,
                        unit_price=120.0,
                        status="Preparing for Customer",
                        raw_payload={"order_item_id": "900001-2"},
                    ),
                ],
            )
        ]


class TemporaryFailureOrderAdapter(SuccessOrderAdapter):
    def fetch_orders(
        self,
        heartbeat=None,
        *,
        start_date: date | datetime | None = None,
        end_date: date | datetime | None = None,
    ) -> list[OrderSnapshot]:
        raise AdapterTemporaryError("mock Takealot 503")


class AuthFailureOrderAdapter(SuccessOrderAdapter):
    def fetch_orders(
        self,
        heartbeat=None,
        *,
        start_date: date | datetime | None = None,
        end_date: date | datetime | None = None,
    ) -> list[OrderSnapshot]:
        raise AdapterAuthError("mock Takealot 401")


def adapter_factory(store: dict[str, object], credentials: AdapterCredentials) -> BaseAdapter:
    name = str(store["name"])
    if "503" in name:
        return TemporaryFailureOrderAdapter(credentials)
    if "401" in name:
        return AuthFailureOrderAdapter(credentials)
    return SuccessOrderAdapter(credentials)


def main() -> None:
    client = TestClient(app)
    service = OrderService()
    suffix = uuid4().hex[:8]
    cookies = login(client, "admin", "admin123")

    success_store = create_store(f"Order Smoke Store {suffix}")
    queued = client.post(
        f"/api/v1/stores/{success_store['id']}/orders/sync/force",
        json={"reason": "order sync smoke"},
        cookies=cookies,
    )
    assert queued.status_code == 200, queued.text
    task_id = queued.json()["task_id"]
    processed = service.process_order_sync_task(task_id, adapter_factory=adapter_factory)
    assert processed["status"] == "succeeded", processed

    orders = client.get(
        f"/api/v1/orders?store_id={success_store['id']}",
        cookies=cookies,
    )
    assert orders.status_code == 200, orders.text
    order_payload = orders.json()["orders"]
    assert len(order_payload) == 1, order_payload
    assert order_payload[0]["status"] == "preparing", order_payload
    assert order_payload[0]["fulfillment_status"] == "Preparing for Customer", order_payload
    assert order_payload[0]["item_count"] == 2, order_payload

    detail = client.get(
        f"/api/v1/orders/{order_payload[0]['order_id']}",
        cookies=cookies,
    )
    assert detail.status_code == 200, detail.text
    detail_payload = detail.json()
    assert len(detail_payload["items"]) == 2, detail_payload
    assert all(item["status"] == "preparing" for item in detail_payload["items"]), detail_payload
    assert any(event["event_type"] == "order.created" for event in detail_payload["events"]), detail_payload
    assert_audit(task_id, "orders.sync.worker", "success")
    assert_successful_status_mapping()
    assert_takealot_sales_line_total_mapping()

    temporary_store = create_store(f"Order Smoke 503 Store {suffix}")
    temporary_task = create_order_task(temporary_store)
    temporary_result = service.process_order_sync_task(
        temporary_task["id"],
        adapter_factory=adapter_factory,
    )
    assert temporary_result["status"] == "waiting_retry", temporary_result
    temporary_events = app_state.list_task_events(temporary_task["id"])
    assert any(event["event_type"] == "task.retry_scheduled" for event in temporary_events), temporary_events

    auth_store = create_store(f"Order Smoke 401 Store {suffix}")
    auth_task = create_order_task(auth_store)
    auth_result = service.process_order_sync_task(
        auth_task["id"],
        adapter_factory=adapter_factory,
    )
    assert auth_result["status"] == "failed", auth_result
    expired_store = app_state.get_store(auth_store["id"])
    assert expired_store["credential_status"] == "expired", expired_store
    assert_audit(auth_task["id"], "orders.sync.worker", "failed")

    warehouse_user = app_state.create_user(
        {
            "tenant_id": DEMO_TENANT_ID,
            "username": f"order_warehouse_{suffix}",
            "email": f"order_warehouse_{suffix}@demo.local",
            "password": "warehouse123",
            "role": "warehouse",
            "status": "active",
            "force_password_reset": False,
        }
    )
    warehouse_cookies = login(client, warehouse_user["username"], "warehouse123")
    forbidden = client.post(
        f"/api/v1/stores/{success_store['id']}/orders/sync/force",
        json={"reason": "warehouse should not sync"},
        cookies=warehouse_cookies,
    )
    assert forbidden.status_code == 403, forbidden.text

    print(
        json.dumps(
            {
                "task_id": task_id,
                "order_count": len(order_payload),
                "item_count": len(detail_payload["items"]),
                "retry_status": temporary_result["status"],
                "auth_failure_status": auth_result["status"],
                "permission_status": forbidden.status_code,
            },
            ensure_ascii=False,
        )
    )


def login(client: TestClient, username: str, password: str):
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.cookies


def create_store(name: str) -> dict[str, object]:
    return app_state.create_store(
        {
            "tenant_id": DEMO_TENANT_ID,
            "name": name,
            "platform": "takealot",
            "status": "active",
            "api_key": f"order-key-{uuid4().hex[:8]}",
            "api_secret": f"order-secret-{uuid4().hex[:8]}",
            "masked_api_key": "ordr********test",
            "api_key_status": "configured",
            "credential_status": "configured",
            "feature_policies": {
                "bidding_enabled": False,
                "listing_enabled": True,
                "sync_enabled": True,
            },
        }
    )


def create_order_task(store: dict[str, object]) -> dict[str, object]:
    return app_state.create_task(
        task_type=SYNC_TAKEALOT_ORDERS_TASK_TYPE,
        domain="orders",
        queue_name="order-sync",
        actor_user_id=ADMIN_USER_ID,
        actor_role="super_admin",
        tenant_id=DEMO_TENANT_ID,
        store_id=str(store["id"]),
        target_type="store",
        target_id=str(store["id"]),
        request_id=f"smoke-order-sync-{uuid4().hex[:8]}",
        label=f"{store['name']} order sync",
        next_action="Run mock Takealot order adapter",
    )


def assert_audit(task_id: str, action: str, result: str) -> None:
    audits = app_state.list_audits(DEMO_TENANT_ID)
    assert any(
        audit["task_id"] == task_id
        and audit["action"] == action
        and audit["result"] == result
        for audit in audits
    ), audits[:5]


def assert_successful_status_mapping() -> None:
    from src.modules.orders.status import normalize_takealot_order_status

    assert normalize_takealot_order_status("New Lead Time Order") == "preparing"
    assert normalize_takealot_order_status("Preparing for Customer") == "preparing"
    assert normalize_takealot_order_status("Shipped") == "shipped"
    assert normalize_takealot_order_status("Cancelled") == "cancelled"


def assert_takealot_sales_line_total_mapping() -> None:
    snapshots = TakealotAdapter._sales_to_orders(
        [
            {
                "order_id": "TAKEALOT-LINE-TOTAL",
                "order_item_id": "TAKEALOT-LINE-TOTAL-1",
                "sku": "LINE-TOTAL-SKU",
                "title": "Line Total Item",
                "quantity": 2,
                "selling_price": 120.0,
                "currency": "ZAR",
                "sale_status": "Shipped",
                "order_date": "2026-04-23T09:30:00Z",
            }
        ]
    )

    assert len(snapshots) == 1, snapshots
    assert snapshots[0].total_amount == 120.0, snapshots[0]
    assert snapshots[0].items[0].quantity == 2, snapshots[0].items[0]
    assert snapshots[0].items[0].unit_price == 60.0, snapshots[0].items[0]


if __name__ == "__main__":
    main()
