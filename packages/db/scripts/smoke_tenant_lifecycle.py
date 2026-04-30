from __future__ import annotations

import json
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


def count_active_sessions(user_id: str) -> int:
    from src.platform.db.session import get_db_session

    with get_db_session() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select count(*) as session_count
                from auth_sessions
                where user_id = %s and status = 'active' and expires_at > now()
                """,
                (user_id,),
            )
            row = cursor.fetchone()
    return int(row["session_count"])


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
            "subscription_status": "active",
            "admin_username": admin_username,
            "admin_email": admin_email,
            "admin_password": admin_password,
            "reason": "tenant lifecycle smoke create",
        },
        cookies=cookies,
    )
    assert_status(response, 200, "create lifecycle tenant", secrets=[admin_password])
    payload = response.json()
    return payload["tenant"]["tenant_id"]


def update_tenant_status(
    client: Any,
    cookies: Any,
    *,
    tenant_id: str,
    status: str,
    reason: str,
) -> dict[str, Any]:
    response = client.patch(
        f"/admin/api/tenants/{tenant_id}",
        json={"status": status, "reason": reason},
        cookies=cookies,
    )
    assert_status(response, 200, f"tenant status {status}")
    payload = response.json()
    assert payload["tenant"]["status"] == status, payload
    return payload


def assert_tenant_auth_blocked(
    client: Any,
    *,
    cookies: Any,
    username: str,
    password: str,
    label: str,
) -> None:
    me_response = client.get("/api/auth/me", cookies=cookies)
    assert_status(me_response, 401, f"{label} /auth/me", secrets=[password])

    login_response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert_status(login_response, 401, f"{label} login", secrets=[password])

    store_response = client.post(
        "/api/v1/stores",
        json={
            "name": f"Blocked Store {uuid4().hex[:8]}",
            "platform": "takealot",
            "api_key": f"blockedkey{uuid4().hex[:12]}",
            "api_secret": f"blockedsecret{uuid4().hex[:16]}",
            "status": "active",
        },
        cookies=cookies,
    )
    assert_status(store_response, 401, f"{label} store write", secrets=[password])


def reset_tenant_admin_password(
    client: Any,
    cookies: Any,
    *,
    tenant_id: str,
) -> dict[str, Any]:
    response = client.post(
        f"/admin/api/tenants/{tenant_id}/reset-admin-password",
        json={"reason": "tenant lifecycle smoke password reset"},
        cookies=cookies,
    )
    assert_status(response, 200, "reset tenant admin password")
    return response.json()


def main() -> None:
    require_database_url()
    prepare_database()

    from fastapi.testclient import TestClient

    from api_main import app
    from src.platform.settings.base import settings

    unique_suffix = uuid4().hex[:8]
    tenant_slug = f"tenant-life-{unique_suffix}"
    tenant_name = f"Tenant Lifecycle {unique_suffix}"
    tenant_admin_username = f"tenant_life_{unique_suffix}"
    tenant_admin_email = f"{tenant_admin_username}@smoke.local"
    tenant_admin_password = f"TenantLife{unique_suffix}!"
    temporary_password = "temp12345"

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
    tenant_admin_row = get_user_row(tenant_admin_username)
    tenant_admin_user_id = str(tenant_admin_row["id"])

    tenant_admin_cookies, tenant_admin_login = login(
        client,
        username=tenant_admin_username,
        password=tenant_admin_password,
    )
    assert tenant_admin_login["session"]["user"]["role"] == "tenant_admin", tenant_admin_login
    assert count_active_sessions(tenant_admin_user_id) >= 1

    audit_count = count_audits(tenant_id)
    suspend_payload = update_tenant_status(
        client,
        super_admin_cookies,
        tenant_id=tenant_id,
        status="suspended",
        reason="tenant lifecycle smoke suspend",
    )
    assert suspend_payload["revoked_session_count"] >= 1, suspend_payload
    assert get_tenant_row(tenant_slug)["status"] == "suspended"
    assert count_active_sessions(tenant_admin_user_id) == 0
    assert_tenant_auth_blocked(
        client,
        cookies=tenant_admin_cookies,
        username=tenant_admin_username,
        password=tenant_admin_password,
        label="suspended tenant",
    )
    suspend_actions = audit_actions_since(tenant_id, audit_count)
    assert "admin.tenant.status.update" in suspend_actions, suspend_actions

    update_tenant_status(
        client,
        super_admin_cookies,
        tenant_id=tenant_id,
        status="active",
        reason="tenant lifecycle smoke restore from suspended",
    )
    restored_cookies, restored_login = login(
        client,
        username=tenant_admin_username,
        password=tenant_admin_password,
    )
    assert restored_login["session"]["user"]["username"] == tenant_admin_username, restored_login

    update_tenant_status(
        client,
        super_admin_cookies,
        tenant_id=tenant_id,
        status="disabled",
        reason="tenant lifecycle smoke disable",
    )
    assert get_tenant_row(tenant_slug)["status"] == "disabled"
    assert_tenant_auth_blocked(
        client,
        cookies=restored_cookies,
        username=tenant_admin_username,
        password=tenant_admin_password,
        label="disabled tenant",
    )

    update_tenant_status(
        client,
        super_admin_cookies,
        tenant_id=tenant_id,
        status="active",
        reason="tenant lifecycle smoke restore from disabled",
    )
    password_reset_login_cookies, _ = login(
        client,
        username=tenant_admin_username,
        password=tenant_admin_password,
    )
    assert count_active_sessions(tenant_admin_user_id) >= 1

    audit_count = count_audits(tenant_id)
    reset_payload = reset_tenant_admin_password(
        client,
        super_admin_cookies,
        tenant_id=tenant_id,
    )
    assert reset_payload["admin_user"]["username"] == tenant_admin_username, reset_payload
    assert reset_payload["admin_user"]["force_password_reset"] is True, reset_payload
    assert reset_payload["revoked_session_count"] >= 1, reset_payload
    assert get_user_row(tenant_admin_username)["force_password_reset"] is True
    assert count_active_sessions(tenant_admin_user_id) == 0
    reset_actions = audit_actions_since(tenant_id, audit_count)
    assert "admin.tenant.admin_password.reset" in reset_actions, reset_actions

    assert_tenant_auth_blocked(
        client,
        cookies=password_reset_login_cookies,
        username=tenant_admin_username,
        password=tenant_admin_password,
        label="password reset old credentials",
    )
    temp_cookies, temp_login = login(
        client,
        username=tenant_admin_username,
        password=temporary_password,
    )
    assert temp_login["session"]["user"]["username"] == tenant_admin_username, temp_login
    me_after_temp_login = client.get("/api/auth/me", cookies=temp_cookies)
    assert_status(me_after_temp_login, 200, "temporary password /auth/me")

    print(
        json.dumps(
            {
                "tenant_id": tenant_id,
                "tenant_slug": tenant_slug,
                "tenant_status": get_tenant_row(tenant_slug)["status"],
                "tenant_admin_username": tenant_admin_username,
                "tenant_admin_password": mask_secret(tenant_admin_password),
                "temporary_password": mask_secret(temporary_password),
                "checks": {
                    "suspended_blocks_login": True,
                    "disabled_blocks_login": True,
                    "restore_reopens_login": True,
                    "reset_revokes_sessions": True,
                    "temporary_password_login": True,
                },
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
