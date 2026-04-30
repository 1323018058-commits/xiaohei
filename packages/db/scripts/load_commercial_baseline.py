from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "apps" / "api"

sys.path.insert(0, str(API_ROOT))


@dataclass
class RequestMetric:
    step: str
    status_code: int
    elapsed_ms: float
    ok: bool
    error: str | None = None


def require_database_url() -> None:
    from src.platform.settings.base import settings

    if not settings.database_url:
        raise SystemExit("XH_DATABASE_URL must be set before running local ASGI load smoke")


def require_database_url_for_account_pool() -> None:
    from src.platform.settings.base import settings

    if not settings.database_url:
        raise SystemExit(
            "XH_DATABASE_URL must be set before preparing the load-test account pool"
        )


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = math.ceil((p / 100) * len(ordered)) - 1
    return ordered[max(0, min(rank, len(ordered) - 1))]


def summarize_metrics(metrics: list[RequestMetric]) -> dict[str, Any]:
    by_step: dict[str, list[RequestMetric]] = {}
    for metric in metrics:
        by_step.setdefault(metric.step, []).append(metric)

    summary: dict[str, Any] = {}
    for step, step_metrics in sorted(by_step.items()):
        durations = [metric.elapsed_ms for metric in step_metrics]
        failures = [metric for metric in step_metrics if not metric.ok]
        summary[step] = {
            "count": len(step_metrics),
            "error_count": len(failures),
            "error_rate": len(failures) / len(step_metrics) if step_metrics else 0,
            "p50_ms": round(percentile(durations, 50), 2),
            "p95_ms": round(percentile(durations, 95), 2),
            "p99_ms": round(percentile(durations, 99), 2),
            "max_ms": round(max(durations) if durations else 0, 2),
        }
    return summary


def failure_samples(metrics: list[RequestMetric], limit: int = 12) -> list[dict[str, Any]]:
    samples = []
    for metric in metrics:
        if metric.ok:
            continue
        samples.append(
            {
                "step": metric.step,
                "status_code": metric.status_code,
                "elapsed_ms": round(metric.elapsed_ms, 2),
                "error": metric.error,
            }
        )
        if len(samples) >= limit:
            break
    return samples


async def record_request(
    metrics: list[RequestMetric],
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    step: str,
    headers: dict[str, str] | None = None,
    json_payload: dict[str, Any] | None = None,
) -> httpx.Response | None:
    started_at = perf_counter()
    try:
        response = await client.request(
            method,
            url,
            headers=headers,
            json=json_payload,
        )
        elapsed_ms = (perf_counter() - started_at) * 1000
        metrics.append(
            RequestMetric(
                step=step,
                status_code=response.status_code,
                elapsed_ms=elapsed_ms,
                ok=200 <= response.status_code < 400,
            )
        )
        return response
    except Exception as exc:
        elapsed_ms = (perf_counter() - started_at) * 1000
        metrics.append(
            RequestMetric(
                step=step,
                status_code=-1,
                elapsed_ms=elapsed_ms,
                ok=False,
                error=type(exc).__name__,
            )
        )
        return None


def cookie_header(response: httpx.Response, cookie_name: str) -> dict[str, str]:
    cookie_value = response.cookies.get(cookie_name)
    if not cookie_value:
        return {}
    return {"cookie": f"{cookie_name}={cookie_value}"}


