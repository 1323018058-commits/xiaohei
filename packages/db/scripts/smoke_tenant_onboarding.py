from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "apps" / "api"

sys.path.insert(0, str(API_ROOT))


def require_database_url() -> None:
    from src.platform.settings.base import settings

    if not settings.database_url:
        raise SystemExit("XH_DATABASE_URL must be set before running tenant onboarding smoke")


def prepare_database() -> None:
    from src.platform.db.session import apply_sql_directory

    apply_sql_directory(ROOT / "packages" / "db" / "migrations")
    apply_sql_directory(ROOT / "packages" / "db" / "seeds")


def mask_secret(value: str | None, *, prefix: int = 2, suffix: int = 2) -> str | None:
    if value is None:
        return None
    if len(value) <= prefix + suffix:
        return "*" * len(value)
    return f"{value[:prefix]}***{value[-suffix:]}"


def sanitize_text(text: str, secrets: list[str]) -> str:
    sanitized = text
    for secret in secrets:
        if secret:
            sanitized = sanitized.replace(secret, "***")
    return sanitized


def assert_status(response: Any, expected: int, label: str, *, secrets: list[str] | None = None) -> None:
    if response.status_code == expected:
        return
    safe_text = sanitize_text(response.text, secrets or [])
    raise AssertionError(f"{label} returned {response.status_code}: {safe_text[:500]}")


def request_with_candidates(
    client: Any,
    *,
    method: str,
    url: str,
    candidates: list[tuple[str, dict[str, Any]]],
    cookies: Any,
    secrets: list[str],
) -> Any:
    validation_failures: list[str] = []
    for label, payload in candidates:
        response = getattr(client, method)(url, json=payload, cookies=cookies)
        if response.status_code < 400:
            return response
        if response.status_code in {400, 422}:
            validation_failures.append(
                f"{label}:{response.status_code}:{sanitize_text(response.text, secrets)[:240]}"
            )
            continue
        raise AssertionError(
            f"{method.upper()} {url} failed for {label}: "
            f"{response.status_code} {sanitize_text(response.text, secrets)[:500]}"
        )
    raise AssertionError(
        f"{method.upper()} {url} did not accept any candidate payload: {' | '.join(validation_failures)}"
    )


def login(client: Any, *, username: str, password: str) -> tuple[Any, dict[str, Any]]:
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert_status(
        response,
        200,
        f"login for {username}",
        secrets=[password],
    )
    return response.cookies, response.json()


def get_tenant_row(tenant_slug: str) -> dict[str, Any]:
    from src.platform.db.session import get_db_session

    with get_db_session() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select id, slug, name, status, plan, created_at, updated_at
                from tenants
                where slug = %s
                """,
                (tenant_slug,),
            )
            row = cursor.fetchone()
    assert row is not None, f"tenant {tenant_slug} was not created"
    return row


def get_user_row(username: str) -> dict[str, Any]:
    from src.platform.db.session import get_db_session

    with get_db_session() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select id, tenant_id, username, email, role, status, force_password_reset
                from users
                where username = %s
                """,
                (username,),
            )
            row = cursor.fetchone()
    assert row is not None, f"user {username} was not created"
    return row


def get_subscription_row(tenant_id: str) -> dict[str, Any]:
    from src.platform.db.session import get_db_session

    with get_db_session() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select tenant_id, plan, status, updated_by, created_at, updated_at
                from tenant_subscriptions
                where tenant_id = %s
                """,
                (tenant_id,),
            )
            row = cursor.fetchone()
    assert row is not None, f"subscription for tenant {tenant_id} was not created"
    return row


def get_store_count(tenant_id: str) -> int:
    from src.platform.db.session import get_db_session

    with get_db_session() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select count(*) as store_count
                from stores
                where tenant_id = %s and deleted_at is null
                """,
                (tenant_id,),
            )
            row = cursor.fetchone()
    return int(row["store_count"])


