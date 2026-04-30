from __future__ import annotations

import json
import os
import sys
from uuid import uuid4
from pathlib import Path

os.environ["XH_DATABASE_URL"] = ""

ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "apps" / "api"

sys.path.insert(0, str(API_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from api_main import app  # noqa: E402
from src.modules.common.dev_state import ADMIN_USER_ID, DEMO_TENANT_ID, app_state  # noqa: E402


def main() -> None:
    client = TestClient(app)
    suffix = uuid4().hex[:8]

    admin_cookies = login(client, "admin", "admin123")
    tenant_cookies = login(client, "tenant_admin", "tenant123")
    warehouse_user = app_state.create_user(
        {
            "tenant_id": DEMO_TENANT_ID,
            "username": f"warehouse_ops_{suffix}",
            "email": f"warehouse_ops_{suffix}@demo.local",
            "password": "warehouse123",
            "role": "warehouse",
            "status": "active",
            "force_password_reset": False,
        }
    )
    warehouse_cookies = login(client, warehouse_user["username"], "warehouse123")

    retry_task = create_task("Task ops retry smoke")
    app_state.update_task(
        retry_task["id"],
        status="waiting_retry",
        stage="backoff",
        attempt_count=2,
        max_retries=3,
        retryable=True,
        next_retry_at=None,
        error_code="TAKEALOT_503",
        error_msg="Temporary platform failure",
        error_details={"http_status": 503},
    )
    retry_response = client.post(
        f"/api/tasks/{retry_task['id']}/retry-now",
        json={"reason": "smoke retry now"},
        cookies=admin_cookies,
    )
    assert retry_response.status_code == 200, retry_response.text
    retry_payload = retry_response.json()
    assert retry_payload["status"] == "queued", retry_payload
    assert retry_payload["stage"] == "queued", retry_payload
    assert retry_payload["error_code"] is None, retry_payload
    assert_event(client, retry_task["id"], "task.retry_requested", admin_cookies)
    assert_audit(retry_task["id"], "task.retry_now")

    cancel_task = create_task("Task ops cancel smoke")
    app_state.update_task(
        cancel_task["id"],
        status="running",
        stage="syncing",
        attempt_count=1,
        lease_owner="smoke-worker",
        lease_token="smoke-lease",
    )
    cancel_response = client.post(
        f"/api/tasks/{cancel_task['id']}/cancel",
        json={"reason": "smoke cancel"},
        cookies=admin_cookies,
    )
    assert cancel_response.status_code == 200, cancel_response.text
    cancel_payload = cancel_response.json()
    assert cancel_payload["status"] == "cancelled", cancel_payload
    assert cancel_payload["stage"] == "cancelled", cancel_payload
    assert cancel_payload["error_code"] == "TASK_CANCELLED", cancel_payload
    assert_event(client, cancel_task["id"], "task.cancelled", admin_cookies)
    assert_audit(cancel_task["id"], "task.cancel")

    permission_task = create_task("Task ops permission smoke")
    forbidden_response = client.post(
        f"/api/tasks/{permission_task['id']}/cancel",
        json={"reason": "warehouse should not mutate"},
        cookies=warehouse_cookies,
    )
    assert forbidden_response.status_code == 403, forbidden_response.text

    foreign = app_state.create_tenant_with_admin(
        {
            "slug": f"foreign-task-ops-{suffix}",
            "name": f"Foreign Task Ops {suffix}",
            "plan": "starter",
            "subscription_status": "active",
            "admin_username": f"foreign_admin_{suffix}",
            "admin_email": f"foreign_admin_{suffix}@demo.local",
            "admin_password": "foreign123",
        },
        updated_by=ADMIN_USER_ID,
    )
    foreign_task = create_task(
        "Foreign task ops smoke",
        tenant_id=foreign["tenant"]["id"],
        actor_user_id=foreign["admin_user"]["id"],
        actor_role="tenant_admin",
    )
    isolated_response = client.get(
        f"/api/tasks/{foreign_task['id']}",
        cookies=tenant_cookies,
    )
    assert isolated_response.status_code == 404, isolated_response.text

    print(
        json.dumps(
            {
                "retry_task_id": retry_task["id"],
                "retry_status": retry_payload["status"],
                "cancel_task_id": cancel_task["id"],
                "cancel_status": cancel_payload["status"],
                "permission_status": forbidden_response.status_code,
                "tenant_isolation_status": isolated_response.status_code,
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


def create_task(
    label: str,
    *,
    tenant_id: str = DEMO_TENANT_ID,
    actor_user_id: str = ADMIN_USER_ID,
    actor_role: str = "super_admin",
) -> dict[str, object]:
    return app_state.create_task(
        task_type="SYNC_STORE_LISTINGS",
        domain="store",
        queue_name="store-sync",
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        tenant_id=tenant_id,
        store_id=None,
        target_type="store_collection",
        target_id=f"smoke-task-ops-{uuid4().hex[:8]}",
        request_id=f"smoke-task-ops-{uuid4().hex[:8]}",
        label=label,
        next_action="Operator task operation smoke",
    )


def assert_event(
    client: TestClient,
    task_id: str,
    event_type: str,
    cookies,
) -> None:
    response = client.get(f"/api/tasks/{task_id}/events", cookies=cookies)
    assert response.status_code == 200, response.text
    events = response.json()["events"]
    assert any(event["event_type"] == event_type for event in events), events


def assert_audit(task_id: str, action: str) -> None:
    audits = app_state.list_audits(DEMO_TENANT_ID)
    assert any(
        audit["task_id"] == task_id and audit["action"] == action
        for audit in audits
    ), audits[:5]


if __name__ == "__main__":
    main()