def ensure_load_account_pool(
    args: argparse.Namespace,
    password: str,
) -> list[str]:
    if args.account_pool_size <= 1:
        return [args.username]

    require_database_url_for_account_pool()
    from uuid import uuid4

    from src.modules.common.postgres_state import hash_password
    from src.platform.db.session import get_db_session

    pool_usernames = [
        f"{args.username}_{index}"
        for index in range(1, args.account_pool_size + 1)
    ]
    password_hash = hash_password(password)

    with get_db_session() as connection:
        with connection.cursor() as cursor:
            base_user = cursor.execute(
                """
                select id, tenant_id, role, expires_at
                from users
                where username = %s
                """,
                (args.username,),
            ).fetchone()
            if base_user is None:
                connection.rollback()
                raise SystemExit(f"Base load user '{args.username}' was not found")
            if (
                args.include_admin
                and base_user["role"] not in {"super_admin", "tenant_admin"}
            ):
                connection.rollback()
                raise SystemExit(
                    "The base load user must be super_admin or tenant_admin when admin probes are enabled"
                )

            base_feature_flags = cursor.execute(
                """
                select feature_key, enabled
                from user_feature_flags
                where user_id = %s
                order by feature_key asc
                """,
                (base_user["id"],),
            ).fetchall()

            for username in pool_usernames:
                email = f"{username}@load.local"
                user_id = cursor.execute(
                    """
                    insert into users (
                      id, tenant_id, username, email, role, status, expires_at,
                      force_password_reset, version, created_at, updated_at
                    )
                    values (%s, %s, %s, %s, %s, 'active', %s, false, 1, now(), now())
                    on conflict (username)
                    do update set
                      email = excluded.email,
                      role = excluded.role,
                      status = 'active',
                      expires_at = excluded.expires_at,
                      force_password_reset = false,
                      updated_at = now(),
                      version = users.version + 1
                    returning id
                    """,
                    (
                        str(uuid4()),
                        base_user["tenant_id"],
                        username,
                        email,
                        base_user["role"],
                        base_user["expires_at"],
                    ),
                ).fetchone()["id"]

                cursor.execute(
                    """
                    insert into user_passwords (
                      id, user_id, password_hash, password_version, updated_at
                    )
                    values (%s, %s, %s, 1, now())
                    on conflict (user_id)
                    do update set
                      password_hash = excluded.password_hash,
                      password_version = user_passwords.password_version + 1,
                      updated_at = now()
                    """,
                    (str(uuid4()), user_id, password_hash),
                )

                for feature_flag in base_feature_flags:
                    cursor.execute(
                        """
                        insert into user_feature_flags (
                          id, user_id, feature_key, enabled, source, updated_by,
                          version, created_at, updated_at
                        )
                        values (%s, %s, %s, %s, 'load_test', %s, 1, now(), now())
                        on conflict (user_id, feature_key)
                        do update set
                          enabled = excluded.enabled,
                          source = excluded.source,
                          updated_by = excluded.updated_by,
                          updated_at = now(),
                          version = user_feature_flags.version + 1
                        """,
                        (
                            str(uuid4()),
                            user_id,
                            feature_flag["feature_key"],
                            feature_flag["enabled"],
                            base_user["id"],
                        ),
                    )
        connection.commit()

    return pool_usernames


def assign_virtual_users(
    total_users: int,
    account_pool: list[str],
    *,
    seed: int,
) -> list[str]:
    rng = random.Random(seed)
    return [rng.choice(account_pool) for _ in range(total_users)]


def prime_load_account_pool_sessions(account_pool: list[str]) -> None:
    if len(account_pool) <= 1:
        return

    from src.platform.db.session import get_db_session
    from src.platform.settings.base import settings

    with get_db_session() as connection:
        with connection.cursor() as cursor:
            user_rows = cursor.execute(
                """
                select id, username
                from users
                where username = any(%s::text[])
                """,
                (account_pool,),
            ).fetchall()
            if len(user_rows) != len(account_pool):
                connection.rollback()
                raise SystemExit(
                    "Load account pool warmup failed because some shadow accounts are missing"
                )

            user_ids = [row["id"] for row in user_rows]
            existing_sessions = cursor.execute(
                """
                select distinct on (user_id) user_id, session_token
                from auth_sessions
                where user_id = any(%s::uuid[])
                  and status = 'active'
                  and expires_at > now()
                  and created_at >= now() - interval '5 minutes'
                order by user_id asc, created_at desc
                """,
                (user_ids,),
            ).fetchall()
            warmed_user_ids = {row["user_id"] for row in existing_sessions}
            expires_at = datetime.now(UTC) + timedelta(
                seconds=settings.session_max_age_seconds
            )
            for user_row in user_rows:
                if user_row["id"] in warmed_user_ids:
                    continue
                cursor.execute(
                    """
                    insert into auth_sessions (
                      user_id, session_token, status, expires_at, created_at
                    )
                    values (%s, %s, 'active', %s, now())
                    """,
                    (user_row["id"], os.urandom(16).hex(), expires_at),
                )
        connection.commit()


async def prime_application_sessions(
    *,
    base_url: str,
    transport: httpx.ASGITransport | None,
    timeout: httpx.Timeout,
    user_agent: str,
    account_pool: list[str],
    password: str,
) -> None:
    if len(account_pool) <= 1:
        return

    semaphore = asyncio.Semaphore(min(20, len(account_pool)))

    async def warm_account(client: httpx.AsyncClient, username: str) -> None:
        async with semaphore:
            response = await client.post(
                "/api/auth/login",
                json={"username": username, "password": password},
            )
            if response.status_code != 200:
                raise RuntimeError(
                    f"Application session warmup failed for {username}: {response.status_code}"
                )

    async with httpx.AsyncClient(
        base_url=base_url,
        transport=transport,
        timeout=timeout,
        headers={"user-agent": user_agent},
    ) as client:
        await asyncio.gather(
            *(warm_account(client, username) for username in account_pool)
        )