def list_audits_since(tenant_id: str, audit_count: int) -> list[dict[str, Any]]:
    from src.platform.db.session import get_db_session

    with get_db_session() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select
                  id,
                  tenant_id,
                  actor_user_id,
                  actor_role,
                  action,
                  target_type,
                  target_id,
                  before,
                  after,
                  diff,
                  reason,
                  result,
                  created_at
                from audit_logs
                where tenant_id = %s
                order by created_at asc, id asc
                """,
                (tenant_id,),
            )
            rows = cursor.fetchall()
    return rows[audit_count:]


def count_audits(tenant_id: str) -> int:
    from src.platform.db.session import get_db_session

    with get_db_session() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select count(*) as audit_count
                from audit_logs
                where tenant_id = %s
                """,
                (tenant_id,),
            )
            row = cursor.fetchone()
    return int(row["audit_count"])


def flatten_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def audit_matches(
    audit: dict[str, Any],
    *,
    tenant_id: str,
    expected_plan: str,
    expected_status: str,
) -> bool:
    if str(audit["tenant_id"]) != tenant_id or audit["result"] != "success":
        return False

    target_related = audit["target_id"] in {tenant_id, None} or audit["target_type"] in {
        "tenant",
        "tenant_subscription",
        "subscription",
    }
    if not target_related:
        return False

    haystack = " ".join(
        flatten_to_text(audit.get(key))
        for key in ("action", "target_type", "before", "after", "diff", "reason")
    ).lower()
    return expected_plan.lower() in haystack and expected_status.lower() in haystack


def fetch_usage(client: Any, cookies: Any, *, tenant_id: str, expected_plan: str, expected_status: str) -> dict[str, Any]:
    response = client.get("/admin/api/tenant/usage", cookies=cookies)
    assert_status(response, 200, "tenant usage lookup")
    payload = response.json()
    assert payload["tenant_id"] == tenant_id, response.text
    assert payload["plan"] == expected_plan, response.text
    assert payload["subscription_status"] == expected_status, response.text
    return payload


