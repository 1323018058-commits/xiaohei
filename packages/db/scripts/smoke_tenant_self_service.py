from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from smoke_billing_lifecycle import create_tenant, update_subscription
from smoke_tenant_onboarding import (
    get_tenant_row,
    login,
    mask_secret,
    prepare_database,
    require_database_url,
    sanitize_text,
)


def assert_status(response, expected: int, label: str, *, secrets: list[str] | None = None) -> None:
    if response.status_code == expected:
        return
    safe_text = sanitize_text(response.text, secrets or [])
    raise AssertionError(f"{label} returned {response.status_code}: {safe_text[:500]}")


def assert_me_status(client, cookies, expected_status: str) -> dict:
    response = client.get("/api/auth/me", cookies=cookies)
    assert_status(response, 200, f"/auth/me {expected_status}")
    payload = response.json()
    assert payload["subscription_status"] == expected_status, payload
    assert payload["user"]["subscription_status"] == expected_status, payload
    return payload


def assert_usage_status(client, cookies, expected_status: str) -> dict:
    response = client.get("/admin/api/tenant/usage", cookies=cookies)
    assert_status(response, 200, f"tenant self usage {expected_status}")
    payload = response.json()
    assert payload["subscription_status"] == expected_status, payload
    return payload


def create_store(client, cookies, *, name: str, expected_status: int) -> None:
    api_key = f"selfkey{uuid4().hex[:12]}"
    api_secret = f"selfsecret{uuid4().hex[:16]}"
    response = client.post(
        "/api/v1/stores",
        json={
            "name": name,
            "platform": "takealot",
            "api_key": api_key,
            "api_secret": api_secret,
            "status": "active",
        },
        cookies=cookies,
    )
    assert_status(response, expected_status, f"self-service create store {name}", secrets=[api_key, api_secret])


def main() -> None:
    require_database_url()
    prepare_database()

    from fastapi.testclient import TestClient

    from api_main import app
    from src.platform.settings.base import settings

    unique_suffix = uuid4().hex[:8]
    tenant_slug = f"self-service-{unique_suffix}"
    tenant_name = f"Self Service {unique_suffix}"
    tenant_admin_username = f"self_admin_{unique_suffix}"
    tenant_admin_email = f"{tenant_admin_username}@smoke.local"
    tenant_admin_password = f"SelfService{unique_suffix}!"
    now = datetime.now(UTC)
    paid_through = now + timedelta(days=30)
    expired_at = now - timedelta(minutes=5)
    renewed_until = now + timedelta(days=60)

    client = TestClient(app)

    super_admin_cookies, super_admin_login = login(
        client,
        username=settings.demo_username,
        password=settings.demo_password,
    )
    assert super_admin_login["session"]["user"]["role"] == "super_admin", super_admin_login

    tenant_id = create_tenant(
        client,
        super_admin_cookies,
        tenant_slug=tenant_slug,
        tenant_name=tenant_name,
        admin_username=tenant_admin_username,
        admin_email=tenant_admin_email,
        admin_password=tenant_admin_password,
    )
    assert tenant_id == str(get_tenant_row(tenant_slug)["id"])

    update_subscription(
        client,
        super_admin_cookies,
        tenant_id=tenant_id,
        plan="starter",
        status="active",
        trial_ends_at=None,
        current_period_ends_at=paid_through,
        reason="tenant self-service smoke paid activation",
    )

    tenant_admin_cookies, _ = login(
        client,
        username=tenant_admin_username,
        password=tenant_admin_password,
    )
    assert_me_status(client, tenant_admin_cookies, "active")
    active_usage = assert_usage_status(client, tenant_admin_cookies, "active")
    assert active_usage["tenant_id"] == tenant_id, active_usage
    assert active_usage["current_period_ends_at"] is not None, active_usage

    update_subscription(
        client,
        super_admin_cookies,
        tenant_id=tenant_id,
        plan="starter",
        status="active",
        trial_ends_at=None,
        current_period_ends_at=expired_at,
        reason="tenant self-service smoke expire",
    )
    assert_me_status(client, tenant_admin_cookies, "past_due")
    past_due_usage = assert_usage_status(client, tenant_admin_cookies, "past_due")
    assert "subscription is not writable" in past_due_usage["warnings"], past_due_usage
    create_store(
        client,
        tenant_admin_cookies,
        name=f"Self Service Blocked {unique_suffix}",
        expected_status=402,
    )

    update_subscription(
        client,
        super_admin_cookies,
        tenant_id=tenant_id,
        plan="starter",
        status="active",
        trial_ends_at=None,
        current_period_ends_at=renewed_until,
        reason="tenant self-service smoke renewal",
    )
    assert_me_status(client, tenant_admin_cookies, "active")
    renewed_usage = assert_usage_status(client, tenant_admin_cookies, "active")
    assert renewed_usage["current_period_ends_at"] is not None, renewed_usage
    create_store(
        client,
        tenant_admin_cookies,
        name=f"Self Service Store {unique_suffix}",
        expected_status=200,
    )

    print(
        json.dumps(
            {
                "tenant_id": tenant_id,
                "tenant_slug": tenant_slug,
                "tenant_admin_username": tenant_admin_username,
                "tenant_admin_password": mask_secret(tenant_admin_password),
                "checks": {
                    "dashboard_usage_reads_own_tenant": True,
                    "auth_me_reflects_past_due_without_relogin": True,
                    "past_due_store_write_blocked": True,
                    "renewal_restores_store_write": True,
                },
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