async def virtual_user(
    user_index: int,
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    metrics: list[RequestMetric],
    *,
    username: str,
    password: str,
    session_cookie_name: str,
    iterations: int,
    include_admin: bool,
    perform_logout: bool,
) -> None:
    async with semaphore:
        login = await record_request(
            metrics,
            client,
            "POST",
            "/api/auth/login",
            step="login",
            json_payload={"username": username, "password": password},
        )
        if login is None or login.status_code != 200:
            return

        headers = cookie_header(login, session_cookie_name)
        if not headers:
            metrics.append(
                RequestMetric(
                    step="session_cookie",
                    status_code=-1,
                    elapsed_ms=0,
                    ok=False,
                    error="missing_cookie",
                )
            )
            return

        for _ in range(iterations):
            await record_request(
                metrics,
                client,
                "GET",
                "/api/auth/me",
                step="me",
                headers=headers,
            )
            await record_request(
                metrics,
                client,
                "GET",
                "/api/v1/stores",
                step="stores",
                headers=headers,
            )
            await record_request(
                metrics,
                client,
                "GET",
                "/api/tasks",
                step="tasks",
                headers=headers,
            )
            if include_admin:
                await record_request(
                    metrics,
                    client,
                    "GET",
                    "/admin/api/system/health",
                    step="health",
                    headers=headers,
                )

        if perform_logout:
            await record_request(
                metrics,
                client,
                "POST",
                "/api/auth/logout",
                step="logout",
                headers=headers,
            )