def main() -> None:
    require_database_url()
    prepare_database()

    from fastapi.testclient import TestClient

    from api_main import app
    from src.platform.settings.base import settings

    unique_suffix = uuid4().hex[:8]
    initial_plan = "starter"
    upgraded_plan = "growth"
    tenant_slug = f"tenant-onboard-{unique_suffix}"
    tenant_name = f"Tenant Onboarding {unique_suffix}"
    tenant_admin_username = f"tenant_admin_{unique_suffix}"
    tenant_admin_email = f"{tenant_admin_username}@smoke.local"
    tenant_admin_password = f"TenantPass{unique_suffix}!"
    store_api_key = f"tenantkey{uuid4().hex[:12]}"
    store_api_secret = f"tenantsecret{uuid4().hex[:16]}"
    store_name = f"Smoke Onboarding Store {unique_suffix}"

    client = TestClient(app)

    super_admin_cookies, super_admin_login = login(
        client,
        username=settings.demo_username,
        password=settings.demo_password,
    )
    assert super_admin_login["session"]["user"]["role"] == "super_admin", super_admin_login

    create_tenant = request_with_candidates(
        client,
        method="post",
        url="/admin/api/tenants",
        cookies=super_admin_cookies,
        secrets=[tenant_admin_password],
        candidates=[
            (
                "flat_admin_plan",
                {
                    "slug": tenant_slug,
                    "name": tenant_name,
                    "plan": initial_plan,
                    "admin_username": tenant_admin_username,
                    "admin_email": tenant_admin_email,
                    "admin_password": tenant_admin_password,
                },
            ),
            (
                "flat_tenant_admin",
                {
                    "slug": tenant_slug,
                    "name": tenant_name,
                    "subscription_plan": initial_plan,
                    "tenant_admin_username": tenant_admin_username,
                    "tenant_admin_email": tenant_admin_email,
                    "tenant_admin_password": tenant_admin_password,
                },
            ),
            (
                "nested_admin_subscription",
                {
                    "tenant": {"slug": tenant_slug, "name": tenant_name},
                    "admin": {
                        "username": tenant_admin_username,
                        "email": tenant_admin_email,
                        "password": tenant_admin_password,
                        "role": "tenant_admin",
                    },
                    "subscription": {"plan": initial_plan},
                },
            ),
            (
                "nested_tenant_admin_subscription",
                {
                    "tenant": {"slug": tenant_slug, "name": tenant_name},
                    "tenant_admin": {
                        "username": tenant_admin_username,
                        "email": tenant_admin_email,
                        "password": tenant_admin_password,
                    },
                    "subscription": {"plan": initial_plan, "status": "active"},
                },
            ),
        ],
    )
    assert create_tenant.status_code in {200, 201}, create_tenant.text

    tenant_row = get_tenant_row(tenant_slug)
    tenant_id = str(tenant_row["id"])
    tenant_admin_row = get_user_row(tenant_admin_username)
    subscription_row = get_subscription_row(tenant_id)

    assert str(tenant_admin_row["tenant_id"]) == tenant_id, tenant_admin_row
    assert tenant_admin_row["role"] == "tenant_admin", tenant_admin_row
    assert tenant_admin_row["status"] == "active", tenant_admin_row
    assert subscription_row["plan"] == initial_plan, subscription_row
    assert subscription_row["status"] == "active", subscription_row

    tenant_admin_cookies, tenant_admin_login = login(
        client,
        username=tenant_admin_username,
        password=tenant_admin_password,
    )
    assert tenant_admin_login["session"]["user"]["role"] == "tenant_admin", tenant_admin_login
    assert tenant_admin_login["session"]["user"]["subscription_status"] == "active", tenant_admin_login

    initial_usage = fetch_usage(
        client,
        tenant_admin_cookies,
        tenant_id=tenant_id,
        expected_plan=initial_plan,
        expected_status="active",
    )
    assert initial_usage["limits"]["max_stores"] == 1, initial_usage
    assert initial_usage["usage"]["active_users"] == 1, initial_usage

    create_store = client.post(
        "/api/v1/stores",
        json={
            "name": store_name,
            "platform": "takealot",
            "api_key": store_api_key,
            "api_secret": store_api_secret,
            "status": "active",
        },
        cookies=tenant_admin_cookies,
    )
    assert_status(
        create_store,
        200,
        "tenant store creation",
        secrets=[store_api_key, store_api_secret],
    )
    store_payload = create_store.json()
    store_id = store_payload["store_id"]
    assert get_store_count(tenant_id) == 1, store_payload

    audit_count = count_audits(tenant_id)

    upgrade = request_with_candidates(
        client,
        method="patch",
        url=f"/admin/api/tenants/{tenant_id}/subscription",
        cookies=super_admin_cookies,
        secrets=[],
        candidates=[
            (
                "flat_plan_status",
                {"plan": upgraded_plan, "status": "active", "reason": "tenant onboarding smoke upgrade"},
            ),
            (
                "nested_subscription",
                {
                    "subscription": {"plan": upgraded_plan, "status": "active"},
                    "reason": "tenant onboarding smoke upgrade",
                },
            ),
            (
                "flat_plan_code_subscription_status",
                {
                    "plan_code": upgraded_plan,
                    "subscription_status": "active",
                    "reason": "tenant onboarding smoke upgrade",
                },
            ),
        ],
    )
    assert upgrade.status_code == 200, upgrade.text

    subscription_after_upgrade = get_subscription_row(tenant_id)
    assert subscription_after_upgrade["plan"] == upgraded_plan, subscription_after_upgrade
    assert subscription_after_upgrade["status"] == "active", subscription_after_upgrade
    usage_after_upgrade = fetch_usage(
        client,
        tenant_admin_cookies,
        tenant_id=tenant_id,
        expected_plan=upgraded_plan,
        expected_status="active",
    )
    assert usage_after_upgrade["limits"]["max_stores"] == 3, usage_after_upgrade

    upgrade_audits = list_audits_since(tenant_id, audit_count)
    assert any(
        audit_matches(audit, tenant_id=tenant_id, expected_plan=upgraded_plan, expected_status="active")
        for audit in upgrade_audits
    ), upgrade_audits

    audit_count = count_audits(tenant_id)
    pause = request_with_candidates(
        client,
        method="patch",
        url=f"/admin/api/tenants/{tenant_id}/subscription",
        cookies=super_admin_cookies,
        secrets=[],
        candidates=[
            (
                "flat_status",
                {"plan": upgraded_plan, "status": "paused", "reason": "tenant onboarding smoke pause"},
            ),
            (
                "nested_status",
                {
                    "subscription": {"plan": upgraded_plan, "status": "paused"},
                    "reason": "tenant onboarding smoke pause",
                },
            ),
            (
                "flat_subscription_status",
                {
                    "plan_code": upgraded_plan,
                    "subscription_status": "paused",
                    "reason": "tenant onboarding smoke pause",
                },
            ),
        ],
    )
    assert pause.status_code == 200, pause.text

    subscription_after_pause = get_subscription_row(tenant_id)
    assert subscription_after_pause["plan"] == upgraded_plan, subscription_after_pause
    assert subscription_after_pause["status"] == "paused", subscription_after_pause
    usage_after_pause = fetch_usage(
        client,
        tenant_admin_cookies,
        tenant_id=tenant_id,
        expected_plan=upgraded_plan,
        expected_status="paused",
    )
    assert "subscription is not writable" in usage_after_pause["warnings"], usage_after_pause

    pause_audits = list_audits_since(tenant_id, audit_count)
    assert any(
        audit_matches(audit, tenant_id=tenant_id, expected_plan=upgraded_plan, expected_status="paused")
        for audit in pause_audits
    ), pause_audits

    audit_count = count_audits(tenant_id)
    resume = request_with_candidates(
        client,
        method="patch",
        url=f"/admin/api/tenants/{tenant_id}/subscription",
        cookies=super_admin_cookies,
        secrets=[],
        candidates=[
            (
                "flat_resume",
                {"plan": upgraded_plan, "status": "active", "reason": "tenant onboarding smoke resume"},
            ),
            (
                "nested_resume",
                {
                    "subscription": {"plan": upgraded_plan, "status": "active"},
                    "reason": "tenant onboarding smoke resume",
                },
            ),
            (
                "flat_resume_subscription_status",
                {
                    "plan_code": upgraded_plan,
                    "subscription_status": "active",
                    "reason": "tenant onboarding smoke resume",
                },
            ),
        ],
    )
    assert resume.status_code == 200, resume.text

    subscription_after_resume = get_subscription_row(tenant_id)
    assert subscription_after_resume["plan"] == upgraded_plan, subscription_after_resume
    assert subscription_after_resume["status"] == "active", subscription_after_resume
    usage_after_resume = fetch_usage(
        client,
        tenant_admin_cookies,
        tenant_id=tenant_id,
        expected_plan=upgraded_plan,
        expected_status="active",
    )
    assert usage_after_resume["usage"]["active_stores"] == 1, usage_after_resume

    resume_audits = list_audits_since(tenant_id, audit_count)
    assert any(
        audit_matches(audit, tenant_id=tenant_id, expected_plan=upgraded_plan, expected_status="active")
        for audit in resume_audits
    ), resume_audits

    print(
        json.dumps(
            {
                "tenant_id": tenant_id,
                "tenant_slug": tenant_slug,
                "tenant_status": tenant_row["status"],
                "tenant_admin_username": tenant_admin_username,
                "tenant_admin_password": mask_secret(tenant_admin_password),
                "store_id": store_id,
                "store_api_key": mask_secret(store_api_key),
                "store_api_secret": mask_secret(store_api_secret),
                "initial_plan": initial_plan,
                "upgraded_plan": upgraded_plan,
                "subscription_status": subscription_after_resume["status"],
                "audit_counts": {
                    "upgrade": len(upgrade_audits),
                    "pause": len(pause_audits),
                    "resume": len(resume_audits),
                },
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
