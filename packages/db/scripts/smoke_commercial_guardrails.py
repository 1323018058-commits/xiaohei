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
        raise SystemExit("XH_DATABASE_URL must be set before running commercial smoke")


def prepare_database() -> None:
    from src.platform.db.session import apply_sql_directory

    apply_sql_directory(ROOT / "packages" / "db" / "migrations")
    apply_sql_directory(ROOT / "packages" / "db" / "seeds")


def ensure_tenant(tenant_id: str, *, name: str, slug: str) -> None:
    from src.platform.db.session import get_db_session

    with get_db_session() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                insert into tenants (id, name, slug, plan, status, created_at, updated_at)
                values (%s, %s, %s, 'pro', 'active', now(), now())
                on conflict (id) do nothing
                """,
                (tenant_id, name, slug),
            )
        connection.commit()


def main() -> None:
    require_database_url()
    prepare_database()

    from fastapi.testclient import TestClient

    from api_main import app
    from src.modules.common.dev_state import DEMO_TENANT_ID, app_state

    client = TestClient(app)

    unique_suffix = uuid4().hex[:8]
    claim_task_type = f"guardrail.claim.once.{unique_suffix}"
    other_tenant_id = str(uuid4())
    ensure_tenant(
        other_tenant_id,
        name=f"Guardrail Tenant {unique_suffix}",
        slug=f"guardrail-{unique_suffix}",
    )

    other_user = app_state.create_user(
        {
            "tenant_id": other_tenant_id,
            "username": f"guardrail_admin_{unique_suffix}",
            "email": f"guardrail_{unique_suffix}@example.com",
            "role": "tenant_admin",
            "password": "guardrail123",
            "status": "active",
            "force_password_reset": False,
        }
    )
    other_store = app_state.create_store(
        {
            "tenant_id": other_tenant_id,
            "name": f"Guardrail Store {unique_suffix}",
            "platform": "takealot",
            "status": "active",
            "api_key": f"guardrail-key-{unique_suffix}",
            "api_secret": f"guardrail-secret-{unique_suffix}",
            "masked_api_key": f"guar********{unique_suffix[-4:]}",
            "api_key_status": "configured",
            "credential_status": "configured",
            "feature_policies": {
                "bidding_enabled": True,
                "listing_enabled": True,
                "sync_enabled": True,
            },
        }
    )
    other_listing = app_state.upsert_store_listing(
        store_id=other_store["id"],
        external_listing_id=f"guardrail-listing-{unique_suffix}",
        platform_product_id=None,
        sku=f"GUARDRAIL-SKU-{unique_suffix}",
        title="Guardrail Listing",
        platform_price=88.8,
        stock_quantity=5,
        currency="ZAR",
        sync_status="synced",
        raw_payload={"source": "commercial_guardrail"},
    )
    other_rule, _ = app_state.upsert_bidding_rule(
        store_id=other_store["id"],
        sku=other_listing["sku"],
        listing_id=other_listing["id"],
        floor_price=66.6,
        ceiling_price=99.9,
        strategy_type="manual",
        is_active=True,
    )
    other_task = app_state.create_task(
        task_type="guardrail.sync.visibility",
        domain="smoke",
        queue_name="smoke",
        actor_user_id=other_user["id"],
        actor_role=other_user["role"],
        tenant_id=other_tenant_id,
        store_id=other_store["id"],
        target_type="store",
        target_id=other_store["id"],
        request_id=f"guardrail-task-{unique_suffix}",
        label="Guardrail visibility task",
        next_action="Stay hidden from demo tenant",
    )
    claim_task = app_state.create_task(
        task_type=claim_task_type,
        domain="smoke",
        queue_name="smoke",
        actor_user_id=other_user["id"],
        actor_role=other_user["role"],
        tenant_id=other_tenant_id,
        store_id=None,
        target_type="smoke_task",
        target_id=unique_suffix,
        request_id=f"guardrail-claim-{unique_suffix}",
        label="Guardrail claim task",
        next_action="Verify worker lease exclusivity",
    )
    app_state.append_audit(
        request_id=f"guardrail-audit-{unique_suffix}",
        tenant_id=other_tenant_id,
        store_id=other_store["id"],
        actor_user_id=other_user["id"],
        actor_role=other_user["role"],
        action="guardrail.audit.seed",
        action_label="Seed guardrail audit",
        risk_level="low",
        target_type="store",
        target_id=other_store["id"],
        target_label=other_store["name"],
        before=None,
        after={"store_id": other_store["id"]},
        reason="commercial isolation smoke",
        result="success",
        task_id=other_task["id"],
    )

    login = client.post(
        "/api/auth/login",
        json={"username": "tenant_admin", "password": "tenant123"},
    )
    assert login.status_code == 200, login.text
    cookies = login.cookies

    me = client.get("/api/auth/me", cookies=cookies)
    assert me.status_code == 200, me.text
    assert me.json()["user"]["username"] == "tenant_admin", me.text
    assert me.json()["user"]["role"] == "tenant_admin", me.text

    users = client.get("/admin/api/users", cookies=cookies)
    assert users.status_code == 200, users.text
    assert all(
        user["username"] != other_user["username"]
        for user in users.json()["users"]
    ), users.text

    other_user_detail = client.get(f"/admin/api/users/{other_user['id']}", cookies=cookies)
    assert other_user_detail.status_code == 404, other_user_detail.text

    audits = client.get("/admin/api/audits", cookies=cookies)
    assert audits.status_code == 200, audits.text
    assert all(
        audit["tenant_id"] == DEMO_TENANT_ID
        for audit in audits.json()["audits"]
        if audit["tenant_id"] is not None
    ), audits.text

    stores = client.get("/api/v1/stores", cookies=cookies)
    assert stores.status_code == 200, stores.text
    assert all(
        store["store_id"] != other_store["id"]
        for store in stores.json()["stores"]
    ), stores.text

    other_store_detail = client.get(f"/api/v1/stores/{other_store['id']}", cookies=cookies)
    assert other_store_detail.status_code == 404, other_store_detail.text

    other_store_listings = client.get(
        f"/api/v1/stores/{other_store['id']}/listings",
        cookies=cookies,
    )
    assert other_store_listings.status_code == 404, other_store_listings.text

    tasks = client.get("/api/tasks", cookies=cookies)
    assert tasks.status_code == 200, tasks.text
    assert all(
        task["tenant_id"] == DEMO_TENANT_ID
        for task in tasks.json()["tasks"]
        if task["tenant_id"] is not None
    ), tasks.text

    other_task_detail = client.get(f"/api/tasks/{other_task['id']}", cookies=cookies)
    assert other_task_detail.status_code == 404, other_task_detail.text

    task_events = client.get(f"/api/tasks/{other_task['id']}/events", cookies=cookies)
    assert task_events.status_code == 404, task_events.text

    bidding_rules = client.get(
        f"/api/v1/bidding/rules?store_id={other_store['id']}",
        cookies=cookies,
    )
    assert bidding_rules.status_code == 404, bidding_rules.text

    first_claim = app_state.claim_queued_tasks(
        {claim_task_type},
        worker_id="guardrail-worker-a",
        limit=1,
    )
    second_claim = app_state.claim_queued_tasks(
        {claim_task_type},
        worker_id="guardrail-worker-b",
        limit=1,
    )
    assert len(first_claim) == 1, first_claim
    assert first_claim[0]["id"] == claim_task["id"], first_claim
    assert second_claim == [], second_claim

    print(
        json.dumps(
            {
                "tenant_isolation_verified": True,
                "demo_tenant_id": DEMO_TENANT_ID,
                "hidden_store_id": other_store["id"],
                "hidden_rule_id": other_rule["id"],
                "hidden_task_id": other_task["id"],
                "claim_task_id": claim_task["id"],
                "first_claim_worker": first_claim[0]["lease_owner"],
                "second_claim_count": len(second_claim),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