async def run_load(args: argparse.Namespace) -> dict[str, Any]:
    started_at_utc = datetime.now(UTC)
    metrics: list[RequestMetric] = []
    semaphore = asyncio.Semaphore(args.concurrency)
    timeout = httpx.Timeout(args.timeout_seconds)

    app = None
    if args.local_asgi:
        require_database_url()
        from api_main import app as local_app

        app = local_app
        base_url = "http://testserver"
        mode = "asgi_in_process"
    elif args.base_url:
        base_url = args.base_url.rstrip("/")
        mode = "network"
    else:
        raise SystemExit(
            "Real load runs require --base-url or XH_LOAD_BASE_URL. "
            "Use --local-asgi only for local script validation."
        )

    def make_transport() -> httpx.ASGITransport | None:
        if app is None:
            return None
        return httpx.ASGITransport(app=app)

    password = resolve_password(args)
    account_pool = ensure_load_account_pool(args, password)
    perform_logout = len(account_pool) <= 1
    prime_load_account_pool_sessions(account_pool)
    await prime_application_sessions(
        base_url=base_url,
        transport=make_transport(),
        timeout=timeout,
        user_agent=args.user_agent,
        account_pool=account_pool,
        password=password,
    )
    warmup_usernames = assign_virtual_users(
        args.warmup_users,
        account_pool,
        seed=args.random_seed,
    )
    load_usernames = assign_virtual_users(
        args.users,
        account_pool,
        seed=args.random_seed + 1,
    )

    if args.warmup_users > 0:
        warmup_metrics: list[RequestMetric] = []
        warmup_semaphore = asyncio.Semaphore(args.warmup_concurrency)
        async with httpx.AsyncClient(
            base_url=base_url,
            transport=make_transport(),
            timeout=timeout,
            headers={"user-agent": args.user_agent},
        ) as warmup_client:
            await asyncio.gather(
                *(
                    virtual_user(
                        user_index,
                        warmup_client,
                        warmup_semaphore,
                        warmup_metrics,
                        username=warmup_usernames[user_index],
                        password=password,
                        session_cookie_name=args.session_cookie_name,
                        iterations=1,
                        include_admin=args.include_admin,
                        perform_logout=perform_logout,
                    )
                    for user_index in range(args.warmup_users)
                )
            )

    async with httpx.AsyncClient(
        base_url=base_url,
        transport=make_transport(),
        timeout=timeout,
        headers={"user-agent": args.user_agent},
    ) as client:
        started_at = perf_counter()
        await asyncio.gather(
            *(
                virtual_user(
                    user_index,
                    client,
                    semaphore,
                    metrics,
                    username=load_usernames[user_index],
                    password=password,
                    session_cookie_name=args.session_cookie_name,
                    iterations=args.iterations,
                    include_admin=args.include_admin,
                    perform_logout=perform_logout,
                )
                for user_index in range(args.users)
            )
        )
        elapsed_seconds = perf_counter() - started_at

    total = len(metrics)
    failures = [metric for metric in metrics if not metric.ok]
    five_xx = [
        metric
        for metric in metrics
        if 500 <= metric.status_code <= 599
    ]
    durations = [metric.elapsed_ms for metric in metrics]
    step_summary = summarize_metrics(metrics)

    global_p95 = percentile(durations, 95)
    global_p99 = percentile(durations, 99)
    login_p95 = step_summary.get("login", {}).get("p95_ms", 0)
    error_rate = len(failures) / total if total else 1
    finished_at_utc = datetime.now(UTC)
    passed = (
        total > 0
        and error_rate <= args.max_error_rate
        and not five_xx
        and global_p95 <= args.max_p95_ms
        and global_p99 <= args.max_p99_ms
        and login_p95 <= args.max_login_p95_ms
    )

    return {
        "passed": passed,
        "mode": mode,
        "base_url": base_url if mode == "network" else None,
        "started_at": started_at_utc.isoformat(),
        "finished_at": finished_at_utc.isoformat(),
        "users": args.users,
        "iterations": args.iterations,
        "concurrency": args.concurrency,
        "warmup_users": args.warmup_users,
        "username": args.username,
        "account_pool_size": len(account_pool),
        "perform_logout": perform_logout,
        "session_cookie_name": args.session_cookie_name,
        "total_requests": total,
        "elapsed_seconds": round(elapsed_seconds, 2),
        "requests_per_second": round(total / elapsed_seconds, 2) if elapsed_seconds else 0,
        "error_count": len(failures),
        "error_rate": round(error_rate, 4),
        "five_xx_count": len(five_xx),
        "global": {
            "p50_ms": round(percentile(durations, 50), 2),
            "p95_ms": round(global_p95, 2),
            "p99_ms": round(global_p99, 2),
            "max_ms": round(max(durations) if durations else 0, 2),
        },
        "thresholds": {
            "max_error_rate": args.max_error_rate,
            "max_p95_ms": args.max_p95_ms,
            "max_p99_ms": args.max_p99_ms,
            "max_login_p95_ms": args.max_login_p95_ms,
            "five_xx_allowed": 0,
        },
        "failure_samples": failure_samples(metrics),
        "steps": step_summary,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Commercial P0 API load baseline")
    parser.add_argument("--users", type=int, default=int(os.getenv("XH_LOAD_USERS", "10")))
    parser.add_argument("--iterations", type=int, default=int(os.getenv("XH_LOAD_ITERATIONS", "1")))
    parser.add_argument("--concurrency", type=int, default=int(os.getenv("XH_LOAD_CONCURRENCY", "5")))
    parser.add_argument("--warmup-users", type=int, default=int(os.getenv("XH_LOAD_WARMUP_USERS", "0")))
    parser.add_argument(
        "--warmup-concurrency",
        type=int,
        default=int(os.getenv("XH_LOAD_WARMUP_CONCURRENCY", "2")),
    )
    parser.add_argument("--username", default=os.getenv("XH_LOAD_USERNAME", "tenant_admin"))
    parser.add_argument("--password", default=None)
    parser.add_argument("--password-env", default="XH_LOAD_PASSWORD")
    parser.add_argument("--base-url", default=os.getenv("XH_LOAD_BASE_URL"))
    parser.add_argument(
        "--account-pool-size",
        type=int,
        default=int(os.getenv("XH_LOAD_ACCOUNT_POOL_SIZE", "100")),
    )
    parser.add_argument(
        "--random-seed",
        type=int,
        default=int(os.getenv("XH_LOAD_RANDOM_SEED", "42")),
    )
    parser.add_argument("--local-asgi", action="store_true")
    parser.add_argument(
        "--session-cookie-name",
        default=os.getenv("XH_LOAD_SESSION_COOKIE_NAME", "erp_session"),
    )
    parser.add_argument("--user-agent", default="XiaoheiERPCommercialLoad/1.0")
    parser.add_argument("--timeout-seconds", type=float, default=15)
    parser.add_argument(
        "--include-admin",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--max-error-rate", type=float, default=0.01)
    parser.add_argument("--max-p95-ms", type=float, default=1500)
    parser.add_argument("--max-p99-ms", type=float, default=3000)
    parser.add_argument("--max-login-p95-ms", type=float, default=2000)
    parser.add_argument("--output", default=None)
    parser.add_argument("--no-fail", action="store_true")
    return parser.parse_args()


def resolve_password(args: argparse.Namespace) -> str:
    if args.password:
        return args.password
    env_password = os.getenv(args.password_env)
    if env_password:
        return env_password
    if args.local_asgi:
        return "tenant123"
    raise SystemExit(
        f"Set {args.password_env} or pass --password before running against a real API."
    )


def write_output(path_value: str, result: dict[str, Any]) -> None:
    output_path = Path(path_value)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    if args.users <= 0 or args.iterations <= 0 or args.concurrency <= 0:
        raise SystemExit("users, iterations, and concurrency must be greater than 0")
    if args.warmup_users < 0 or args.warmup_concurrency <= 0:
        raise SystemExit("warmup-users must be >= 0 and warmup-concurrency must be greater than 0")
    if args.account_pool_size <= 0:
        raise SystemExit("account-pool-size must be greater than 0")

    result = asyncio.run(run_load(args))
    if args.output:
        write_output(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["passed"] and not args.no_fail:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
