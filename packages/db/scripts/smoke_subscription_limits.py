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
        raise SystemExit("XH_DATABASE_URL must be set before running subscription smoke")


def prepare_database() -> None:
    from src.platform.db.session import apply_sql_directory

    apply_sql_directory(ROOT / "packages" / "db" / "migrations")
    apply_sql_directory(ROOT / "packages" / "db" / "seeds")


def seed_starter_tenant() -> tuple[str, str, str]:
    from src.modules.common.postgres_state import hash_password
    from src.platform.db.session import get_db_session

    tenant_id = str(uuid4())
    user_id = str(uuid4())
    suffix = uuid4().hex[:8]
    username = f"quota_admin_{suffix}"
    password = f"QuotaPass{suffix}!"
    with get_db_session() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                insert into tenants (id, slug, name, status, plan, created_at, updated_at)
                values (%s, %s, %s, 'active', 'starter', now(), now())
                """,
                (
                    tenant_id,
                    f"guardrail-quota-{suffix}",
                    f"Guardrail Quota {suffix}",
                ),
            )
            cursor.execute(
                """
                insert into tenant_subscriptions (tenant_id, plan, status, created_at, updated_at)
                values (%s, 'starter', 'active', now(), now())
                """,
                (tenant_id,),
            )
            cursor.execute(
                """
                insert into users (
                  id, tenant_id, username, email, role, status,
                  force_password_reset, version, created_at, updated_at
                )
                values (%s, %s, %s, %s, 'tenant_admin', 'active', false, 1, now(), now())
                """,
                (
                    user_id,
                    tenant_id,
                    username,
                    f"{username}@guardrail.local",
                ),
            )
            cursor.execute(
                """
                insert into user_passwords (user_id, password_hash, password_version, updated_at)
                values (%s, %s, 1, now())
                """,
                (user_id, hash_password(password)),
            )
        connection.commit()
    return tenant_id, username, password


def main() -> None:
    require_database_url()
    prepare_database()
    tenant_id, username, password = seed_starter_tenant()

    from fastapi.testclient import TestClient

    from api_main import app

    client = TestClient(app)
    login = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert login.status_code == 200, login.text
    cookies = login.cookies

    usage = client.get("/admin/api/tenant/usage", cookies=cookies)
    assert usage.status_code == 200, usage.text
    usage_payload = usage.json()
    assert usage_payload["tenant_id"] == tenant_id, usage.text
    assert usage_payload["plan"] == "starter", usage.text
    assert usage_payload["limits"]["max_users"] == 3, usage.text
    assert usage_payload["limits"]["max_stores"] == 1, usage.text
    assert usage_payload["usage"]["active_users"] == 1, usage.text

    created_users = []
    for index in range(2):
        create_user = client.post(
            "/admin/api/users",
            json={
                "username": f"quota_op_{uuid4().hex[:8]}",
                "email": None,
                "role": "operator",
                "password": "temp12345",
            },
            cookies=cookies,
        )
        assert create_user.status_code == 200, create_user.text
        created_users.append(create_user.json()["user"]["user_id"])

    blocked_user = client.post(
        "/admin/api/users",
        json={
            "username": f"quota_op_{uuid4().hex[:8]}",
            "email": None,
            "role": "operator",
            "password": "temp12345",
        },
        cookies=cookies,
    )
    assert blocked_user.status_code == 429, blocked_user.text

    create_store = client.post(
        "/api/v1/stores",
        json={
            "name": f"Guardrail Quota Store {uuid4().hex[:8]}",
            "platform": "takealot",
            "api_key": f"quotaapikey{uuid4().hex[:12]}",
            "api_secret": f"quotasecret{uuid4().hex[:12]}",
            "status": "active",
        },
        cookies=cookies,
    )
    assert create_store.status_code == 200, create_store.text
    store_id = create_store.json()["store_id"]

    blocked_store = client.post(
        "/api/v1/stores",
        json={
            "name": f"Guardrail Quota Store {uuid4().hex[:8]}",
            "platform": "takealot",
            "api_key": f"quotaapikey{uuid4().hex[:12]}",
            "api_secret": f"quotasecret{uuid4().hex[:12]}",
            "status": "active",
        },
        cookies=cookies,
    )
    assert blocked_store.status_code == 429, blocked_store.text

    usage_after = client.get("/admin/api/tenant/usage", cookies=cookies)
    assert usage_after.status_code == 200, usage_after.text
    usage_after_payload = usage_after.json()
    assert usage_after_payload["usage"]["active_users"] == 3, usage_after.text
    assert usage_after_payload["usage"]["active_stores"] == 1, usage_after.text
    assert usage_after_payload["remaining"]["users"] == 0, usage_after.text
    assert usage_after_payload["remaining"]["stores"] == 0, usage_after.text

    print(
        json.dumps(
            {
                "tenant_id": tenant_id,
                "plan": usage_after_payload["plan"],
                "created_users": len(created_users),
                "store_id": store_id,
                "blocked_user_status": blocked_user.status_code,
                "blocked_store_status": blocked_store.status_code,
                "usage": usage_after_payload["usage"],
                "remaining": usage_after_payload["remaining"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
