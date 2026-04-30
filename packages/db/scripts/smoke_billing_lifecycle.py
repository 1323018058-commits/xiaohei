from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from smoke_tenant_onboarding import (
    count_audits,
    get_tenant_row,
    get_user_row,
    login,
    mask_secret,
    prepare_database,
    require_database_url,
    sanitize_text,
)


def assert_status(response: Any, expected: int, label: str, *, secrets: list[str] | None = None) -> None:
    if response.status_code == expected:
        return
    safe_text = sanitize_text(response.text, secrets or [])
    raise AssertionError(f"{label} returned {response.status_code}: {safe_text[:500]}")


def audit_actions_since(tenant_id: str, audit_count: int) -> list[str]:
    from src.platform.db.session import get_db_session

    with get_db_session() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select action
                from audit_logs
                where tenant_id = %s
                order by created_at asc, id asc
                """,
                (tenant_id,),
            )
            rows = cursor.fetchall()
    return [row["action"] for row in rows[audit_count:]]


def create_tenant(
    client: Any,
    cookies: Any,
    *,
    tenant_slug: str,
    tenant_name: str,
    admin_username: str,
    admin_email: str,
    admin_password: str,
) -> str:
    response = client.post(
        "/admin/api/tenants",
        json={
            "slug": tenant_slug,
            "name": tenant_name,
            "plan": "starter",
            "subscription_status": "trialing",
            "admin_username": admin_username,
            "admin_email": admin_email,
            "admin_password": admin_password,
            "reason": "billing lifecycle smoke create",
        },
        cookies=cookies,
    )
    assert_status(response, 200, "create billing tenant", secrets=[admin_password])
    return response.json()["tenant"]["tenant_id"]


def update_subscription(
    client: Any,
    cookies: Any,
    *,
    tenant_id: str,
    plan: str,
    status: str,
    trial_ends_at: datetime | None,
    current_period_ends_at: datetime | None,
    reason: str,
) -> dict[str, Any]:
    response = client.patch(
        f"/admin/api/tenants/{tenant_id}/subscription",
        json={
            "plan": plan,
            "status": status,
            "trial_ends_at": trial_ends_at.isoformat() if trial_ends_at else None,
            "current_period_ends_at": current_period_ends_at.isoformat() if current_period_ends_at else None,
            "reason": reason,
        },
        cookies=cookies,
    )
    assert_status(response, 200, f"subscription {status}")
    return response.json()


def fetch_usage(client: Any, cookies: Any, *, tenant_id: str, expected_status: str) -> dict[str, Any]:
    response = client.get(
        f"/admin/api/tenant/usage?tenant_id={tenant_id}",
        cookies=cookies,
    )
    assert_status(response, 200, "billing tenant usage")
    payload = response.json()
    assert payload["subscription_status"] == expected_status, payload
    return payload


def create_operator(
    client: Any,
    cookies: Any,
    *,
    username: str,
    expected_status: int,
) -> None:
    response = client.post(
        "/admin/api/users",
        json={
            "username": username,
            "email": f"{username}@smoke.local",
            "role": "operator",
            "password": f"Operator{uuid4().hex[:8]}!",
        },
        cookies=cookies,
    )
    assert_status(response, expected_status, f"create operator {username}")


def main() -> None:
    require_database_url()
    prepare_database()

    from fastapi.testclient import TestClient

    from api_main import app
    from src.platform.settings.base import settings

    unique_suffix = uuid4().hex[:8]
    tenant_slug = f"billing-life-{unique_suffix}"
    tenant_name = f"Billing Lifecycle {unique_suffix}"
    tenant_admin_username = f"billing_admin_{unique_suffix}"
    tenant_admin_email = f"{tenant_admin_username}@smoke.local"
    tenant_admin_password = f"BillingLife{unique_suffix}!"
    now = datetime.now(UTC)
    trial_end = now + timedelta(days=7)
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
    assert get_user_row(tenant_admin_username)["role"] == "tenant_admin"

    tenant_admin_cookies, _ = login(
        client,
        username=tenant_admin_username,
        password=tenant_admin_password,
    )

    audit_count = count_audits(tenant_id)
    update_subscription(
        client,
        super_admin_cookies,
        tenant_id=tenant_id,
        plan="starter",
        status="active",
        trial_ends_at=trial_end,
        current_period_ends_at=paid_through,
        reason="billing lifecycle smoke paid activation",
    )
    active_usage = fetch_usage(
        client,
        super_admin_cookies,
        tenant_id=tenant_id,
        expected_status="active",
    )
    assert active_usage["current_period_ends_at"] is not None, active_usage
    create_operator(
        client,
        tenant_admin_cookies,
        username=f"billing_ops_a_{unique_suffix}",
        expected_status=200,
    )

    update_subscription(
        client,
        super_admin_cookies,
        tenant_id=tenant_id,
        plan="starter",
        status="active",
        trial_ends_at=trial_end,
        current_period_ends_at=expired_at,
        reason="billing lifecycle smoke force expiry",
    )
    expired_usage = fetch_usage(
        client,
        super_admin_cookies,
        tenant_id=tenant_id,
        expected_status="past_due",
    )
    assert "subscription is not writable" in expired_usage["warnings"], expired_usage
    create_operator(
        client,
        tenant_admin_cookies,
        username=f"billing_ops_blocked_{unique_suffix}",
        expected_status=402,
    )

    update_subscription(
        client,
        super_admin_cookies,
        tenant_id=tenant_id,
        plan="starter",
        status="active",
        trial_ends_at=trial_end,
        current_period_ends_at=renewed_until,
        reason="billing lifecycle smoke renewal",
    )
    renewed_usage = fetch_usage(
        client,
        super_admin_cookies,
        tenant_id=tenant_id,
        expected_status="active",
    )
    assert renewed_usage["current_period_ends_at"] is not None, renewed_usage
    create_operator(
        client,
        tenant_admin_cookies,
        username=f"billing_ops_b_{unique_suffix}",
        expected_status=200,
    )

    actions = audit_actions_since(tenant_id, audit_count)
    subscription_updates = [
        action
        for action in actions
        if action == "admin.tenant.subscription.update"
    ]
    assert len(subscription_updates) >= 3, actions

    print(
        json.dumps(
            {
                "tenant_id": tenant_id,
                "tenant_slug": tenant_slug,
                "tenant_admin_username": tenant_admin_username,
                "tenant_admin_password": mask_secret(tenant_admin_password),
                "checks": {
                    "paid_activation_allows_write": True,
                    "expired_period_blocks_write": True,
                    "renewal_restores_write": True,
                    "subscription_audit_count": len(subscription_updates),
                },
                "periods": {
                    "paid_through": paid_through.isoformat(),
                    "expired_at": expired_at.isoformat(),
                    "renewed_until": renewed_until.isoformat(),
                },
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
